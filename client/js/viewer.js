// Renders remote frames on a canvas with zoom/pan and a local cursor overlay.
export class Viewer {
  constructor(canvas, stage) {
    this.canvas = canvas;
    this.stage = stage;
    this.ctx = canvas.getContext('2d', { alpha: false, desynchronized: true });
    this.bitmap = null;
    this.frameW = 16;
    this.frameH = 9;
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this.cursor = { x: -1, y: -1 };
    this.showCursor = true;
    this.frames = 0;
    this.pending = false;
    this.decoding = Promise.resolve();
    this.onFirstFrame = null;
    new ResizeObserver(() => this.resize()).observe(stage);
    this.resize();
  }

  resize() {
    const r = this.stage.getBoundingClientRect();
    this.dpr = Math.min(window.devicePixelRatio || 1, 3);
    this.cssW = Math.max(1, r.width);
    this.cssH = Math.max(1, r.height);
    this.canvas.width = Math.round(this.cssW * this.dpr);
    this.canvas.height = Math.round(this.cssH * this.dpr);
    this.clampPan();
    this.draw(true);
  }

  layout() {
    const fit = Math.min(this.cssW / this.frameW, this.cssH / this.frameH);
    const s = fit * this.zoom;
    const w = this.frameW * s;
    const h = this.frameH * s;
    return { x: (this.cssW - w) / 2 + this.panX, y: (this.cssH - h) / 2 + this.panY, w, h, s };
  }

  clampPan() {
    const fit = Math.min(this.cssW / this.frameW, this.cssH / this.frameH);
    const w = this.frameW * fit * this.zoom;
    const h = this.frameH * fit * this.zoom;
    const mx = Math.max(0, (w - this.cssW) / 2);
    const my = Math.max(0, (h - this.cssH) / 2);
    this.panX = Math.max(-mx, Math.min(mx, this.panX));
    this.panY = Math.max(-my, Math.min(my, this.panY));
  }

  reset() {
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this.draw();
  }

  clear() {
    if (this.bitmap && this.bitmap.close) this.bitmap.close();
    this.bitmap = null;
    this.frames = 0;
    this.reset();
  }

  push(frame, done) {
    this.decoding = this.decoding.then(async () => {
      try {
        const bmp = await createImageBitmap(new Blob([frame.jpeg], { type: 'image/jpeg' }));
        if (this.bitmap && this.bitmap.close) this.bitmap.close();
        const sizeChanged = bmp.width !== this.frameW || bmp.height !== this.frameH;
        this.bitmap = bmp;
        this.frameW = bmp.width;
        this.frameH = bmp.height;
        if (sizeChanged) this.clampPan();
        if (frame.cx >= 0 && !this.cursorLocked()) this.cursor = { x: frame.cx, y: frame.cy };
        this.frames += 1;
        if (this.frames === 1 && this.onFirstFrame) this.onFirstFrame();
        this.draw();
      } catch (err) {
        console.warn('orbit: frame decode failed', err);
      } finally {
        done();
      }
    });
  }

  // While the user is actively moving the pointer we trust the local estimate.
  cursorLocked() { return performance.now() - (this.localMoveAt || 0) < 350; }

  setHostCursor(x, y) {
    if (this.cursorLocked()) return;
    this.cursor = { x, y };
    this.draw();
  }

  moveLocalCursor(nx, ny) {
    this.localMoveAt = performance.now();
    this.cursor = { x: Math.max(0, Math.min(1, nx)), y: Math.max(0, Math.min(1, ny)) };
    this.follow();
    this.draw();
  }

  draw(sync = false) {
    if (sync) { this.render(); return; }
    if (this.pending) return;
    this.pending = true;
    requestAnimationFrame(() => { this.pending = false; this.render(); });
  }

  render() {
    const { ctx, dpr } = this;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#08090a';
    ctx.fillRect(0, 0, this.cssW, this.cssH);
    if (!this.bitmap) return;
    const L = this.layout();
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = L.s < 1 ? 'high' : 'medium';
    ctx.drawImage(this.bitmap, L.x, L.y, L.w, L.h);
    if (this.showCursor && this.cursor.x >= 0) this.drawCursor(L.x + this.cursor.x * L.w, L.y + this.cursor.y * L.h);
  }

  drawCursor(x, y) {
    const ctx = this.ctx;
    const s = 1.05;
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(s, s);
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(0, 17);
    ctx.lineTo(4.2, 13.2);
    ctx.lineTo(7.2, 19.6);
    ctx.lineTo(10, 18.4);
    ctx.lineTo(7.1, 12.2);
    ctx.lineTo(12.6, 12.2);
    ctx.closePath();
    ctx.shadowColor = 'rgba(0,0,0,.45)';
    ctx.shadowBlur = 4;
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.lineWidth = 1.2;
    ctx.strokeStyle = '#111216';
    ctx.stroke();
    ctx.restore();
  }

  toNormalized(clientX, clientY) {
    const r = this.canvas.getBoundingClientRect();
    const L = this.layout();
    return {
      x: Math.max(0, Math.min(1, (clientX - r.left - L.x) / L.w)),
      y: Math.max(0, Math.min(1, (clientY - r.top - L.y) / L.h)),
    };
  }

  zoomAt(factor, clientX, clientY) {
    const r = this.canvas.getBoundingClientRect();
    const px = clientX - r.left;
    const py = clientY - r.top;
    const before = this.layout();
    const ix = (px - before.x) / before.w;
    const iy = (py - before.y) / before.h;
    this.zoom = Math.max(1, Math.min(6, this.zoom * factor));
    const after = this.layout();
    this.panX += px - (after.x + ix * after.w);
    this.panY += py - (after.y + iy * after.h);
    this.clampPan();
    this.draw();
  }

  panBy(dx, dy) {
    this.panX += dx;
    this.panY += dy;
    this.clampPan();
    this.draw();
  }

  // Keep the cursor visible when zoomed in (trackpad mode).
  follow() {
    if (this.zoom <= 1.01 || this.cursor.x < 0) return;
    const L = this.layout();
    const cx = L.x + this.cursor.x * L.w;
    const cy = L.y + this.cursor.y * L.h;
    const mx = this.cssW * 0.18;
    const my = this.cssH * 0.18;
    if (cx < mx) this.panX += mx - cx;
    if (cx > this.cssW - mx) this.panX -= cx - (this.cssW - mx);
    if (cy < my) this.panY += my - cy;
    if (cy > this.cssH - my) this.panY -= cy - (this.cssH - my);
    this.clampPan();
  }

  displayedWidth() { return this.layout().w; }
}
