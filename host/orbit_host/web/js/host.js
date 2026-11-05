// Orbit PC dashboard — talks to the local host service over a loopback-only, token-protected API.
const P = {
  home: '<path d="M3.5 10.5 12 3.5l8.5 7"/><path d="M5.5 9v10.5a1 1 0 0 0 1 1h4v-6h3v6h4a1 1 0 0 0 1-1V9"/>',
  phone: '<rect x="6" y="2.5" width="12" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
  activity: '<path d="M3 12h4l3-7.5 4 15 3-7.5h4"/>',
  sliders: '<path d="M4 6.5h9M17 6.5h3M15 4.5v4M4 12h3M11 12h9M9 10v4M4 17.5h11M19 17.5h1M17 15.5v4"/>',
  power: '<path d="M12 3v8.5"/><path d="M17.7 6.8a8 8 0 1 1-11.4 0"/>',
  shield: '<path d="M12 21s7.5-3.5 7.5-9.5V5.8L12 3 4.5 5.8v5.7C4.5 17.5 12 21 12 21z"/>',
  shieldCheck: '<path d="M12 21s7.5-3.5 7.5-9.5V5.8L12 3 4.5 5.8v5.7C4.5 17.5 12 21 12 21z"/><path d="m9 12 2 2 4-4"/>',
  copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/><path d="M15.5 8.5V6a2.5 2.5 0 0 0-2.5-2.5H6A2.5 2.5 0 0 0 3.5 6v7A2.5 2.5 0 0 0 6 15.5h2.5"/>',
  refresh: '<path d="M20.5 12a8.5 8.5 0 1 1-2.5-6"/><path d="M20.5 3.5v5h-5"/>',
  key: '<circle cx="8" cy="15.5" r="4.5"/><path d="m11.2 12.3 9.3-9.3M17 6.5l2.5 2.5M14.5 9l2 2"/>',
  wifi: '<path d="M2.5 9a14 14 0 0 1 19 0M5.5 12.3a9.5 9.5 0 0 1 13 0M8.6 15.6a5 5 0 0 1 6.8 0"/><path d="M12 19h.01"/>',
  alert: '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5M12 17.5h.01"/>',
  trash: '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l.8 12.2A1.5 1.5 0 0 0 8.8 20.5h6.4a1.5 1.5 0 0 0 1.5-1.3L17.5 7"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  pointer: '<path d="M5 3.5 19 10l-6.2 1.8L10 18z"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  logIn: '<path d="M14 3.5h4a2.5 2.5 0 0 1 2.5 2.5v12a2.5 2.5 0 0 1-2.5 2.5h-4"/><path d="M10 16.5 14.5 12 10 7.5M14.5 12H3.5"/>',
  logOut: '<path d="M10 3.5H6A2.5 2.5 0 0 0 3.5 6v12A2.5 2.5 0 0 0 6 20.5h4"/><path d="M15 16.5 19.5 12 15 7.5M19.5 12h-11"/>',
  bell: '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4.5M12 8h.01"/>',
  lock: '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
};
const icon = (n, cls = '') =>
  `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[n] || ''}</svg>`;
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
document.querySelectorAll('[data-icon]').forEach((el) => { el.insertAdjacentHTML('afterbegin', icon(el.dataset.icon)); el.removeAttribute('data-icon'); });

const token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('orbit.token') || '';
if (token) sessionStorage.setItem('orbit.token', token);
history.replaceState(null, '', location.pathname);

let state = null;
let ws = null;
let retry = 0;
let receivedAt = 0;

