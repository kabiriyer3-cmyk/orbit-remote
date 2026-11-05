"""Authenticated, end-to-end encrypted channel used over the WebSocket.

Handshake (all values base64):
  phone -> host  {"t":"hello","v":1,"epk":<P-256 point>,"n":<16 bytes>}
  host  -> phone {"t":"hello","v":1,"id","name","ik":<SPKI>,"epk","n","sig"}

``sig`` is an ECDSA-P256/SHA-256 signature (r||s) by the host's long-term
identity key over the transcript. The phone pins that key (TOFU, fingerprint
shown on both screens). Both sides derive per-direction AES-256-GCM keys with
HKDF-SHA256 from an ephemeral ECDH secret. Every later message, including the
pairing-code proof, input events and video frames, is sealed with AES-GCM
using a strictly increasing 96-bit counter nonce.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import os
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

PROTO = b"ORBIT/1"
AUTH_LABEL = b"orbit/1 auth|"


class HandshakeError(Exception):
    pass


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def load_identity(path: Path) -> ec.EllipticCurvePrivateKey:
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if isinstance(key, ec.EllipticCurvePrivateKey):
            return key
    key = ec.generate_private_key(ec.SECP256R1())
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def public_spki(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def tls_context(identity_path: Path, key: ec.EllipticCurvePrivateKey) -> ssl.SSLContext:
    """TLS server context whose certificate carries the host identity key.

    The phone pins the SHA-256 of the certificate's public key, which is the same
    fingerprint shown on both screens, so the transport (TLS) and the application
    channel are bound to one key. The certificate is self-signed: LAN hosts can't
    get a publicly trusted one, and trust comes from the pinned key instead.
    """
    cert_path = identity_path.with_name("tls-cert.pem")
    spki = public_spki(key)
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = None
    if cert_path.exists():
        try:
            existing = x509.load_pem_x509_certificate(cert_path.read_bytes())
            same_key = existing.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            ) == spki
            if same_key and existing.not_valid_after_utc > now + datetime.timedelta(days=30):
                cert = existing
        except ValueError:
            cert = None
    if cert is None:
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Orbit host")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256())
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(cert_path), str(identity_path))
    return ctx


def fingerprint(spki: bytes) -> str:
    digest = hashlib.sha256(spki).hexdigest().upper()[:16]
    return " ".join(digest[i : i + 4] for i in range(0, 16, 4))


def auth_proof(secret: str, transcript_hash: bytes) -> bytes:
    return hmac.new(secret.encode("utf-8"), AUTH_LABEL + transcript_hash, hashlib.sha256).digest()


class SecureChannel:
    def __init__(self, send_key: bytes, recv_key: bytes) -> None:
        self._send = AESGCM(send_key)
        self._recv = AESGCM(recv_key)
        self._send_ctr = 0
        self._recv_ctr = 0

    @staticmethod
    def _nonce(counter: int) -> bytes:
        return b"\x00\x00\x00\x00" + counter.to_bytes(8, "big")

    def seal(self, plaintext: bytes) -> bytes:
        nonce = self._nonce(self._send_ctr)
        self._send_ctr += 1
        return self._send.encrypt(nonce, plaintext, None)

    def open(self, ciphertext: bytes) -> bytes:
        nonce = self._nonce(self._recv_ctr)
        self._recv_ctr += 1
        try:
            return self._recv.decrypt(nonce, ciphertext, None)
        except InvalidTag as exc:
            raise HandshakeError("message authentication failed") from exc


def _hkdf(shared: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(shared)


def server_handshake(
    identity: ec.EllipticCurvePrivateKey, host_id: str, host_name: str, hello: dict
) -> tuple[dict, SecureChannel, bytes]:
    if hello.get("t") != "hello" or hello.get("v") != 1:
        raise HandshakeError("unsupported client")
    try:
        c_epk = b64d(str(hello["epk"]))
        c_nonce = b64d(str(hello["n"]))
    except (KeyError, ValueError) as exc:
        raise HandshakeError("malformed hello") from exc
    if len(c_epk) != 65 or c_epk[0] != 4 or len(c_nonce) != 16:
        raise HandshakeError("malformed hello")
    try:
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), c_epk)
    except ValueError as exc:
        raise HandshakeError("invalid key") from exc

    eph = ec.generate_private_key(ec.SECP256R1())
    h_epk = eph.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    h_nonce = os.urandom(16)
    transcript = PROTO + b"|" + c_epk + c_nonce + h_epk + h_nonce + host_id.encode("utf-8")
    r, s = decode_dss_signature(identity.sign(transcript, ec.ECDSA(hashes.SHA256())))
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")

    shared = eph.exchange(ec.ECDH(), peer)
    th = hashlib.sha256(transcript).digest()
    channel = SecureChannel(
        send_key=_hkdf(shared, th, b"orbit/1 h2c"), recv_key=_hkdf(shared, th, b"orbit/1 c2h")
    )
    reply = {
        "t": "hello",
        "v": 1,
        "id": host_id,
        "name": host_name,
        "ik": b64e(public_spki(identity)),
        "epk": b64e(h_epk),
        "n": b64e(h_nonce),
        "sig": b64e(signature),
    }
    return reply, channel, th
