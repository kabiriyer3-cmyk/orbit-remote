// Bottom sheets and toasts.
import { hydrateIcons, icon } from './icons.js';

const backdrop = () => document.getElementById('sheet-backdrop');
const sheetEl = () => document.getElementById('sheet');
let closeHandler = null;
let generation = 0; // guards against a close animation hiding a sheet opened right after it

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function openSheet(html, { onClose, dismissible = true, className = '' } = {}) {
  const el = sheetEl();
  generation += 1;
  el.className = `sheet ${className}`;
  el.innerHTML = `<div class="sheet-handle"></div>${html}`;
  hydrateIcons(el);
  closeHandler = onClose || null;
  backdrop().classList.remove('hidden');
  el.classList.remove('hidden');
  requestAnimationFrame(() => { backdrop().classList.add('show'); el.classList.add('show'); });
  backdrop().onclick = dismissible ? () => closeSheet() : null;
  return el;
}

export function closeSheet(result) {
  const el = sheetEl();
  if (el.classList.contains('hidden')) return;
  el.classList.remove('show');
  backdrop().classList.remove('show');
  const gen = generation;
  setTimeout(() => {
    if (gen !== generation) return;
    el.classList.add('hidden');
    backdrop().classList.add('hidden');
  }, 220);
  const fn = closeHandler;
  closeHandler = null;
  if (fn) fn(result);
}

export function sheetOpen() { return !sheetEl().classList.contains('hidden'); }

export function toast(text, kind = 'info', ms = 2800) {
  const stack = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast toast-${kind}`;
  const ic = { info: 'info', success: 'check', error: 'alert', warning: 'alert' }[kind] || 'info';
  el.innerHTML = `${icon(ic)}<span>${escapeHtml(text)}</span>`;
  stack.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 250); }, ms);
}

export function confirmSheet({ title, body, confirm = 'Continue', cancel = 'Cancel', danger = false, iconName = 'info' }) {
  return new Promise((resolve) => {
    const el = openSheet(`
      <div class="sheet-head"><div class="sheet-icon ${danger ? 'danger' : ''}" data-icon="${iconName}"></div>
        <div><h3>${title}</h3></div></div>
      <div class="sheet-body">${body}</div>
      <div class="sheet-actions">
        <button class="btn btn-secondary" data-act="cancel">${cancel}</button>
        <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-act="ok">${confirm}</button>
      </div>`, { onClose: (r) => resolve(r === true) });
    el.querySelector('[data-act="cancel"]').onclick = () => closeSheet(false);
    el.querySelector('[data-act="ok"]').onclick = () => closeSheet(true);
  });
}
