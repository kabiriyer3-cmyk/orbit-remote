// Orbit phone client — app shell.
import { hydrateIcons, icon } from './icons.js';
import { store } from './store.js';
import { native, isNative } from './native.js';
import { OrbitSession } from './session.js';
import { Viewer } from './viewer.js';
import { player } from './audio.js';
import { GestureController, KeyboardSink, Modifiers } from './input.js';
import { openSheet, closeSheet, toast, confirmSheet, escapeHtml as esc, sheetOpen } from './ui.js';

const VERSION = '1.2.0';
const REPO_URL = 'https://github.com/kabiriyer3-cmyk/orbit-remote';
const DEFAULT_PORT = 47800;
const $ = (id) => document.getElementById(id);

const QUALITY = {
  speed: { quality: 50, maxWidth: 1280, fps: 30, label: 'Speed', hint: 'Lower detail, lowest latency' },
  balanced: { quality: 68, maxWidth: 1600, fps: 30, label: 'Balanced', hint: 'Best for most Wi‑Fi networks' },
  sharp: { quality: 85, maxWidth: 2560, fps: 24, label: 'Sharp', hint: 'Crisp text, needs a strong network' },
};


hydrateIcons();
$('app-version').textContent = `v${VERSION}`;
document.body.classList.toggle('native', isNative);

let deviceName = 'Phone';
native.deviceName().then((n) => { deviceName = n; });

// ─────────────────────────────── Connect screen
const addrInput = $('in-address');
const codeInput = $('in-code');
const codeBox = $('code-input');
const cells = [...codeBox.querySelectorAll('span')];
const connectBtn = $('btn-connect');

function formatAddress(address, port) {
  const host = address.includes(':') ? `[${address}]` : address;
  return Number(port) === DEFAULT_PORT ? address : `${host}:${port}`;
}

function parseAddress(text) {
  const raw = text.trim().replace(/^(ws|http)s?:\/\//i, '').replace(/\/.*$/, '');
  if (!raw) return null;
  let address = raw;
  let port = DEFAULT_PORT;
  const v6 = raw.match(/^\[([^\]]+)\](?::(\d+))?$/);
  if (v6) { address = v6[1]; port = Number(v6[2] || DEFAULT_PORT); }
  else if ((raw.match(/:/g) || []).length === 1) {
    const [h, p] = raw.split(':');
    address = h;
    port = Number(p) || DEFAULT_PORT;
  }
  if (!/^[\w.\-:]+$/.test(address) || port < 1 || port > 65535) return null;
  return { address, port };
}

function renderCode() {
  const v = codeInput.value.replace(/\D/g, '').slice(0, 6);
  if (codeInput.value !== v) codeInput.value = v;
  cells.forEach((c, i) => {
    c.textContent = v[i] || '';
    c.classList.toggle('filled', !!v[i]);
    c.classList.toggle('active', i === Math.min(v.length, 5));
  });
  codeBox.classList.remove('error');
}

function setCodeEnabled(on) { codeBox.classList.toggle('disabled', !on); }

function setConnecting(label) {
  connectBtn.disabled = !!label;
  connectBtn.querySelector('span').textContent = label || 'Connect';
}

if (store.last.address) addrInput.value = formatAddress(store.last.address, store.last.port);
$('in-remember').checked = store.prefs.remember !== false;
codeInput.addEventListener('input', () => {
  renderCode();
  if (codeInput.value.length === 6 && parseAddress(addrInput.value)) codeInput.blur();
});
codeInput.addEventListener('focus', () => codeBox.classList.add('focus'));
codeInput.addEventListener('blur', () => codeBox.classList.remove('focus'));
addrInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); codeInput.focus(); } });
addrInput.addEventListener('input', () => {
  const t = parseAddress(addrInput.value);
  const known = t && store.hostByAddress(t.address, t.port);
  setCodeEnabled(!(known && known.token));
});
renderCode();

$('connect-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const target = parseAddress(addrInput.value);
  if (!target) {
    toast('Enter the address shown in Orbit on your PC', 'warning');
    addrInput.focus();
    return;
  }
  const known = store.hostByAddress(target.address, target.port);
  if (!(known && known.token) && codeInput.value.length !== 6) {
    codeBox.classList.add('error');
    toast('Enter the 6-digit session code', 'warning');
    codeInput.focus();
    return;
  }
  startSession({ ...target, code: codeInput.value, remember: $('in-remember').checked });
});

