// Local persistence: client identity, known PCs (pinned keys + trust tokens) and preferences.
const KEY = 'orbit.v1';

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
}

const defaults = () => ({
  clientId: uuid(),
  deviceName: '',
  hosts: {},
  last: { address: '', port: 47800 },
  prefs: { mode: 'trackpad', speed: 1, quality: 'balanced', showCursor: true, remember: true },
});

let state;
try {
  state = Object.assign(defaults(), JSON.parse(localStorage.getItem(KEY) || '{}'));
  state.prefs = Object.assign(defaults().prefs, state.prefs || {});
} catch {
  state = defaults();
}
const save = () => localStorage.setItem(KEY, JSON.stringify(state));
save();

export const store = {
  get clientId() { return state.clientId; },
  get prefs() { return state.prefs; },
  get last() { return state.last; },
  setPref(key, value) { state.prefs[key] = value; save(); },
  setLast(address, port) { state.last = { address, port }; save(); },
  hosts() {
    return Object.values(state.hosts).sort((a, b) => (b.lastUsed || 0) - (a.lastUsed || 0));
  },
  host(id) { return state.hosts[id] || null; },
  hostByAddress(address, port) {
    return Object.values(state.hosts).find((h) => h.address === address && Number(h.port) === Number(port)) || null;
  },
  upsertHost(id, data) {
    state.hosts[id] = Object.assign({ id }, state.hosts[id] || {}, data, { lastUsed: Date.now() });
    save();
    return state.hosts[id];
  },
  clearToken(id) {
    if (state.hosts[id]) { delete state.hosts[id].token; save(); }
  },
  forget(id) { delete state.hosts[id]; save(); },
};
