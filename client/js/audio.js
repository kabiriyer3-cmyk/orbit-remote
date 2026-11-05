// Plays the PC's sound on the phone. The host streams little-endian 16-bit interleaved PCM
// (MSG_AUDIO) that we decode and schedule through the Web Audio API with a small buffer, so
// playback stays smooth without drifting far behind the screen.
const MAX_LEAD = 0.5;   // seconds queued ahead; drop older audio past this to stay in sync
const START_LEAD = 0.12; // initial buffer before the first block plays

export class AudioPlayer {
  constructor() {
    this.ctx = null;
    this.gain = null;
    this.playAt = 0;
    this.rate = 48000;
    this.channels = 2;
    this.muted = false;
    this.playing = false;
  }

  get supported() {
    return typeof (window.AudioContext || window.webkitAudioContext) === 'function';
  }

  async start(rate = 48000, channels = 2) {
    if (!this.supported) throw new Error('no Web Audio');
    this.rate = rate || 48000;
    this.channels = channels || 2;
    if (!this.ctx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new Ctx({ sampleRate: this.rate, latencyHint: 'interactive' });
      this.gain = this.ctx.createGain();
      this.gain.connect(this.ctx.destination);
    }
    this.gain.gain.value = this.muted ? 0 : 1;
    this.playAt = 0;
    this.playing = true;
    await this.unlock();
  }

  // Browsers keep audio suspended until the page has had a tap. Never wait on that forever:
  // if it's still locked, the next touch anywhere unlocks it (see the listener below).
  async unlock() {
    if (!this.ctx || this.ctx.state !== 'suspended') return;
    await Promise.race([this.ctx.resume().catch(() => {}), new Promise((r) => setTimeout(r, 600))]);
  }

  // frame: Uint8Array of interleaved int16 PCM
  push(bytes) {
    if (!this.playing || !this.ctx) return;
    const frames = Math.floor(bytes.length / 2 / this.channels);
    if (frames <= 0) return;
    const pcm = new Int16Array(bytes.buffer, bytes.byteOffset, frames * this.channels);
    const buffer = this.ctx.createBuffer(this.channels, frames, this.rate);
    for (let ch = 0; ch < this.channels; ch += 1) {
      const out = buffer.getChannelData(ch);
      for (let i = 0; i < frames; i += 1) out[i] = pcm[i * this.channels + ch] / 32768;
    }
    const now = this.ctx.currentTime;
    if (this.playAt < now + 0.001) this.playAt = now + START_LEAD; // first block or we fell behind
    else if (this.playAt > now + MAX_LEAD) this.playAt = now + START_LEAD; // too far ahead: resync
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.gain);
    src.start(this.playAt);
    this.playAt += buffer.duration;
  }

  setMuted(muted) {
    this.muted = muted;
    if (this.gain) this.gain.gain.value = muted ? 0 : 1;
  }

  stop() {
    this.playing = false;
    this.playAt = 0;
    if (this.ctx && this.ctx.state === 'running') this.ctx.suspend().catch(() => {});
  }

  close() {
    this.stop();
    if (this.ctx) { this.ctx.close().catch(() => {}); this.ctx = null; this.gain = null; }
  }
}

export const player = new AudioPlayer();
const unlockOnTouch = () => { if (player.playing) player.unlock(); };
document.addEventListener('pointerdown', unlockOnTouch, { passive: true, capture: true });
document.addEventListener('keydown', unlockOnTouch, { passive: true, capture: true });