function ago(ts) {
  if (!ts) return 'never';
  const s = Math.round((Date.now() - ts) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function hostRow(h, extra = '') {
  return `<div class="row" role="button" tabindex="0" data-id="${esc(h.id)}" data-address="${esc(h.address)}" data-port="${h.port}">
    <span class="row-icon">${icon('monitor')}</span>
    <span class="row-main"><span class="row-title-line"><span class="row-title">${esc(h.name || 'PC')}</span>${h.token ? `<span class="trust-ic" title="Trusted" aria-label="Trusted">${icon('shieldCheck')}</span>` : ''}</span>
      <span class="row-sub">${esc(formatAddress(h.address, h.port))}${extra}</span></span>
    <span class="row-end">${h.token ? `<span class="badge badge-accent">${icon('shieldCheck')}Trusted</span>` : ''}
      ${h.more ? `<button class="icon-btn" data-more="${esc(h.id)}" aria-label="Options">${icon('more')}</button>` : icon('chevronRight')}</span>
  </div>`;
}

function renderRecent() {
  const hosts = store.hosts();
  $('section-recent').classList.toggle('hidden', hosts.length === 0);
  $('list-recent').innerHTML = hosts.map((h) => hostRow({ ...h, more: true }, ` · ${ago(h.lastUsed)}`)).join('');
}

function useHost(address, port, id) {
  const known = (id && store.host(id)) || store.hostByAddress(address, port);
  addrInput.value = formatAddress(address, port);
  if (known && known.token && known.address === address) {
    startSession({ address, port, code: '', remember: true });
    return;
  }
  setCodeEnabled(true);
  codeInput.focus();
}

$('list-recent').addEventListener('click', (e) => {
  const more = e.target.closest('[data-more]');
  if (more) { e.stopPropagation(); hostOptions(more.dataset.more); return; }
  const row = e.target.closest('.row');
  if (row) useHost(row.dataset.address, Number(row.dataset.port), row.dataset.id);
});

function hostOptions(id) {
  const h = store.host(id);
  if (!h) return;
  const el = openSheet(`
    <div class="sheet-head"><div class="sheet-icon" data-icon="monitor"></div>
      <div><h3>${esc(h.name)}</h3><p>${esc(formatAddress(h.address, h.port))}</p></div></div>
    <div class="sheet-body">
      <div class="kv"><span>Security key</span><span>${esc(h.fingerprint || '—')}</span></div>
      <div class="kv"><span>Access</span><span>${h.token ? 'Trusted — no code needed' : 'Session code'}</span></div>
      <div class="kv"><span>Last connected</span><span>${ago(h.lastUsed)}</span></div>
    </div>
    <div class="sheet-actions">
      <button class="btn btn-secondary" data-act="forget">Forget</button>
      <button class="btn btn-primary" data-act="connect">Connect</button>
    </div>`);
  el.querySelector('[data-act="connect"]').onclick = () => { closeSheet(); useHost(h.address, h.port, h.id); };
  el.querySelector('[data-act="forget"]').onclick = () => {
    store.forget(id);
    closeSheet();
    renderRecent();
    renderNearby(lastNearby);
    toast(`${h.name} forgotten`, 'success');
  };
}

// Nearby discovery (UDP broadcast through the Android shell)
let lastNearby = [];
let scanning = false;
function renderNearby(devices) {
  lastNearby = devices;
  const list = $('list-nearby');
  let empty = $('nearby-empty');
  if (!empty) {
    empty = document.createElement('div');
    empty.id = 'nearby-empty';
    empty.className = 'empty';
    list.after(empty);
  }
  list.innerHTML = devices.map((d) => {
    const known = store.host(d.id);
    return hostRow({ id: d.id, name: d.name, address: d.address, port: d.port || DEFAULT_PORT, token: known && known.token }, d.version ? ` · Orbit ${esc(d.version)}` : '');
  }).join('');
  empty.classList.toggle('hidden', devices.length > 0);
  empty.innerHTML = isNative
    ? `${icon('wifi')}<span>${scanning ? 'Looking for PCs running Orbit…' : 'No PCs found. Open Orbit on your PC and join the same Wi‑Fi.'}</span>`
    : `${icon('info')}<span>Automatic discovery works in the Orbit Android app. Enter the address manually.</span>`;
}

async function scan() {
  if (scanning || !isNative) { renderNearby(lastNearby); return; }
  scanning = true;
  const btn = $('btn-scan');
  btn.classList.add('busy');
  renderNearby(lastNearby);
  const devices = await native.discover(1800);
  scanning = false;
  btn.classList.remove('busy');
  renderNearby(devices);
}
$('btn-scan').addEventListener('click', scan);
$('list-nearby').addEventListener('click', (e) => {
  const row = e.target.closest('.row');
  if (row) useHost(row.dataset.address, Number(row.dataset.port), row.dataset.id);
});

$('btn-about').addEventListener('click', () => {
  openSheet(`
    <div class="sheet-head"><img src="img/logo.svg" alt="">
      <div><h3>Orbit ${VERSION}</h3><p>Mouse and keyboard for a Windows PC on your Wi‑Fi</p></div></div>
    <div class="sheet-body">
      <div class="sheet-section"><h4>Gestures</h4>
        <div class="kv"><span>Tap</span><span>Left click</span></div>
        <div class="kv"><span>Two‑finger tap</span><span>Right click</span></div>
        <div class="kv"><span>Two‑finger drag</span><span>Scroll</span></div>
        <div class="kv"><span>Pinch</span><span>Zoom the view</span></div>
        <div class="kv"><span>Press &amp; hold</span><span>Drag (trackpad) · right click (touch)</span></div>
        <div class="kv"><span>Three‑finger tap</span><span>Keyboard</span></div></div>
      <div class="sheet-section"><h4>Security</h4>
        <p class="muted">The connection is encrypted and tied to the PC's security key. A new phone needs the one-time code, and someone at the PC has to accept it.</p></div>
    </div>
    <div class="sheet-actions">
      <a class="btn btn-secondary" href="${REPO_URL}" target="_blank" rel="noopener">GitHub</a>
      <button class="btn btn-primary" data-act="close">Done</button>
    </div>`).querySelector('[data-act="close"]').onclick = () => closeSheet();
});

// ─────────────────────────────── Session
const viewer = new Viewer($('screen'), $('stage'));
let current = null; // { session, target, ready }
const activeSession = () => (current && current.ready ? current.session : null);
const gestures = new GestureController($('stage'), viewer, () => {
  const s = activeSession();
  return s && !(s.session && s.session.viewOnly) ? s : null;
});
const modifiers = new Modifiers(renderMods);
const keyboard = new KeyboardSink($('kbd'), () => {
  const s = activeSession();
  return s && !(s.session && s.session.viewOnly) ? s : null;
}, modifiers);

function verifySheet(info, target) {
  return new Promise((resolve) => {
    const prior = store.hostByAddress(target.address, target.port);
    const warn = prior && prior.id !== info.id
      ? `<p class="warn">This address used to belong to <b>${esc(prior.name)}</b>, which had a different security key. Continue only if you reinstalled Orbit or this is a different PC.</p>` : '';
    const groups = info.fingerprint.split(' ').map((g) => `<span>${esc(g)}</span>`).join('');
    const el = openSheet(`
      <div class="sheet-head"><div class="sheet-icon accent" data-icon="shield"></div>
        <div><h3>Verify ${esc(info.name)}</h3><p>First connection to this PC</p></div></div>
      <div class="sheet-body">
        ${warn}
        <p>Check that Orbit on your PC shows the same <b>security key</b>:</p>
        <div class="fingerprint">${groups}</div>
        <p class="muted">Orbit remembers this key and warns you if it ever changes.</p>
      </div>
      <div class="sheet-actions">
        <button class="btn btn-secondary" data-act="cancel">Cancel</button>
        <button class="btn btn-primary" data-act="ok">It matches</button>
      </div>`, { onClose: (r) => resolve(r === true) });
    el.querySelector('[data-act="cancel"]').onclick = () => closeSheet(false);
    el.querySelector('[data-act="ok"]').onclick = () => closeSheet(true);
  });
}

function pendingSheet(s) {
  const el = openSheet(`
    <div class="pending-art"><div class="spinner"></div></div>
    <div class="sheet-head" style="justify-content:center;text-align:center;margin-top:12px">
      <div><h3>Waiting for approval</h3><p>Accept the request in Orbit on ${esc(s.hostName || 'your PC')}</p></div></div>
    <div class="sheet-actions single"><button class="btn btn-secondary" data-act="cancel">Cancel</button></div>`,
  { dismissible: false });
  el.querySelector('[data-act="cancel"]').onclick = () => { closeSheet(); s.disconnect(); };
}

function startSession(target) {
  if (current) return;
  store.setLast(target.address, target.port);
  store.setPref('remember', target.remember);
  setConnecting('Connecting…');
  const saved = store.hostByAddress(target.address, target.port);
  const s = new OrbitSession({
    address: target.address,
    port: target.port,
    pin: (saved && saved.fingerprint) || '',
    pinnedHostId: saved && saved.id,
    code: target.code,
    clientId: store.clientId,
    deviceName,
    remember: target.remember,
    resolveHost: (id) => store.host(id),
    verify: (info) => verifySheet(info, target),
  });
  current = { session: s, target, ready: false };
  s.addEventListener('state', (e) => {
    const st = e.detail.state;
    if (st === 'securing') setConnecting('Securing…');
    if (st === 'authenticating') setConnecting('Signing in…');
    if (st === 'pending') { setConnecting('Waiting…'); pendingSheet(s); }
  });
  s.addEventListener('ready', (e) => onReady(s, e.detail));
  s.addEventListener('failed', (e) => onFailed(s, e.detail.reason));
  s.addEventListener('closed', (e) => onClosed(s, e.detail.reason));
  s.addEventListener('frame', (e) => {
    const f = e.detail;
    frameTimes.push(performance.now());
    viewer.push(f, () => s.ack(f.seq));
  });
  s.addEventListener('cursor', (e) => viewer.setHostCursor(e.detail.x, e.detail.y));
  s.addEventListener('rtt', updateStats);
  s.addEventListener('monitor', () => { viewer.reset(); toast('Display switched', 'success', 1600); });
  s.addEventListener('audio', (e) => player.push(e.detail.pcm));
  s.addEventListener('audiostate', (e) => onAudioState(s, e.detail));
  s.addEventListener('control', (e) => {
    toast(e.detail.viewOnly ? 'The PC switched this session to view only' : 'Control enabled', e.detail.viewOnly ? 'warning' : 'success');
  });
  s.connect();
}

function onReady(s, d) {
  if (!current || current.session !== s) return;
  const t = current.target;
  const prior = store.host(d.hostId);
  store.upsertHost(d.hostId, {
    name: d.hostName,
    address: t.address,
    port: t.port,
    fingerprint: d.fingerprint,
    token: d.token || (d.authMode === 'token' && prior ? prior.token : undefined),
  });
  current.ready = true;
  if (sheetOpen()) closeSheet();
  setConnecting('');
  codeInput.value = '';
  renderCode();
  enterSession(s, d.session);
  if (d.token) toast(`${d.hostName} trusts this phone now`, 'success');
}

function onFailed(s, reason) {
  if (!current || current.session !== s) return;
  const t = current.target;
  current = null;
  if (sheetOpen()) closeSheet();
  setConnecting('');
  switch (reason) {
    case 'bad_code':
      codeBox.classList.add('error');
      setCodeEnabled(true);
      toast('Wrong session code', 'error');
      codeInput.focus();
      break;
    case 'untrusted':
      if (s.hostId) store.clearToken(s.hostId);
      renderRecent();
      setCodeEnabled(true);
      addrInput.value = formatAddress(t.address, t.port);
      toast('This PC no longer trusts this phone — enter the session code', 'warning', 4200);
      codeInput.focus();
      break;
    case 'need_code':
      setCodeEnabled(true);
      toast('Enter the 6-digit session code', 'warning');
      codeInput.focus();
      break;
    case 'declined': toast('The PC declined the request', 'error'); break;
    case 'locked': toast('Too many wrong codes. Try again in a minute.', 'error', 4200); break;
    case 'busy': toast('This PC already has the maximum number of phones connected', 'error', 4200); break;
    case 'cancelled': break;
    case 'fingerprint': fingerprintSheet(s, t); break;
    case 'handshake':
    case 'crypto': toast('Could not set up a secure connection', 'error'); break;
    case 'insecure_context': toast('This browser blocks the encryption Orbit needs — use the Orbit app', 'error', 5000); break;
    case 'unreachable':
    case 'closed':
    default:
      unreachableSheet(t);
  }
}

function unreachableSheet(t) {
  const el = openSheet(`
    <div class="sheet-head"><div class="sheet-icon danger" data-icon="wifi"></div>
      <div><h3>Can't reach ${esc(formatAddress(t.address, t.port))}</h3><p>Check these and try again</p></div></div>
    <div class="sheet-body">
      <div class="kv"><span>Orbit is open on the PC</span><span>${icon('check')}</span></div>
      <div class="kv"><span>Phone and PC are on the same Wi‑Fi</span><span>${icon('check')}</span></div>
      <div class="kv"><span>The address matches the one in Orbit</span><span>${icon('check')}</span></div>
      <div class="kv"><span>Windows Firewall allows Orbit</span><span>${icon('check')}</span></div>
      <p class="muted" style="margin-top:12px">On the PC: Orbit → Settings → <b>Allow through firewall</b>.</p>
    </div>
    <div class="sheet-actions">
      <button class="btn btn-secondary" data-act="close">Close</button>
      <button class="btn btn-primary" data-act="retry">Try again</button>
    </div>`);
  el.querySelector('[data-act="close"]').onclick = () => closeSheet();
  el.querySelector('[data-act="retry"]').onclick = () => { closeSheet(); setTimeout(() => startSession(t), 240); };
}

function fingerprintSheet(s, t) {
  const known = store.host(s.hostId);
  const el = openSheet(`
    <div class="sheet-head"><div class="sheet-icon danger" data-icon="alert"></div>
      <div><h3>Security key changed</h3><p>${esc(s.hostName || 'This PC')} presented a different key</p></div></div>
    <div class="sheet-body">
      <p>Someone could be impersonating your PC. If you just reinstalled Orbit or reset its settings, you can forget the old key and pair again.</p>
      <div class="kv"><span>Saved key</span><span>${esc(known ? known.fingerprint : '—')}</span></div>
      <div class="kv"><span>New key</span><span>${esc(s.fingerprint || '—')}</span></div>
    </div>
    <div class="sheet-actions">
      <button class="btn btn-secondary" data-act="close">Cancel</button>
      <button class="btn btn-danger" data-act="forget">Forget &amp; re-pair</button>
    </div>`);
  el.querySelector('[data-act="close"]').onclick = () => closeSheet();
  el.querySelector('[data-act="forget"]').onclick = () => {
    store.forget(s.hostId);
    closeSheet();
    renderRecent();
    setCodeEnabled(true);
    addrInput.value = formatAddress(t.address, t.port);
    toast('Enter the session code to pair again', 'info');
    codeInput.focus();
  };
}

function onClosed(s, reason) {
  if (!current || current.session !== s) return;
  const t = current.target;
  current = null;
  exitSession();
  if (reason === 'user') return;
  if (reason === 'lost') {
    confirmSheet({ title: 'Connection lost', body: `<p>The connection to the PC dropped.</p>`, confirm: 'Reconnect', iconName: 'wifi' })
      .then((again) => { if (again) startSession(t); });
  } else {
    toast(reason || 'Disconnected', 'info', 3200);
  }
}

// ─────────────────────────────── Session view
const sessionView = $('view-session');
const statusEl = $('stage-status');
let frameTimes = [];
let statsTimer = 0;

function enterSession(s, info) {
  $('view-connect').classList.add('hidden');
  sessionView.classList.remove('hidden', 'immersive', 'kbd-open');
  $('btn-restore').classList.add('hidden');
  $('hud-name').textContent = info.name || s.hostName;
  statusEl.classList.remove('gone', 'hidden');
  $('stage-status-text').textContent = 'Waiting for the first frame…';
  viewer.clear();
  viewer.showCursor = store.prefs.showCursor !== false;
  viewer.onFirstFrame = () => { statusEl.classList.add('gone'); setTimeout(() => statusEl.classList.add('hidden'), 300); };
  viewer.resize();
  setMode(store.prefs.mode || 'trackpad', false);
  gestures.speed = Number(store.prefs.speed) || 1;
  s.config(QUALITY[store.prefs.quality] || QUALITY.balanced);
  frameTimes = [];
  clearInterval(statsTimer);
  statsTimer = setInterval(updateStats, 1000);
  history.pushState({ orbit: 'session' }, '');
  native.keepAwake(true);
  native.immersive(true);
  if (info.viewOnly) toast('View only — this PC does not allow control', 'warning', 3600);
  soundWanted = false;
  setSoundUi(false);
  $('btn-sound').classList.toggle('hidden', !player.supported);
  if (store.prefs.sound && info.audio !== false) setSound(true);
}

function exitSession() {
  clearInterval(statsTimer);
  soundWanted = false;
  player.stop();
  setSoundUi(false);
  keyboard.close();
  setKeyboardUi(false);
  sessionView.classList.add('hidden');
  $('view-connect').classList.remove('hidden');
  viewer.clear();
  native.keepAwake(false);
  native.immersive(false);
  renderRecent();
  if (history.state && history.state.orbit === 'session') history.back();
}

function updateStats() {
  const s = activeSession();
  if (!s) return;
  const t = performance.now();
  frameTimes = frameTimes.filter((x) => t - x < 1000);
  const rtt = Math.round(s.rtt || 0);
  $('hud-stats').textContent = `${frameTimes.length} fps · ${rtt} ms`;
  $('hud-dot').className = `dot ${rtt < 90 ? 'dot-green' : rtt < 220 ? 'dot-amber' : 'dot-red'}`;
}

function setMode(mode, announce = true) {
  gestures.mode = mode;
  store.setPref('mode', mode);
  const seg = $('seg-mode');
  seg.dataset.mode = mode;
  seg.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
  if (announce) toast(mode === 'touch' ? 'Touch: tap exactly where you want to click' : 'Trackpad: move the pointer like a laptop touchpad', 'info', 2200);
}
$('seg-mode').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-mode]');
  if (b && b.dataset.mode !== gestures.mode) setMode(b.dataset.mode);
});

