// Thin wrapper around the Android shell's OrbitNative plugin (no-ops in a browser).
const cap = globalThis.Capacitor;
export const isNative = !!(cap && typeof cap.isNativePlatform === 'function' && cap.isNativePlatform());

function call(method, options = {}) {
  if (!isNative) return Promise.reject(new Error('native unavailable'));
  if (typeof cap.nativePromise === 'function') return cap.nativePromise('OrbitNative', method, options);
  const plugin = cap.Plugins && cap.Plugins.OrbitNative;
  if (plugin && plugin[method]) return plugin[method](options);
  return Promise.reject(new Error('plugin missing'));
}

export const native = {
  async discover(timeout = 1600) {
    if (!isNative) return [];
    try {
      const res = await call('discover', { timeout });
      return Array.isArray(res && res.devices) ? res.devices : [];
    } catch {
      return [];
    }
  },
  openTunnel(host, port, pin) { return call('openTunnel', { host, port: Number(port), pin }); },
  keepAwake(enabled) { return call('keepAwake', { enabled }).catch(() => {}); },
  immersive(enabled) { return call('setImmersive', { enabled }).catch(() => {}); },
  async syncInsets() {
    if (!isNative) return;
    try {
      const i = await call('getInsets');
      const st = document.documentElement.style;
      for (const k of ['top', 'right', 'bottom', 'left']) st.setProperty(`--orbit-inset-${k}`, `${Math.max(0, Number(i[k]) || 0)}px`);
    } catch { /* older shell: CSS env() fallback */ }
  },
  haptic() {
    return call('haptic').catch(() => { if (navigator.vibrate) navigator.vibrate(8); });
  },
  async deviceName() {
    try {
      const info = await call('deviceInfo');
      return (info && info.name) || 'Android phone';
    } catch {
      return /Android/i.test(navigator.userAgent) ? 'Android phone' : 'Browser';
    }
  },
};
