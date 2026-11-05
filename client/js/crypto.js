// Orbit secure channel: ECDH P-256 + ECDSA host identity + HKDF + AES-256-GCM (WebCrypto).
const te = new TextEncoder();
const subtle = globalThis.crypto && globalThis.crypto.subtle;

export const b64 = {
  enc(u8) {
    let s = '';
    for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    return btoa(s);
  },
  dec(str) {
    const bin = atob(str);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  },
};

export function concat(...parts) {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) { out.set(p, off); off += p.length; }
  return out;
}

export function cryptoAvailable() {
  return !!subtle && globalThis.isSecureContext !== false;
}

async function sha256(data) {
  return new Uint8Array(await subtle.digest('SHA-256', data));
}

export async function fingerprintOf(spki) {
  const hex = Array.from(await sha256(spki), (b) => b.toString(16).padStart(2, '0')).join('').toUpperCase().slice(0, 16);
  return hex.match(/.{4}/g).join(' ');
}

export async function authProof(secret, transcriptHash) {
  const key = await subtle.importKey('raw', te.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return new Uint8Array(await subtle.sign('HMAC', key, concat(te.encode('orbit/1 auth|'), transcriptHash)));
}

export class SecureChannel {
  constructor(sendKey, recvKey) {
    this.sendKey = sendKey;
    this.recvKey = recvKey;
    this.sendCtr = 0n;
    this.recvCtr = 0n;
  }
  static nonce(ctr) {
    const n = new Uint8Array(12);
    new DataView(n.buffer).setBigUint64(4, ctr, false);
    return n;
  }
  async seal(plain) {
    const iv = SecureChannel.nonce(this.sendCtr++);
    return new Uint8Array(await subtle.encrypt({ name: 'AES-GCM', iv }, this.sendKey, plain));
  }
  async open(sealed) {
    const iv = SecureChannel.nonce(this.recvCtr++);
    return new Uint8Array(await subtle.decrypt({ name: 'AES-GCM', iv }, this.recvKey, sealed));
  }
}

export class Handshake {
  static async start() {
    const pair = await subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']);
    const epk = new Uint8Array(await subtle.exportKey('raw', pair.publicKey));
    const nonce = crypto.getRandomValues(new Uint8Array(16));
    return new Handshake(pair, epk, nonce);
  }
  constructor(pair, epk, nonce) {
    this.pair = pair;
    this.epk = epk;
    this.nonce = nonce;
  }
  hello() {
    return { t: 'hello', v: 1, epk: b64.enc(this.epk), n: b64.enc(this.nonce) };
  }
  async finish(reply) {
    if (reply.t !== 'hello' || reply.v !== 1) throw new Error('protocol');
    const ik = b64.dec(reply.ik);
    const hepk = b64.dec(reply.epk);
    const hn = b64.dec(reply.n);
    const sig = b64.dec(reply.sig);
    const transcript = concat(te.encode('ORBIT/1|'), this.epk, this.nonce, hepk, hn, te.encode(String(reply.id)));
    const identity = await subtle.importKey('spki', ik, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
    const valid = await subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, identity, sig, transcript);
    if (!valid) throw new Error('signature');
    const peer = await subtle.importKey('raw', hepk, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
    const shared = await subtle.deriveBits({ name: 'ECDH', public: peer }, this.pair.privateKey, 256);
    const th = await sha256(transcript);
    const base = await subtle.importKey('raw', shared, 'HKDF', false, ['deriveKey']);
    const derive = (info, usage) => subtle.deriveKey(
      { name: 'HKDF', hash: 'SHA-256', salt: th, info: te.encode(info) }, base,
      { name: 'AES-GCM', length: 256 }, false, [usage]);
    const channel = new SecureChannel(await derive('orbit/1 c2h', 'encrypt'), await derive('orbit/1 h2c', 'decrypt'));
    return { channel, th, fingerprint: await fingerprintOf(ik) };
  }
}