// Keyboard
let kbdOpenedAt = 0;
let fullHeight = window.innerHeight;
function setKeyboardUi(open) {
  $('modbar').classList.toggle('hidden', !open);
  sessionView.classList.toggle('kbd-open', open);
  $('btn-keyboard').classList.toggle('on', open);
  if (open) kbdOpenedAt = performance.now();
}
function toggleKeyboard() {
  if (sessionView.classList.contains('kbd-open')) {
    keyboard.close();
    setKeyboardUi(false);
  } else {
    fullHeight = Math.max(fullHeight, window.innerHeight);
    if (keyboard.isOpen) $('kbd').blur();
    keyboard.open();
    setKeyboardUi(true);
  }
}
keyboard.onBlur = () => setKeyboardUi(false);
$('btn-keyboard').addEventListener('click', toggleKeyboard);
$('btn-kbd-close').addEventListener('click', () => { keyboard.close(); setKeyboardUi(false); });
gestures.addEventListener('keyboard', toggleKeyboard);
window.addEventListener('resize', () => {
  if (!sessionView.classList.contains('kbd-open')) { fullHeight = Math.max(window.innerHeight, fullHeight * 0.6); return; }
  // Android hides the keyboard with Back without blurring the input.
  if (performance.now() - kbdOpenedAt > 700 && window.innerHeight >= fullHeight - 48) {
    keyboard.close();
    setKeyboardUi(false);
  }
});

