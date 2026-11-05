// One connection to an Orbit host: handshake, authentication, frames, input.
import { Handshake, authProof, b64, cryptoAvailable } from './crypto.js';
import { native, isNative } from './native.js';

const MSG_JSON = 1;
const MSG_FRAME = 2;
const te = new TextEncoder();
const td = new TextDecoder();

export class OrbitSession extends EventTarget {
  /**
   * opts: { address, port, code, clientId, deviceName, remember,
   *         pin, pinnedHostId,   // key saved for this address (TLS pinning in the Android app)
   *         resolveHost(id) -> {fingerprint, token} | null,
   *         verify({name, id, fingerprint}) -> Promise<boolean> }
   */
  constructor(opts) {
    super();
    this.opts = opts;
    this.state = 'idle';
    this.ws = null;
    this.channel = null;
    this.recvChain = Promise.resolve();
    this.sendChain = Promise.resolve();
    this.session = null;
    this.rtt = 0;
    this.byeReason = '';
    this.pingTimer = 0;
  }

  emit(type, detail = {}) { this.dispatchEvent(new CustomEvent(type, { detail })); }

  setState(state) {
    this.state = state;
    this.emit('state', { state });
  }

  async connect() {
    if (!cryptoAvailable()) { this.fail('insecure_context'); return; }
    const { address, port } = this.opts;
    const host = address.includes(':') && !address.startsWith('[') ? `[${address}]` : address;
    this.setState('connecting');
    this.tlsFingerprint = '';
    let url = `wss://${host}:${port}/ws`;
    if (isNative) {
      // Android: a native TLS tunnel connects to the PC and pins its key (the same key whose
      // fingerprint is shown on both screens). The WebView reaches the tunnel over loopback only.
      try {
        const tunnel = await native.openTunnel(address, port, this.opts.pin || '');
        this.tlsFingerprint = tunnel.fingerprint;
        url = `ws://127.0.0.1:${tunnel.port}/ws`;
      } catch (err) {
        const text = String((err && err.message) || err);
        const mismatch = text.match(/key_mismatch:([0-9A-F ]+)/);
        if (mismatch) {
          this.hostId = this.opts.pinnedHostId || '';
          this.fingerprint = mismatch[1].trim();
          this.fail('fingerprint');
        } else {
          this.fail('unreachable');
        }
        return;
      }
    }
    let ws;
    try {
      ws = new WebSocket(url);
    } catch {
      this.fail('address');
      return;
    }
    ws.binaryType = 'arraybuffer';
    this.ws = ws;
    const timer = setTimeout(() => {
      if (this.state === 'connecting') { this.fail('unreachable'); try { ws.close(); } catch {} }
    }, 7000);
    ws.onopen = async () => {
      clearTimeout(timer);
      this.setState('securing');
      this.hs = await Handshake.start();
      ws.send(JSON.stringify(this.hs.hello()));
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') { this.onHello(ev.data); return; }
      if (!this.channel) return;
      const data = new Uint8Array(ev.data);
      this.recvChain = this.recvChain
        .then(() => this.channel.open(data))
        .then((plain) => this.onPlain(plain))
        .catch((err) => { console.warn('orbit: decrypt failed', err); this.fail('crypto'); });
    };
    ws.onclose = () => {
      clearTimeout(timer);
      clearInterval(this.pingTimer);
      if (this.state === 'ready') {
        this.setState('closed');
        this.emit('closed', { reason: this.byeReason || 'lost' });
      } else if (!['failed', 'closed'].includes(this.state)) {
        this.fail(this.state === 'connecting' ? 'unreachable' : 'closed');
      }
    };
  }

  async onHello(text) {
    if (this.channel) return;
    let reply;
    try {
      reply = JSON.parse(text);
      const res = await this.hs.finish(reply);
      this.channel = res.channel;
      this.th = res.th;
      this.fingerprint = res.fingerprint;
      this.hostId = String(reply.id);
      this.hostName = String(reply.name || 'PC');
    } catch (err) {
      console.warn('orbit: handshake failed', err);
      this.fail('handshake');
      return;
    }
    if (this.tlsFingerprint && this.tlsFingerprint !== this.fingerprint) {
      // TLS and the encrypted channel must be bound to the same host key.
      this.fail('fingerprint');
      return;
    }
    const known = this.opts.resolveHost(this.hostId);
    if (known && known.fingerprint && known.fingerprint !== this.fingerprint) {
      this.fail('fingerprint');
      return;
    }
    if (!known || !known.fingerprint) {
      this.setState('verifying');
      const ok = await this.opts.verify({ name: this.hostName, id: this.hostId, fingerprint: this.fingerprint });
      if (!ok) { this.fail('cancelled'); return; }
    }
    const token = known && known.token;
    const secret = token || this.opts.code;
    if (!secret) { this.fail('need_code'); return; }
    this.authMode = token ? 'token' : 'code';
    this.setState('authenticating');
    const proof = await authProof(secret, this.th);
    this.send({
      t: 'auth', mode: this.authMode, proof: b64.enc(proof), cid: this.opts.clientId,
      dev: this.opts.deviceName, trust: !!this.opts.remember,
    });
  }

