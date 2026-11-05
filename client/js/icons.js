// Minimal stroke icon set (24×24, 1.75px strokes).
const P = {
  monitor: '<rect x="2.5" y="3.5" width="19" height="13" rx="2"/><path d="M8 20.5h8M12 16.5v4"/>',
  keyboard: '<rect x="2.5" y="5.5" width="19" height="13" rx="2.5"/><path d="M6.5 9.5h.01M10 9.5h.01M14 9.5h.01M17.5 9.5h.01M6.5 12.5h.01M17.5 12.5h.01M10 12.5h4M8 15.5h8"/>',
  pointer: '<path d="M5 3.5 19 10l-6.2 1.8L10 18z"/>',
  hand: '<path d="M8.5 12.5V5a1.5 1.5 0 0 1 3 0v6"/><path d="M11.5 10.5V9a1.5 1.5 0 0 1 3 0v2"/><path d="M14.5 10a1.5 1.5 0 0 1 3 0v1.5"/><path d="M17.5 11a1.5 1.5 0 0 1 3 0v3.5a7 7 0 0 1-7 7h-1.3a6 6 0 0 1-4.9-2.6l-3-4.4a1.6 1.6 0 0 1 2.5-2l1.7 1.9"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  sliders: '<path d="M4 6.5h9M17 6.5h3M15 4.5v4M4 12h3M11 12h9M9 10v4M4 17.5h11M19 17.5h1M17 15.5v4"/>',
  power: '<path d="M12 3v8.5"/><path d="M17.7 6.8a8 8 0 1 1-11.4 0"/>',
  copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/><path d="M15.5 8.5V6a2.5 2.5 0 0 0-2.5-2.5H6A2.5 2.5 0 0 0 3.5 6v7A2.5 2.5 0 0 0 6 15.5h2.5"/>',
  refresh: '<path d="M20.5 12a8.5 8.5 0 1 1-2.5-6"/><path d="M20.5 3.5v5h-5"/>',
  shield: '<path d="M12 21s7.5-3.5 7.5-9.5V5.8L12 3 4.5 5.8v5.7C4.5 17.5 12 21 12 21z"/>',
  shieldCheck: '<path d="M12 21s7.5-3.5 7.5-9.5V5.8L12 3 4.5 5.8v5.7C4.5 17.5 12 21 12 21z"/><path d="m9 12 2 2 4-4"/>',
  phone: '<rect x="6" y="2.5" width="12" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
  trash: '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l.8 12.2A1.5 1.5 0 0 0 8.8 20.5h6.4a1.5 1.5 0 0 0 1.5-1.3L17.5 7"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  wifi: '<path d="M2.5 9a14 14 0 0 1 19 0M5.5 12.3a9.5 9.5 0 0 1 13 0M8.6 15.6a5 5 0 0 1 6.8 0"/><path d="M12 19h.01"/>',
  chevronRight: '<path d="m9.5 6 6 6-6 6"/>',
  chevronDown: '<path d="m6 9.5 6 6 6-6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  zap: '<path d="M13 2.5 4.5 13.5H12l-1 8 8.5-11H12z"/>',
  expand: '<path d="M8.5 3.5h-3a2 2 0 0 0-2 2v3M20.5 8.5v-3a2 2 0 0 0-2-2h-3M3.5 15.5v3a2 2 0 0 0 2 2h3M15.5 20.5h3a2 2 0 0 0 2-2v-3"/>',
  shrink: '<path d="M3.5 8.5h3a2 2 0 0 0 2-2v-3M15.5 3.5v3a2 2 0 0 0 2 2h3M8.5 20.5v-3a2 2 0 0 0-2-2h-3M20.5 15.5h-3a2 2 0 0 0-2 2v3"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4.5M12 8h.01"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  lock: '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
  radar: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12 18 6"/>',
  type: '<path d="M4.5 7V5h15v2M12 5v14M9 19h6"/>',
  mouse: '<rect x="6" y="2.5" width="12" height="19" rx="6"/><path d="M12 6.5v3"/>',
  more: '<path d="M5.5 12h.01M12 12h.01M18.5 12h.01"/>',
  alert: '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5M12 17.5h.01"/>',
  arrowLeft: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
  volume: '<path d="M4.5 9.5h3l4.5-4v13l-4.5-4h-3z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  volumeOff: '<path d="M4.5 9.5h3l4.5-4v13l-4.5-4h-3z"/><path d="m16 9.5 5 5M21 9.5l-5 5"/>',
};

export function icon(name, cls = '') {
  return `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ''}</svg>`;
}

export function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach((el) => {
    el.insertAdjacentHTML('afterbegin', icon(el.dataset.icon, el.dataset.iconClass || ''));
    el.removeAttribute('data-icon');
  });
}