function renderMods(state) {
  document.querySelectorAll('#modbar [data-mod]').forEach((b) => {
    const v = state[b.dataset.mod];
    b.classList.toggle('once', v === 1);
    b.classList.toggle('locked', v === 2);
  });
}
const modbar = $('modbar');
modbar.addEventListener('pointerdown', (e) => { if (e.target.closest('button')) e.preventDefault(); });
modbar.addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.mod) modifiers.toggle(b.dataset.mod);
  else if (b.dataset.key) keyboard.sendKey(b.dataset.key);
});

// Shortcuts
const SHORTCUTS = [
  ['Editing', [['Copy', 'Control+c'], ['Paste', 'Control+v'], ['Cut', 'Control+x'], ['Undo', 'Control+z'], ['Redo', 'Control+y'], ['Select all', 'Control+a'], ['Save', 'Control+s'], ['Find', 'Control+f']]],
  ['Windows', [['Switch app', 'Alt+Tab'], ['Close window', 'Alt+F4'], ['Start menu', 'Meta'], ['Show desktop', 'Meta+d'], ['File Explorer', 'Meta+e'], ['Task view', 'Meta+Tab'], ['Screenshot', 'Meta+Shift+s'], ['Task Manager', 'Control+Shift+Escape']]],
];
const KEY_LABEL = { Control: 'Ctrl', Meta: 'Win', Escape: 'Esc', Alt: 'Alt', Shift: 'Shift', Tab: 'Tab' };
const comboHtml = (c) => `<span class="combo">${c.split('+').map((k) => `<kbd>${esc(KEY_LABEL[k] || (k.length === 1 ? k.toUpperCase() : k))}</kbd>`).join('')}</span>`;