  onPlain(plain) {
    if (plain[0] === MSG_FRAME) {
      const dv = new DataView(plain.buffer, plain.byteOffset + 1, 16);
      this.emit('frame', {
        seq: dv.getUint32(0, true), w: dv.getUint16(4, true), h: dv.getUint16(6, true),
        cx: dv.getFloat32(8, true), cy: dv.getFloat32(12, true), jpeg: plain.subarray(17),
      });
      return;
    }
    if (plain[0] !== MSG_JSON) return;
    const m = JSON.parse(td.decode(plain.subarray(1)));
    switch (m.t) {
      case 'pending':
        this.setState('pending');
        break;
      case 'auth':
        if (m.ok) {
          this.session = m.session;
          this.setState('ready');
          this.emit('ready', {
            session: m.session, token: m.token || null, hostId: this.hostId, hostName: this.hostName,
            fingerprint: this.fingerprint, authMode: this.authMode,
          });
          this.startPing();
        } else {
          this.fail(m.reason || 'denied');
        }
        break;
      case 'cur': this.emit('cursor', { x: m.x, y: m.y }); break;
      case 'pong': this.rtt = Math.max(0, performance.now() - m.ts); this.emit('rtt', { rtt: this.rtt }); break;
      case 'mon': this.session.monitor = m.monitor; this.session.monitors = m.monitors; this.emit('monitor', m); break;
      case 'control': this.session.viewOnly = !!m.viewOnly; this.emit('control', m); break;
      case 'bye': this.byeReason = m.reason || 'host'; break;
      default: break;
    }
  }

  startPing() {
    clearInterval(this.pingTimer);
    const ping = () => this.send({ t: 'ping', ts: performance.now() });
    ping();
    this.pingTimer = setInterval(ping, 2000);
  }

  send(obj) {
    const ws = this.ws;
    if (!this.channel || !ws || ws.readyState !== WebSocket.OPEN) return;
    const body = te.encode(JSON.stringify(obj));
    const plain = new Uint8Array(body.length + 1);
    plain[0] = MSG_JSON;
    plain.set(body, 1);
    this.sendChain = this.sendChain
      .then(() => this.channel.seal(plain))
      .then((sealed) => { if (ws.readyState === WebSocket.OPEN) ws.send(sealed); })
      .catch(() => {});
  }

  fail(reason) {
    if (['failed', 'closed'].includes(this.state)) return;
    clearInterval(this.pingTimer);
    this.setState('failed');
    this.emit('failed', { reason });
    try { if (this.ws && this.ws.readyState <= 1) this.ws.close(); } catch {}
  }

  disconnect() {
    if (this.state === 'ready') this.send({ t: 'bye' });
    this.byeReason = 'user';
    const ws = this.ws;
    setTimeout(() => { try { ws && ws.close(); } catch {} }, 120);
    if (this.state !== 'ready') this.fail('cancelled');
  }

  // Input helpers -----------------------------------------------------------
  move(x, y) { this.send({ t: 'move', x, y }); }
  rel(dx, dy) { this.send({ t: 'rel', dx, dy }); }
  button(b, a = 'click') { this.send({ t: 'btn', b, a }); }
  wheel(dx, dy) { this.send({ t: 'wheel', dx, dy }); }
  key(k, a = 'press') { this.send({ t: 'key', k, a }); }
  combo(keys) { this.send({ t: 'combo', keys }); }
  text(s) { this.send({ t: 'text', s }); }
  ack(seq) { this.send({ t: 'ack', s: seq }); }
  config(cfg) { this.send(Object.assign({ t: 'cfg' }, cfg)); }
  monitor(i) { this.send({ t: 'mon', i }); }
  pause() { this.send({ t: 'pause' }); }
  resume() { this.send({ t: 'resume' }); }
}
