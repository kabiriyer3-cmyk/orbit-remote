"""Minimal Python implementation of the phone protocol (used by the self-test)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import ssl
import struct
from typing import Any

import aiohttp
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from .capture import FRAME_HEADER, MSG_AUDIO, MSG_FRAME, MSG_JSON
from .secure import PROTO, SecureChannel, _hkdf, auth_proof, fingerprint


def _pinning_context() -> ssl.SSLContext:
    # The host certificate is self-signed; trust comes from pinning its public key below,
    # exactly like the Android app does.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class TestClient:
    def __init__(self, url: str, pin: str | None = None) -> None:
        self.url = url
        self.pin = pin
        self.tls_fingerprint = ""
        self.session: aiohttp.ClientSession | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.channel: SecureChannel | None = None
        self.th = b""
        self.host_fingerprint = ""

    async def __aenter__(self) -> "TestClient":
        self.session = aiohttp.ClientSession()
        tls = _pinning_context() if self.url.startswith("wss://") else None
        self.ws = await self.session.ws_connect(self.url, max_msg_size=8 * 1024 * 1024, ssl=tls if tls else True)
        if tls:
            ssl_object = self.ws.get_extra_info("ssl_object")
            der = ssl_object.getpeercert(binary_form=True) if ssl_object else None
            if not der:
                raise ConnectionError("no TLS certificate from host")
            spki = x509.load_der_x509_certificate(der).public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            self.tls_fingerprint = fingerprint(spki)
            if self.pin and self.pin != self.tls_fingerprint:
                await self.__aexit__()
                raise ConnectionError("host security key changed")
        await self._handshake()
        if tls and self.tls_fingerprint != self.host_fingerprint:
            raise ConnectionError("TLS key does not match the host identity")
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()

    async def _handshake(self) -> None:
        assert self.ws
        eph = ec.generate_private_key(ec.SECP256R1())
        epk = eph.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        nonce = os.urandom(16)
        await self.ws.send_str(json.dumps({"t": "hello", "v": 1, "epk": base64.b64encode(epk).decode(), "n": base64.b64encode(nonce).decode()}))
        reply = json.loads((await self.ws.receive(timeout=10)).data)
        ik = base64.b64decode(reply["ik"])
        h_epk = base64.b64decode(reply["epk"])
        h_nonce = base64.b64decode(reply["n"])
        sig = base64.b64decode(reply["sig"])
        transcript = PROTO + b"|" + epk + nonce + h_epk + h_nonce + reply["id"].encode()
        identity = serialization.load_der_public_key(ik)
        assert isinstance(identity, ec.EllipticCurvePublicKey)
        der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
        identity.verify(der, transcript, ec.ECDSA(hashes.SHA256()))
        shared = eph.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), h_epk))
        self.th = hashlib.sha256(transcript).digest()
        self.channel = SecureChannel(send_key=_hkdf(shared, self.th, b"orbit/1 c2h"), recv_key=_hkdf(shared, self.th, b"orbit/1 h2c"))
        self.host_fingerprint = fingerprint(ik)
        self.host_hello = reply

    async def send(self, obj: dict[str, Any]) -> None:
        assert self.ws and self.channel
        await self.ws.send_bytes(self.channel.seal(bytes([MSG_JSON]) + json.dumps(obj).encode()))

    async def recv(self, timeout: float = 10.0) -> tuple[str, Any]:
        assert self.ws and self.channel
        msg = await self.ws.receive(timeout=timeout)
        if msg.type != aiohttp.WSMsgType.BINARY:
            return "closed", None
        plain = self.channel.open(msg.data)
        if plain[0] == MSG_JSON:
            return "json", json.loads(plain[1:])
        if plain[0] == MSG_FRAME:
            seq, w, h, cx, cy = FRAME_HEADER.unpack_from(plain, 1)
            return "frame", {"seq": seq, "w": w, "h": h, "cx": cx, "cy": cy, "jpeg": plain[1 + FRAME_HEADER.size :]}
        if plain[0] == MSG_AUDIO:
            rate, channels, bits, seq = struct.unpack_from("<IBBH", plain, 1)
            return "audio", {"rate": rate, "channels": channels, "bits": bits, "seq": seq, "pcm": plain[9:]}
        return "unknown", plain

    async def auth_with_code(self, code: str, trust: bool = False, cid: str = "selftest") -> None:
        proof = base64.b64encode(auth_proof(code, self.th)).decode()
        await self.send({"t": "auth", "mode": "code", "proof": proof, "cid": cid, "dev": "Self-test", "trust": trust})

    async def auth_with_token(self, token: str, cid: str) -> None:
        proof = base64.b64encode(auth_proof(token, self.th)).decode()
        await self.send({"t": "auth", "mode": "token", "proof": proof, "cid": cid, "dev": "Self-test"})


__all__ = ["TestClient", "struct", "asyncio"]