$('btn-shortcuts').addEventListener('click', () => {
  const s = activeSession();
  if (!s) return;
  const sections = SHORTCUTS.map(([title, items]) => `<div class="sheet-section"><h4>${title}</h4><div class="grid-keys">
    ${items.map(([label, combo]) => `<button class="keycap" data-combo="${combo}"><span>${label}</span>${comboHtml(combo)}</button>`).join('')}</div></div>`).join('');
  const fkeys = Array.from({ length: 12 }, (_, i) => `<button class="keycap center" data-combo="F${i + 1}">F${i + 1}</button>`).join('');
  const media = [['Vol −', 'VolumeDown'], ['Vol +', 'VolumeUp'], ['Mute', 'VolumeMute'], ['Play', 'MediaPlayPause']]
    .map(([l, k]) => `<button class="keycap center" data-combo="${k}">${l}</button>`).join('');
  const el = openSheet(`
    <div class="sheet-head"><div class="sheet-icon" data-icon="zap"></div><div><h3>Shortcuts</h3><p>Sent straight to the PC</p></div></div>
    <div class="grid-keys">
      <button class="keycap" data-act="type"><span>Type text…</span>${icon('type')}</button>
      <button class="keycap" data-act="lock"><span>Lock PC</span>${icon('lock')}</button>
    </div>
    ${sections}
    <div class="sheet-section"><h4>Function keys</h4><div class="grid-keys cols-4">${fkeys}</div></div>
    <div class="sheet-section"><h4>Media</h4><div class="grid-keys cols-4">${media}</div></div>`);
  el.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.combo) {
      const keys = b.dataset.combo.split('+');
      if (keys.length > 1) s.combo(keys); else s.key(keys[0]);
      native.haptic();
      closeSheet();
    } else if (b.dataset.act === 'type') {
      closeSheet();
      setTimeout(composeSheet, 230);
    } else if (b.dataset.act === 'lock') {
      s.send({ t: 'sys', a: 'lock' });
      closeSheet();
      toast('Lock request sent', 'success');
    }
  });
});

