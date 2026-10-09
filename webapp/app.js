/* Персональная книга — Mini App. Одна страница, без сборки. */
(() => {
  'use strict';

  /* ===================================================================== Telegram */
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const initData = tg && tg.initData ? tg.initData : '';
  const inTelegram = !!initData;
  const query = new URLSearchParams(location.search);
  const reduceMotion = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  const haptic = {
    select() { try { tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged(); } catch (e) { /* без вибрации */ } },
    tap() { try { tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred('light'); } catch (e) { /* без вибрации */ } },
    ok() { try { tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred('success'); } catch (e) { /* без вибрации */ } },
    bad() { try { tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred('error'); } catch (e) { /* без вибрации */ } },
  };

  // Приложение всегда светлое и белое, что бы ни стояло в теме Telegram
  const WHITE = '#ffffff';

  function setHeader(color) {
    S.header = color || WHITE;
    try { if (tg) tg.setHeaderColor(S.header); } catch (e) { /* старые версии Telegram */ }
  }

  function applyTheme() {
    const root = document.documentElement;
    root.dataset.scheme = 'light';
    root.style.colorScheme = 'light';
    if (tg) {
      try { tg.setBackgroundColor(WHITE); } catch (e) { /* ok */ }
      try { if (tg.setBottomBarColor) tg.setBottomBarColor(WHITE); } catch (e) { /* ok */ }
      setHeader(WHITE);
    }
  }

  function initTelegram() {
    applyTheme();
    if (!tg) return;
    try { tg.ready(); } catch (e) { /* ok */ }
    try { tg.expand(); } catch (e) { /* ok */ }
    try { if (tg.disableVerticalSwipes) tg.disableVerticalSwipes(); } catch (e) { /* ok */ }
    try { tg.onEvent('themeChanged', applyTheme); } catch (e) { /* ok */ }
    try { tg.BackButton.onClick(onBackButton); } catch (e) { /* нет BackButton */ }
  }

  function setBackButton(visible) {
    try { if (tg && tg.BackButton) { visible ? tg.BackButton.show() : tg.BackButton.hide(); } } catch (e) { /* ok */ }
  }

  /* ===================================================================== утилиты */
  const app = document.getElementById('app');
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function plural(n, forms) {
    const a = Math.abs(n) % 100, b = a % 10;
    if (a > 10 && a < 20) return forms[2];
    if (b > 1 && b < 5) return forms[1];
    if (b === 1) return forms[0];
    return forms[2];
  }

  /* ---- иконки: один нарисованный набор, сетка 24px, линия 2px с круглыми концами, мягкая заливка ----
     class="a" — светло-лавандовая заливка, class="b" — тёплый акцент, без класса — только линия.
     Цвета заливок задаёт CSS (--ic-a, --ic-b), линия берёт currentColor. Нет иконки для id — рисуем нейтральную generic. */
  const ICONS = {
    /* --- интерфейс --- */
    back: '<path d="M15 5l-7 7 7 7"/>',
    next: '<path d="M9 5l7 7-7 7"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    download: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>',
    upload: '<path d="M12 16V5M7.5 9.5L12 5l4.5 4.5M5 19.5h14"/>',
    refresh: '<path d="M19 8a7.5 7.5 0 0 0-13-2L4.5 8M4.5 4v4h4M5 16a7.5 7.5 0 0 0 13 2l1.5-2M19.5 20v-4h-4"/>',
    send: '<path class="a" d="M4 12l16-8-6 16-3-6.5z"/><path d="M11 13.5L20 4"/>',
    share: '<circle class="a" cx="6" cy="12" r="2.6"/><circle class="a" cx="17.5" cy="6" r="2.6"/><circle class="a" cx="17.5" cy="18" r="2.6"/><path d="M8.3 10.8l7-3.6M8.3 13.2l7 3.6"/>',
    copy: '<rect class="a" x="8.5" y="8.5" width="11" height="11" rx="2.5"/><path d="M15.5 8.5V6A2.5 2.5 0 0 0 13 3.5H6A2.5 2.5 0 0 0 3.5 6v7A2.5 2.5 0 0 0 6 15.5h2.5"/>',
    link: '<path d="M10.2 13.8a3.6 3.6 0 0 0 5.1 0l3-3a3.6 3.6 0 0 0-5.1-5.1l-1 1"/><path d="M13.8 10.2a3.6 3.6 0 0 0-5.1 0l-3 3a3.6 3.6 0 0 0 5.1 5.1l1-1"/>',
    clip: '<path d="M20 11.5l-8 8a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7L10 17a1.6 1.6 0 0 1-2.3-2.3L15 7.5"/>',
    qr: '<rect class="a" x="3.5" y="3.5" width="7" height="7" rx="1.8"/><rect class="a" x="13.5" y="3.5" width="7" height="7" rx="1.8"/><rect class="a" x="3.5" y="13.5" width="7" height="7" rx="1.8"/><path d="M14 14h2.5v2.5M20.5 14v.01M14 20.5h.01M17.5 20.5h3V18"/>',
    receipt: '<path class="a" d="M6 3.5h12v17l-2-1.4-2 1.4-2-1.4-2 1.4-2-1.4-2 1.4z"/><path d="M9 8h6M9 11.5h6M9 15h3"/>',
    lock: '<rect class="a" x="4.5" y="10.5" width="15" height="10" rx="2.8"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5M12 14.4v2.4"/>',
    clock: '<circle class="a" cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    done: '<circle class="a" cx="12" cy="12" r="8.5"/><path d="M8 12.4l2.8 2.8 5.2-5.6"/>',
    error: '<circle class="a" cx="12" cy="12" r="8.5"/><path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6"/>',
    warn: '<path class="b" d="M12 4l9 16H3z"/><path d="M12 10v4.4M12 17.2v.01"/>',
    admin: '<path d="M4 7h9.6M18.4 7H20M4 17h1.6M10.4 17H20"/><circle class="b" cx="16" cy="7" r="2.4"/><circle class="b" cx="8" cy="17" r="2.4"/>',
    trash: '<path class="a" d="M6.5 7.5l.9 11a1.5 1.5 0 0 0 1.5 1.4h6.2a1.5 1.5 0 0 0 1.5-1.4l.9-11z"/><path d="M4.5 7.5h15M9.5 7.5V5.6a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v1.9M10.5 11.5v5M13.5 11.5v5"/>',
    camera: '<path class="a" d="M4.5 8h2.6l1.4-2.2h7l1.4 2.2h2.6A1.5 1.5 0 0 1 21 9.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5v-9A1.5 1.5 0 0 1 4.5 8z"/><circle class="b" cx="12" cy="13.5" r="3.4"/>',
    image: '<rect class="a" x="3.5" y="4.5" width="17" height="15" rx="3"/><circle class="b" cx="9" cy="9.6" r="1.9"/><path d="M3.8 16.6l4.8-4.6a1.6 1.6 0 0 1 2.2 0l3.7 3.6 1.5-1.4a1.6 1.6 0 0 1 2.2 0l2 1.9"/>',
    phone: '<rect class="a" x="6.5" y="3" width="11" height="18" rx="3"/><path d="M10.5 17.5h3"/>',
    card: '<rect class="a" x="3" y="5.5" width="18" height="13" rx="3"/><path d="M3 10h18"/><path class="b" d="M7 14.5h3.2"/>',
    leaf: '<path class="a" d="M5 19c0-8 4.5-13.5 14-14.5 0 9-5 14.5-12.5 14.5z"/><path d="M5 19c2-4 5-7 9-9"/>',
    info: '<circle class="a" cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8v.01"/>',
    globe: '<circle class="a" cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.3 2.5 3.4 5.3 3.4 8.5s-1.1 6-3.4 8.5c-2.3-2.5-3.4-5.3-3.4-8.5S9.7 6 12 3.5z"/>',
    generic: '<circle class="a" cx="12" cy="12" r="8.5"/><circle class="b" cx="12" cy="12" r="2.6"/>',

    /* --- шаги мастера --- */
    child: '<circle class="a" cx="12" cy="13" r="7"/><path d="M9.4 12v.01M14.6 12v.01"/><path d="M9.9 15.4c.7.8 1.4 1.1 2.1 1.1s1.4-.3 2.1-1.1"/><path class="b" d="M12 6c-.2-1.4.4-2.4 1.7-3"/>',
    cake: '<path class="a" d="M4.5 12.5h15v7a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M4.5 16.5q1.9-1.8 3.75 0t3.75 0 3.75 0 3.75 0"/><path d="M12 9v3.5"/><path class="b" d="M12 3.6c1.3 1 1.6 1.8 1.6 2.5a1.6 1.6 0 0 1-3.2 0c0-.7.3-1.5 1.6-2.5z"/>',
    boy: '<circle class="a" cx="12" cy="12.8" r="8"/><path class="b" d="M4.4 11c.6-4.2 3.6-6.5 7.6-6.5s7 2.3 7.6 6.5c-2.2-.2-4-1.2-5-2.6-1.6 1.6-5.2 2.6-10.2 2.6z"/><path d="M9.2 13.8v.01M14.8 13.8v.01"/><path d="M9.6 16.8c1.3 1.1 3.5 1.1 4.8 0"/>',
    girl: '<path class="b" d="M12 3.6c-4.7 0-7.4 3.2-7.4 7.8v5.6c0 1.4.8 2.2 2 2.2h2.2V15h6.4v4.2H17c1.2 0 2-.8 2-2.2v-5.6c0-4.6-2.7-7.8-7-7.8z"/><circle class="a" cx="12" cy="12.6" r="5.2"/><path d="M9.8 12.6v.01M14.2 12.6v.01"/><path d="M10 15c.6.6 1.3.9 2 .9s1.4-.3 2-.9"/>',
    portrait: '<rect class="a" x="3.5" y="3.5" width="17" height="17" rx="5"/><circle class="b" cx="12" cy="10" r="3"/><path d="M6.8 18.4c.8-2.6 2.8-3.9 5.2-3.9s4.4 1.3 5.2 3.9"/>',
    heart: '<path class="a" d="M12 20.2C6.6 16.4 3.4 13.1 3.4 9.3a4.5 4.5 0 0 1 8.6-1.9 4.5 4.5 0 0 1 8.6 1.9c0 3.8-3.2 7.1-8.6 10.9z"/>',
    smile: '<circle class="a" cx="12" cy="12" r="8.5"/><path d="M9 10.2v.01M15 10.2v.01"/><path d="M8.6 14c.9 1.9 2.1 2.8 3.4 2.8s2.5-.9 3.4-2.8"/>',
    sad: '<circle class="a" cx="12" cy="12" r="8.5"/><path d="M9 10v.01M15 10v.01"/><path d="M8.8 16.6c.9-1.4 2-2.1 3.2-2.1s2.3.7 3.2 2.1"/>',
    pin: '<path class="a" d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/><circle class="b" cx="12" cy="10" r="2.4"/>',
    bulb: '<path class="a" d="M8.2 14.6A6 6 0 1 1 15.8 14.6c-.9.7-1.3 1.5-1.3 2.4H9.5c0-.9-.4-1.7-1.3-2.4z"/><path d="M9.8 20h4.4M10.2 17.6h3.6"/>',
    book: '<path class="a" d="M12 6.5C10 5 7 4.5 3.8 5v12.7c3.2-.4 6.2.1 8.2 1.6 2-1.5 5-2 8.2-1.6V5c-3.2-.5-6.2 0-8.2 1.5z"/><path d="M12 6.5v12.8"/>',
    rainbow: '<path class="a" d="M3.5 18a8.5 8.5 0 0 1 17 0z"/><path d="M7.5 18a4.5 4.5 0 0 1 9 0"/><path class="b" d="M10.2 18a1.8 1.8 0 0 1 3.6 0z"/>',
    palette: '<path class="a" d="M12 3.5c-4.7 0-8.5 3.6-8.5 8.3 0 4.5 3.4 8.2 7.7 8.2 1.6 0 2.3-1 2-2.1-.3-1.1.3-2.1 1.6-2.1h2.3c1.9 0 3.4-1.4 3.4-3.2 0-4.4-3.8-8.1-8.5-8.1z"/><path class="b" d="M7.8 11.6v.01M11 7.8v.01M15.4 8.4v.01" stroke-width="2.8"/>',
    pencil: '<path class="a" d="M4.2 19.8l.9-4 10.9-10.9a2 2 0 0 1 2.8 0l.3.3a2 2 0 0 1 0 2.8L8.2 18.9z"/><path d="M14 6.9l3.1 3.1M5.1 15.8l3.1 3.1"/>',
    bubble: '<path class="a" d="M5 4.5h14A1.5 1.5 0 0 1 20.5 6v9a1.5 1.5 0 0 1-1.5 1.5h-7L7.5 20.2V16.5H5A1.5 1.5 0 0 1 3.5 15V6A1.5 1.5 0 0 1 5 4.5z"/><path d="M8 9h8M8 12.3h5"/>',
    moon: '<path class="a" d="M12 3a6.2 6.2 0 0 0 9 9 9 9 0 1 1-9-9z"/><circle class="b" cx="17" cy="6" r="1.5"/>',
    lang_ru: '<path class="a" d="M5 4.5h14A1.5 1.5 0 0 1 20.5 6v9a1.5 1.5 0 0 1-1.5 1.5h-7L7.5 20.2V16.5H5A1.5 1.5 0 0 1 3.5 15V6A1.5 1.5 0 0 1 5 4.5z"/><text x="12" y="13.6" text-anchor="middle" font-size="9" font-weight="900" fill="currentColor" stroke="none">А</text>',
    lang_ky: '<path class="a" d="M5 4.5h14A1.5 1.5 0 0 1 20.5 6v9a1.5 1.5 0 0 1-1.5 1.5h-7L7.5 20.2V16.5H5A1.5 1.5 0 0 1 3.5 15V6A1.5 1.5 0 0 1 5 4.5z"/><text x="12" y="13.6" text-anchor="middle" font-size="9" font-weight="900" fill="currentColor" stroke="none">Ө</text>',
    envelope: '<rect class="a" x="3.5" y="5.5" width="17" height="13" rx="2.8"/><path d="M4.2 7.6l7.8 5.8 7.8-5.8"/>',
    gift: '<rect class="a" x="4" y="10.2" width="16" height="10.3" rx="2"/><rect class="a" x="3" y="6.8" width="18" height="3.4" rx="1.2"/><path d="M12 6.8v13.7"/><path class="b" d="M12 6.8C10 6.8 8 6.2 8 4.8c0-1.2 1-1.6 1.8-1.4 1.1.3 2.2 1.8 2.2 3.4zM12 6.8c2 0 4-.6 4-2 0-1.2-1-1.6-1.8-1.4-1.1.3-2.2 1.8-2.2 3.4z"/>',

    /* --- места --- */
    mountains: '<path class="a" d="M2.8 19.5L9.5 7.5l3.7 6.3 2.3-3.6 5.7 9.3z"/><path class="b" d="M9.5 7.5L7.6 11l1.6-.9 1.2 1 1.4-1.1z"/>',
    yurt: '<path class="a" d="M3.5 19.5v-5c0-3.7 3.8-7.2 8.5-7.2s8.5 3.5 8.5 7.2v5z"/><path d="M3.5 14.3h17M12 7.3V4.6"/><path class="b" d="M9.8 19.5v-3.4a2.2 2.2 0 0 1 4.4 0v3.4"/>',
    lake: '<path class="a" d="M3.5 13.5l4.2-6.2 3 3.8 2.6-3.1 6.2 5.5z"/><path d="M3 17.2q1.5-1.5 3 0t3 0 3 0 3 0 3 0 3 0M6 20.6q1.5-1.5 3 0t3 0 3 0 3 0"/>',
    bazaar: '<path class="a" d="M4 10.5l1.4-5.5h13.2l1.4 5.5z"/><path class="b" d="M4 10.5a2.67 2.67 0 0 0 5.33 0 2.67 2.67 0 0 0 5.34 0 2.67 2.67 0 0 0 5.33 0z"/><path d="M5.5 14.5V20M18.5 14.5V20M3.5 20h17"/>',
    rocket: '<path class="a" d="M12 2.8c3 2.3 4.4 5.4 4.4 8.9V16H7.6v-4.3c0-3.5 1.4-6.6 4.4-8.9z"/><circle class="b" cx="12" cy="9.6" r="1.9"/><path d="M7.6 11.8L5 14.4v3.2l2.6-1.6M16.4 11.8l2.6 2.6v3.2L16.4 16"/><path class="b" d="M10 16.6h4L12 21z"/>',
    fish: '<ellipse class="a" cx="10.5" cy="12" rx="7" ry="4.8"/><path class="b" d="M16.8 12l4.2-4v8z"/><path d="M7.4 11v.01"/>',

    /* --- ценности и характер --- */
    truth: '<path class="a" d="M5 4.5h14A1.5 1.5 0 0 1 20.5 6v9a1.5 1.5 0 0 1-1.5 1.5h-7L7.5 20.2V16.5H5A1.5 1.5 0 0 1 3.5 15V6A1.5 1.5 0 0 1 5 4.5z"/><path d="M8.6 10.6l2.2 2.2 4.4-4.6"/>',
    home: '<path class="a" d="M4.5 11L12 4.5l7.5 6.5v8a1.5 1.5 0 0 1-1.5 1.5H6A1.5 1.5 0 0 1 4.5 19z"/><path class="b" d="M12 17.6c-2.2-1.5-3.2-2.6-3.2-3.8a1.7 1.7 0 0 1 3.2-.8 1.7 1.7 0 0 1 3.2.8c0 1.2-1 2.3-3.2 3.8z"/>',
    tulip: '<path class="a" d="M6.8 4.5c0 5.2 1.8 8.4 5.2 8.4s5.2-3.2 5.2-8.4c-1.8.5-3.2 1.4-5.2 3.4-2-2-3.4-2.9-5.2-3.4z"/><path d="M12 12.9v7.6"/><path class="b" d="M12 17.6c-3 0-4.4-1.6-4.4-3.6 2.8 0 4.4 1.2 4.4 3.6z"/>',
    paw: '<ellipse class="a" cx="12" cy="15.6" rx="4.4" ry="3.7"/><circle class="b" cx="6.2" cy="11.6" r="1.3"/><circle class="b" cx="9.6" cy="7.6" r="1.3"/><circle class="b" cx="14.4" cy="7.6" r="1.3"/><circle class="b" cx="17.8" cy="11.6" r="1.3"/>',
    elder: '<path class="b" d="M12 3.5c-4 0-6.8 3-6.8 7.2 0 3.2 1 5.6 2.6 7.3h8.4c1.6-1.7 2.6-4.1 2.6-7.3 0-4.2-2.8-7.2-6.8-7.2z"/><circle class="a" cx="12" cy="12.4" r="4.4"/><path d="M10.3 12v.01M13.7 12v.01"/><path d="M10.6 14.3c.8.6 1.9.6 2.8 0"/>',
    flag: '<path d="M6 21V4"/><path class="b" d="M6 5c3-1.6 5.5 1.6 8.5 0s3.5-.4 3.5-.4v7.4s-1.2.9-3.5.4c-3-1.6-5.5 1.6-8.5 0z"/>',
    search: '<circle class="a" cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
    laugh: '<circle class="a" cx="12" cy="12" r="8.5"/><path d="M9 9.6v.01M15 9.6v.01"/><path class="b" d="M7.8 13h8.4c0 2.6-1.9 4.4-4.2 4.4S7.8 15.6 7.8 13z"/>',
    shy: '<circle class="a" cx="12" cy="12" r="8.5"/><path d="M9 10.6v.01M15 10.6v.01"/><circle class="b" cx="7.4" cy="14" r="1.2"/><circle class="b" cx="16.6" cy="14" r="1.2"/><path d="M10.4 16.4c.9.5 2.3.5 3.2 0"/>',
    anchor: '<circle class="a" cx="12" cy="5.8" r="2.3"/><path d="M12 8.1V20M7.5 11.5h9M4.5 13.5c.2 3.6 3.4 6.5 7.5 6.5s7.3-2.9 7.5-6.5"/>',
    sprout: '<path d="M12 21v-9"/><path class="a" d="M12 12c0-3.6-2.6-6-6.5-6 0 3.6 2.4 6 6.5 6z"/><path class="b" d="M12 14c0-3 2.2-5.6 6.5-5.6 0 3.2-2.4 5.6-6.5 5.6z"/>',

    /* --- темы и миры --- */
    compass: '<circle class="a" cx="12" cy="12" r="8.5"/><path class="b" d="M15.6 8.4l-2 5.2-5.2 2 2-5.2z"/>',
    dino: '<path class="a" d="M2.8 18.6C6 18.2 6.6 13.4 10.4 13.2c2.2-.1 4-.2 4.3-2.8l.4-3.6c.2-2.2 1.9-3.2 3.7-2.7 1.7.5 2.4 1.8 2.1 3.1-.2.8-.9 1.2-1.7 1.2h-.8c-.2 2.2.2 3.8.8 5.2v7H16.4v-3H10.6v3H7.8v-3c-1.6 1-3.2 1.8-5 1z"/><path d="M18.6 6.2v.01"/><path class="b" d="M9.4 15.4v.01M12.6 15.4v.01"/>',
    fox: '<path class="a" d="M3.5 4.5l4.8 3c1.1-.4 2.4-.6 3.7-.6s2.6.2 3.7.6l4.8-3c.3 3.6-.3 6.6-1.6 8.8-1.3 3.5-3.9 6.3-6.9 6.3s-5.6-2.8-6.9-6.3C3.8 11.1 3.2 8.1 3.5 4.5z"/><path class="b" d="M10.2 14.4h3.6L12 16.6z"/><path d="M8.6 11.8v.01M15.4 11.8v.01"/>',
    hero: '<path class="a" d="M12 3.5l7 2.6v5.4c0 4.2-2.8 7.4-7 9-4.2-1.6-7-4.8-7-9V6.1z"/><path class="b" d="M12.8 8l-2.8 4h2.4l-.8 3.6 3-4.2h-2.4z"/>',
    chest: '<path class="a" d="M4 10.2c0-2.6 2-4.2 4.4-4.2h7.2c2.4 0 4.4 1.6 4.4 4.2z"/><rect class="a" x="4" y="10.2" width="16" height="9.3" rx="1.6"/><path d="M4 12.8h16"/><rect class="b" x="10.4" y="11.4" width="3.2" height="3.4" rx="1"/>',
    boat: '<path class="a" d="M11 4v10H5.2z"/><path class="b" d="M13.4 6.4V14H19z"/><path class="a" d="M4 16.4h16l-2.4 3.5H6.4z"/>',
    friends: '<circle class="b" cx="16.2" cy="8.6" r="2.7"/><path class="b" d="M13.4 14.2c.8-.4 1.7-.6 2.8-.6 2.8 0 4.6 1.6 4.8 4.9h-6.4"/><circle class="a" cx="8.4" cy="8.2" r="3"/><path class="a" d="M2.8 19.4c.3-3.6 2.6-5.6 5.6-5.6s5.3 2 5.6 5.6z"/>',
    tooth: '<path class="a" d="M7.6 3.8c1.6 0 2.5.7 4.4.7s2.8-.7 4.4-.7c2.2 0 3.6 1.9 3.4 4.6-.2 2.2-1 3.6-1.4 5.6-.4 2-.6 6-2.4 6-1.4 0-1.3-3.4-2.4-4.6-.4-.5-1.1-.5-1.6-.5s-1.2 0-1.6.5c-1.1 1.2-1 4.6-2.4 4.6-1.8 0-2-4-2.4-6-.4-2-1.2-3.4-1.4-5.6C4 5.7 5.4 3.8 7.6 3.8z"/>',
    tree: '<path class="a" d="M12 3l5.5 7h-3l4 5.5h-13l4-5.5h-3z"/><path class="b" d="M10.4 15.5h3.2V20h-3.2z"/>',
    buoy: '<circle class="a" cx="12" cy="12" r="8.5"/><circle class="b" cx="12" cy="12" r="3.4"/><path d="M6 6l3.6 3.6M18 6l-3.6 3.6M6 18l3.6-3.6M18 18l-3.6-3.6"/>',
    wrench: '<path class="a" d="M14.7 6.3a4 4 0 0 0-5.4 5.1L3.8 17a2 2 0 0 0 2.8 2.8l5.6-5.5a4 4 0 0 0 5.2-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
    ninja: '<circle class="a" cx="12" cy="12" r="8.5"/><rect class="b" x="6" y="9.6" width="12" height="4.6" rx="2.3"/><path d="M9.4 11.9v.01M14.6 11.9v.01M20 8.2l2 -1.6M20.2 10.6l1.9 1.6"/>',
    crown: '<path class="a" d="M3.5 8.5l4.2 3.6L12 5.5l4.3 6.6 4.2-3.6-1.6 10H5.1z"/><path class="b" d="M5.4 16.5h13.2l-.5 3H5.9z"/>',
    hardhat: '<path class="a" d="M5 15a7 7 0 0 1 14 0z"/><path d="M12 8v7"/><path class="b" d="M3 15h18v2.6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>',

    /* --- стили картинок --- */
    cube: '<path class="a" d="M12 3.5l7.5 4.2v8.6L12 20.5l-7.5-4.2V7.7z"/><path class="b" d="M12 3.5l7.5 4.2L12 12 4.5 7.7z"/><path d="M12 12v8.5"/>',
    shapes: '<circle class="a" cx="8.5" cy="8.5" r="4.5"/><rect class="b" x="11" y="11" width="9" height="9" rx="1.8"/>',
    lens: '<circle class="a" cx="12" cy="12" r="8.5"/><circle class="b" cx="12" cy="12" r="3.8"/><path d="M15.6 7.4v.01"/>',

    /* --- увлечения --- */
    horseshoe: '<path class="a" d="M4.8 5C4 9 4.2 13.5 6.2 16.6 7.6 18.8 9.6 20 12 20s4.4-1.2 5.8-3.4C19.8 13.5 20 9 19.2 5h-4c.3 3.2.2 6-.7 8-.5 1.2-1.3 1.9-2.5 1.9s-2-.7-2.5-1.9C8.6 11 8.5 8.2 8.8 5z"/><path d="M6.6 9v.01M7.3 13v.01M17.4 9v.01M16.7 13v.01"/>',
    car: '<path class="a" d="M4 16.5v-3.2c0-.7.2-1.3.6-1.9l1.7-3.4c.4-.8 1.2-1.3 2.1-1.3h7.2c.9 0 1.7.5 2.1 1.3l1.7 3.4c.4.6.6 1.2.6 1.9v3.2c0 .6-.4 1-1 1H5c-.6 0-1-.4-1-1z"/><path d="M4.6 12.4h14.8"/><circle class="b" cx="7.8" cy="17.5" r="2.1"/><circle class="b" cx="16.2" cy="17.5" r="2.1"/>',
    brush: '<path d="M19.6 4.4L11.8 12.2"/><path class="a" d="M9.6 12.6c1.9-.4 3.6 1.1 3.2 3.2-.4 2.6-3 4.2-6.6 4.2 1-1 1.2-1.9 1-2.8-.2-2.1.5-4.2 2.4-4.6z"/>',
    note: '<circle class="a" cx="7" cy="17.5" r="2.8"/><circle class="a" cx="17" cy="15.5" r="2.8"/><path d="M9.8 17.5V6.2l10-2v11.3M9.8 9.8l10-2"/>',
    ball: '<circle class="a" cx="12" cy="12" r="8.5"/><path class="b" d="M12 8.4l3 2.2-1.1 3.5h-3.8L9 10.6z"/><path d="M12 8.4V3.6M15 10.6l4.4-1.6M13.9 14.1l2.8 3.9M10.1 14.1L7.3 18M9 10.6L4.6 9"/>',
    doll: '<circle class="a" cx="12" cy="6.4" r="3.2"/><path class="b" d="M12 10.6c-2.4 0-3.6 3-4.6 9.4h9.2c-1-6.4-2.2-9.4-4.6-9.4z"/><path d="M8.6 12.6L5.6 14.4M15.4 12.6l3 1.8"/>',
    planet: '<circle class="a" cx="12" cy="12" r="5.6"/><ellipse cx="12" cy="12" rx="9.6" ry="3.2" transform="rotate(-24 12 12)"/>',
    brick: '<rect class="a" x="3.5" y="9.5" width="17" height="10" rx="2"/><rect class="b" x="5.6" y="5.6" width="3.4" height="3.9" rx="1"/><rect class="b" x="10.3" y="5.6" width="3.4" height="3.9" rx="1"/><rect class="b" x="15" y="5.6" width="3.4" height="3.9" rx="1"/>',
    candy: '<ellipse class="a" cx="12" cy="12" rx="5" ry="4.2"/><path class="b" d="M7.2 10.2L3.4 7.6v8.8l3.8-2.6zM16.8 10.2l3.8-2.6v8.8l-3.8-2.6z"/><path d="M10.2 8.6l-1 6.4"/>',
  };
  function icon(name, cls) {
    const body = ICONS[name] || ICONS.generic;
    return '<svg class="ic' + (cls ? ' ' + cls : '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + body + '</svg>';
  }

  /* ---- какая иконка к какому варианту (сервер присылает id; если иконки нет — нейтральная generic) ---- */
  const PLACE_META = {
    mountains: { i: 'mountains', sub: 'снежные вершины и горные ручьи' },
    yurt: { i: 'yurt', sub: 'зелёные луга, кони и дымок над юртой' },
    issykkul: { i: 'lake', sub: 'синее озеро и горы вдали' },
    silkroad: { i: 'bazaar', sub: 'караваны, сладкие дыни и яркие лавки' },
    space: { i: 'rocket', sub: 'звёзды, планеты и уютный корабль' },
    underwater: { i: 'fish', sub: 'кораллы, рыбки и лучи солнца' },
    custom: { i: 'pencil', sub: 'опишите место сами' },
  };
  const VALUE_META = {
    kindness: { i: 'heart', sub: 'делиться теплом и помогать другим' },
    honesty: { i: 'truth', sub: 'говорить правду, даже когда непросто' },
    help_parents: { i: 'home', sub: 'быть опорой для мамы и папы' },
    gratitude: { i: 'tulip', sub: 'ценить добро и говорить «спасибо»' },
    animals: { i: 'paw', sub: 'беречь тех, кто слабее' },
    respect_elders: { i: 'elder', sub: 'слушать и помогать старшим' },
    courage: { i: 'flag', sub: 'поступать правильно, когда страшно' },
  };
  const TOPIC_ICON = { adventure: 'compass', dinosaurs: 'dino', space: 'rocket', animals: 'fox', superheroes: 'hero', pirates: 'chest', sea: 'boat', friends: 'friends', kindness: 'heart', life_lesson: 'tooth', custom: 'pencil' };
  const WORLD_ICON = { forest_house: 'tree', rescue_team: 'buoy', workshop_helpers: 'wrench', ninja_animals: 'ninja', caped_hero: 'hero', kingdom: 'crown', dino_friend: 'dino', space_crew: 'rocket', builders: 'hardhat', mountain_friends: 'mountains', custom: 'pencil' };
  const STYLE_ICON = { cartoon3d: 'cube', flat2d: 'shapes', realistic: 'lens' };
  const LIKE_ICON = { 'Лошади': 'horseshoe', 'Животные': 'paw', 'Динозавры': 'dino', 'Машинки': 'car', 'Рисование': 'brush', 'Музыка': 'note', 'Футбол': 'ball', 'Куклы': 'doll', 'Космос': 'planet', 'Конструктор': 'brick', 'Книги': 'book', 'Сладости': 'candy' };
  const TRAIT_ICON = { kind: 'heart', brave: 'flag', curious: 'search', funny: 'laugh', shy: 'shy', stubborn: 'anchor', caring: 'sprout' };
  const STEP_ICON = {
    name: 'child', age: 'cake', gender: 'friends', appearance: 'portrait', likes: 'heart', traits: 'smile', place: 'pin', value: 'bulb',
    topic: 'book', world: 'rainbow', style: 'palette', extras: 'bubble', islamic: 'moon', language: 'globe', dedication: 'envelope', photo: 'camera',
    summary: 'gift',
  };
  const iconOf = (map, id, fallback) => (map && map[id]) || fallback || 'generic';
  // сообщение об ошибке: значок + текст (текст всегда экранируем)
  const errorHtml = (text) => icon('error') + '<span>' + esc(text) + '</span>';

  const ORNAMENT = '<svg class="orn" viewBox="0 0 120 12" aria-hidden="true"><g stroke="currentColor" stroke-width="1.2"><path d="M2 6h42M76 6h42"/></g><g fill="currentColor"><circle cx="52" cy="6" r="2"/><circle cx="60" cy="6" r="3"/><circle cx="68" cy="6" r="2"/></g></svg>';

  /* ---- иллюстрация экрана ожидания: раскрытая книга, страницы переворачиваются, карандаш пишет ---- */
  function waitArt() {
    return '<svg viewBox="0 0 320 176" preserveAspectRatio="xMidYMid slice" aria-hidden="true">' +
      '<ellipse cx="160" cy="150" rx="92" ry="9" fill="#e4defd"/>' +
      '<path d="M160 56C136 40 98 36 62 42v80c36-6 74-2 98 14 24-16 62-20 98-14V42c-36-6-74-2-98 14z" fill="#fff" stroke="#4a35c9" stroke-width="4" stroke-linejoin="round"/>' +
      '<path d="M160 56v80" stroke="#4a35c9" stroke-width="4" stroke-linecap="round"/>' +
      '<g fill="none" stroke="#d9d3f5" stroke-width="4" stroke-linecap="round"><path d="M80 70c22-3 46 0 66 9M80 86c22-3 46 0 66 9M80 102c22-3 36 0 52 6"/></g>' +
      '<path class="pg" fill="#fff" stroke="#4a35c9" stroke-width="4" stroke-linejoin="round" d="M160 56c24-16 62-20 98-14v80c-36-6-74-2-98 14z"/>' +
      '<g fill="none" stroke="#ffd3a3" stroke-width="4" stroke-linecap="round"><path d="M178 72c20-6 42-5 62-1M178 88c20-6 42-5 62-1M178 104c20-6 32-5 46-2"/></g>' +
      '<g class="fl"><path d="M236 34l22-22 10 10-22 22-14 4z" fill="#ffd3a3" stroke="#4a35c9" stroke-width="4" stroke-linejoin="round"/><path d="M254 16l10 10" stroke="#4a35c9" stroke-width="4" stroke-linecap="round"/></g>' +
      '</svg>';
  }

  /* ===================================================================== API */
  class ApiError extends Error {
    constructor(message, status, code, data) { super(message); this.status = status; this.code = code; this.data = data; }
  }

  async function api(path, opts) {
    const o = opts || {};
    const headers = { Authorization: 'tma ' + (initData || 'dev') };
    let body;
    if (o.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(o.json); }
    else if (o.form) { body = o.form; }
    let res;
    try {
      res = await fetch(path, { method: o.method || 'GET', headers, body });
    } catch (e) {
      throw new ApiError('Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.', 0, 'network');
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* не JSON */ }
    if (!res.ok) {
      throw new ApiError((data && data.error) || 'Не получилось выполнить запрос. Попробуйте ещё раз.', res.status, data && data.code, data);
    }
    return data;
  }

  /* ===================================================================== состояние */
  function freshAnswers(keep) {
    return Object.assign({
      name: '', age: null, gender: null, hair: '', eyes: '', clothes: '', likes: [], traits: [],
      place: null, place_custom: '', value: null, topic: null, topic_custom: '', world: null, cartoons: '', style: null, request: '', favorites: '',
      islamic: false, headscarf: false, language: null, dedication: '', photo_consent: false,
    }, keep || {});
  }

  const S = {
    cfg: null, screen: 'boot', steps: [], idx: 0, returnToSummary: false, header: null,
    a: freshAnswers(), photo: null, photoUrl: null,
    orderId: null, order: null, pollId: 0, pollFails: 0, stage: 0, tipTimer: null, tipIndex: 0,
    fb: { rating: null, would_pay: null, comment: '', sent: false },
    adminTab: 'checks', admin: null, adminTimer: null, payTimer: null, payId: 0,
    inv: { credits: 1, note: '', list: null, error: '', fresh: null }, closedWa: null,
  };

  const opts = () => S.cfg.options;
  const traitLabel = (t) => (S.a.gender === 'girl' ? t.girl : t.boy);
  const placeLabel = () => {
    if (S.a.place === 'custom') return S.a.place_custom.trim();
    const p = opts().places.find((x) => x.id === S.a.place);
    return p ? p.label : '';
  };

  // Темы книги и пожелания: бэкенд мог ещё не прислать новые поля, поэтому читаем осторожно
  const topicList = () => (S.cfg && S.cfg.options && Array.isArray(S.cfg.options.topics) ? S.cfg.options.topics : []);
  const defaultTopic = () => {
    const list = topicList();
    const want = S.cfg && S.cfg.options && S.cfg.options.default_topic;
    return (list.find((t) => t.id === want) || list.find((t) => t.id === 'adventure') || list[0] || {}).id || null;
  };
  const topicLabel = () => {
    if (S.a.topic === 'custom') return S.a.topic_custom.trim() || 'Своя тема';
    const t = topicList().find((x) => x.id === S.a.topic);
    return t ? t.label : '';
  };
  // Миры любимых мультфильмов: если сервер не прислал options.worlds (или список пуст), шаг и поля анкеты пропускаем
  const worldList = () => (S.cfg && S.cfg.options && Array.isArray(S.cfg.options.worlds) ? S.cfg.options.worlds.filter((w) => w && w.id) : []);
  const worldPicked = () => worldList().find((w) => w.id === S.a.world) || null;
  const worldLabel = () => { const w = worldPicked(); return w ? (w.label || '') : ''; };
  // Стиль картинок: если сервер не прислал options.styles (или список пуст), шаг пропускаем и поле не шлём
  const styleList = () => (S.cfg && S.cfg.options && Array.isArray(S.cfg.options.styles) ? S.cfg.options.styles.filter((x) => x && x.id) : []);
  const defaultStyle = () => {
    const list = styleList();
    const want = S.cfg && S.cfg.options && S.cfg.options.default_style;
    return (list.find((x) => x.id === want) || list.find((x) => x.id === 'cartoon3d') || list[0] || {}).id || null;
  };
  const stylePicked = () => styleList().find((x) => x.id === S.a.style) || null;
  const styleLabel = () => { const x = stylePicked(); return x ? (x.label || '') : ''; };
  const limitOf = (key, fallback) => {
    const v = S.cfg && S.cfg.limits && Number(S.cfg.limits[key]);
    return v > 0 ? v : fallback;
  };
  const requestMax = () => limitOf('request_max', 300);
  const favoritesMax = () => limitOf('favorites_max', 120);
  const cartoonsMax = () => limitOf('cartoons_max', 120);
  const textMax = () => limitOf('text_max', 120);
  const pagesCount = () => {
    const n = S.cfg && S.cfg.book_format && Number(S.cfg.book_format.pages);
    return n > 0 ? n : 8;
  };

  // Доступ и печать: бэкенд мог ещё не прислать новые поля, поэтому всё читается осторожно
  const isAdmin = () => !!(S.cfg && (S.cfg.is_admin || (S.cfg.access && S.cfg.access.is_admin)));
  const accessClosed = () => !!(S.cfg && S.cfg.access && S.cfg.access.granted === false && !isAdmin());
  const printCfg = () => (S.cfg && S.cfg.print && S.cfg.print.enabled ? S.cfg.print : null);
  // ссылка «хочу получить доступ» (не та же, что print.whatsapp_url: у них разные сообщения владельцу)
  const accessWaUrl = () => (S.cfg && S.cfg.access_whatsapp_url) || S.closedWa || null;
  const PHOTO_PROMISE = 'После создания книги фото ребёнка автоматически удаляются, не позднее чем через 24 часа.';

  function openExternal(url) {
    if (!url) return;
    try { if (tg && tg.openLink) { tg.openLink(url); return; } } catch (e) { /* откроем обычной ссылкой */ }
    window.open(url, '_blank');
  }

  function leaveScreen() {
    clearInterval(S.tipTimer);
    S.tipTimer = null;
    clearTimeout(S.autoTimer);
    clearInterval(S.adminTimer);
    S.adminTimer = null;
    if (S.io) { S.io.disconnect(); S.io = null; }
    S.payId += 1;
  }

  /* ===================================================================== экраны-заглушки */
  function showBoot() {
    S.screen = 'boot';
    app.innerHTML = '<div class="boot"><i aria-label="Загрузка"></i></div>';
    setBackButton(false);
  }

  function stateScreen(iconName, title, text, buttons, extra) {
    const btns = (buttons || []).map((b) => '<button type="button" class="btn ' + (b.cls || '') + '" data-act="' + b.act + '">' + (b.icon ? icon(b.icon) : '') + esc(b.label) + '</button>').join('');
    app.innerHTML = '<section class="screen state" role="alert"><div class="big" aria-hidden="true">' + icon(iconName) + '</div>' +
      '<h1>' + esc(title) + '</h1><p>' + esc(text) + '</p>' + (extra || '') +
      (btns ? '<div class="btns">' + btns + '</div>' : '') + '</section>';
  }

  function showBlocked() {
    leaveScreen();
    S.screen = 'blocked';
    setBackButton(false);
    setHeader();
    stateScreen('phone', 'Откройте приложение в Telegram',
      'Эта страница работает внутри Telegram. Найдите нашего бота и нажмите кнопку «Создать книгу» — там всё и случится.', [],
      '<details><summary>Для владельца бота</summary><pre>Чтобы проверить в обычном браузере, поставьте DEV_MODE=1 в файле .env и перезапустите сервер.</pre></details>');
  }

  function showFatal(err, retry) {
    leaveScreen();
    S.screen = 'fatal';
    haptic.bad();
    setBackButton(false);
    setHeader();
    S.retry = retry;
    stateScreen('sad', 'Что-то пошло не так', err.message || 'Не получилось открыть приложение.',
      [{ act: 'retry', label: 'Попробовать ещё раз', icon: 'refresh' }]);
  }

  // Закрытый бот: создавать книгу можно только по личной ссылке
  function showClosed() {
    leaveScreen();
    S.screen = 'closed';
    setBackButton(false);
    setHeader();
    const buttons = [];
    if (accessWaUrl()) buttons.push({ act: 'wa-open', label: 'Написать в WhatsApp', icon: 'send' });
    buttons.push({ act: 'home', label: 'Проверить доступ', cls: 'ghost', icon: 'refresh' });
    stateScreen('lock', 'Бот работает по личным ссылкам', 'Ссылку на доступ вы получите после оплаты. Напишите нам, и мы вышлем её.', buttons);
    const box = $('.state');
    if (box) box.setAttribute('role', 'status');
  }

  /* ===================================================================== приветствие */
  // Фото готовой книги: твёрдая обложка и развороты на столе (портрет 3:4, 720×960)
  const EXAMPLES_LABEL = 'Примеры книги про Артёма и динозаврика';
  const EXAMPLE = [
    { img: '/static/img/shot-cover.jpg', w: 720, h: 960, alt: 'Книга «Артём и маленький Топик» с твёрдой обложкой: мальчик с рюкзаком и зелёный динозаврик в очках с печеньем' },
    { img: '/static/img/shot-p2.jpg', w: 720, h: 960, alt: 'Разворот 2: Артём присел рядом с динозавриком Топиком у входа в лес, слева текст, справа картинка' },
    { img: '/static/img/shot-p3.jpg', w: 720, h: 960, alt: 'Разворот 3: Артём приподнимает ветку, Топик смеётся, справа текст' },
    { img: '/static/img/shot-p4.jpg', w: 720, h: 960, alt: 'Разворот 4: Артём и Топик держатся за руки и переходят мелкую речку' },
    { img: '/static/img/shot-p6.jpg', w: 720, h: 960, alt: 'Разворот 6: на вершине на закате Артём обнимает Топика и зовёт его маму' },
    { img: '/static/img/shot-p7.jpg', w: 720, h: 960, alt: 'Разворот 7: Артём и Топик обнимаются с мамой-динозавром на цветущем лугу' },
  ];

  function exampleRail() {
    const cards = EXAMPLE.map((x, i) => {
      const img = '<img src="' + x.img + '" alt="' + esc(x.alt) + '" width="' + x.w + '" height="' + x.h + '" decoding="async"' + (i === 0 ? ' fetchpriority="high"' : ' loading="lazy"') + '>';
      return '<article class="ex shot" aria-label="' + (i === 0 ? 'Обложка' : 'Разворот книги') + '">' + img + '</article>';
    }).join('');
    const pips = EXAMPLE.map((x, i) => '<button type="button" class="pip" data-act="rail-go" data-i="' + i + '" aria-label="Пример ' + (i + 1) + ' из ' + EXAMPLE.length + '"' + (i === 0 ? ' aria-current="true"' : '') + '></button>').join('');
    return '<div class="showcase"><div class="rail" id="rail" tabindex="0" role="region" aria-roledescription="карусель" aria-label="' + EXAMPLES_LABEL + '">' + cards + '</div>' +
      '<p class="cap">' + EXAMPLES_LABEL + '</p><div class="pips" role="group" aria-label="Выбор примера">' + pips + '</div></div>';
  }

  function showWelcome() {
    leaveScreen();
    if (accessClosed()) { showClosed(); return; }
    S.screen = 'welcome';
    setBackButton(false);
    setHeader();
    const c = S.cfg;
    const left = c.limits.remaining_today;
    const pills = [];
    if (c.dev_mode) pills.push('<span class="pill dev">Режим разработчика</span>');
    if (c.mock) pills.push('<span class="pill">Тестовая сборка: картинки-заглушки</span>');
    const second = c.mock ? 'В тестовом режиме — быстрее минуты' : 'Обычно 5–15 минут, приложение можно закрыть';
    const notice = c.privacy_warning
      ? '<div class="notice warn" role="note">' + icon('warn') + '<span>' + esc(c.privacy_warning) + '</span></div>' : '';
    const closedMode = !!(c.access && c.access.closed);
    const credits = closedMode && c.access.granted && !isAdmin() && typeof c.access.credits === 'number'
      ? '<p class="credits-line">Доступно книг: <b>' + c.access.credits + '</b></p>' : '';
    const priceLine = closedMode
      ? 'Цена книги <b>' + esc(c.price_text) + '</b>. Ссылка на доступ приходит после оплаты.'
      : c.free_in_test
      ? 'Книга стоит <b>' + esc(c.price_text) + '</b>. Сейчас тест — <b>бесплатно</b>. Осталось ' + left + ' из ' + c.limits.books_per_day + ' на сегодня.'
      : 'Цена книги — <b>' + esc(c.price_text) + '</b>. Оплата переводом по QR-коду.';
    const perk = (name, b, d) => '<li><span class="e" aria-hidden="true">' + icon(name) + '</span><div><b>' + b + '</b><span class="d">' + d + '</span></div></li>';
    const startBtn = (extra) => '<button type="button" class="btn" data-act="start"' + (left < 1 ? ' disabled' : '') + (extra || '') + '>' + icon('book') + 'Создать книгу</button>';

    app.innerHTML = '<section class="screen welcome">' +
      '<header class="hero"><div class="hero-top"><span class="logo"><img class="logo-img" src="/static/img/logo.jpg" width="36" height="36" alt="" decoding="async">Bala story</span>' +
      (c.is_admin ? '<button type="button" class="btn ghost small admin-link" data-act="open-admin">' + icon('admin') + 'Админка</button>' : '') + '</div>' +
      '<div class="pills">' + pills.join('') + '</div>' +
      '<h1>Книга, где главный герой — <em>ваш малыш</em></h1>' +
      '<p class="lead">Придумаем добрую историю, нарисуем страницы и пришлём PDF-книгу прямо в чат.</p>' +
      exampleRail() +
      '<div class="cta" id="hero-cta">' +
      (left < 1 ? '<p class="form-error" role="alert">' + errorHtml('Лимит на сегодня исчерпан. Приходите завтра: малыша ждёт новая книга.') + '</p>' : '') +
      startBtn() + '<p class="price-line">' + priceLine + '</p>' + credits + '</div></header>' +
      '<div class="sheet">' +
      '<section class="block"><h2>Чем она особенная</h2><ul class="perks">' +
      perk('child', 'Герой — ваш малыш', 'Имя, характер и увлечения вплетены в сюжет, а на картинках — похожая внешность') +
      perk('heart', 'Добрый смысл без нравоучений', 'Герой сам делает выбор — и ребёнок понимает, что такое доброта, честность и смелость') +
      perk('mountains', 'С любовью к Кыргызстану', 'Горы, джайлоо, юрта и Иссык-Куль. На русском или кыргызском') +
      perk('moon', 'Исламский режим — по желанию', 'Скромная одежда героев, светлые традиции и никакой магии') +
      '</ul></section>' +
      '<section class="block"><h2>Как это работает</h2><ol class="timeline">' +
      '<li><span class="n">1</span><div><b>Отвечаете на вопросы</b><span class="d">Пара минут: имя, возраст, любимое, характер, тема книги и пожелания</span></div></li>' +
      '<li><span class="n">2</span><div><b>Мы пишем и рисуем</b><span class="d">' + second + '</span></div></li>' +
      '<li><span class="n">3</span><div><b>Получаете книгу в чат</b><span class="d">Обложка, посвящение, ' + pagesCount() + ' ' + plural(pagesCount(), ['страница', 'страницы', 'страниц']) + ' с иллюстрациями во весь разворот и тёплое пожелание</span></div></li>' +
      '</ol></section>' + (notice ? '<div class="block">' + notice + '</div>' : '') + '</div>' +
      '<div class="dock off" id="dock" aria-hidden="true">' + startBtn(' tabindex="-1"') + '</div>' +
      '</section>';
    window.scrollTo(0, 0);
    bindWelcome();
  }

  /* карусель примеров: индикатор позиции и переход по точкам; нижняя кнопка появляется, когда главная ушла с экрана */
  function bindWelcome() {
    const rail = document.getElementById('rail');
    if (rail) {
      const cards = $$('.ex', rail), pips = $$('.pip');
      let raf = 0;
      const update = () => {
        raf = 0;
        const atEnd = rail.scrollLeft >= rail.scrollWidth - rail.clientWidth - 2;
        let best = 0, dist = Infinity;
        cards.forEach((card, i) => { const d = Math.abs(card.offsetLeft - rail.scrollLeft - 20); if (d < dist) { dist = d; best = i; } });
        if (atEnd) best = cards.length - 1;
        pips.forEach((p, i) => { if (i === best) p.setAttribute('aria-current', 'true'); else p.removeAttribute('aria-current'); });
      };
      rail.addEventListener('scroll', () => { if (!raf) raf = requestAnimationFrame(update); }, { passive: true });
    }
    const cta = $('#hero-cta .btn'), dock = document.getElementById('dock');
    if (!cta || !dock) return;
    const btn = $('button', dock);
    const toggle = (visible) => {
      dock.classList.toggle('off', !visible);
      dock.setAttribute('aria-hidden', String(!visible));
      if (btn) btn.tabIndex = visible ? 0 : -1;
    };
    if ('IntersectionObserver' in window) {
      S.io = new IntersectionObserver((entries) => toggle(!entries[entries.length - 1].isIntersecting), { threshold: 0.4 });
      S.io.observe(cta);
    } else {
      toggle(true);                                      // без IntersectionObserver нижняя кнопка видна всегда
    }
  }

  function goToExample(el) {
    const rail = document.getElementById('rail');
    const card = rail && $$('.ex', rail)[Number(el.dataset.i)];
    if (!card) return;
    rail.scrollTo({ left: Math.max(0, card.offsetLeft - 20), behavior: reduceMotion ? 'auto' : 'smooth' });
    haptic.select();
  }

  /* ===================================================================== мастер */
  const NAME_RE = /^[\p{L}][\p{L}\s'’.\-]*$/u;
  const nameClean = () => S.a.name.trim().replace(/\s+/g, ' ');
  const nameOk = () => { const n = nameClean(); return n.length >= 1 && n.length <= 30 && NAME_RE.test(n); };
  const nameShown = () => esc(nameClean() || 'малыш');

  // содержимое карточки-варианта: плитка с иконкой, название, пояснение и галочка выбора
  function optionHtml(iconName, label, sub) {
    return '<span class="e" aria-hidden="true">' + icon(iconName) + '</span><span class="t"><b>' + esc(label) + '</b>' + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</span>' + icon('check', 'tick');
  }

  function choiceButtons(field, items, kind) {
    return items.map((it) => {
      const on = String(S.a[field]) === String(it.id);
      return '<button type="button" class="' + kind + '" role="radio" aria-checked="' + on + '" data-act="pick" data-field="' + field + '" data-value="' + esc(it.id) + '">' + it.html + '</button>';
    }).join('');
  }

  const STEP = {
    name: {
      title: () => 'Как зовут нашего героя?',
      hint: () => 'Мы вплетём имя в каждую страницу — малыш сразу узнает себя!',
      body: () => '<label class="field"><span class="lbl" id="l-name">Имя малыша</span>' +
        '<input class="input" id="in-name" data-field="name" maxlength="30" autocomplete="off" autocapitalize="words" enterkeyhint="next" placeholder="Например, Айдар" aria-labelledby="l-name" aria-describedby="c-name" value="' + esc(S.a.name) + '"></label>' +
        '<div class="counter" id="c-name">' + S.a.name.length + '/30</div><p class="field-error" id="e-name" role="alert" hidden></p>',
      valid: nameOk,
      mount() { focusField('in-name'); },
    },
    age: {
      title: () => 'Сколько малышу лет?',
      hint: () => 'Подберём длину и сложность книги — чтобы было в самый раз.',
      auto: true,
      body: () => '<div class="age-grid" role="radiogroup" aria-label="Возраст">' +
        choiceButtons('age', [3, 4, 5, 6, 7, 8, 9].map((n) => ({ id: n, html: n })), 'age') + '</div>' +
        '<p class="age-note">Книги подходят детям от 3 до 9 лет.</p>',
      valid: () => S.a.age != null,
    },
    gender: {
      title: () => 'Кто у нас главный герой?',
      hint: () => 'Чтобы в книге всё звучало правильно: «он пошёл» или «она пошла».',
      auto: true,
      body: () => '<div class="tiles" role="radiogroup" aria-label="Пол ребёнка">' +
        choiceButtons('gender', [
          { id: 'boy', html: '<span class="big" aria-hidden="true">' + icon('boy') + '</span><b>Мальчик</b>' },
          { id: 'girl', html: '<span class="big" aria-hidden="true">' + icon('girl') + '</span><b>Девочка</b>' },
        ], 'tile') + '</div>',
      valid: () => !!S.a.gender,
    },
    appearance: {
      optional: true,
      title: () => 'Как выглядит ' + nameShown() + '?',
      hint: () => (S.cfg.photo_supported
        ? 'Сфотографируйте малыша, и художник нарисует героя на него похожим. Это необязательно: можно просто описать словами.'
        : 'Необязательно, но тогда герой на картинках будет очень похож на малыша.'),
      body: () => (S.cfg.photo_supported ? '<div class="photo-box" id="photo-box"></div><p class="or-line"><span>или опишите словами</span></p>' : '') + [
        ['hair', 'Волосы', 'Например: тёмные кудряшки'],
        ['eyes', 'Глаза', 'Например: зелёные'],
        ['clothes', 'Одежда', 'Например: красная куртка и синие джинсы'],
      ].map((f) => '<label class="field"><span class="lbl">' + f[1] + '</span><input class="input" data-field="' + f[0] + '" maxlength="120" autocomplete="off" enterkeyhint="next" placeholder="' + f[2] + '" value="' + esc(S.a[f[0]]) + '"></label>').join(''),
      isEmpty: () => !S.photo && !S.a.hair.trim() && !S.a.eyes.trim() && !S.a.clothes.trim(),
      valid: () => !S.photo || S.a.photo_consent,
      mount() { if (S.cfg.photo_supported) refreshPhoto(); else focusField(null, 'input'); },
    },
    likes: {
      title: () => 'Что любит ' + nameShown() + '?',
      hint: () => 'Выберите до 3 любимых занятий — они станут суперсилой героя.',
      body: () => '<div class="chips-meta" id="m-likes"></div><div class="chips" id="chips-likes"></div>' +
        '<div class="add-row"><input class="input" id="in-like" maxlength="40" autocomplete="off" enterkeyhint="done" placeholder="Своё увлечение" aria-label="Своё увлечение"><button type="button" class="btn secondary small" data-act="like-add" id="b-like" disabled>' + icon('plus') + 'Добавить</button></div>',
      valid: () => S.a.likes.length >= 1,
      mount() { refreshChips('likes'); },
    },
    traits: {
      title: () => 'Какой у героя характер?',
      hint: () => 'Выберите до 3 черт — именно с ними герой справится с трудностями.',
      body: () => '<div class="chips-meta" id="m-traits"></div><div class="chips" id="chips-traits"></div>',
      valid: () => S.a.traits.length >= 1,
      mount() { refreshChips('traits'); },
    },
    place: {
      title: () => 'Где случится приключение?',
      hint: () => 'Это место появится на всех картинках — выбирайте самое любимое.',
      auto: true,
      body: () => '<div class="opts" role="radiogroup" aria-label="Место действия">' +
        choiceButtons('place', opts().places.map((p) => {
          const m = PLACE_META[p.id] || { i: 'generic', sub: '' };
          return { id: p.id, html: optionHtml(m.i, p.label, m.sub) };
        }), 'opt') + '</div><div id="custom-place"></div>',
      valid: () => !!S.a.place && (S.a.place !== 'custom' || S.a.place_custom.trim().length > 0),
      mount() { refreshCustom('place', false); },
    },
    value: {
      title: () => 'Чему научит книга?',
      hint: () => 'Герой не станет читать нотации — он покажет это своим поступком.',
      auto: true,
      body: () => '<div class="opts" role="radiogroup" aria-label="Ценность">' +
        choiceButtons('value', opts().values.map((v) => {
          const m = VALUE_META[v.id] || { i: 'generic', sub: '' };
          return { id: v.id, html: optionHtml(m.i, v.label, m.sub) };
        }), 'opt') + '</div>',
      valid: () => !!S.a.value,
    },
    topic: {
      title: () => 'Какую книгу хотите?',
      hint: () => 'Тема задаёт сюжет: про что будут приключения героя. Главным героем останется ваш малыш.',
      auto: true,
      body: () => '<div class="opts" role="radiogroup" aria-label="Тема книги">' +
        choiceButtons('topic', topicList().map((t) => {
          return { id: t.id, html: optionHtml(iconOf(TOPIC_ICON, t.id), t.label, t.hint) };
        }), 'opt') + '</div><div id="custom-topic"></div>',
      valid: () => !!S.a.topic && (S.a.topic !== 'custom' || S.a.topic_custom.trim().length > 0),
      mount() { refreshCustom('topic', false); },
    },
    // Необязательный шаг: «как в мультфильме» без чужих героев — выбираем оригинальный мир по духу; автопереход выключен, ниже есть поле
    world: {
      optional: true,
      title: () => 'Какой мир любит ' + nameShown() + '?',
      hint: () => 'Выберите, на что похоже. Герои будут похожи по духу, но свои: чужих мультперсонажей использовать нельзя',
      body: () => '<div class="opts" role="radiogroup" aria-label="Мир, который любит малыш">' +
        choiceButtons('world', worldList().map((w) => {
          return { id: w.id, html: optionHtml(iconOf(WORLD_ICON, w.id), w.label, w.hint) };
        }), 'opt') + '</div><div id="custom-world" aria-live="polite"></div>' +
        '<label class="field tight cartoons"><span class="lbl" id="l-cart">Названия любимых мультиков или героев</span>' +
        '<input class="input" id="in-cart" data-field="cartoons" maxlength="' + cartoonsMax() + '" autocomplete="off" enterkeyhint="next" aria-labelledby="l-cart" aria-describedby="n-cart c-cart" placeholder="например: Маша и Медведь, Фиксики" value="' + esc(S.a.cartoons) + '"></label>' +
        '<div class="field-foot"><p class="note" id="n-cart">Мы возьмём характер и настроение, а нарисуем своих героев</p>' +
        '<span class="counter" id="c-cart">' + S.a.cartoons.length + '/' + cartoonsMax() + '</span></div>',
      isEmpty: () => !S.a.world && !S.a.cartoons.trim(),
      valid: () => true,
      mount() { refreshWorldNote(); const h = $('h1.q'); if (h) h.focus({ preventScroll: true }); },
    },
    // Обязательный шаг с предвыбранным значением: повторное нажатие выбор не снимает; карточки покрупнее, слева большая иконка стиля
    style: {
      title: () => 'В каком стиле рисуем книгу?',
      hint: () => 'Так будут выглядеть все картинки: от обложки до последней страницы.',
      auto: true,
      body: () => '<div class="opts styles" role="radiogroup" aria-label="Стиль картинок">' +
        choiceButtons('style', styleList().map((x) => {
          return { id: x.id, html: optionHtml(iconOf(STYLE_ICON, x.id), x.label, x.hint) };
        }), 'opt style-opt') + '</div>',
      valid: () => !!stylePicked(),
    },
    extras: {
      optional: true,
      title: () => 'Что ещё добавить?',
      hint: () => 'Необязательно: расскажите, что обязательно должно быть в книге. Этот шаг можно пропустить.',
      body: () => '<label class="field tight"><span class="lbl" id="l-req">Что вы хотите увидеть в книге?</span>' +
        '<textarea class="textarea" id="in-req" data-field="request" maxlength="' + requestMax() + '" rows="4" aria-labelledby="l-req" aria-describedby="c-req" placeholder="Хочу, чтобы Алихан водил экскаватор и помогал зайчику">' + esc(S.a.request) + '</textarea></label>' +
        '<div class="counter" id="c-req">' + S.a.request.length + '/' + requestMax() + '</div>' +
        '<p class="chips-meta ex-meta" id="l-ex">Нажмите, чтобы добавить в текст:</p>' +
        '<div class="chips ex-chips" id="chips-ex" role="group" aria-labelledby="l-ex">' + requestExamples().map((x, i) =>
          '<button type="button" class="chip" data-act="req-example" data-i="' + i + '" aria-pressed="' + S.a.request.includes(x.text) + '">' + icon(x.i) + esc(x.label) + '</button>').join('') + '</div>' +
        '<label class="field tight fav"><span class="lbl" id="l-fav">Любимые герои, животные, игрушки</span>' +
        '<input class="input" id="in-fav" data-field="favorites" maxlength="' + favoritesMax() + '" autocomplete="off" enterkeyhint="next" aria-labelledby="l-fav" aria-describedby="c-fav" placeholder="например: зайчик, экскаватор, динозавр" value="' + esc(S.a.favorites) + '"></label>' +
        '<div class="counter" id="c-fav">' + S.a.favorites.length + '/' + favoritesMax() + '</div>' +
        '<div class="notice" role="note">' + icon('info') + '<span>Героев известных мультфильмов мы заменяем на похожих, но оригинальных персонажей.</span></div>',
      isEmpty: () => !S.a.request.trim() && !S.a.favorites.trim(),
      valid: () => true,
    },
    islamic: {
      title: () => 'Добавим исламские ценности?',
      hint: () => 'Это по желанию — можно просто нажать «Дальше».',
      body: () => {
        const girl = S.a.gender === 'girl';
        return '<div class="switch-row"><div class="t"><b id="sw-i">' + icon('moon') + 'Исламские ценности</b><p>Скромная одежда героев на картинках, редкие слова «Бисмиллях» и «Альхамдулиллях», никакой магии и волшебных существ.</p></div>' +
          '<button type="button" class="switch" role="switch" aria-checked="' + S.a.islamic + '" aria-labelledby="sw-i" data-act="switch" data-field="islamic"></button></div>' +
          (S.a.islamic && girl ? '<div class="switch-row"><div class="t"><b id="sw-h">' + icon('girl') + 'Героиня в платке</b><p>Необязательно: на картинках героиня будет в платке.</p></div>' +
            '<button type="button" class="switch" role="switch" aria-checked="' + S.a.headscarf + '" aria-labelledby="sw-h" data-act="switch" data-field="headscarf"></button></div>' : '');
      },
      valid: () => true,
    },
    language: {
      title: () => 'На каком языке читаем?',
      hint: () => 'Весь текст книги будет на выбранном языке.',
      auto: true,
      body: () => '<div class="tiles" role="radiogroup" aria-label="Язык книги">' +
        choiceButtons('language', [
          { id: 'ru', html: '<span class="big" aria-hidden="true">' + icon('lang_ru') + '</span><b>Русский</b><small>Книга на русском</small>' },
          { id: 'ky', html: '<span class="big" aria-hidden="true">' + icon('lang_ky') + '</span><b>Кыргызча</b><small>Китеп кыргызча</small>' },
        ], 'tile') + '</div>' +
        '<p class="sum-note">Кыргызский текст пишет нейросеть, и пока в нём возможны неточности — его обязательно вычитывает носитель языка.</p>',
      valid: () => !!S.a.language,
    },
    dedication: {
      optional: true,
      title: () => 'Что напишем на странице посвящения?',
      hint: () => 'Страница будет называться «Для ' + nameShown() + '», а под ней — ваши тёплые слова.',
      body: () => '<label class="field"><span class="lbl" id="l-ded">Посвящение</span><textarea class="textarea" id="in-ded" data-field="dedication" maxlength="120" rows="4" aria-labelledby="l-ded" aria-describedby="c-ded" placeholder="Например: Любимому сыну от мамы и папы">' + esc(S.a.dedication) + '</textarea></label>' +
        '<div class="counter" id="c-ded">' + S.a.dedication.length + '/120</div>',
      isEmpty: () => !S.a.dedication.trim(),
      valid: () => true,
      mount() { focusField('in-ded'); },
    },
    summary: {
      title: () => 'Всё готово к созданию!',
      hint: () => 'Проверьте ответы — любой можно поправить.',
      cta: () => 'Создать книгу',
      body: () => summaryHtml(),
      valid: () => true,
    },
  };

  function focusField(id, selector) {
    setTimeout(() => {
      const el = id ? document.getElementById(id) : $(selector || 'input');
      if (el && S.screen === 'wizard') { try { el.focus({ preventScroll: true }); } catch (e) { /* ok */ } }
    }, 60);
  }

  /* --- подсказки для пожеланий: нажатие вставляет готовую фразу, повторное убирает --- */
  function requestExamples() {
    const nm = nameClean() || 'малыш';
    const girl = S.a.gender === 'girl';
    return [
      { i: 'hardhat', label: 'Экскаватор', text: 'Хочу, чтобы ' + nm + (girl ? ' водила экскаватор и помогала зайчику.' : ' водил экскаватор и помогал зайчику.') },
      { i: 'dino', label: 'Динозавр', text: 'Пусть в книге будет большой добрый динозавр.' },
      { i: 'tooth', label: 'Зубки и врач', text: 'Про то, как ' + nm + ' чистит зубки и не боится идти к врачу.' },
      { i: 'elder', label: 'Бабушка', text: 'Пусть в книге будут бабушка с дедушкой и тёплые лепёшки.' },
    ];
  }

  function syncExamples() {
    const list = requestExamples();
    $$('[data-act="req-example"]').forEach((b) => b.setAttribute('aria-pressed', String(S.a.request.includes(list[Number(b.dataset.i)].text))));
  }

  function addExample(i) {
    const item = requestExamples()[i];
    const area = document.getElementById('in-req');
    if (!item || !area) return;
    const cur = S.a.request;
    let next;
    if (cur.includes(item.text)) {
      next = cur.replace(item.text, '').replace(/\s{2,}/g, ' ').trim();
    } else {
      next = cur.trim() ? cur.trim() + ' ' + item.text : item.text;
      if (next.length > requestMax()) { showFormError('Не помещается: в этом поле не больше ' + requestMax() + ' символов. Сократите текст.'); return; }
    }
    S.a.request = next;
    area.value = next;
    const counter = document.getElementById('c-req');
    if (counter) counter.textContent = next.length + '/' + requestMax();
    haptic.select();
    syncExamples();
    updateFooter();
  }

  function summaryHtml() {
    const a = S.a;
    const traits = opts().traits.filter((t) => a.traits.includes(t.id)).map(traitLabel).join(', ');
    const value = (opts().values.find((v) => v.id === a.value) || {}).label || '';
    const lang = (opts().languages.find((l) => l.id === a.language) || {}).label || '';
    const look = [S.photo ? 'по фото' : '', a.hair, a.eyes, a.clothes].map((x) => x.trim()).filter(Boolean).join('; ');
    const wishes = !a.request.trim() && !a.favorites.trim()
      ? [['extras', 'Пожелания', 'нет']]
      : [a.request.trim() && ['extras', 'Пожелания', a.request.trim()], a.favorites.trim() && ['extras', 'Любимые герои', a.favorites.trim()]].filter(Boolean);
    // мир и мультики: строка «Мир» есть всегда (даже «не выбран», чтобы её можно было изменить), «Любимые мультики» только если вписаны
    const world = worldLabel()
      ? worldLabel() + (a.world === 'custom' && !a.request.trim() ? ': опишите в пожеланиях' : '')
      : 'не выбран';
    const cartoons = a.cartoons.trim() ? [['world', 'Любимые мультики', a.cartoons.trim()]] : [];
    const style = styleLabel() || (styleList().length ? 'не выбран' : '');
    const rows = [
      ['name', 'Имя', nameClean()],
      ['age', 'Возраст', a.age + ' ' + plural(a.age, ['год', 'года', 'лет'])],
      ['gender', 'Герой', a.gender === 'girl' ? 'Девочка' : 'Мальчик'],
      ['appearance', 'Внешность', look || 'не указана'],
      ['likes', 'Любит', a.likes.join(', ')],
      ['traits', 'Характер', traits],
      ['place', 'Место', placeLabel()],
      ['value', 'Чему учит книга', value],
      ['topic', 'Тема книги', topicLabel()],
      ['world', 'Мир', world],
      ...cartoons,
      ['style', 'Стиль', style],
      ...wishes,
      ['islamic', 'Исламский режим', a.islamic ? (a.gender === 'girl' && a.headscarf ? 'Да, героиня в платке' : 'Да') : 'Нет'],
      ['language', 'Язык', lang],
      ['dedication', 'Посвящение', a.dedication.trim() || 'нет'],
    ];
    const left = S.cfg.limits.remaining_today;
    const warn = S.cfg.privacy_warning ? '<div class="notice warn" role="note">' + icon('warn') + '<span>' + esc(S.cfg.privacy_warning) + '</span></div>' : '';
    const promise = S.photo ? '<div class="notice promise" role="note">' + icon('lock') + '<b>' + esc(PHOTO_PROMISE) + '</b></div>' : '';
    const acc = S.cfg.access;
    const cost = acc && acc.closed && !isAdmin() && typeof acc.credits === 'number'
      ? 'Будет использована 1 книга по вашей ссылке (доступно: ' + acc.credits + '). '
      : (S.cfg.free_in_test ? 'Сейчас тест: книга бесплатна (осталось ' + left + ' из ' + S.cfg.limits.books_per_day + ' на сегодня). ' : 'Цена: ' + esc(S.cfg.price_text) + '. ');
    return warn + promise + '<ul class="summary">' + rows.filter((r) => S.steps.includes(r[0])).map((r) => {
      return '<li><span class="e" aria-hidden="true">' + icon(iconOf(STEP_ICON, r[0])) + '</span><span class="k">' + r[1] + '</span><span class="v' + (r[1] === 'Пожелания' || r[1] === 'Любимые мультики' ? ' clamp' : '') + '">' + esc(r[2]) + '</span>' +
        '<button type="button" class="edit" data-act="edit" data-step="' + r[0] + '" aria-label="Изменить: ' + r[1] + '">Изменить</button></li>';
    }).join('') + '</ul>' +
      '<p class="sum-note">' + cost + 'Готовую книгу пришлём в этот чат.</p>';
  }

  /* --- чипы --- */
  function chipItems(kind) {
    if (kind === 'likes') {
      const preset = opts().likes;
      return preset.concat(S.a.likes.filter((x) => !preset.includes(x))).map((x) => ({ id: x, label: x, i: iconOf(LIKE_ICON, x, 'pencil') }));
    }
    return opts().traits.map((t) => ({ id: t.id, label: traitLabel(t), i: iconOf(TRAIT_ICON, t.id, 'smile') }));
  }

  function refreshChips(kind) {
    const box = document.getElementById('chips-' + kind);
    if (!box) return;
    const selected = S.a[kind];
    box.innerHTML = chipItems(kind).map((it) => {
      const on = selected.includes(it.id);
      const dis = !on && selected.length >= 3;
      return '<button type="button" class="chip" data-act="toggle" data-kind="' + kind + '" data-id="' + esc(it.id) + '" aria-pressed="' + on + '"' + (dis ? ' aria-disabled="true"' : '') + '>' +
        (on ? icon('check') : icon(it.i)) + esc(it.label) + '</button>';
    }).join('');
    const meta = document.getElementById('m-' + kind);
    if (meta) meta.textContent = 'Выбрано ' + selected.length + ' из 3' + (selected.length >= 3 ? ' — нажмите на выбранное, чтобы убрать' : '');
    const add = document.getElementById('b-like');
    if (add) { const v = ($('#in-like') || {}).value || ''; add.disabled = !v.trim() || selected.length >= 3; }
    updateFooter();
  }

  function toggleChip(kind, id) {
    const list = S.a[kind];
    const at = list.indexOf(id);
    if (at >= 0) { list.splice(at, 1); haptic.select(); }
    else if (list.length >= 3) { haptic.bad(); const meta = document.getElementById('m-' + kind); if (meta) meta.textContent = 'Можно выбрать не больше 3. Нажмите на выбранное, чтобы убрать.'; return; }
    else { list.push(id); haptic.select(); }
    refreshChips(kind);
  }

  function addCustomLike() {
    const input = $('#in-like');
    const value = (input.value || '').trim().replace(/\s+/g, ' ');
    if (!value || S.a.likes.length >= 3) return;
    if (!S.a.likes.some((x) => x.toLowerCase() === value.toLowerCase())) S.a.likes.push(value);
    input.value = '';
    haptic.select();
    refreshChips('likes');
  }

  /* --- место и тема: свой вариант (поле появляется под списком) --- */
  const CUSTOM = {
    place: { box: 'custom-place', input: 'in-cp', lbl: 'l-cp', label: 'Опишите место', field: 'place_custom', ph: 'Например: сад у бабушки в деревне', max: () => 120 },
    topic: { box: 'custom-topic', input: 'in-ct', lbl: 'l-ct', label: 'Опишите тему', field: 'topic_custom', ph: 'Например: строим снежную крепость', max: textMax },
  };
  function refreshCustom(kind, focus) {
    const c = CUSTOM[kind];
    const box = document.getElementById(c.box);
    if (!box) return;
    if (S.a[kind] !== 'custom') { box.innerHTML = ''; return; }
    if (!box.firstChild) {
      box.innerHTML = '<label class="field custom-place"><span class="lbl" id="' + c.lbl + '">' + c.label + '</span><input class="input" id="' + c.input + '" data-field="' + c.field + '" maxlength="' + c.max() + '" autocomplete="off" enterkeyhint="next" aria-labelledby="' + c.lbl + '" placeholder="' + c.ph + '" value="' + esc(S.a[c.field]) + '"></label>';
    }
    if (focus) {
      focusField(c.input);
      setTimeout(() => { const el = document.getElementById(c.input); if (el && S.screen === 'wizard') el.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' }); }, 90);
    }
  }

  /* --- мир: для «своего варианта» подсказываем, где его описать (поле отдельно не нужно: пожелания есть на соседнем шаге) --- */
  function refreshWorldNote() {
    const box = document.getElementById('custom-world');
    if (!box) return;
    if (S.a.world !== 'custom') { box.innerHTML = ''; return; }
    if (!box.firstChild) {
      box.innerHTML = '<div class="notice world-note" role="note">' + icon('pencil') + '<span>Свой мир можно описать словами на шаге «Что ещё добавить?»</span></div>';
    }
  }

  /* --- фото --- */
  function refreshPhoto() {
    const box = document.getElementById('photo-box');
    if (!box) return;
    const note = '<p class="privacy-note">' + icon('lock') + '<span>' + esc(PHOTO_PROMISE) + '</span></p>';
    if (!S.photo) {
      box.innerHTML = '<div class="photo-btns"><label class="photo-pick" for="file-cam" tabindex="0"><span class="big" aria-hidden="true">' + icon('camera') + '</span>Сфотографировать</label>' +
        '<label class="photo-pick alt" for="file" tabindex="0"><span class="big" aria-hidden="true">' + icon('image') + '</span>Выбрать из галереи</label></div>' +
        '<input type="file" class="vh" id="file-cam" accept="image/*" capture="user"><input type="file" class="vh" id="file" accept="image/*">' + note;
    } else {
      box.innerHTML = '<div class="photo-prev"><img src="' + S.photoUrl + '" alt="Выбранное фото"><div class="t">' + icon('done') + 'Фото добавлено</div><button type="button" class="btn ghost small" data-act="photo-remove">' + icon('trash') + 'Убрать</button></div>' +
        '<label class="check-row"><input type="checkbox" id="consent" data-field="photo_consent"' + (S.a.photo_consent ? ' checked' : '') + '><span>Я родитель и согласен(на) на обработку фото для создания книги</span></label>' + note;
    }
    updateFooter();
  }

  function loadBitmap(file) {
    if (window.createImageBitmap) {
      return createImageBitmap(file, { imageOrientation: 'from-image' }).catch(() => loadImg(file));
    }
    return loadImg(file);
  }
  function loadImg(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('img')); };
      img.src = url;
    });
  }
  async function downscale(file, max) {
    const bmp = await loadBitmap(file);
    const w0 = bmp.width, h0 = bmp.height;
    const k = Math.min(1, max / Math.max(w0, h0));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(w0 * k); canvas.height = Math.round(h0 * k);
    canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('blob'))), 'image/jpeg', 0.88));
  }

  const PHOTO_LIMIT = 8 * 1024 * 1024;     // как на сервере (MAX_PHOTO_BYTES)
  const isPlainPhoto = (file) => /^image\/(jpeg|png|webp)$/i.test(file.type || '') || /\.(jpe?g|png|webp)$/i.test(file.name || '');
  const isHeic = (file) => /heic|heif/i.test((file.type || '') + ' ' + (file.name || ''));

  async function onPhotoChosen(file) {
    if (!file) return;
    let blob = null;
    try {
      blob = await downscale(file, 1024);
    } catch (e) {
      // браузер не смог уменьшить снимок (память, редкий формат): обычный JPEG/PNG небольшого размера отправляем как есть,
      // сервер уменьшит его сам и вернёт понятную ошибку, если не получится
      if (isPlainPhoto(file) && file.size <= PHOTO_LIMIT) blob = file;
    }
    if (!blob) {
      if (S.photo) return;                 // другой снимок уже добавлен (два выбора подряд): запоздалую ошибку не показываем
      showFormError(isHeic(file)
        ? 'Это фото в формате HEIC, его не удалось открыть. Выберите другой снимок или включите «Наиболее совместимый» в настройках камеры (Настройки → Камера → Форматы).'
        : 'Не получилось открыть это фото' + (file.type ? ' (' + file.type + ')' : '') + '. Выберите другой снимок в формате JPEG или PNG.');
      return;
    }
    if (S.photoUrl) URL.revokeObjectURL(S.photoUrl);
    S.photo = blob; S.photoUrl = URL.createObjectURL(blob); S.a.photo_consent = false;
    haptic.select();
    refreshPhoto();
  }

  /* --- навигация по шагам --- */
  function buildSteps() {
    const list = ['name', 'age', 'gender', 'appearance', 'likes', 'traits', 'place', 'value'];
    if (topicList().length) list.push('topic');           // старый сервер без тем: шаг пропускаем
    if (worldList().length) list.push('world');           // старый сервер без миров: шаг пропускаем
    if (styleList().length) list.push('style');           // старый сервер без стилей: шаг пропускаем
    list.push('extras', 'islamic', 'language', 'dedication', 'summary');
    return list;
  }

  function startWizard(keep) {
    S.a = freshAnswers(keep);
    if (!S.a.topic) S.a.topic = defaultTopic();
    if (!stylePicked()) S.a.style = defaultStyle();      // шаг обязательный, но уже с выбранным «3D-мультик»
    if (S.photoUrl) URL.revokeObjectURL(S.photoUrl);
    S.photo = null; S.photoUrl = null;
    S.steps = buildSteps();
    S.idx = 0;
    S.returnToSummary = false;
    renderStep('fwd');
  }

  function normalize() {
    if (!(S.a.islamic && S.a.gender === 'girl')) S.a.headscarf = false;
  }

  function renderStep(dir) {
    leaveScreen();
    S.screen = 'wizard';
    setHeader();
    const id = S.steps[S.idx];
    const st = STEP[id];
    const total = S.steps.length;
    normalize();
    const segs = S.steps.map((_, i) => '<i class="' + (i < S.idx ? 'on' : (i === S.idx ? 'now' : '')) + '"></i>').join('');
    app.innerHTML = '<section class="screen wizard" data-step="' + id + '">' +
      '<header class="topbar"><button type="button" class="back" data-act="back">' + icon('back') + 'Назад</button>' +
      '<span class="step-count">Шаг ' + (S.idx + 1) + ' из ' + total + '</span></header>' +
      '<div class="seg" role="progressbar" aria-label="Шаг ' + (S.idx + 1) + ' из ' + total + '" aria-valuemin="1" aria-valuemax="' + total + '" aria-valuenow="' + (S.idx + 1) + '">' + segs + '</div>' +
      '<main class="main enter-' + (dir || 'fwd') + '"><div class="sticker" aria-hidden="true">' + icon(iconOf(STEP_ICON, id)) + '</div>' +
      '<h1 class="q" tabindex="-1">' + st.title() + '</h1>' +
      '<p class="hint">' + st.hint() + '</p><div class="body">' + st.body() + '</div></main>' +
      '<footer class="footer"><p class="form-error" id="form-error" role="alert" hidden></p>' +
      '<button type="button" class="btn" data-act="next" id="next"></button></footer></section>';
    if (st.mount) st.mount();
    updateFooter();
    setBackButton(true);
    window.scrollTo(0, 0);
    if (!st.mount) { const h = $('h1.q'); if (h) h.focus({ preventScroll: true }); }
  }

  function updateFooter() {
    if (S.screen !== 'wizard') return;
    const btn = document.getElementById('next');
    if (!btn) return;
    const st = STEP[S.steps[S.idx]];
    const skip = st.optional && st.isEmpty && st.isEmpty();
    btn.disabled = !st.valid();
    btn.innerHTML = st.cta ? icon('book') + esc(st.cta()) : (skip ? 'Пропустить' : 'Дальше') + icon('arrow');
    hideFormError();
  }

  function showFormError(text) {
    const el = document.getElementById('form-error');
    if (el) { el.innerHTML = errorHtml(text); el.hidden = false; }
    haptic.bad();
  }
  function hideFormError() { const el = document.getElementById('form-error'); if (el) el.hidden = true; }

  function go(index, dir) {
    clearTimeout(S.autoTimer);
    S.idx = Math.max(0, Math.min(S.steps.length - 1, index));
    renderStep(dir);
  }

  function next() {
    const id = S.steps[S.idx];
    if (!STEP[id].valid()) return;
    if (id === 'summary') { submit(); return; }
    haptic.tap();
    if (S.returnToSummary) { S.returnToSummary = false; go(S.steps.length - 1, 'fwd'); return; }
    go(S.idx + 1, 'fwd');
  }

  function back() {
    haptic.tap();
    if (S.returnToSummary) { S.returnToSummary = false; go(S.steps.length - 1, 'back'); return; }
    if (S.idx === 0) { showWelcome(); return; }
    go(S.idx - 1, 'back');
  }

  function onBackButton() {
    if (S.screen === 'wizard') back();
    else if (S.screen === 'admin') { haptic.tap(); refreshConfig().then(showWelcome); }
  }

  function pick(el) {
    const field = el.dataset.field;
    let value = el.dataset.value;
    if (field === 'age') value = Number(value);
    if (field === 'world' && S.a.world === value) value = null;      // шаг необязательный: повторное нажатие снимает выбор
    S.a[field] = value;
    haptic.select();
    $$('[data-field="' + field + '"]').forEach((b) => b.setAttribute('aria-checked', String(value != null && String(b.dataset.value) === String(value))));
    if (field === 'place' || field === 'topic') refreshCustom(field, value === 'custom');
    if (field === 'world') refreshWorldNote();
    updateFooter();
    const st = STEP[S.steps[S.idx]];
    if (st.auto && value !== 'custom') {                 // «свой вариант»: сначала нужно вписать текст
      const stepId = S.steps[S.idx];
      clearTimeout(S.autoTimer);
      S.autoTimer = setTimeout(() => { if (S.screen === 'wizard' && S.steps[S.idx] === stepId && S.a[field] === value) next(); }, 260);
    }
  }

  /* --- отправка анкеты --- */
  function payload() {
    const a = S.a;
    const body = {
      name: nameClean(), age: a.age, gender: a.gender,
      appearance: { hair: a.hair.trim(), eyes: a.eyes.trim(), clothes: a.clothes.trim() },
      likes: a.likes, traits: a.traits, place: a.place, place_custom: a.place === 'custom' ? a.place_custom.trim() : '',
      value: a.value,
      topic: a.topic, topic_custom: a.topic === 'custom' ? a.topic_custom.trim() : '', request: a.request.trim(), favorites: a.favorites.trim(),
      islamic: a.islamic, headscarf: a.headscarf, language: a.language,
      dedication: a.dedication.trim(), photo_consent: !!(S.photo && a.photo_consent),
    };
    if (worldList().length) {                      // сервер без миров этих полей не знает: не шлём
      body.world = worldPicked() ? a.world : null; // пропустили шаг: null
      body.cartoons = a.cartoons.trim();
    }
    if (styleList().length) body.style = stylePicked() ? a.style : defaultStyle();   // сервер без стилей поля не знает: не шлём
    return body;
  }

  async function submit() {
    const btn = document.getElementById('next');
    if (!btn || btn.classList.contains('busy')) return;
    btn.classList.add('busy'); btn.disabled = true; btn.textContent = 'Отправляю';
    hideFormError();
    try {
      let res;
      if (S.photo) {
        const form = new FormData();
        form.append('profile', JSON.stringify(payload()));
        form.append('photo', S.photo, 'photo.jpg');
        res = await api('/api/orders', { method: 'POST', form });
      } else {
        res = await api('/api/orders', { method: 'POST', json: payload() });
      }
      haptic.ok();
      S.cfg.limits.remaining_today = Math.max(0, S.cfg.limits.remaining_today - 1);
      if (S.cfg.access && typeof S.cfg.access.credits === 'number' && !isAdmin()) S.cfg.access.credits = Math.max(0, S.cfg.access.credits - 1);
      if (res.status === 'awaiting_payment') { showPay(res.order_id); return; }
      showWait(res.order_id);
    } catch (e) {
      if (e.status === 403 && e.code === 'closed') {
        haptic.bad();
        S.closedWa = (e.data && e.data.whatsapp_url) || null;
        await refreshConfig();
        if (S.cfg.access) S.cfg.access.granted = false;
        showClosed();
        return;
      }
      if (e.status === 409 && e.data && e.data.order_id) { showWait(e.data.order_id); return; }
      btn.classList.remove('busy');
      updateFooter();
      showFormError(e.message);
      if (e.data && e.data.field && STEP_BY_FIELD[e.data.field]) {
        const stepIndex = S.steps.indexOf(STEP_BY_FIELD[e.data.field]);
        if (stepIndex >= 0) { S.returnToSummary = true; go(stepIndex, 'back'); showFormError(e.message); }
      }
    }
  }
  const STEP_BY_FIELD = { name: 'name', age: 'age', gender: 'gender', likes: 'likes', traits: 'traits', place: 'place', place_custom: 'place', value: 'value', topic: 'topic', topic_custom: 'topic', world: 'world', cartoons: 'world', style: 'style', request: 'extras', favorites: 'extras', language: 'language', dedication: 'dedication', photo: 'appearance', photo_consent: 'appearance' };

  /* ===================================================================== ожидание */
  const STAGES = [['pencil', 'Пишу книгу'], ['image', 'Рисую обложку'], ['palette', 'Иллюстрации'], ['book', 'Собираю книгу']];
  const TIPS = {
    '-1': ['Вы в очереди — скоро начнём', 'Совсем чуть-чуть, и мы возьмёмся за дело'],
    0: ['Подбираю самые тёплые слова', 'Придумываю, как герой сделает правильный выбор', 'Выбираю добрый и интересный сюжет', 'Проверяю, чтобы у книги был светлый конец'],
    1: ['Рисую героя с любовью', 'Выбираю самые тёплые краски для обложки'],
    2: ['Раскрашиваю горы и джайлоо', 'Дорисовываю улыбку нашему герою', 'Расставляю краски по местам', 'Добавляю в картинки уютные детали'],
    3: ['Складываю страницы в красивую книгу', 'Почти готово — проверяю каждую страницу'],
  };

  function rowHtml(key, label) {
    return '<li class="prow" data-k="' + key + '"><div class="thumb shimmer"></div><div class="pt"><b>' + label + '</b><div class="skels"><span class="skel"></span><span class="skel s"></span></div></div></li>';
  }

  // число страниц берём из ответа сервера (обычно 8): лишние строки убираем, недостающие добавляем
  function syncRows(n) {
    const list = $('.preview');
    if (!list) return;
    const have = $$('.prow', list).length - 1;
    for (let i = have + 1; i <= n; i++) list.insertAdjacentHTML('beforeend', rowHtml('p' + i, 'Страница ' + i));
    for (let i = have; i > n; i--) { const row = $('.prow[data-k="p' + i + '"]', list); if (row) row.remove(); }
  }

  function showWait(orderId) {
    leaveScreen();
    S.screen = 'wait';
    S.orderId = orderId;
    S.pollFails = 0;
    S.stage = 0;
    S.tipIndex = 0;
    setBackButton(false);
    setHeader();
    const eta = S.cfg.mock ? 'В тестовом режиме это быстрее минуты.' : 'Обычно 5–15 минут. Можно закрыть приложение — PDF придёт в чат.';
    const rows = rowHtml('cover', 'Обложка') + Array.from({ length: pagesCount() }, (_, i) => rowHtml('p' + (i + 1), 'Страница ' + (i + 1))).join('');
    app.innerHTML = '<section class="screen wait">' +
      '<div class="scene">' + waitArt() + '</div>' +
      '<h1>Пишем вашу книгу</h1><p class="tip" id="tip" aria-live="polite">' + TIPS[0][0] + '</p>' +
      '<div class="bar" role="progressbar" aria-label="Готовность книги" aria-valuemin="0" aria-valuemax="100" aria-valuenow="2"><i></i></div>' +
      '<ol class="stages">' + STAGES.map((s, i) => '<li data-stage="' + i + '"><span class="dot">' + icon('check') + '</span><span class="si" aria-hidden="true">' + icon(s[0]) + '</span><span class="lbl">' + s[1] + '</span></li>').join('') + '</ol>' +
      '<p class="stay">' + icon('clock') + '<span>' + eta + '</span></p>' +
      '<div id="conn"></div><h2 class="sub">Страницы появляются по мере готовности</h2><ul class="preview">' + rows + '</ul></section>';
    if (!reduceMotion) S.tipTimer = setInterval(rotateTip, 4600);
    S.pollId += 1;
    poll(S.pollId);
  }

  function rotateTip() {
    const tip = document.getElementById('tip');
    if (!tip) return;
    const list = TIPS[S.stage] || TIPS[0];
    S.tipIndex = (S.tipIndex + 1) % list.length;
    tip.classList.add('fade');
    setTimeout(() => { tip.textContent = list[S.tipIndex]; tip.classList.remove('fade'); }, 350);
  }

  async function poll(token) {
    if (token !== S.pollId) return;
    let order = null;
    try {
      order = await api('/api/orders/' + encodeURIComponent(S.orderId));
      S.pollFails = 0;
      const conn = document.getElementById('conn'); if (conn) conn.innerHTML = '';
    } catch (e) {
      if (e.status === 404 || e.status === 401) { showFatal(e, () => boot()); return; }
      S.pollFails += 1;
      const conn = document.getElementById('conn');
      if (conn && S.pollFails >= 2) conn.innerHTML = '<p class="conn">Нет связи с сервером, пробую снова…</p>';
    }
    if (token !== S.pollId) return;
    if (order) {
      S.order = order;
      if (order.status === 'awaiting_payment' || order.status === 'payment_review') { showPay(order.id, order); return; }
      if (order.status === 'cancelled') { await refreshConfig(); showWelcome(); return; }
      if (order.status === 'done') { showResult(order); return; }
      if (order.status === 'error') { showOrderError(order); return; }
      updateWait(order);
    }
    setTimeout(() => poll(token), S.pollFails > 4 ? 6000 : 1800);
  }

  function updateWait(o) {
    const p = o.progress;
    const bar = $('.bar'); if (bar) { bar.setAttribute('aria-valuenow', p.percent); $('i', bar).style.setProperty('--p', p.percent / 100); }
    if (p.stage !== S.stage && p.stage >= 0) { S.stage = p.stage; S.tipIndex = 0; const tip = document.getElementById('tip'); if (tip) tip.textContent = (TIPS[p.stage] || TIPS[0])[0]; }
    if (p.stage === -1 && S.stage !== -1) { S.stage = -1; const tip = document.getElementById('tip'); if (tip) tip.textContent = TIPS['-1'][0]; }
    $$('.stages li').forEach((li) => {
      const i = Number(li.dataset.stage);
      li.classList.toggle('done', p.stage > i);
      li.classList.toggle('active', p.stage === i);
      if (i === 2) $('.lbl', li).textContent = p.stage === 2 ? p.label : STAGES[2][1];
    });
    const first = $('.stages li[data-stage="0"] .lbl');
    if (first) first.textContent = p.stage === -1 ? 'Жду очереди…' : STAGES[0][1];
    // обложка и страницы: текст сразу после написания, картинка — когда нарисована
    if (o.pages && o.pages.length) syncRows(o.pages.length);
    fillRow('cover', o.cover_url, o.title ? o.title : null);
    (o.pages || []).forEach((page, i) => fillRow('p' + (i + 1), page.image_url, page.text));
  }

  function fillRow(key, imageUrl, text) {
    const row = $('.prow[data-k="' + key + '"]');
    if (!row) return;
    if (text && !row.dataset.text) {
      row.dataset.text = '1';
      const holder = $('.skels', row);
      if (holder) holder.outerHTML = '<p>' + esc(text) + '</p>';
    }
    if (imageUrl && !row.dataset.img) {
      row.dataset.img = '1';
      const img = new Image();
      img.alt = key === 'cover' ? 'Обложка' : 'Иллюстрация к странице ' + key.slice(1);
      img.onload = () => { img.classList.add('on'); $('.thumb', row).classList.remove('shimmer'); };
      img.src = imageUrl;
      $('.thumb', row).appendChild(img);
    }
  }

  function showOrderError(o) {
    leaveScreen();
    S.screen = 'order-error';
    haptic.bad();
    setBackButton(false);
    setHeader();
    const detail = o.error_detail ? '<details><summary>Подробности для администратора</summary><pre>' + esc(o.error_detail) + '</pre></details>' : '';
    stateScreen('sad', 'Ой, книга не получилась', o.error || 'Что-то пошло не так. Попробуйте ещё раз через несколько минут.',
      [{ act: 'retry-order', label: 'Попробовать ещё раз', icon: 'refresh' }, { act: 'home', label: 'Вернуться в начало', cls: 'ghost' }], detail);
  }

  /* ===================================================================== результат */
  /* Книга в приложении повторяет PDF: бумага, золотые линии; обложка квадратная, страницы истории с широкой картинкой 2:1 */
  const HEART = '<svg class="heart" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 21.2C7 17.6 2.6 13.9 2.6 9.2c0-2.8 2.1-4.8 4.7-4.8 1.9 0 3.6 1 4.7 2.7 1.1-1.7 2.8-2.7 4.7-2.7 2.6 0 4.7 2 4.7 4.8 0 4.7-4.4 8.4-9.4 12z"/></svg>';

  function folioHtml(n) {
    return '<div class="folio"><span class="divider" aria-hidden="true"><i></i><i></i><i></i></span><span class="badge" aria-hidden="true">' + n + '</span></div>';
  }

  /* Акценты в тексте страницы: реплики (строка начинается с тире) и предложения с «!» красим в #D4472F.
     Если сервер прислал разбор (page.lines: куски {t, a}), берём его; иначе разбираем текст сами по тем же правилам. */
  function accentRuns(line) {
    const text = String(line);
    if (/^\s*[—–-]/.test(text)) return [{ t: text, a: true }];
    const runs = [];
    const re = /[^.!?…]+(?:[.!?…]+[»"”)]*)?\s*|[.!?…]+[»"”)]*\s*/g;   // предложение вместе со знаками в конце и пробелом
    let m;
    while ((m = re.exec(text)) !== null) {
      const a = m[0].includes('!');
      const last = runs[runs.length - 1];
      if (last && last.a === a) last.t += m[0]; else runs.push({ t: m[0], a });
    }
    return runs;
  }

  function accentHtml(page) {
    const text = String(page.text == null ? '' : page.text);
    let lines = null;
    if (Array.isArray(page.lines) && page.lines.length) {
      const ok = page.lines.every((l) => Array.isArray(l) && l.every((r) => r && typeof r.t === 'string'));
      const joined = ok ? page.lines.map((l) => l.map((r) => r.t).join('')).join('\n') : '';
      if (ok && joined.replace(/\s+/g, ' ').trim() === text.replace(/\s+/g, ' ').trim()) lines = page.lines;   // разбор сервера совпал с текстом
    }
    if (!lines) lines = text.split('\n').map(accentRuns);
    return lines.map((runs) => runs.map((r) => (r.a ? '<span class="acc">' + esc(r.t) + '</span>' : esc(r.t))).join('')).join('\n');
  }

  /* Страница истории: широкая картинка 2:1 на всю ширину слайда, под ней бумажная карточка с крупным текстом.
     Чередования «картинка / текст» нет: картинка всегда сверху. В PDF та же страница идёт разворотом, текст лежит на картинке. */
  function storySlide(page, i) {
    const n = i + 1;
    const art = page.image_url ? '<div class="art wide"><img src="' + esc(page.image_url) + '" alt="Иллюстрация к странице ' + n + '" decoding="async"></div>' : '';
    const leaf = '<div class="leaf"><div class="txt"><p>' + accentHtml(page) + '</p></div>' + folioHtml(n) + '</div>';
    return '<article class="slide page" aria-label="Страница ' + n + '">' + art + leaf + '</article>';
  }

  function slidesHtml(o) {
    const b = o.book;
    const mock = o.mock ? '<p class="mock">' + esc(b.mock_note) + '</p>' : '';
    const titled = o.cover_has_title === true;      // название уже нарисовано на картинке обложки
    const out = [];
    out.push('<article class="slide cover' + (titled ? ' titled' : '') + '" aria-label="Обложка"><div class="art"><img src="' + esc(o.cover_url) + '" alt="' + esc(titled ? 'Обложка книги: ' + b.title : 'Обложка книги') + '" decoding="async"></div>' +
      (titled ? '' : '<div class="band" style="background:' + esc(o.cover_color || '#34503f') + '"><h2>' + esc(b.title) + '</h2><p>' + esc(b.caption) + '</p></div>') + '</article>');
    out.push('<article class="slide center" aria-label="Посвящение"><h2>' + esc(b.dedication_title) + '</h2>' + ORNAMENT +
      (b.dedication_text ? '<p class="it">' + esc(b.dedication_text) + '</p>' : '') + mock + '</article>');
    o.pages.forEach((p, i) => out.push(storySlide(p, i)));
    out.push('<article class="slide center end" aria-label="Конец"><h2>' + esc(b.the_end) + '</h2>' + ORNAMENT + '<div class="frame">' + esc(b.moral) + '</div>' +
      HEART + '<p class="wish">' + esc(b.wish) + '</p>' + ORNAMENT.replace('class="orn"', 'class="orn small"') + '<p class="sig">' + esc(b.signature) + '</p>' + mock + '</article>');
    return out.join('');
  }

  function deliveryHtml(o) {
    if (o.delivered === true) return '<p class="status" id="status">' + icon('check') + 'PDF уже в вашем чате</p>';
    if (o.delivered === false) {
      const bot = S.cfg.bot_username ? '<button type="button" class="btn secondary small" data-act="open-bot">Открыть бота</button>' : '';
      return '<div class="status warn" id="status"><div class="row">' + icon('warn') + '<span>PDF не отправился в чат: возможно, вы ещё не запускали бота. Скачайте файл кнопкой внизу или запустите бота (/start) и повторите отправку.</span></div>' +
        '<div class="btnrow">' + bot + '<button type="button" class="btn secondary small" data-act="resend">' + icon('send') + 'Отправить в чат ещё раз</button></div></div>';
    }
    return '';
  }

  function printHtml() {
    const p = printCfg();
    if (!p) return '';
    return '<section class="print" id="print-offer"><div class="print-head"><span class="big" aria-hidden="true">' + icon('book') + '</span><h2>' + esc(p.title || 'Хотите заказать печатную версию?') + '</h2></div>' +
      '<ul class="print-rows"><li><b>' + esc(p.pdf_price || S.cfg.price_text) + '</b> — PDF</li>' +
      '<li><b>' + esc(p.print_price) + '</b> — мягкая фотокнига 21×21 см</li></ul>' +
      (p.whatsapp_url ? '<button type="button" class="btn" data-act="print-order">' + icon('send') + 'Заказать в WhatsApp</button>' : '') + '</section>';
  }

  function feedbackHtml() {
    const f = S.fb;
    if (f.sent) return '<section class="feedback" id="feedback"><p class="thanks"><span class="big" aria-hidden="true">' + icon('heart') + '</span>Спасибо! Ваш отзыв помогает книгам становиться лучше.</p></section>';
    const price = esc(S.cfg.price_text);
    return '<section class="feedback" id="feedback"><h2>Как вам книга?</h2>' +
      '<div class="rate" role="radiogroup" aria-label="Оценка">' +
      '<button type="button" class="opt" role="radio" aria-checked="' + (f.rating === 'up') + '" data-act="fb-rate" data-v="up"><span class="big" aria-hidden="true">' + icon('smile') + '</span><b>Понравилась</b></button>' +
      '<button type="button" class="opt" role="radio" aria-checked="' + (f.rating === 'down') + '" data-act="fb-rate" data-v="down"><span class="big" aria-hidden="true">' + icon('sad') + '</span><b>Не понравилась</b></button></div>' +
      '<label class="field"><span class="lbl" id="l-fb">Комментарий (необязательно)</span><textarea class="textarea" id="fb-comment" maxlength="1000" rows="3" aria-labelledby="l-fb" placeholder="Что понравилось или что можно улучшить?">' + esc(f.comment) + '</textarea></label>' +
      '<p class="buy" id="l-buy">Купили бы такую книгу за ' + price + '?</p>' +
      '<div class="buy-row" role="radiogroup" aria-labelledby="l-buy">' + [['yes', 'Да'], ['maybe', 'Возможно'], ['no', 'Нет']].map((x) =>
        '<button type="button" class="chip" role="radio" aria-checked="' + (f.would_pay === x[0]) + '" data-act="fb-buy" data-v="' + x[0] + '">' + x[1] + '</button>').join('') + '</div>' +
      '<p class="form-error" id="fb-error" role="alert" hidden></p>' +
      '<button type="button" class="btn" data-act="fb-send" id="fb-send"' + ((f.rating || f.would_pay) ? '' : ' disabled') + '>Отправить отзыв</button></section>';
  }

  function confetti() {
    if (reduceMotion) return;
    const box = $('.confetti');
    if (!box) return;
    const colors = ['#5b45e0', '#ffd3a3', '#b9aef2', '#ff9d6b', '#e4defd', '#8f7cf0'];
    for (let i = 0; i < 46; i++) {
      const p = document.createElement('i');
      p.style.cssText = 'left:' + (Math.random() * 100).toFixed(1) + '%;width:' + (6 + Math.random() * 6).toFixed(1) + 'px;height:' + (9 + Math.random() * 9).toFixed(1) + 'px;background:' + colors[i % colors.length] +
        ';animation-duration:' + (2.6 + Math.random() * 2).toFixed(2) + 's;animation-delay:' + (Math.random() * 0.9).toFixed(2) + 's;--dx:' + ((Math.random() - 0.5) * 90).toFixed(0) + 'px;--rx:' + (Math.random() * 720 - 360).toFixed(0) + 'deg';
      box.appendChild(p);
    }
    setTimeout(() => { if (box.parentNode) box.remove(); }, 5600);
  }

  function showResult(o) {
    leaveScreen();
    S.screen = 'result';
    S.pollId += 1;
    S.order = o;
    S.fb = { rating: null, would_pay: null, comment: '', sent: false };
    setBackButton(false);
    setHeader();
    haptic.ok();
    const count = 2 + o.pages.length + 1;
    app.innerHTML = '<section class="screen result"><div class="confetti" aria-hidden="true"></div>' +
      '<header class="r-head"><div class="done" aria-hidden="true">' + icon('done') + '</div><h1>Ура! Книга готова</h1><p class="bt">' + esc(o.book.title) + '</p>' + deliveryHtml(o) + '</header>' +
      '<div class="pager-wrap"><div class="pager-nav"><button type="button" class="pn" data-act="pager-prev" aria-label="Предыдущая страница">' + icon('back') + '</button>' +
      '<span class="count" id="pager-count" aria-live="polite">1 / ' + count + '</span>' +
      '<button type="button" class="pn" data-act="pager-next" aria-label="Следующая страница">' + icon('next') + '</button></div>' +
      '<div class="pager" id="pager" tabindex="0" role="region" aria-roledescription="карусель" aria-label="Страницы книги">' + slidesHtml(o) + '</div>' +
      '<p class="pager-cap">В PDF страница идёт разворотом: картинка на оба листа, текст на ней.</p></div>' +
      printHtml() + feedbackHtml() +
      '<button type="button" class="btn secondary again" data-act="again">' + icon('gift') + 'Сделать ещё одну, для брата или сестры</button>' +
      '<footer class="footer"><button type="button" class="btn" data-act="download">' + icon('download') + 'Скачать PDF</button></footer></section>';
    bindPager(count);
    window.scrollTo(0, 0);
    confetti();
  }

  function bindPager(count) {
    const pager = document.getElementById('pager');
    const label = document.getElementById('pager-count');
    const prev = $('[data-act="pager-prev"]'), nextBtn = $('[data-act="pager-next"]');
    let raf = 0;
    const update = () => {
      raf = 0;
      const slides = $$('.slide', pager);
      const mid = pager.scrollLeft + pager.clientWidth / 2;
      let best = 0, dist = Infinity;
      slides.forEach((s, i) => { const d = Math.abs(s.offsetLeft + s.offsetWidth / 2 - mid); if (d < dist) { dist = d; best = i; } });
      label.textContent = (best + 1) + ' / ' + count;
      prev.disabled = best === 0; nextBtn.disabled = best === count - 1;
    };
    pager.addEventListener('scroll', () => { if (!raf) raf = requestAnimationFrame(update); }, { passive: true });
    pager.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight') { e.preventDefault(); pageBy(1); } else if (e.key === 'ArrowLeft') { e.preventDefault(); pageBy(-1); }
    });
    update();
  }

  function pageBy(dir) {
    const pager = document.getElementById('pager');
    const slide = $('.slide', pager);
    if (!pager || !slide) return;
    pager.scrollBy({ left: dir * (slide.offsetWidth + 12), behavior: 'smooth' });
    haptic.select();
  }

  const absUrl = (path) => new URL(path, location.origin).href;

  function downloadPdf() {
    const o = S.order;
    if (!o || !o.pdf_url) return;
    haptic.tap();
    const url = absUrl(o.pdf_url) + '&download=1';
    try {
      if (tg && tg.isVersionAtLeast && tg.isVersionAtLeast('8.0') && tg.downloadFile && url.indexOf('https://') === 0) {
        tg.downloadFile({ url, file_name: 'kniga.pdf' });
        return;
      }
      if (tg && tg.openLink) { tg.openLink(url); return; }
    } catch (e) { /* откроем обычной ссылкой */ }
    window.open(url, '_blank');
  }

  async function resend() {
    const btn = $('[data-act="resend"]');
    if (btn) { btn.disabled = true; btn.classList.add('busy'); }
    try {
      const res = await api('/api/orders/' + encodeURIComponent(S.order.id) + '/send', { method: 'POST' });
      S.order.delivered = !!res.delivered;
      const old = document.getElementById('status');
      if (old) old.outerHTML = deliveryHtml(S.order);
      if (res.delivered) haptic.ok(); else haptic.bad();
    } catch (e) {
      if (btn) { btn.disabled = false; btn.classList.remove('busy'); }
      haptic.bad();
      const old = document.getElementById('status');
      if (old) old.insertAdjacentHTML('beforeend', '<p class="field-error" role="alert">' + esc(e.message) + '</p>');
    }
  }

  async function sendFeedback() {
    const f = S.fb;
    const btn = document.getElementById('fb-send');
    btn.disabled = true; btn.classList.add('busy');
    try {
      await api('/api/feedback', { method: 'POST', json: { order_id: S.order.id, rating: f.rating, comment: f.comment.trim(), would_pay: f.would_pay } });
      f.sent = true;
      haptic.ok();
      document.getElementById('feedback').outerHTML = feedbackHtml();
    } catch (e) {
      btn.classList.remove('busy'); btn.disabled = false;
      const err = document.getElementById('fb-error');
      err.innerHTML = errorHtml(e.message); err.hidden = false;
      haptic.bad();
    }
  }

  async function refreshConfig() {
    try { S.cfg = await api('/api/config'); S.steps = buildSteps(); } catch (e) { /* оставим прежние значения */ }
  }

  async function again() {
    haptic.tap();
    const keep = { language: S.a.language, islamic: S.a.islamic, style: S.a.style };
    await refreshConfig();
    if (accessClosed()) { showClosed(); return; }
    if (S.cfg.limits.remaining_today < 1) { showWelcome(); return; }
    startWizard(keep);
  }

  /* ===================================================================== оплата по QR */
  function ago(ts) {
    if (!ts) return '';
    const m = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
    if (m < 1) return 'только что';
    if (m < 60) return m + ' мин назад';
    const h = Math.round(m / 60);
    return h < 24 ? h + ' ч назад' : Math.round(h / 24) + ' дн. назад';
  }

  function confirmDialog(text, onYes) {
    if (tg && tg.showConfirm) { try { tg.showConfirm(text, (ok) => { if (ok) onYes(); }); return; } catch (e) { /* обычный диалог */ } }
    if (window.confirm(text)) onYes();
  }

  async function showPay(orderId, order) {
    leaveScreen();
    S.screen = 'pay';
    S.orderId = orderId;
    S.pollId += 1;                      // опрос экрана ожидания больше не нужен
    const token = S.payId;
    setBackButton(false);
    setHeader();
    if (!order) {
      try { order = await api('/api/orders/' + encodeURIComponent(orderId)); }
      catch (e) { if (S.screen === 'pay' && token === S.payId) showFatal(e, () => boot()); return; }
      if (S.screen !== 'pay' || token !== S.payId) return;
    }
    if (!order.payment) {
      if (order.status === 'cancelled') { await refreshConfig(); showWelcome(); } else showWait(orderId);
      return;
    }
    S.order = order;
    const pay = order.payment;
    const sent = pay.receipt_sent;
    const note = pay.note ? '<div class="notice warn" role="alert">' + icon('warn') + '<span><b>Оплата не подтверждена.</b> ' + esc(pay.note) + '</span></div>' : '';
    const qr = pay.qr_url
      ? '<button type="button" class="qr-card" data-act="qr-zoom" aria-label="Увеличить QR-код"><img class="qr" src="' + esc(pay.qr_url) + '" alt="QR-код для оплаты" width="240" height="240"></button>'
      : '<div class="qr-card empty"><p>QR-код пока не загружен. Напишите нам, и мы всё подключим.</p></div>';
    const state = sent
      ? '<div class="pay-state" role="status"><span class="big" aria-hidden="true">' + icon('clock') + '</span><div><b>Чек получен — проверяем оплату</b><span>Обычно это занимает несколько минут. Как только мы подтвердим, книга начнёт создаваться, а в чат придёт сообщение. Приложение можно закрыть.</span></div></div>'
      : '';
    app.innerHTML = '<section class="screen pay">' +
      '<header class="pay-head"><span class="big" aria-hidden="true">' + icon('card') + '</span><h1>Оплата книги</h1>' +
      '<p>Книга для ' + esc(pay.child) + ' — <b>' + esc(pay.price_text) + '</b></p></header>' +
      '<div class="pay-body">' + note + state + (sent ? '' : qr) +
      (sent ? '' : '<p class="amount">К оплате: <b>' + esc(pay.price_text) + '</b></p>') +
      (sent || !pay.qr_url ? '' : '<button type="button" class="btn secondary small qr-save" data-act="qr-save">' + icon('download') + 'Сохранить QR в телефон</button>') +
      (sent ? '' : '<ol class="pay-steps"><li><span class="n">1</span><span>' + esc(pay.instructions) + '</span></li>' +
        '<li><span class="n">2</span><span>Переведите точную сумму и сделайте скриншот или фото чека.</span></li>' +
        '<li><span class="n">3</span><span>Нажмите «Отправить чек» внизу. Мы проверим оплату и сразу начнём писать книгу.</span></li></ol>') +
      '</div>' +
      '<footer class="footer"><p class="form-error" id="pay-error" role="alert" hidden></p>' +
      '<input type="file" class="vh" id="receipt-file" accept="image/*">' +
      (pay.qr_url ? '<label class="btn" id="receipt-btn" for="receipt-file" tabindex="0">' + icon('receipt') + (sent ? 'Отправить другой чек' : 'Отправить чек') + '</label>' : '') +
      '<button type="button" class="btn ghost small cancel-link" data-act="cancel-unpaid">Отменить заказ</button></footer></section>';
    window.scrollTo(0, 0);
    payPoll(token, pay);
  }

  function payPoll(token, shown) {
    setTimeout(async () => {
      if (token !== S.payId || S.screen !== 'pay') return;
      try {
        const o = await api('/api/orders/' + encodeURIComponent(S.orderId));
        if (token !== S.payId || S.screen !== 'pay') return;
        if (!o.payment) { if (o.status === 'cancelled') { await refreshConfig(); showWelcome(); } else showWait(S.orderId); return; }
        if (o.payment.receipt_sent !== shown.receipt_sent || o.payment.note !== shown.note) { haptic.tap(); showPay(S.orderId, o); return; }
      } catch (e) { /* попробуем позже */ }
      payPoll(token, shown);
    }, 4000);
  }

  function showPayError(text) {
    const el = document.getElementById('pay-error');
    if (el) { el.innerHTML = errorHtml(text); el.hidden = false; }
    haptic.bad();
  }

  async function uploadReceipt(file) {
    if (!file) return;
    const btn = document.getElementById('receipt-btn');
    if (btn) btn.classList.add('busy');
    const err = document.getElementById('pay-error'); if (err) err.hidden = true;
    try {
      let blob;
      try { blob = await downscale(file, 1600); } catch (e) { throw new Error('Не получилось открыть файл. Отправьте скриншот или фото чека (JPEG или PNG).'); }
      const form = new FormData();
      form.append('receipt', blob, 'check.jpg');
      await api('/api/orders/' + encodeURIComponent(S.orderId) + '/receipt', { method: 'POST', form });
      haptic.ok();
      showPay(S.orderId);
    } catch (e) {
      if (btn) btn.classList.remove('busy');
      showPayError(e.message);
    }
  }

  function cancelUnpaid() {
    confirmDialog('Отменить заказ? Анкету придётся заполнить заново.', async () => {
      try {
        await api('/api/orders/' + encodeURIComponent(S.orderId) + '/cancel', { method: 'POST' });
        await refreshConfig();
        showWelcome();
      } catch (e) { showPayError(e.message); }
    });
  }

  function zoomQr() {
    const img = $('.qr');
    if (!img) return;
    const box = document.createElement('div');
    box.className = 'qr-zoom';
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', 'QR-код');
    box.innerHTML = '<img src="' + esc(img.getAttribute('src')) + '" alt="QR-код для оплаты"><p>Нажмите, чтобы закрыть</p>';
    box.addEventListener('click', () => box.remove());
    document.body.appendChild(box);
  }

  function saveQr() {
    const o = S.order;
    if (!o || !o.payment || !o.payment.qr_url) return;
    haptic.tap();
    const url = absUrl(o.payment.qr_url) + '&download=1';
    try {
      if (tg && tg.isVersionAtLeast && tg.isVersionAtLeast('8.0') && tg.downloadFile && url.indexOf('https://') === 0) {
        tg.downloadFile({ url, file_name: 'qr-oplata.png' });
        return;
      }
      if (tg && tg.openLink) { tg.openLink(url); return; }
    } catch (e) { /* откроем обычной ссылкой */ }
    window.open(url, '_blank');
  }

  /* ===================================================================== админка */
  async function showAdmin(tab) {
    leaveScreen();
    S.screen = 'admin';
    if (tab) S.adminTab = tab;
    setBackButton(true);
    setHeader();
    if (!S.admin) app.innerHTML = '<div class="boot"><i aria-label="Загрузка"></i></div>';
    await loadAdmin();
    if (S.screen !== 'admin') return;
    S.adminTimer = setInterval(() => { if (S.screen === 'admin' && S.adminTab === 'checks' && !document.hidden) loadAdmin(true); }, 15000);
  }

  async function loadAdmin(quiet) {
    try {
      S.admin = await api('/api/admin/payments');
    } catch (e) {
      if (quiet) return;
      showFatal(e, () => showAdmin());
      return;
    }
    if (S.screen === 'admin') renderAdmin(quiet);
  }

  const closedOn = (st) => st.closed === undefined || st.closed === null ? true : !!st.closed;

  async function loadInvites() {
    try {
      const res = await api('/api/admin/invites');
      S.inv.list = (res && res.invites) || [];
      S.inv.listError = '';
    } catch (e) {
      S.inv.list = S.inv.list || [];
      S.inv.listError = e.message;
    }
    if (S.screen === 'admin' && S.adminTab === 'invites') renderAdmin(true);
  }

  function renderAdmin(quiet) {
    const a = S.admin;
    const keep = quiet ? window.scrollY : 0;
    const tabs = [['checks', 'Чеки', a.pending.length], ['invites', 'Ссылки', 0], ['settings', 'Настройки', 0]].map((t) =>
      '<button type="button" role="tab" aria-selected="' + (S.adminTab === t[0]) + '" data-act="admin-tab" data-tab="' + t[0] + '">' + t[1] + (t[2] ? '<b class="n">' + t[2] + '</b>' : '') + '</button>').join('');
    app.innerHTML = '<section class="screen admin"><header class="a-head"><h1>' + icon('admin') + 'Админка</h1>' +
      '<p>' + (closedOn(a.settings) ? 'Бот <b class="on">закрыт</b>: книги выдаются по личным ссылкам' : 'Бот <b class="off">открыт для всех</b>') + '</p>' +
      '<p>' + (a.settings.enabled && a.settings.has_qr ? 'Приём оплаты <b class="on">включён</b>' : 'Приём оплаты <b class="off">выключен</b>' + (closedOn(a.settings) ? '' : ': книги сейчас бесплатные')) +
      ' · подтверждено за сутки: ' + a.paid_today + '</p></header>' +
      '<div class="tabs" role="tablist">' + tabs + '</div><div class="a-body">' +
      (S.adminTab === 'checks' ? adminChecks(a) : S.adminTab === 'invites' ? adminInvites() : adminSettings(a.settings)) + '</div></section>';
    if (quiet) window.scrollTo(0, keep); else window.scrollTo(0, 0);
  }

  function adminChecks(a) {
    const cards = a.pending.map((p) =>
      '<article class="rcard" data-id="' + esc(p.id) + '">' +
      (p.receipt_url ? '<button type="button" class="rimg" data-act="zoom-img" data-src="' + esc(p.receipt_url) + '" aria-label="Открыть чек"><img src="' + esc(p.receipt_url) + '" alt="Чек" loading="lazy"></button>' : '') +
      '<div class="rmeta"><b>' + esc(p.user) + (p.username ? ' <small>@' + esc(p.username) + '</small>' : '') + '</b>' +
      '<span>Книга для ' + esc(p.child) + '</span><span class="ago">' + icon('receipt') + 'Чек ' + esc(ago(p.receipt_at)) + '</span></div>' +
      '<div class="ract"><button type="button" class="btn small" data-act="approve" data-id="' + esc(p.id) + '">' + icon('check') + 'Подтвердить</button>' +
      '<button type="button" class="btn small secondary" data-act="reject-open" data-id="' + esc(p.id) + '">Отклонить</button></div>' +
      '<div class="reject" hidden><div class="chips">' + ['Сумма не совпадает', 'Платёж не найден', 'Чек не читается'].map((r) =>
        '<button type="button" class="chip" data-act="reject-reason" data-text="' + esc(r) + '">' + esc(r) + '</button>').join('') + '</div>' +
      '<input class="input" type="text" maxlength="200" placeholder="Причина (покупатель её увидит)" aria-label="Причина отказа">' +
      '<button type="button" class="btn small danger" data-act="reject" data-id="' + esc(p.id) + '">Отправить отказ</button></div></article>').join('');
    const empty = '<div class="a-empty"><span class="big" aria-hidden="true">' + icon('leaf') + '</span><p>Новых чеков нет. Как только покупатель отправит чек, он появится здесь и придёт вам в чат.</p></div>';
    const waiting = a.awaiting.length
      ? '<h2 class="a-sub">Ещё не прислали чек (' + a.awaiting.length + ')</h2><ul class="mini">' + a.awaiting.map((p) =>
        '<li><div><b>' + esc(p.user) + '</b><span>' + esc(p.child) + ' · ' + esc(ago(p.created_at)) + (p.pay_note ? ' · отказ: ' + esc(p.pay_note) : '') + '</span></div>' +
        '<button type="button" class="btn small secondary" data-act="approve" data-id="' + esc(p.id) + '">Подтвердить без чека</button></li>').join('') + '</ul>' : '';
    const recent = a.recent.length
      ? '<h2 class="a-sub">Недавно подтверждены</h2><ul class="mini done">' + a.recent.map((p) =>
        '<li><div><b>' + esc(p.user) + '</b><span>' + esc(p.child) + ' · ' + esc(ago(p.paid_at)) + '</span></div><span class="tag">' + esc(p.status === 'done' ? 'книга готова' : p.status === 'error' ? 'ошибка' : 'создаётся') + '</span></li>').join('') + '</ul>' : '';
    return (cards || empty) + waiting + recent;
  }

  /* --- вкладка «Ссылки»: личные ссылки доступа --- */
  function inviteMeta(inv) {
    const books = Number(inv.credits) || 0;
    const base = books + ' ' + plural(books, ['книга', 'книги', 'книг']);
    if (inv.used_by === null || inv.used_by === undefined) return base + ' · не использована' + (inv.created_at ? ' · создана ' + ago(inv.created_at) : '');
    return base + ' · использована: ' + (inv.user_name || 'пользователь') + (inv.used_at ? ' · ' + ago(inv.used_at) : '');
  }

  function adminInvites() {
    const iv = S.inv;
    const fresh = iv.fresh
      ? '<div class="link-card" role="status"><b>' + icon('done') + 'Ссылка создана</b><p class="url" id="inv-url">' + esc(iv.fresh.url) + '</p>' +
        '<div class="btnrow"><button type="button" class="btn small" data-act="inv-copy">' + icon('copy') + 'Скопировать</button>' +
        '<button type="button" class="btn small secondary" data-act="inv-share">' + icon('share') + 'Отправить</button></div></div>' : '';
    let rows;
    if (iv.list === null) rows = '<p class="a-hint">Загружаю список…</p>';
    else if (!iv.list.length) rows = '<p class="a-hint">' + (iv.listError ? esc(iv.listError) : 'Ссылок пока нет. Создайте первую выше.') + '</p>';
    else rows = '<ul class="mini invites">' + iv.list.map((inv) => {
      const used = inv.used_by !== null && inv.used_by !== undefined;
      return '<li' + (used ? ' class="used"' : '') + '><div><b>' + esc(inv.note || 'без заметки') + '</b><span>' + esc(inviteMeta(inv)) + '</span></div>' +
        (used ? '' : '<div class="btnrow">' +
          (inv.url ? '<button type="button" class="btn small secondary" data-act="inv-copy" data-url="' + esc(inv.url) + '">' + icon('copy') + 'Скопировать</button>' : '') +
          '<button type="button" class="btn small secondary" data-act="inv-revoke" data-token="' + esc(inv.token) + '">Отозвать</button></div>') + '</li>';
    }).join('') + '</ul>';
    return '<div class="set">' +
      '<div class="switch-row stepper-row"><div class="t"><b id="l-credits">Сколько книг даёт ссылка</b></div>' +
      '<div class="stepper" role="group" aria-labelledby="l-credits">' +
      '<button type="button" class="pn" data-act="inv-minus" aria-label="Меньше"' + (iv.credits <= 1 ? ' disabled' : '') + '>' + icon('minus') + '</button>' +
      '<output class="val" id="inv-credits" aria-live="polite">' + iv.credits + '</output>' +
      '<button type="button" class="pn" data-act="inv-plus" aria-label="Больше"' + (iv.credits >= 5 ? ' disabled' : '') + '>' + icon('plus') + '</button></div></div>' +
      '<label class="field"><span class="lbl" id="l-inv-note">Заметка (видите только вы)</span><input class="input" id="inv-note" type="text" maxlength="80" autocomplete="off" aria-labelledby="l-inv-note" placeholder="Для кого, например: Айгуль, Instagram" value="' + esc(iv.note) + '"></label>' +
      '<p class="form-error" id="inv-error" role="alert"' + (iv.error ? '' : ' hidden') + '>' + (iv.error ? errorHtml(iv.error) : '') + '</p>' +
      '<button type="button" class="btn" data-act="inv-create" id="inv-create">' + icon('link') + 'Создать ссылку</button></div>' +
      fresh + '<h2 class="a-sub">Созданные ссылки</h2>' + rows;
  }

  async function createInvite() {
    const btn = document.getElementById('inv-create');
    const err = document.getElementById('inv-error');
    if (!btn || btn.disabled) return;
    if (err) err.hidden = true;
    btn.classList.add('busy'); btn.disabled = true;
    S.inv.error = '';
    try {
      const note = ((document.getElementById('inv-note') || {}).value || '').trim().slice(0, 80);
      const res = await adminAction('/api/admin/invites', { credits: S.inv.credits, note });
      S.inv.fresh = res; S.inv.note = '';
      haptic.ok();
      renderAdmin(true);
      loadInvites();
    } catch (e) {
      haptic.bad();
      S.inv.error = e.message;                       // например, 409, если бот не запущен
      btn.classList.remove('busy'); btn.disabled = false;
      if (err) { err.innerHTML = errorHtml(e.message); err.hidden = false; }
    }
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(() => true).catch(() => copyFallback(text));
    }
    return Promise.resolve(copyFallback(text));
  }
  function copyFallback(text) {
    try {
      const ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      return ok;
    } catch (e) { return false; }
  }

  async function copyInvite(el) {
    const url = el.dataset.url || (S.inv.fresh && S.inv.fresh.url);
    if (!url) return;
    const ok = await copyText(url);
    if (ok) haptic.ok(); else haptic.bad();
    showAdminToast(ok ? 'Ссылка скопирована' : 'Не получилось скопировать. Ссылка: ' + url);
  }

  function shareInvite() {
    const f = S.inv.fresh;
    if (!f || !f.url) return;
    haptic.tap();
    const link = 'https://t.me/share/url?url=' + encodeURIComponent(f.url) + '&text=' + encodeURIComponent('Ссылка для создания персональной книги:');
    try { if (tg && tg.openTelegramLink) { tg.openTelegramLink(link); return; } } catch (e) { /* откроем обычной ссылкой */ }
    window.open(link, '_blank');
  }

  function revokeInvite(el) {
    const token = el.dataset.token;
    confirmDialog('Отозвать ссылку? По ней больше нельзя будет получить доступ.', async () => {
      el.classList.add('busy'); el.disabled = true;
      try {
        await adminAction('/api/admin/invites/' + encodeURIComponent(token) + '/revoke');
        if (S.inv.fresh && S.inv.fresh.token === token) S.inv.fresh = null;
        haptic.ok();
        await loadInvites();
      } catch (e) { el.classList.remove('busy'); el.disabled = false; haptic.bad(); showAdminToast(e.message); }
    });
  }

  function adminSettings(st) {
    const qr = st.qr_url
      ? '<div class="qr-card small"><img class="qr" src="' + esc(st.qr_url) + '" alt="Текущий QR-код" width="180" height="180"></div>'
      : '<div class="qr-card empty small"><p>QR-код ещё не загружен</p></div>';
    return '<div class="set">' +
      '<div class="switch-row"><div class="t"><b id="sw-closed">' + icon('lock') + 'Закрытый бот</b><p>Книги создают только по личным ссылкам из вкладки «Ссылки». Вам доступ открыт всегда.</p></div>' +
      '<button type="button" class="switch" role="switch" aria-labelledby="sw-closed" aria-checked="' + closedOn(st) + '" data-act="closed-switch"></button></div>' +
      '<div class="switch-row"><div class="t"><b id="sw-pay">' + icon('qr') + 'Приём оплаты по QR</b><p>' + (st.has_qr ? 'Когда включено, книга создаётся только после вашего подтверждения.' : 'Сначала загрузите QR-код ниже.') + '</p></div>' +
      '<button type="button" class="switch" role="switch" aria-labelledby="sw-pay" aria-checked="' + !!st.enabled + '" data-act="pay-switch"' + (st.has_qr ? '' : ' disabled') + '></button></div>' +
      '<h2 class="a-sub">Ваш QR-код</h2>' + qr +
      '<input type="file" class="vh" id="qr-file" accept="image/*">' +
      '<label class="btn secondary small" id="qr-btn" for="qr-file" tabindex="0">' + icon('upload') + (st.has_qr ? 'Заменить QR-код' : 'Загрузить QR-код') + '</label>' +
      '<label class="field"><span class="lbl">Цена (показывается покупателю)</span><input class="input" id="set-price" type="text" maxlength="40" value="' + esc(st.price_text) + '" placeholder="499 сом"></label>' +
      '<label class="field"><span class="lbl">Цена печатной книги</span><input class="input" id="set-print" type="text" maxlength="40" value="' + esc(st.print_price || '') + '" placeholder="1 290 сом"></label>' +
      '<label class="field"><span class="lbl">Номер WhatsApp</span><input class="input" id="set-wa" type="tel" inputmode="numeric" maxlength="20" value="' + esc(st.whatsapp || '') + '" placeholder="996555123456" aria-describedby="h-wa"><span class="help" id="h-wa">Номер с кодом страны, например 996555123456. На него придут заказы печатной версии; пустое поле скрывает предложение печати.</span></label>' +
      '<label class="field"><span class="lbl">Подсказка для покупателя</span><textarea class="textarea" id="set-text" maxlength="400" rows="4" placeholder="' + esc(st.default_instructions) + '">' + esc(st.instructions) + '</textarea></label>' +
      '<p class="form-error" id="set-error" role="alert" hidden></p><p class="saved" id="set-saved" role="status" hidden>' + icon('check') + 'Сохранено</p>' +
      '<button type="button" class="btn" data-act="settings-save">' + icon('check') + 'Сохранить настройки</button></div>';
  }

  async function adminAction(path, body) {
    return api(path, { method: 'POST', json: body === undefined ? {} : body });
  }

  async function approvePayment(el) {
    const id = el.dataset.id;
    confirmDialog('Подтвердить оплату? Книга сразу начнёт создаваться.', async () => {
      el.classList.add('busy'); el.disabled = true;
      try { await adminAction('/api/admin/orders/' + encodeURIComponent(id) + '/approve'); haptic.ok(); await loadAdmin(true); }
      catch (e) { el.classList.remove('busy'); el.disabled = false; haptic.bad(); await loadAdmin(true); showAdminToast(e.message); }
    });
  }

  async function rejectPayment(el) {
    const card = el.closest('.rcard');
    const reason = card ? $('input', card).value.trim() : '';
    el.classList.add('busy'); el.disabled = true;
    try { await adminAction('/api/admin/orders/' + encodeURIComponent(el.dataset.id) + '/reject', { reason }); haptic.ok(); await loadAdmin(true); }
    catch (e) { el.classList.remove('busy'); el.disabled = false; haptic.bad(); showAdminToast(e.message); }
  }

  function showAdminToast(text) {
    const old = $('.toast'); if (old) old.remove();
    const t = document.createElement('div'); t.className = 'toast'; t.setAttribute('role', 'alert'); t.textContent = text;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }

  async function saveAdminSettings() {
    const btn = $('[data-act="settings-save"]');
    const err = document.getElementById('set-error'), ok = document.getElementById('set-saved');
    err.hidden = true; ok.hidden = true;
    btn.classList.add('busy'); btn.disabled = true;
    try {
      const st = S.admin.settings;
      const res = await adminAction('/api/admin/settings', {
        closed: closedOn(st), whatsapp: document.getElementById('set-wa').value.trim(), print_price: document.getElementById('set-print').value,
        enabled: st.enabled, price_text: document.getElementById('set-price').value, instructions: document.getElementById('set-text').value,
      });
      S.admin.settings = Object.assign({}, S.admin.settings, res);
      haptic.ok();
      renderAdmin(true);
      const saved = document.getElementById('set-saved'); if (saved) saved.hidden = false;
    } catch (e) {
      btn.classList.remove('busy'); btn.disabled = false;
      err.innerHTML = errorHtml(e.message); err.hidden = false; haptic.bad();
      const ids = { price_text: 'set-price', print_price: 'set-print', whatsapp: 'set-wa', instructions: 'set-text' };
      $$('.set .invalid').forEach((x) => x.classList.remove('invalid'));
      const bad = e.data && ids[e.data.field] && document.getElementById(ids[e.data.field]);
      if (bad) { bad.classList.add('invalid'); try { bad.focus({ preventScroll: true }); } catch (x) { /* ok */ } }
    }
  }

  async function uploadQr(file) {
    if (!file) return;
    const btn = document.getElementById('qr-btn');
    if (btn) btn.classList.add('busy');
    try {
      const form = new FormData();
      form.append('qr', file, file.name || 'qr.png');
      const res = await api('/api/admin/qr', { method: 'POST', form });
      S.admin.settings = Object.assign({}, S.admin.settings, res);
      haptic.ok();
      renderAdmin(true);
    } catch (e) {
      if (btn) btn.classList.remove('busy');
      showAdminToast(e.message);
    }
  }

  function zoomReceipt(src) {
    const box = document.createElement('div');
    box.className = 'qr-zoom dark';
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', 'Чек');
    box.innerHTML = '<img src="' + esc(src) + '" alt="Чек"><p>Нажмите, чтобы закрыть</p>';
    box.addEventListener('click', () => box.remove());
    document.body.appendChild(box);
  }

  /* ===================================================================== события */
  const ACTIONS = {
    start: () => { haptic.tap(); if (accessClosed()) { showClosed(); return; } startWizard(); },
    next, back,
    pick: (el) => pick(el),
    toggle: (el) => toggleChip(el.dataset.kind, el.dataset.id),
    'like-add': addCustomLike,
    'req-example': (el) => addExample(Number(el.dataset.i)),
    edit: (el) => { S.returnToSummary = true; go(S.steps.indexOf(el.dataset.step), 'back'); },
    switch: (el) => {
      const field = el.dataset.field;
      S.a[field] = !S.a[field];
      if (field === 'islamic' && !S.a.islamic) S.a.headscarf = false;
      haptic.select();
      $('.body').innerHTML = STEP.islamic.body();
      const again = $('[data-field="' + field + '"]'); if (again) again.focus({ preventScroll: true });
    },
    'photo-remove': () => { if (S.photoUrl) URL.revokeObjectURL(S.photoUrl); S.photo = null; S.photoUrl = null; S.a.photo_consent = false; refreshPhoto(); },
    retry: () => { if (S.retry) S.retry(); else boot(); },
    'retry-order': async () => { await refreshConfig(); S.a.name ? go(S.steps.length - 1, 'back') : showWelcome(); },
    home: async () => { await refreshConfig(); showWelcome(); },
    download: downloadPdf,
    resend,
    'open-bot': () => { const url = 'https://t.me/' + S.cfg.bot_username; if (tg && tg.openTelegramLink) tg.openTelegramLink(url); else window.open(url, '_blank'); },
    'pager-prev': () => pageBy(-1),
    'pager-next': () => pageBy(1),
    'fb-rate': (el) => { S.fb.rating = S.fb.rating === el.dataset.v ? null : el.dataset.v; haptic.select(); syncFeedback(); },
    'fb-buy': (el) => { S.fb.would_pay = S.fb.would_pay === el.dataset.v ? null : el.dataset.v; haptic.select(); syncFeedback(); },
    'fb-send': sendFeedback,
    again,
    'cancel-unpaid': cancelUnpaid,
    'qr-zoom': zoomQr,
    'qr-save': saveQr,
    'open-admin': () => { haptic.tap(); showAdmin('checks'); },
    'admin-tab': (el) => { S.adminTab = el.dataset.tab; haptic.select(); renderAdmin(); if (S.adminTab === 'invites') loadInvites(); },
    'closed-switch': (el) => { const st = S.admin.settings; st.closed = !closedOn(st); el.setAttribute('aria-checked', String(st.closed)); haptic.select(); },
    'inv-minus': () => { S.inv.credits = Math.max(1, S.inv.credits - 1); haptic.select(); renderAdmin(true); },
    'inv-plus': () => { S.inv.credits = Math.min(5, S.inv.credits + 1); haptic.select(); renderAdmin(true); },
    'inv-create': createInvite,
    'inv-copy': copyInvite,
    'inv-share': shareInvite,
    'inv-revoke': revokeInvite,
    'print-order': () => { const pr = printCfg(); haptic.tap(); if (pr && pr.whatsapp_url) openExternal(pr.whatsapp_url); },
    'wa-open': () => { haptic.tap(); openExternal(accessWaUrl()); },
    approve: approvePayment,
    'reject-open': (el) => { const r = $('.reject', el.closest('.rcard')); r.hidden = !r.hidden; if (!r.hidden) $('input', r).focus({ preventScroll: true }); },
    'reject-reason': (el) => { const input = $('input', el.closest('.reject')); input.value = el.dataset.text; haptic.select(); },
    reject: rejectPayment,
    'zoom-img': (el) => zoomReceipt(el.dataset.src),
    'rail-go': goToExample,
    'pay-switch': (el) => { S.admin.settings.enabled = !S.admin.settings.enabled; el.setAttribute('aria-checked', String(S.admin.settings.enabled)); haptic.select(); },
    'settings-save': saveAdminSettings,
  };

  function syncFeedback() {
    $$('[data-act="fb-rate"]').forEach((b) => b.setAttribute('aria-checked', String(S.fb.rating === b.dataset.v)));
    $$('[data-act="fb-buy"]').forEach((b) => b.setAttribute('aria-checked', String(S.fb.would_pay === b.dataset.v)));
    const send = document.getElementById('fb-send');
    if (send) send.disabled = !(S.fb.rating || S.fb.would_pay || S.fb.comment.trim());
  }

  document.addEventListener('click', (ev) => {
    const el = ev.target.closest('[data-act]');
    if (!el || el.disabled || (el.getAttribute('aria-disabled') === 'true' && el.dataset.act !== 'toggle')) return;
    const fn = ACTIONS[el.dataset.act];
    if (fn) fn(el, ev);
  });

  document.addEventListener('input', (ev) => {
    const el = ev.target;
    if (el.id === 'in-like') { const add = document.getElementById('b-like'); add.disabled = !el.value.trim() || S.a.likes.length >= 3; return; }
    if (el.id === 'fb-comment') { S.fb.comment = el.value; syncFeedback(); return; }
    if (el.id === 'inv-note') { S.inv.note = el.value; return; }
    const field = el.dataset && el.dataset.field;
    if (!field) return;
    if (el.type === 'checkbox') { S.a[field] = el.checked; haptic.select(); updateFooter(); return; }
    S.a[field] = el.value;
    if (field === 'name') {
      $('#c-name').textContent = el.value.length + '/30';
      const bad = el.value.trim() && !NAME_RE.test(nameClean());
      el.classList.toggle('invalid', !!bad);
      const err = $('#e-name'); err.hidden = !bad; err.textContent = bad ? 'В имени могут быть только буквы, пробел и дефис.' : '';
    }
    if (field === 'dedication') $('#c-ded').textContent = el.value.length + '/120';
    if (field === 'request') { $('#c-req').textContent = el.value.length + '/' + requestMax(); syncExamples(); }
    if (field === 'favorites') $('#c-fav').textContent = el.value.length + '/' + favoritesMax();
    if (field === 'cartoons') $('#c-cart').textContent = el.value.length + '/' + cartoonsMax();
    updateFooter();
  });

  // Страницы старых книг (до широкого формата) квадратные: если картинка не широкая, показываем её квадратом, а не обрезаем до 2:1
  document.addEventListener('load', (ev) => {
    const img = ev.target;
    if (!img || img.tagName !== 'IMG' || !img.naturalWidth || !img.naturalHeight) return;
    const art = img.closest('.art.wide');
    if (art && img.naturalWidth / img.naturalHeight < 1.5) art.classList.add('sq');
  }, true);

  document.addEventListener('change', (ev) => {
    if (ev.target.id === 'file' || ev.target.id === 'file-cam') onPhotoChosen(ev.target.files && ev.target.files[0]);
    if (ev.target.id === 'receipt-file') { const f = ev.target.files && ev.target.files[0]; ev.target.value = ''; uploadReceipt(f); }
    if (ev.target.id === 'qr-file') { const f = ev.target.files && ev.target.files[0]; ev.target.value = ''; uploadQr(f); }
  });

  document.addEventListener('keydown', (ev) => {
    if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.tagName === 'LABEL' && ev.target.htmlFor) { ev.preventDefault(); const f = document.getElementById(ev.target.htmlFor); if (f) f.click(); return; }
    if (ev.key !== 'Enter' || ev.isComposing) return;
    const el = ev.target;
    if (el.id === 'in-like') { ev.preventDefault(); addCustomLike(); return; }
    if (S.screen === 'wizard' && el.tagName === 'INPUT' && el.type === 'text') {
      ev.preventDefault();
      const btn = document.getElementById('next');
      if (btn && !btn.disabled) next();
    }
  });

  document.addEventListener('visibilitychange', async () => {
    if (document.hidden) return;
    if (S.screen === 'wait') { S.pollId += 1; poll(S.pollId); return; }
    // вернулись из бота, где открыли личную ссылку: счёт книг мог измениться
    if (S.screen === 'closed' || S.screen === 'welcome') {
      const key = () => JSON.stringify([S.cfg && S.cfg.access, S.cfg && S.cfg.limits && S.cfg.limits.remaining_today]);
      const before = key();
      await refreshConfig();
      if ((S.screen === 'closed' || S.screen === 'welcome') && key() !== before) showWelcome();
    }
  });

  /* ===================================================================== запуск */
  async function boot() {
    initTelegram();
    showBoot();
    try {
      S.cfg = await api('/api/config');
    } catch (e) {
      if (e.status === 401) { showBlocked(); return; }
      showFatal(e, boot);
      return;
    }
    S.steps = buildSteps();
    if (S.cfg.is_admin && query.get('admin') === '1') { showAdmin('checks'); return; }
    if (S.cfg.active_order_id) { showWait(S.cfg.active_order_id); return; }
    showWelcome();
  }

  boot();
})();