// ─── Transport ───
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/api/host/ws?token=${encodeURIComponent(token)}`);
  ws.onopen = () => { retry = 0; $('offline').classList.add('hidden'); };
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'state') { state = msg; receivedAt = Date.now(); render(); }
    } catch { /* ignore malformed frames */ }
  };
  ws.onclose = () => {
    if (state) $('offline').classList.remove('hidden');
    setStatus('red', 'Offline', 'Orbit service is not reachable');
    setTimeout(connect, Math.min(4000, 400 * 2 ** retry++));
  };
}

async function action(name, extra = {}) {
  try {
    const res = await fetch('/api/host/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Orbit-Token': token },
      body: JSON.stringify({ action: name, ...extra }),
    });
    const out = await res.json().catch(() => ({}));
    if (!res.ok || out.ok === false) throw new Error(out.error || res.statusText);
    return true;
  } catch (err) {
    toast(`Couldn’t complete that: ${err.message || err}`, 'error');
    return false;
  }
}

// ─── Helpers ───
function toast(text, kind = 'info', ms = 2600) {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.innerHTML = `${icon(kind === 'success' ? 'check' : kind === 'error' ? 'alert' : 'info')}<span>${esc(text)}</span>`;
  $('toasts').append(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 220); }, ms);
}

async function copy(text, btn) {
  try { await navigator.clipboard.writeText(text); } catch {
    const ta = Object.assign(document.createElement('textarea'), { value: text });
    document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove();
  }
  if (btn) {
    const old = btn.innerHTML;
    btn.classList.add('done');
    btn.innerHTML = `${icon('check')}Copied`;
    setTimeout(() => { btn.classList.remove('done'); btn.innerHTML = old; }, 1400);
  }
}

function duration(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

function ago(ts) {
  if (!ts) return 'never';
  const d = Date.now() / 1000 - ts;
  if (d < 60) return 'just now';
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

const clock = (ts) => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const primaryAddress = () => (state && state.addresses && state.addresses[0]) || '127.0.0.1';
const addressLabel = () => (state && state.port && state.port !== 47800 ? `${primaryAddress()}:${state.port}` : primaryAddress());

function setStatus(color, text, sub, live = false) {
  $('status-dot').className = `dot dot-${color}${live ? ' dot-live' : ''}`;
  $('status-text').textContent = text;
  $('status-sub').textContent = sub;
}

function empty(ic, title, sub) {
  return `<div class="empty"><div class="empty-art">${icon(ic)}</div><b>${esc(title)}</b><span>${esc(sub)}</span></div>`;
}

// ─── Render ───
let lastCode = '';
function render() {
  const s = state;
  const n = s.sessions.length;
  document.title = n ? `Orbit — ${n} connected` : 'Orbit';
  $('side-host').textContent = s.name;
  $('side-version').textContent = `Orbit ${s.version}`;
  $('side-mode').textContent = s.demo ? 'Demo mode' : s.admin ? 'Administrator' : 'Standard user';

  if (s.pending.length) setStatus('amber', 'Access request', `${s.pending[0].device} is waiting`, true);
  else if (n) setStatus('accent', 'In use', `${n} phone${n > 1 ? 's' : ''} connected`, true);
  else setStatus('green', 'Ready', 'Waiting for a phone');

  // Overview
  $('ov-address').textContent = addressLabel();
  $('ov-alt').innerHTML = s.addresses.slice(1, 4).map((a) => `<span class="chip mono">${esc(a)}</span>`).join('');
  $('ov-id').textContent = s.deviceId;
  if (s.code !== lastCode) {
    const cells = $('ov-code').querySelectorAll('span');
    [...s.code].forEach((d, i) => { cells[i].textContent = d; });
    if (lastCode) { $('ov-code').classList.remove('flip'); void $('ov-code').offsetWidth; $('ov-code').classList.add('flip'); }
    lastCode = s.code;
  }
  $('ov-fp').innerHTML = s.fingerprint.split(' ').map((g) => `<span>${esc(g)}</span>`).join('');
  $('btn-disconnect-all').disabled = !n;
  $('ov-session-count').textContent = `${n} / 3`;
  const showAdmin = s.platform === 'win32' && !s.admin && !s.demo && localStorage.getItem('orbit.hideAdmin') !== '1';
  $('admin-banner').classList.toggle('hidden', !showAdmin);

  const sessionsHtml = n
    ? s.sessions.map(sessionRow).join('')
    : empty('phone', 'No one is connected', 'Open Orbit on your phone and enter the address and code above.');
  $('ov-sessions').innerHTML = sessionsHtml;
  $('dev-sessions').innerHTML = n ? s.sessions.map(sessionRow).join('') : empty('phone', 'No active sessions', 'Phones you connect will show up here.');

  // Devices
  $('nav-devices').textContent = n;
  $('nav-devices').classList.toggle('hidden', !n);
  $('dev-trusted-count').textContent = s.trusted.length;
  $('dev-trusted').innerHTML = s.trusted.length
    ? s.trusted.map((t) => `
      <div class="row">
        <span class="row-icon">${icon('phone')}</span>
        <span class="row-main">
          <span class="row-title">${esc(t.name || 'Phone')}<span class="tag green">${icon('shieldCheck')}Trusted</span></span>
          <span class="row-sub">Added ${esc(ago(t.added))} · last seen ${esc(ago(t.lastSeen))}</span>
        </span>
        <span class="row-actions"><button class="btn btn-sm btn-ghost btn-danger" data-revoke="${esc(t.clientId)}" data-name="${esc(t.name || 'Phone')}">${icon('trash')}Remove</button></span>
      </div>`).join('')
    : empty('shield', 'No trusted devices', 'When you approve a phone, tick “Trust this device” to skip the code next time.');

  renderActivity();
  renderSettings();
  renderApproval();
}

function sessionRow(x) {
  const since = Date.now() / 1000 - x.since;
  return `
    <div class="row">
      <span class="row-icon">${icon('phone')}<i class="badge"></i></span>
      <span class="row-main">
        <span class="row-title">${esc(x.device)}${x.trusted ? `<span class="tag green">${icon('shieldCheck')}Trusted</span>` : ''}${x.viewOnly ? '<span class="tag amber">View only</span>' : '<span class="tag accent">Controlling</span>'}</span>
        <span class="row-sub">${esc(x.ip)} · <span data-since="${x.since}">${duration(since)}</span> · ${x.megabytes} MB</span>
      </span>
      <span class="row-actions">
        <button class="btn btn-sm btn-ghost" data-viewonly="${esc(x.id)}" data-value="${x.viewOnly ? '0' : '1'}">${icon(x.viewOnly ? 'pointer' : 'eye')}${x.viewOnly ? 'Allow control' : 'View only'}</button>
        <button class="btn btn-sm btn-ghost btn-danger" data-disconnect="${esc(x.id)}">${icon('power')}Disconnect</button>
      </span>
    </div>`;
}

const EV_ICON = { connect: 'logIn', disconnect: 'logOut', request: 'bell', security: 'shield', warning: 'alert', info: 'info' };
let filter = 'all';
function renderActivity() {
  const items = state.activity.slice().reverse().filter((e) => {
    if (filter === 'all') return true;
    if (filter === 'connect') return e.kind === 'connect' || e.kind === 'disconnect';
    if (filter === 'security') return e.kind === 'security' || e.kind === 'warning';
    return e.kind === filter;
  });
  $('act-list').innerHTML = items.length
    ? items.map((e) => `
      <div class="row">
        <span class="ev-icon ev-${esc(e.kind)}">${icon(EV_ICON[e.kind] || 'info')}</span>
        <span class="ev-text">${esc(e.text)}</span>
        <span class="ev-time" title="${esc(new Date(e.ts * 1000).toLocaleString())}">${esc(clock(e.ts))}</span>
      </div>`).join('')
    : empty('activity', 'Nothing here yet', 'Connections and security events will appear as they happen.');
}

function setSegment(id, value) {
  $(id).querySelectorAll('button').forEach((b) => b.classList.toggle('active', Number(b.dataset.v) === Number(value)));
}

function setRange(value) {
  const r = $('set-quality');
  r.value = value;
  $('set-quality-out').textContent = value;
  r.style.setProperty('--p', `${((value - r.min) / (r.max - r.min)) * 100}%`);
}

function renderSettings() {
  const st = state.settings;
  if (document.activeElement !== $('set-name')) $('set-name').value = st.deviceName;
  $('set-autostart').checked = !!st.autostart;
  $('set-autostart').disabled = state.platform !== 'win32';
  $('set-approval').checked = !!st.requireApproval;
  $('set-input').checked = !!st.allowInput;
  if (!draggingRange) setRange(st.quality);
  setSegment('set-fps', st.fps);
  setSegment('set-width', st.maxWidth);
  $('set-elevate').disabled = state.admin || state.platform !== 'win32';
  $('set-elevate').textContent = state.admin ? 'Running as admin' : 'Restart as admin';
  $('about-version').textContent = state.version;
  $('about-input').textContent = state.demo ? 'Demo input' : `${state.input} input`;
}

// ─── Approval dialog ───
let shownRequest = null;
function renderApproval() {
  const req = state.pending[0];
  if (!req) { $('approval').classList.add('hidden'); shownRequest = null; return; }
  if (shownRequest !== req.id) {
    shownRequest = req.id;
    $('ap-device').textContent = req.device;
    $('ap-sub').textContent = `Connecting from ${req.ip} on your network`;
    $('ap-fp').textContent = state.fingerprint;
    $('ap-trust').checked = !!req.wantsTrust;
    $('approval').classList.remove('hidden');
    $('ap-accept').focus();
  }
  const more = state.pending.length - 1;
  $('ap-more').classList.toggle('hidden', more < 1);
  $('ap-more').textContent = `+${more} more waiting`;
  tickApproval();
}

function tickApproval() {
  const req = state && state.pending[0];
  if (!req) return;
  const left = Math.max(0, req.timeout - req.age - (Date.now() - receivedAt) / 1000);
  $('ap-timer').textContent = `${Math.ceil(left)} s`;
  $('ap-bar').style.transform = `scaleX(${left / req.timeout})`;
}

$('ap-accept').onclick = () => shownRequest && action('approve', { id: shownRequest, trust: $('ap-trust').checked });
$('ap-decline').onclick = () => shownRequest && action('decline', { id: shownRequest });
document.addEventListener('keydown', (e) => {
  if ($('approval').classList.contains('hidden')) return;
  if (e.key === 'Escape') $('ap-decline').click();
});

// ─── Events ───
$('nav').addEventListener('click', (e) => {
  const b = e.target.closest('.nav-item');
  if (!b) return;
  document.querySelectorAll('.nav-item').forEach((x) => x.classList.toggle('active', x === b));
  document.querySelectorAll('.page').forEach((p) => p.classList.toggle('hidden', p.dataset.page !== b.dataset.page));
  document.querySelector('.main').scrollTop = 0;
});

document.addEventListener('click', async (e) => {
  const t = e.target.closest('button');
  if (!t || !state) return;
  if (t.dataset.action) {
    const a = t.dataset.action;
    if (a === 'disconnect_all' && !confirm('Disconnect every phone?')) return;
    const ok = await action(a);
    if (!ok) return;
    if (a === 'regenerate_code') toast('New session code generated', 'success');
    if (a === 'firewall') toast('Confirm the Windows prompt to add the firewall rule');
    if (a === 'disconnect_all') toast('All phones disconnected', 'success');
  } else if (t.dataset.copy) {
    copy(t.dataset.copy === 'code' ? state.code : addressLabel(), t);
  } else if (t.dataset.disconnect) {
    if (await action('disconnect', { id: t.dataset.disconnect })) toast('Phone disconnected', 'success');
  } else if (t.dataset.viewonly) {
    action('view_only', { id: t.dataset.viewonly, value: t.dataset.value === '1' });
  } else if (t.dataset.revoke) {
    if (!confirm(`Remove ${t.dataset.name}? It will need a session code to connect again.`)) return;
    if (await action('revoke', { clientId: t.dataset.revoke })) toast(`${t.dataset.name} removed`, 'success');
  } else if (t.classList.contains('filter')) {
    filter = t.dataset.filter;
    document.querySelectorAll('.filter').forEach((f) => f.classList.toggle('active', f === t));
    renderActivity();
  } else if (t.dataset.v && t.closest('.segmented')) {
    const key = t.closest('.segmented').id === 'set-fps' ? 'fps' : 'maxWidth';
    setSegment(t.closest('.segmented').id, t.dataset.v);
    action('settings', { values: { [key]: Number(t.dataset.v) } });
  } else if (t.id === 'banner-close') {
    localStorage.setItem('orbit.hideAdmin', '1');
    $('admin-banner').classList.add('hidden');
  }
});

const saveSetting = (key, value) => action('settings', { values: { [key]: value } });
$('set-approval').onchange = (e) => saveSetting('requireApproval', e.target.checked);
$('set-input').onchange = (e) => saveSetting('allowInput', e.target.checked);
$('set-autostart').onchange = async (e) => {
  if (await action('autostart', { value: e.target.checked })) toast(e.target.checked ? 'Orbit will start with Windows' : 'Autostart turned off', 'success');
};
const saveName = () => {
  const v = $('set-name').value.trim();
  if (v && state && v !== state.settings.deviceName) saveSetting('deviceName', v).then((ok) => ok && toast('Device name saved', 'success'));
};
$('set-name').addEventListener('blur', saveName);
$('set-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') e.target.blur(); });
let draggingRange = false;
$('set-quality').addEventListener('input', (e) => { draggingRange = true; setRange(Number(e.target.value)); });
$('set-quality').addEventListener('change', (e) => { draggingRange = false; saveSetting('quality', Number(e.target.value)); });

$('admin-banner').insertAdjacentHTML('beforeend', `<button class="btn btn-sm btn-ghost" id="banner-close" aria-label="Dismiss">${icon('x')}</button>`);

setInterval(() => {
  document.querySelectorAll('[data-since]').forEach((el) => { el.textContent = duration(Date.now() / 1000 - Number(el.dataset.since)); });
  tickApproval();
}, 1000);

if (!token) {
  setStatus('red', 'Not authorised', 'Open the dashboard from the Orbit tray icon');
  document.querySelector('.page').insertAdjacentHTML('afterbegin', '<div class="banner"><span class="banner-icon">' + icon('lock') + '</span><div class="banner-text"><b>Missing access token</b><span>Open this dashboard from the Orbit tray icon.</span></div></div>');
} else {
  connect();
}