function composeSheet() {
  const s = activeSession();
  if (!s) return;
  const el = openSheet(`
    <div class="sheet-head"><div class="sheet-icon" data-icon="type"></div><div><h3>Type text</h3><p>Pasted into the focused window on the PC</p></div></div>
    <textarea class="compose" id="compose" placeholder="Write or paste text…" autocapitalize="sentences"></textarea>
    <label class="switch-row" style="margin-top:12px"><input type="checkbox" id="compose-enter"><span class="switch"></span><span class="switch-text"><b>Press Enter after</b></span></label>
    <div class="sheet-actions">
      <button class="btn btn-secondary" data-act="cancel">Cancel</button>
      <button class="btn btn-primary" data-act="send">Send</button>
    </div>`);
  const ta = el.querySelector('#compose');
  setTimeout(() => ta.focus(), 260);
  el.querySelector('[data-act="cancel"]').onclick = () => closeSheet();
  el.querySelector('[data-act="send"]').onclick = () => {
    if (ta.value) s.text(ta.value);
    if (el.querySelector('#compose-enter').checked) s.key('Enter');
    closeSheet();
    toast('Text sent', 'success', 1600);
  };
}

// Session settings
$('btn-settings').addEventListener('click', () => {
  const s = activeSession();
  if (!s) return;
  const info = s.session || {};
  const q = store.prefs.quality || 'balanced';
  const speed = Number(store.prefs.speed) || 1;
  const host = store.host(s.hostId) || {};
  const el = openSheet(`
    <div class="sheet-head"><div class="sheet-icon" data-icon="sliders"></div><div><h3>Session</h3><p>${esc(info.name || s.hostName)}</p></div></div>
    <div class="sheet-section"><h4>Picture</h4><div class="option-list">
      ${Object.entries(QUALITY).map(([k, v]) => `<button class="option ${k === q ? 'selected' : ''}" data-q="${k}">
        <span class="row-main"><b>${v.label}</b><small>${v.hint}</small></span>${icon('check', 'check')}</button>`).join('')}
    </div></div>
    <div class="sheet-section range-row">
      <div class="range-top"><span>Pointer speed</span><output id="speed-out">${speed.toFixed(1)}×</output></div>
      <input type="range" id="speed" min="0.4" max="2.4" step="0.1" value="${speed}">
    </div>
    <div class="sheet-section">
      <label class="switch-row"><input type="checkbox" id="show-cursor" ${viewer.showCursor ? 'checked' : ''}><span class="switch"></span>
        <span class="switch-text"><b>Show pointer</b><small>Draw the PC's mouse pointer on the stream</small></span></label>
    </div>
    <div class="sheet-section"><h4>Connection</h4>
      <div class="kv"><span>Address</span><span>${esc(formatAddress(host.address || '', host.port || DEFAULT_PORT))}</span></div>
      <div class="kv"><span>Security key</span><span>${esc(s.fingerprint || '')}</span></div>
      <div class="kv"><span>Access</span><span>${info.trusted ? 'Trusted device' : 'Session code'}${info.viewOnly ? ' · view only' : ''}</span></div>
      <div class="kv"><span>Encryption</span><span>AES‑256‑GCM</span></div>
    </div>`);
  const range = el.querySelector('#speed');
  const paint = () => range.style.setProperty('--fill', `${((range.value - 0.4) / 2) * 100}%`);
  paint();
  range.addEventListener('input', () => {
    paint();
    el.querySelector('#speed-out').textContent = `${Number(range.value).toFixed(1)}×`;
    gestures.speed = Number(range.value);
    store.setPref('speed', gestures.speed);
  });
  el.querySelector('#show-cursor').addEventListener('change', (e) => {
    viewer.showCursor = e.target.checked;
    store.setPref('showCursor', viewer.showCursor);
    viewer.draw();
  });
  el.querySelectorAll('[data-q]').forEach((b) => b.addEventListener('click', () => {
    el.querySelectorAll('[data-q]').forEach((x) => x.classList.toggle('selected', x === b));
    store.setPref('quality', b.dataset.q);
    s.config(QUALITY[b.dataset.q]);
  }));
});

