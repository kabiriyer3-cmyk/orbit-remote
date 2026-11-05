// Touch gestures → mouse, and the soft-keyboard bridge.
import { native } from './native.js';

const TAP_MS = 260;
const TAP_SLOP = 9;
const LONG_MS = 480;
const now = () => performance.now();
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

export class GestureController extends EventTarget {
  constructor(surface, viewer, getSession) {
    super();
    this.el = surface;
    this.viewer = viewer;
    this.getSession = getSession;
    this.mode = 'trackpad';
    this.speed = 1;
    this.enabled = true;
    this.pointers = new Map();
    this.gesture = null;
    this.acc = { rx: 0, ry: 0, wx: 0, wy: 0, abs: null };
    this.flushQueued = false;
    const opts = { passive: false };
    surface.addEventListener('pointerdown', (e) => this.down(e), opts);
    surface.addEventListener('pointermove', (e) => this.move(e), opts);
    surface.addEventListener('pointerup', (e) => this.up(e), opts);
    surface.addEventListener('pointercancel', (e) => this.up(e, true), opts);
    surface.addEventListener('wheel', (e) => this.mouseWheel(e), opts);
    surface.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  get session() { return this.enabled ? this.getSession() : null; }

  monitorSize() {
    const s = this.getSession();
    const info = s && s.session;
    const mon = info && (info.monitors || []).find((m) => m.index === info.monitor);
    return mon ? { w: mon.width, h: mon.height } : { w: 1920, h: 1080 };
  }

  // -- batching --------------------------------------------------------------
  queue() {
    if (this.flushQueued) return;
    this.flushQueued = true;
    requestAnimationFrame(() => this.flush());
  }

  flush() {
    this.flushQueued = false;
    const s = this.session;
    if (!s) { this.acc = { rx: 0, ry: 0, wx: 0, wy: 0, abs: null }; return; }
    const a = this.acc;
    if (a.abs) { s.move(a.abs.x, a.abs.y); a.abs = null; }
    const rx = Math.trunc(a.rx);
    const ry = Math.trunc(a.ry);
    if (rx || ry) { s.rel(rx, ry); a.rx -= rx; a.ry -= ry; }
    const wy = Math.trunc(a.wy);
    const wx = Math.trunc(a.wx);
    if (wx || wy) { s.wheel(wx, wy); a.wx -= wx; a.wy -= wy; }
  }

  sendAbs(clientX, clientY) {
    const p = this.viewer.toNormalized(clientX, clientY);
    this.acc.abs = p;
    this.viewer.moveLocalCursor(p.x, p.y);
    this.queue();
    return p;
  }

  sendRel(dx, dy, dt) {
    const mon = this.monitorSize();
    const shown = Math.max(1, this.viewer.displayedWidth());
    const v = Math.hypot(dx, dy) / Math.max(1, dt);
    const accel = 1 + Math.min(2.6, Math.max(0, (v - 0.22) * 1.6));
    const gain = (mon.w / shown) * 0.62 * this.speed * accel * Math.min(1.6, this.viewer.zoom);
    this.acc.rx += dx * gain;
    this.acc.ry += dy * gain;
    const c = this.viewer.cursor.x >= 0 ? this.viewer.cursor : { x: 0.5, y: 0.5 };
    this.viewer.moveLocalCursor(c.x + (dx * gain) / mon.w, c.y + (dy * gain) / mon.h);
    this.queue();
  }

  click(button = 'left', action = 'click') {
    const s = this.session;
    if (!s) return;
    this.flush();
    s.button(button, action);
  }

  // -- pointer handling ------------------------------------------------------
  down(e) {
    e.preventDefault();
    if (e.pointerType === 'mouse') { this.mouseDown(e); return; }
    try { this.el.setPointerCapture(e.pointerId); } catch {}
    const p = { id: e.pointerId, x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, t: now(), lt: now() };
    this.pointers.set(e.pointerId, p);
    const n = this.pointers.size;
    if (n === 1) this.beginOne(p);
    else if (n === 2) this.beginTwo();
    else if (n === 3) this.beginThree();
  }

  move(e) {
    if (e.pointerType === 'mouse') { this.mouseMove(e); return; }
    const p = this.pointers.get(e.pointerId);
    if (!p) return;
    e.preventDefault();
    const dx = e.clientX - p.x;
    const dy = e.clientY - p.y;
    const t = now();
    const dt = t - p.lt;
    p.x = e.clientX;
    p.y = e.clientY;
    p.lt = t;
    if (this.gesture && this.gesture.kind === 'one') this.moveOne(p, dx, dy, dt);
    else if (this.gesture && this.gesture.kind === 'two') this.moveTwo();
  }

  up(e, cancelled = false) {
    if (e.pointerType === 'mouse') { this.mouseUp(e); return; }
    const p = this.pointers.get(e.pointerId);
    if (!p) return;
    this.pointers.delete(e.pointerId);
    const g = this.gesture;
    if (!g) return;
    if (this.pointers.size === 0) {
      if (g.kind === 'one') this.endOne(p, cancelled);
      else if (g.kind === 'two') this.endTwo(cancelled);
      else if (g.kind === 'three') this.endThree(cancelled);
      this.gesture = null;
    }
  }

  // One finger ---------------------------------------------------------------
  beginOne(p) {
    const g = { kind: 'one', p, moved: false, dragging: false, consumed: false, t: now() };
    this.gesture = g;
    g.long = setTimeout(() => {
      if (g.moved || this.gesture !== g) return;
      if (this.mode === 'trackpad') {
        g.dragging = true;
        this.click('left', 'down');
      } else {
        this.sendAbs(p.x, p.y);
        this.click('right');
        g.consumed = true;
      }
      native.haptic();
    }, LONG_MS);
  }

  moveOne(p, dx, dy, dt) {
    const g = this.gesture;
    if (!g.moved && Math.hypot(p.x - p.sx, p.y - p.sy) > TAP_SLOP) {
      g.moved = true;
      if (!g.dragging) clearTimeout(g.long);
      if (this.mode === 'touch' && !g.consumed) {
        this.sendAbs(p.sx, p.sy);
        this.click('left', 'down');
        g.dragging = true;
      }
    }
    if (!g.moved && !g.dragging) return;
    if (this.mode === 'trackpad') this.sendRel(dx, dy, dt);
    else if (g.dragging) this.sendAbs(p.x, p.y);
  }

  endOne(p, cancelled) {
    const g = this.gesture;
    clearTimeout(g.long);
    if (g.dragging) {
      if (this.mode === 'touch') this.sendAbs(p.x, p.y);
      this.click('left', 'up');
      return;
    }
    if (cancelled || g.moved || g.consumed) return;
    if (now() - g.t <= TAP_MS * 1.6) {
      if (this.mode === 'touch') this.sendAbs(p.x, p.y);
      this.click('left');
    }
  }

  cancelOne() {
    const g = this.gesture;
    if (!g || g.kind !== 'one') return;
    clearTimeout(g.long);
    if (g.dragging) this.click('left', 'up');
  }

  // Two fingers --------------------------------------------------------------
  beginTwo() {
    this.cancelOne();
    const [a, b] = [...this.pointers.values()];
    this.gesture = { kind: 'two', t: now(), d0: dist(a, b), m0: mid(a, b), lastD: dist(a, b), lastM: mid(a, b), mode: null, moved: false };
  }

  moveTwo() {
    const g = this.gesture;
    const pts = [...this.pointers.values()];
    if (pts.length < 2) return;
    const d = dist(pts[0], pts[1]);
    const m = mid(pts[0], pts[1]);
    if (!g.mode) {
      const dd = Math.abs(d - g.d0);
      const dm = dist(m, g.m0);
      if (dd > 16 || dm > 10) {
        g.mode = dd > dm * 1.15 ? 'pinch' : 'scroll';
        g.moved = true;
        g.lastD = d;
        g.lastM = m;
      }
      return;
    }
    if (g.mode === 'pinch') {
      this.viewer.zoomAt(d / Math.max(1, g.lastD), m.x, m.y);
      this.viewer.panBy(m.x - g.lastM.x, m.y - g.lastM.y);
    } else {
      this.acc.wy += (m.y - g.lastM.y) * 3.2;
      this.acc.wx -= (m.x - g.lastM.x) * 3.2;
      this.queue();
    }
    g.lastD = d;
    g.lastM = m;
  }

  endTwo(cancelled) {
    const g = this.gesture;
    if (cancelled || g.moved || now() - g.t > 320) return;
    if (this.mode === 'touch') this.sendAbs(g.m0.x, g.m0.y);
    this.click('right');
    native.haptic();
  }

  // Three fingers: toggle keyboard -------------------------------------------
  beginThree() {
    this.gesture = { kind: 'three', t: now() };
  }

  endThree(cancelled) {
    if (!cancelled && now() - this.gesture.t < 400) this.dispatchEvent(new Event('keyboard'));
  }

  // Physical mouse (desktop browsers, Bluetooth mice, DeX) -------------------
  mouseDown(e) {
    try { this.el.setPointerCapture(e.pointerId); } catch {}
    this.sendAbs(e.clientX, e.clientY);
    this.click(['left', 'middle', 'right', 'back', 'forward'][e.button] || 'left', 'down');
  }

  mouseMove(e) {
    if (!this.session) return;
    this.sendAbs(e.clientX, e.clientY);
  }

  mouseUp(e) {
    this.sendAbs(e.clientX, e.clientY);
    this.click(['left', 'middle', 'right', 'back', 'forward'][e.button] || 'left', 'up');
  }

  mouseWheel(e) {
    e.preventDefault();
    if (e.ctrlKey) { this.viewer.zoomAt(e.deltaY < 0 ? 1.1 : 0.9, e.clientX, e.clientY); return; }
    const k = e.deltaMode === 1 ? 40 : 1;
    this.acc.wy -= e.deltaY * k;
    this.acc.wx += e.deltaX * k;
    this.queue();
  }
}

const SENTINEL = '\u00a0'.repeat(8);
const SPECIAL = new Set(['Enter', 'Backspace', 'Tab', 'Escape', 'Delete', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown', 'Insert']);

export class KeyboardSink {
  constructor(input, getSession, modifiers) {
    this.input = input;
    this.getSession = getSession;
    this.mods = modifiers;
    this.composing = false;
    this.last = SENTINEL;
    input.addEventListener('compositionstart', () => { this.composing = true; });
    input.addEventListener('compositionend', () => { this.composing = false; setTimeout(() => this.reset(), 0); });
    input.addEventListener('input', () => this.onInput());
    input.addEventListener('keydown', (e) => this.onKeyDown(e));
    input.addEventListener('blur', () => { if (this.onBlur) this.onBlur(); });
    this.reset();
  }

  get isOpen() { return document.activeElement === this.input; }

  open() {
    this.reset();
    this.input.focus({ preventScroll: true });
  }

  close() { this.input.blur(); }

  reset() {
    this.input.value = SENTINEL;
    this.last = SENTINEL;
    try { this.input.setSelectionRange(SENTINEL.length, SENTINEL.length); } catch {}
  }

  sendKey(key) {
    const s = this.getSession();
    if (!s) return;
    const mods = this.mods.consume();
    if (mods.length) s.combo([...mods, key]);
    else s.key(key);
  }

  onKeyDown(e) {
    if (e.isComposing || e.keyCode === 229) return;
    const s = this.getSession();
    if (!s) return;
    if (SPECIAL.has(e.key) || /^F\d{1,2}$/.test(e.key)) {
      e.preventDefault();
      const mods = this.mods.consume();
      if (e.ctrlKey) mods.push('Control');
      if (e.altKey) mods.push('Alt');
      if (e.shiftKey && e.key !== 'Tab') mods.push('Shift');
      if (e.metaKey) mods.push('Meta');
      if (mods.length) s.combo([...new Set(mods), e.key]);
      else s.key(e.key);
      return;
    }
    if ((e.ctrlKey || e.altKey || e.metaKey) && e.key.length === 1) {
      e.preventDefault();
      const mods = [];
      if (e.ctrlKey) mods.push('Control');
      if (e.altKey) mods.push('Alt');
      if (e.shiftKey) mods.push('Shift');
      if (e.metaKey) mods.push('Meta');
      s.combo([...mods, e.key.toLowerCase()]);
    }
  }

  onInput() {
    const v = this.input.value;
    const last = this.last;
    let i = 0;
    while (i < last.length && i < v.length && last[i] === v[i]) i++;
    const removed = last.length - i;
    const added = v.slice(i).replace(/\u00a0/g, ' ');
    const s = this.getSession();
    if (s) {
      for (let k = 0; k < removed; k++) s.key('Backspace');
      if (added) {
        const mods = this.mods.active();
        if (mods.length && added.length === 1 && added !== '\n') {
          s.combo([...this.mods.consume(), added.toLowerCase()]);
        } else {
          s.text(added);
        }
      }
    }
    this.last = v;
    if (!this.composing) this.reset();
  }
}

export class Modifiers {
  constructor(onChange) {
    this.state = { Control: 0, Alt: 0, Shift: 0, Meta: 0 }; // 0 off, 1 once, 2 locked
    this.onChange = onChange;
  }
  toggle(name) {
    this.state[name] = (this.state[name] + 1) % 3;
    this.onChange(this.state);
  }
  active() { return Object.keys(this.state).filter((k) => this.state[k]); }
  consume() {
    const list = this.active();
    let changed = false;
    for (const k of list) if (this.state[k] === 1) { this.state[k] = 0; changed = true; }
    if (changed) this.onChange(this.state);
    return list;
  }
}