// Sound from the PC
// soundWanted is what the user chose for this session; the host confirms with an 'audio' reply.
let soundWanted = false;
function setSoundUi(on, busy = false) {
  const b = $('btn-sound');
  b.classList.toggle('on', on);
  b.classList.toggle('busy', busy);
  b.setAttribute('aria-pressed', on ? 'true' : 'false');
  b.setAttribute('aria-label', on ? 'Mute PC sound' : 'Play PC sound');
  b.innerHTML = icon(on ? 'volume' : 'volumeOff');
}

async function setSound(on) {
  const s = activeSession();
  if (!s) return;
  soundWanted = on;
  if (!on) {
    s.audio(false);
    player.stop();
    setSoundUi(false);
    return;
  }
  setSoundUi(false, true);
  try {
    await player.start(); // inside the tap handler, so the browser lets it play
  } catch {
    soundWanted = false;
    setSoundUi(false);
    toast('This phone cannot play sound from Orbit', 'error');
    return;
  }
  if (soundWanted && activeSession() === s) s.audio(true);
}

function onAudioState(s, m) {
  if (!current || current.session !== s) return;
  if (m.on && soundWanted) {
    player.start(m.rate, m.channels).catch(() => {});
    setSoundUi(true);
    return;
  }
  soundWanted = false;
  player.stop();
  setSoundUi(false);
  if (m.reason === 'disabled') toast('Sound sharing is turned off on the PC', 'warning', 3600);
  else if (m.reason === 'unavailable') toast('The PC has no sound device to share', 'warning', 3600);
}

$('btn-sound').addEventListener('click', () => {
  const on = !soundWanted;
  store.setPref('sound', on);
  native.haptic();
  setSound(on);
});

// Displays
$('btn-monitors').addEventListener('click', () => {
  const s = activeSession();
  if (!s || !s.session) return;
  const mons = s.session.monitors || [];
  const el = openSheet(`
    <div class="sheet-head"><div class="sheet-icon" data-icon="monitor"></div><div><h3>Displays</h3><p>${mons.length} connected</p></div></div>
    <div class="option-list">${mons.map((m) => `<button class="option ${m.index === s.session.monitor ? 'selected' : ''}" data-i="${m.index}">
      <span class="row-icon">${icon('monitor')}</span>
      <span class="row-main"><b>Display ${m.index}${m.primary ? ' · Primary' : ''}</b><small>${m.width} × ${m.height}</small></span>${icon('check', 'check')}</button>`).join('')}</div>`);
  el.querySelectorAll('[data-i]').forEach((b) => b.addEventListener('click', () => {
    s.monitor(Number(b.dataset.i));
    closeSheet();
  }));
});

// Immersive
$('btn-fullscreen').addEventListener('click', () => { sessionView.classList.add('immersive'); $('btn-restore').classList.remove('hidden'); });
$('btn-restore').addEventListener('click', () => { sessionView.classList.remove('immersive'); $('btn-restore').classList.add('hidden'); });

// Disconnect
async function askDisconnect() {
  const s = activeSession();
  if (!s) return;
  const yes = await confirmSheet({ title: `Disconnect from ${esc(s.hostName)}?`, body: '<p class="muted">You can reconnect any time.</p>', confirm: 'Disconnect', danger: true, iconName: 'power' });
  if (yes && current && current.session === s) s.disconnect();
}
$('btn-disconnect').addEventListener('click', askDisconnect);

// Android back button / browser history
window.addEventListener('popstate', () => {
  if (sheetOpen()) {
    closeSheet();
    if (activeSession()) history.pushState({ orbit: 'session' }, '');
    return;
  }
  if (activeSession()) {
    history.pushState({ orbit: 'session' }, '');
    askDisconnect();
  }
});

// Pause streaming while the app is in the background
document.addEventListener('visibilitychange', () => {
  const s = activeSession();
  if (!s) return;
  if (document.hidden) { s.pause(); if (soundWanted) player.stop(); }
  else {
    s.resume();
    native.immersive(true);
    if (soundWanted) player.start(player.rate, player.channels).catch(() => {});
  }
});

native.syncInsets();
renderRecent();
renderNearby([]);
if (isNative) scan();
