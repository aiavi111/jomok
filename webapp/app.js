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

  // Палитры Telegram для проверки в обычном браузере: ?theme=dark или ?theme=light (только вне Telegram)
  const DEBUG_THEMES = {
    light: { bg_color: '#ffffff', text_color: '#000000', hint_color: '#999999', link_color: '#168acd', button_color: '#40a7e3', button_text_color: '#ffffff', secondary_bg_color: '#efeff3', destructive_text_color: '#e53935' },
    dark: { bg_color: '#212121', text_color: '#ffffff', hint_color: '#aaaaaa', link_color: '#8774e1', button_color: '#8774e1', button_text_color: '#ffffff', secondary_bg_color: '#181818', destructive_text_color: '#ff595a' },
  };
  const NIGHT = '#1b1747';

  function setHeader(color) {
    S.header = color;
    try { if (tg) tg.setHeaderColor(color); } catch (e) { /* старые версии Telegram */ }
  }

  function applyTheme() {
    const root = document.documentElement;
    const debug = !inTelegram && DEBUG_THEMES[query.get('theme')] ? query.get('theme') : null;
    if (debug) {
      const theme = DEBUG_THEMES[debug];
      Object.keys(theme).forEach((key) => root.style.setProperty('--tg-theme-' + key.replace(/_/g, '-'), theme[key]));
      root.style.colorScheme = debug;
      root.dataset.scheme = debug;
    }
    if (tg) {
      try { root.dataset.scheme = tg.colorScheme; root.style.colorScheme = tg.colorScheme; } catch (e) { /* ok */ }
      try { tg.setBackgroundColor('bg_color'); } catch (e) { /* ok */ }
      setHeader(S.header || 'bg_color');
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

  const ICONS = {
    back: '<path d="M15 5l-7 7 7 7"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    next: '<path d="M9 5l7 7-7 7"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    download: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>',
    send: '<path d="M4 12l16-8-6 16-3-6.5L4 12z"/>',
    refresh: '<path d="M19 8a7.5 7.5 0 0 0-13-2L4.5 8M4.5 4v4h4M5 16a7.5 7.5 0 0 0 13 2l1.5-2M19.5 20v-4h-4"/>',
    warn: '<path d="M12 4l9 16H3L12 4zM12 10v4.5M12 17.2v.1"/>',
    clip: '<path d="M20 11.5l-8 8a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7L10 17a1.6 1.6 0 0 1-2.3-2.3L15 7.5"/>',
    gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M18.4 5.6l-1.8 1.8M7.4 16.6l-1.8 1.8"/>',
    upload: '<path d="M12 16V5M7.5 9.5L12 5l4.5 4.5M5 19.5h14"/>',
    minus: '<path d="M5 12h14"/>',
  };
  function icon(name, cls) {
    return '<svg class="ic ' + (cls || '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || '') + '</svg>';
  }

  /* ---- эмодзи и цвета для вариантов ---- */
  const PLACE_META = {
    mountains: { e: '🏔️', hue: '#5b8def', sub: 'снежные вершины и горные ручьи' },
    yurt: { e: '🏕️', hue: '#36d6a8', sub: 'зелёные луга, кони и дымок над юртой' },
    issykkul: { e: '🌊', hue: '#3fa9f5', sub: 'синее озеро и горы вдали' },
    silkroad: { e: '🐪', hue: '#ffb020', sub: 'караваны, сладкие дыни и яркие лавки' },
    space: { e: '🚀', hue: '#7a5cff', sub: 'звёзды, планеты и уютный корабль' },
    underwater: { e: '🐠', hue: '#22c4c4', sub: 'кораллы, рыбки и лучи солнца' },
    custom: { e: '✏️', hue: '#ff7b6b', sub: 'опишите место сами' },
  };
  const VALUE_META = {
    kindness: { e: '💛', hue: '#ffb020', sub: 'делиться теплом и помогать другим' },
    honesty: { e: '🌟', hue: '#7a5cff', sub: 'говорить правду, даже когда непросто' },
    help_parents: { e: '🏡', hue: '#ff7b6b', sub: 'быть опорой для мамы и папы' },
    gratitude: { e: '🙏', hue: '#36d6a8', sub: 'ценить добро и говорить «спасибо»' },
    animals: { e: '🐑', hue: '#3fa9f5', sub: 'беречь тех, кто слабее' },
    respect_elders: { e: '👵', hue: '#ff6fb5', sub: 'слушать и помогать старшим' },
    courage: { e: '🦁', hue: '#ff8a3d', sub: 'поступать правильно, когда страшно' },
  };
  // темы книги: эмодзи и цвет плитки (подпись и подсказку отдаёт сервер в options.topics)
  const TOPIC_META = {
    adventure: { e: '🧭', hue: '#7a5cff' },
    dinosaurs: { e: '🦖', hue: '#36d6a8' },
    space: { e: '🚀', hue: '#5b8def' },
    animals: { e: '🐻', hue: '#ff8a3d' },
    superheroes: { e: '🦸', hue: '#ff7b6b' },
    pirates: { e: '🏴‍☠️', hue: '#3a4a6b' },
    sea: { e: '🌊', hue: '#3fa9f5' },
    friends: { e: '🤝', hue: '#ff6fb5' },
    kindness: { e: '💛', hue: '#ffb020' },
    life_lesson: { e: '🪥', hue: '#22c4c4' },
    custom: { e: '✏️', hue: '#ff7b6b' },
  };
  // миры «как в мультфильме» (подпись, подсказку и эмодзи отдаёт сервер в options.worlds; здесь только цвет плитки и запасное эмодзи)
  const WORLD_META = {
    forest_house: { e: '🏡', hue: '#36d6a8' },
    rescue_team: { e: '🚒', hue: '#ff7b6b' },
    workshop_helpers: { e: '🛠️', hue: '#ffb020' },
    ninja_animals: { e: '🥷', hue: '#7a5cff' },
    caped_hero: { e: '🦸', hue: '#3fa9f5' },
    kingdom: { e: '👑', hue: '#ff6fb5' },
    dino_friend: { e: '🦕', hue: '#22c493' },
    space_crew: { e: '🚀', hue: '#5b8def' },
    builders: { e: '🚜', hue: '#ff8a3d' },
    mountain_friends: { e: '🏔️', hue: '#22c4c4' },
    custom: { e: '✏️', hue: '#ff7b6b' },
  };
  // стили картинок (подпись, подсказку и эмодзи отдаёт сервер в options.styles; здесь только запасное эмодзи и цвет акцента)
  const STYLE_META = {
    cartoon3d: { e: '🧸', hue: '#ffb020' },
    flat2d: { e: '✏️', hue: '#3fa9f5' },
    realistic: { e: '📷', hue: '#8a8f98' },
  };
  const LIKE_EMOJI = { 'Лошади': '🐴', 'Животные': '🐾', 'Динозавры': '🦖', 'Машинки': '🚗', 'Рисование': '🎨', 'Музыка': '🎵', 'Футбол': '⚽', 'Куклы': '🧸', 'Космос': '🚀', 'Конструктор': '🧱', 'Книги': '📚', 'Сладости': '🍬' };
  const TRAIT_EMOJI = { kind: '💛', brave: '🦁', curious: '🔍', funny: '😄', shy: '🌸', stubborn: '💪', caring: '🤗' };
  const STEP_META = {
    name: ['👶', '#7a5cff'], age: ['🎂', '#ff7b6b'], gender: ['🧸', '#3fa9f5'], appearance: ['🎨', '#ff6fb5'],
    likes: ['❤️', '#ff7b6b'], traits: ['🌟', '#ffb020'], place: ['🗺️', '#36d6a8'], value: ['🧭', '#7a5cff'],
    topic: ['📚', '#ff8a3d'], world: ['🌈', '#ff6fb5'], style: ['🖼️', '#5b8def'], extras: ['💭', '#22c4c4'],
    islamic: ['🌙', '#5b8def'], language: ['🌍', '#3fa9f5'], dedication: ['💌', '#ff6fb5'], photo: ['📸', '#22c4c4'],
    summary: ['🎁', '#ffb020'],
  };

  const ORNAMENT = '<svg class="orn" viewBox="0 0 120 12" aria-hidden="true"><g stroke="currentColor" stroke-width="1.2"><path d="M2 6h42M76 6h42"/></g><g fill="currentColor"><circle cx="52" cy="6" r="2"/><circle cx="60" cy="6" r="3"/><circle cx="68" cy="6" r="2"/></g></svg>';

  /* ---- иллюстрации (SVG): ночное небо Тянь-Шаня ---- */
  function starfield(count, width, maxY, seed) {
    let s = seed;
    const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
    let out = '';
    for (let i = 0; i < count; i++) {
      const o = (0.35 + rnd() * 0.65).toFixed(2);
      const twinkle = i % 3 === 0 ? ' class="tw" style="--o:' + o + ';animation-delay:' + (rnd() * 3).toFixed(1) + 's"' : '';
      out += '<circle cx="' + (rnd() * width).toFixed(1) + '" cy="' + (rnd() * maxY).toFixed(1) + '" r="' + (0.5 + rnd() * 1.3).toFixed(2) + '" fill="#fff" opacity="' + o + '"' + twinkle + '/>';
    }
    return out;
  }
  function sparkle(x, y, size, delay, cls) {
    const b = size * 0.28;
    return '<path class="' + (cls || 'tw') + '" style="animation-delay:' + delay + 's" fill="#ffd978" d="M' + x + ' ' + (y - size) + 'Q' + (x + b) + ' ' + (y - b) + ' ' + (x + size) + ' ' + y +
      'Q' + (x + b) + ' ' + (y + b) + ' ' + x + ' ' + (y + size) + 'Q' + (x - b) + ' ' + (y + b) + ' ' + (x - size) + ' ' + y + 'Q' + (x - b) + ' ' + (y - b) + ' ' + x + ' ' + (y - size) + 'Z"/>';
  }

  function heroScene() {
    return '<svg viewBox="0 0 360 400" preserveAspectRatio="xMidYMax slice" aria-hidden="true">' +
      '<defs>' +
      '<linearGradient id="hs" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#15123c"/><stop offset=".45" stop-color="#2c2380"/><stop offset=".78" stop-color="#6a3fb0"/><stop offset="1" stop-color="#ff8fa3"/></linearGradient>' +
      '<radialGradient id="hg"><stop offset="0" stop-color="#ffd978" stop-opacity=".8"/><stop offset="1" stop-color="#ffd978" stop-opacity="0"/></radialGradient>' +
      '<radialGradient id="hh"><stop offset="0" stop-color="#ffb199" stop-opacity=".7"/><stop offset="1" stop-color="#ffb199" stop-opacity="0"/></radialGradient>' +
      '<mask id="hm"><rect width="360" height="400" fill="#fff"/><circle cx="310" cy="64" r="15" fill="#000"/></mask>' +
      '</defs>' +
      '<rect width="360" height="400" fill="url(#hs)"/>' +
      starfield(46, 360, 260, 7) +
      '<circle cx="302" cy="70" r="30" fill="#ffe8a3" opacity=".14"/><circle cx="302" cy="70" r="17" fill="#ffe8a3" mask="url(#hm)"/>' +
      sparkle(58, 128, 6, 0.4) + sparkle(322, 168, 7, 1.3) + sparkle(190, 232, 5, 2.1) + sparkle(30, 232, 4, 0.9) +
      '<ellipse cx="180" cy="330" rx="260" ry="80" fill="url(#hh)"/>' +
      '<path d="M0 338L36 318 64 332 104 300 148 330 190 310 236 336 282 304 324 330 360 316V400H0Z" fill="#4a3aa6" opacity=".85"/>' +
      '<path d="M104 300l-8 11 5-2 5 5 5-5 3 2z" fill="#fff" opacity=".6"/><path d="M282 304l-8 11 5-2 5 5 5-5 3 2z" fill="#fff" opacity=".6"/>' +
      '<path d="M0 360L46 340 96 358 146 334 202 360 254 338 306 358 360 340V400H0Z" fill="#33288a"/>' +
      '<circle cx="236" cy="324" r="52" fill="url(#hg)" class="fl"/>' +
      '<g class="fl"><path d="M192 316v26c16-4 32-3 44 6 12-9 28-10 44-6v-26z" fill="#5b3fe0"/>' +
      '<path d="M236 320c-12-8-28-10-40-6v24c12-3 28-2 40 6z" fill="#fff7e0"/><path d="M236 320c12-8 28-10 40-6v24c-12-3-28-2-40 6z" fill="#fffaf0"/>' +
      '<g stroke="#d9c9a0" stroke-width="1.2" stroke-linecap="round"><path d="M202 322h26M202 328h22M202 334h24M244 322h26M246 328h22M244 334h24"/></g>' +
      '<path d="M236 320v28" stroke="#c9b88a" stroke-width="1"/></g>' +
      sparkle(210, 296, 6, 0, 'rs') + sparkle(264, 288, 7, 1, 'rs') + sparkle(238, 272, 5, 2, 'rs') +
      '<g transform="translate(0,-30)"><path d="M0 380Q60 362 130 374T250 372T360 366V430H0Z" fill="#231b66"/>' +
      '<circle cx="66" cy="380" r="18" fill="#ffc24d" opacity=".22"/>' +
      '<path d="M46 382a20 15 0 0 1 40 0z" fill="#fbe7c6"/><rect x="46" y="380" width="40" height="10" fill="#f0d4a0"/>' +
      '<rect x="61" y="382" width="10" height="8" rx="5" fill="#ffc24d"/><path d="M66 367v-5" stroke="#f0d4a0" stroke-width="2" stroke-linecap="round"/>' +
      '<path class="sm" d="M66 361c-3-4 3-7 0-11" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" opacity=".5"/>' +
      '<path d="M0 396Q90 382 180 394T360 390V430H0Z" fill="#150f45"/></g>' +
      '</svg>';
  }

  function bookScene() {
    const pages = ['#fffaf0', '#fff0cf', '#ffe8bb']
      .map((fill, i) => '<path class="pg" style="animation-delay:' + (i * 0.9).toFixed(1) + 's" fill="' + fill + '" stroke="#e2d2a6" stroke-width=".8" d="M160 128c20-14 60-18 94-10v30c-34-6-74-2-94 10z"/>').join('');
    return '<svg viewBox="0 0 320 196" preserveAspectRatio="xMidYMid slice" aria-hidden="true">' +
      '<defs><linearGradient id="ws" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#15123c"/><stop offset=".6" stop-color="#2c2380"/><stop offset="1" stop-color="#6a3fb0"/></linearGradient>' +
      '<radialGradient id="wg"><stop offset="0" stop-color="#ffd978" stop-opacity=".7"/><stop offset="1" stop-color="#ffd978" stop-opacity="0"/></radialGradient></defs>' +
      '<rect width="320" height="196" fill="url(#ws)"/>' + starfield(34, 320, 150, 11) +
      '<path d="M0 196V176l36-20 40 18 52-26 44 22 52-24 46 22 50-18v46z" fill="#241b66" opacity=".9"/>' +
      '<circle cx="160" cy="128" r="84" fill="url(#wg)"/>' +
      '<g><path d="M56 118v36c40-6 80-4 104 8 24-12 64-14 104-8v-36z" fill="#5b3fe0"/>' +
      '<path d="M160 128c-20-14-60-18-94-10v30c34-6 74-2 94 10z" fill="#fff7e0"/><path d="M160 128c20-14 60-18 94-10v30c-34-6-74-2-94 10z" fill="#fffaf0"/>' +
      '<g stroke="#d9c9a0" stroke-width="1.3" stroke-linecap="round"><path d="M76 126h54M76 134h48M76 142h52M190 126h54M192 134h48M190 142h52"/></g>' +
      pages + '<path d="M160 128v32" stroke="#c9b88a" stroke-width="1.2"/></g>' +
      sparkle(108, 92, 7, 0, 'rs') + sparkle(160, 70, 8, 0.9, 'rs') + sparkle(214, 90, 7, 1.8, 'rs') + sparkle(132, 52, 5, 1.3, 'rs') + sparkle(192, 48, 5, 2.2, 'rs') +
      '<g class="fl"><path d="M250 60c26-10 44-34 52-58-26 4-46 18-58 38-6 10-2 18 6 20z" fill="#ffc24d"/><path d="M246 76l8-18" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/></g>' +
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
    S.payId += 1;
  }

  /* ===================================================================== экраны-заглушки */
  function showBoot() {
    S.screen = 'boot';
    app.innerHTML = '<div class="boot"><i aria-label="Загрузка"></i></div>';
    setBackButton(false);
  }

  function stateScreen(emoji, title, text, buttons, extra) {
    const btns = (buttons || []).map((b) => '<button type="button" class="btn ' + (b.cls || '') + '" data-act="' + b.act + '">' + (b.icon ? icon(b.icon) : '') + esc(b.label) + '</button>').join('');
    app.innerHTML = '<section class="screen state" role="alert"><div class="big em" aria-hidden="true">' + emoji + '</div>' +
      '<h1>' + esc(title) + '</h1><p>' + esc(text) + '</p>' + (extra || '') +
      (btns ? '<div class="btns">' + btns + '</div>' : '') + '</section>';
  }

  function showBlocked() {
    leaveScreen();
    S.screen = 'blocked';
    setBackButton(false);
    setHeader('bg_color');
    stateScreen('📱', 'Откройте приложение в Telegram',
      'Эта страница работает внутри Telegram. Найдите нашего бота и нажмите кнопку «Создать книгу» — там всё и случится ✨', [],
      '<details><summary>Для владельца бота</summary><pre>Чтобы проверить в обычном браузере, поставьте DEV_MODE=1 в файле .env и перезапустите сервер.</pre></details>');
  }

  function showFatal(err, retry) {
    leaveScreen();
    S.screen = 'fatal';
    haptic.bad();
    setBackButton(false);
    setHeader('bg_color');
    S.retry = retry;
    stateScreen('😕', 'Что-то пошло не так', err.message || 'Не получилось открыть приложение.',
      [{ act: 'retry', label: 'Попробовать ещё раз', icon: 'refresh' }]);
  }

  // Закрытый бот: создавать книгу можно только по личной ссылке
  function showClosed() {
    leaveScreen();
    S.screen = 'closed';
    setBackButton(false);
    setHeader('bg_color');
    const buttons = [];
    if (accessWaUrl()) buttons.push({ act: 'wa-open', label: 'Написать в WhatsApp', icon: 'send' });
    buttons.push({ act: 'home', label: 'Проверить доступ', cls: 'ghost', icon: 'refresh' });
    stateScreen('🔒', 'Бот работает по личным ссылкам', 'Ссылку на доступ вы получите после оплаты. Напишите нам, и мы вышлем её.', buttons);
    const box = $('.state');
    if (box) box.setAttribute('role', 'status');
  }

  /* ===================================================================== приветствие */
  const EXAMPLE = [
    { img: '/static/img/ex-cover.jpg', alt: 'Обложка: мальчик в синей жилетке с карандашом на джайлоо', cover: true, title: 'Айдар и Золотой Конь', sub: 'Книга для Айдара' },
    { img: '/static/img/ex-p1.jpg', alt: 'Мальчик читает книгу у юрты', text: 'Шестилетний Айдар жил в уютной юрте на красивом зелёном джайлоо. Больше всего на свете мальчик любил рисовать весёлые картинки и любоваться быстрыми лошадьми.' },
    { img: '/static/img/ex-p3.jpg', alt: 'Мальчик и сурок на горной тропинке', text: 'Около горной тропинки Айдар встретил пушистого сурка. Зверёк сидел на камне и горько плакал, потому что потерял свой любимый круглый камушек.' },
    { img: '/static/img/ex-p4.jpg', alt: 'Мальчик на бревенчатом мостике над ручьём', text: 'Путь лежал через узкий мостик над весёлым журчащим ручьём. Айдар смело зашагал вперёд, рассматривая цветы и бабочек вокруг.' },
  ];

  function showWelcome() {
    leaveScreen();
    if (accessClosed()) { showClosed(); return; }
    S.screen = 'welcome';
    setBackButton(false);
    setHeader(NIGHT);
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
      ? 'Книга стоит <b>' + esc(c.price_text) + '</b>. Сейчас тест — <b>бесплатно</b> 🎉 Осталось ' + left + ' из ' + c.limits.books_per_day + ' на сегодня.'
      : 'Цена книги — <b>' + esc(c.price_text) + '</b>. Оплата переводом по QR-коду 💛';
    const rail = EXAMPLE.map((x) => x.cover
      ? '<article class="ex cover-ex"><img src="' + x.img + '" alt="' + esc(x.alt) + '" width="232" height="232" loading="lazy"><p>' + esc(x.title) + '<small>' + esc(x.sub) + '</small></p></article>'
      : '<article class="ex"><img src="' + x.img + '" alt="' + esc(x.alt) + '" width="232" height="232" loading="lazy"><p>' + esc(x.text) + '</p></article>').join('');
    const perk = (e, hue, b, d) => '<li><span class="e em" style="--hue:' + hue + '" aria-hidden="true">' + e + '</span><div><b>' + b + '</b><span class="d">' + d + '</span></div></li>';

    app.innerHTML = '<section class="screen welcome">' +
      '<header class="hero"><div class="hero-art">' + heroScene() + '</div>' +
      '<div class="hero-text"><div class="pills">' + pills.join('') + '</div>' +
      '<h1>Книга, где главный герой — ваш малыш ✨</h1>' +
      '<p class="lead">Придумаем историю с добрым смыслом, нарисуем иллюстрации и пришлём красивую PDF-книгу прямо в Telegram.</p></div></header>' +
      '<div class="sheet">' +
      '<section class="block"><h2>Вот так выглядит книга 📖</h2><div class="rail" tabindex="0" aria-label="Страницы примера">' + rail + '</div>' +
      '<p class="cap">Пример: книга для Айдара, шесть лет. Такую же вы получите для своего малыша.</p></section>' +
      '<section class="block"><h2>Чем она особенная 💫</h2><ul class="perks">' +
      perk('👶', '#7a5cff', 'Герой — ваш малыш', 'Имя, характер и увлечения вплетены в сюжет, а на картинках — похожая внешность') +
      perk('💛', '#ffb020', 'Добрый смысл без нравоучений', 'Герой сам делает выбор — и ребёнок понимает, что такое доброта, честность и смелость') +
      perk('🏔️', '#36d6a8', 'С любовью к Кыргызстану', 'Горы, джайлоо, юрта и Иссык-Куль. На русском или кыргызском') +
      perk('🌙', '#5b8def', 'Исламский режим — по желанию', 'Скромная одежда героев, светлые традиции и никакой магии') +
      '</ul></section>' +
      '<section class="block"><h2>Как это работает 🧭</h2><ol class="timeline">' +
      '<li><span class="n">1</span><div><b>Отвечаете на вопросы</b><span class="d">Пара минут: имя, возраст, любимое, характер, тема книги и пожелания</span></div></li>' +
      '<li><span class="n">2</span><div><b>Мы пишем и рисуем</b><span class="d">' + second + '</span></div></li>' +
      '<li><span class="n">3</span><div><b>Получаете книгу в чат 💌</b><span class="d">Обложка, посвящение, ' + pagesCount() + ' ' + plural(pagesCount(), ['страница', 'страницы', 'страниц']) + ' с иллюстрациями во весь разворот и тёплое пожелание</span></div></li>' +
      '</ol></section>' + (notice ? '<div class="block">' + notice + '</div>' : '') +
      '<p class="price">' + priceLine + '</p>' + credits + '</div>' +
      '<footer class="footer">' +
      (left < 1 ? '<p class="form-error" role="alert">Лимит на сегодня исчерпан. Приходите завтра — малыша ждёт новая книга 🌙</p>' : '') +
      '<button type="button" class="btn" data-act="start"' + (left < 1 ? ' disabled' : '') + '>✨ Создать книгу</button>' +
      (c.is_admin ? '<button type="button" class="btn ghost small admin-link" data-act="open-admin">' + icon('gear') + 'Админка</button>' : '') + '</footer>' +
      '</section>';
    window.scrollTo(0, 0);
  }

  /* ===================================================================== мастер */
  const NAME_RE = /^[\p{L}][\p{L}\s'’.\-]*$/u;
  const nameClean = () => S.a.name.trim().replace(/\s+/g, ' ');
  const nameOk = () => { const n = nameClean(); return n.length >= 1 && n.length <= 30 && NAME_RE.test(n); };
  const nameShown = () => esc(nameClean() || 'малыш');

  function choiceButtons(field, items, kind) {
    return items.map((it) => {
      const on = String(S.a[field]) === String(it.id);
      return '<button type="button" class="' + kind + '" role="radio" aria-checked="' + on + '" data-act="pick" data-field="' + field + '" data-value="' + esc(it.id) + '">' + it.html + '</button>';
    }).join('');
  }

  const STEP = {
    name: {
      title: () => 'Как зовут нашего героя?',
      hint: () => 'Мы вплетём имя в каждую страницу — малыш сразу узнает себя! 💛',
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
        '<p class="age-note">Книги подходят детям от 3 до 9 лет 🌈</p>',
      valid: () => S.a.age != null,
    },
    gender: {
      title: () => 'Кто у нас главный герой?',
      hint: () => 'Чтобы в книге всё звучало правильно: «он пошёл» или «она пошла».',
      auto: true,
      body: () => '<div class="tiles" role="radiogroup" aria-label="Пол ребёнка">' +
        choiceButtons('gender', [
          { id: 'boy', html: '<span class="big em" aria-hidden="true">👦</span><b>Мальчик</b>' },
          { id: 'girl', html: '<span class="big em" aria-hidden="true">👧</span><b>Девочка</b>' },
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
      hint: () => 'Выберите до 3 любимых занятий — они станут суперсилой героя 💪',
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
          const m = PLACE_META[p.id] || PLACE_META.custom;
          return { id: p.id, html: '<span class="e em" style="--hue:' + m.hue + '" aria-hidden="true">' + m.e + '</span><span class="t"><b>' + esc(p.label) + '</b><small>' + m.sub + '</small></span>' + icon('check', 'tick') };
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
          const m = VALUE_META[v.id] || VALUE_META.kindness;
          return { id: v.id, html: '<span class="e em" style="--hue:' + m.hue + '" aria-hidden="true">' + m.e + '</span><span class="t"><b>' + esc(v.label) + '</b><small>' + m.sub + '</small></span>' + icon('check', 'tick') };
        }), 'opt') + '</div>',
      valid: () => !!S.a.value,
    },
    topic: {
      title: () => 'Какую книгу хотите?',
      hint: () => 'Тема задаёт сюжет: про что будут приключения героя. Главным героем останется ваш малыш.',
      auto: true,
      body: () => '<div class="opts" role="radiogroup" aria-label="Тема книги">' +
        choiceButtons('topic', topicList().map((t) => {
          const m = TOPIC_META[t.id] || { e: t.emoji || '✨', hue: '#7a5cff' };
          return { id: t.id, html: '<span class="e em" style="--hue:' + m.hue + '" aria-hidden="true">' + m.e + '</span><span class="t"><b>' + esc(t.label) + '</b>' + (t.hint ? '<small>' + esc(t.hint) + '</small>' : '') + '</span>' + icon('check', 'tick') };
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
          const m = WORLD_META[w.id] || { e: '✨', hue: '#7a5cff' };
          return { id: w.id, html: '<span class="e em" style="--hue:' + m.hue + '" aria-hidden="true">' + esc(w.emoji || m.e) + '</span><span class="t"><b>' + esc(w.label) + '</b>' + (w.hint ? '<small>' + esc(w.hint) + '</small>' : '') + '</span>' + icon('check', 'tick') };
        }), 'opt') + '</div><div id="custom-world" aria-live="polite"></div>' +
        '<label class="field tight cartoons"><span class="lbl" id="l-cart">Названия любимых мультиков или героев</span>' +
        '<input class="input" id="in-cart" data-field="cartoons" maxlength="' + cartoonsMax() + '" autocomplete="off" enterkeyhint="next" aria-labelledby="l-cart" aria-describedby="n-cart c-cart" placeholder="например: Маша и Медведь, Фиксики" value="' + esc(S.a.cartoons) + '"></label>' +
        '<div class="field-foot"><p class="note" id="n-cart">Мы возьмём характер и настроение, а нарисуем своих героев</p>' +
        '<span class="counter" id="c-cart">' + S.a.cartoons.length + '/' + cartoonsMax() + '</span></div>',
      isEmpty: () => !S.a.world && !S.a.cartoons.trim(),
      valid: () => true,
      mount() { refreshWorldNote(); const h = $('h1.q'); if (h) h.focus({ preventScroll: true }); },
    },
    // Обязательный шаг с предвыбранным значением: повторное нажатие выбор не снимает; карточки покрупнее, слева цветной акцент-превью
    style: {
      title: () => 'В каком стиле рисуем книгу?',
      hint: () => 'Так будут выглядеть все картинки: от обложки до последней страницы.',
      auto: true,
      body: () => '<div class="opts styles" role="radiogroup" aria-label="Стиль картинок">' +
        choiceButtons('style', styleList().map((x) => {
          const m = STYLE_META[x.id] || { e: '🖼️', hue: '#7a5cff' };
          return { id: x.id, html: '<span class="e em sty sty-' + esc(x.id) + '" style="--hue:' + m.hue + '" aria-hidden="true">' + esc(x.emoji || m.e) + '</span><span class="t"><b>' + esc(x.label) + '</b>' + (x.hint ? '<small>' + esc(x.hint) + '</small>' : '') + '</span>' + icon('check', 'tick') };
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
          '<button type="button" class="chip" data-act="req-example" data-i="' + i + '" aria-pressed="' + S.a.request.includes(x.text) + '"><span class="e em" aria-hidden="true">' + x.e + '</span>' + esc(x.label) + '</button>').join('') + '</div>' +
        '<label class="field tight fav"><span class="lbl" id="l-fav">Любимые герои, животные, игрушки</span>' +
        '<input class="input" id="in-fav" data-field="favorites" maxlength="' + favoritesMax() + '" autocomplete="off" enterkeyhint="next" aria-labelledby="l-fav" aria-describedby="c-fav" placeholder="например: зайчик, экскаватор, динозавр" value="' + esc(S.a.favorites) + '"></label>' +
        '<div class="counter" id="c-fav">' + S.a.favorites.length + '/' + favoritesMax() + '</div>' +
        '<div class="notice" role="note"><span class="em" aria-hidden="true">🎭</span><span>Героев известных мультфильмов мы заменяем на похожих, но оригинальных персонажей.</span></div>',
      isEmpty: () => !S.a.request.trim() && !S.a.favorites.trim(),
      valid: () => true,
    },
    islamic: {
      title: () => 'Добавим исламские ценности?',
      hint: () => 'Это по желанию — можно просто нажать «Дальше».',
      body: () => {
        const girl = S.a.gender === 'girl';
        return '<div class="switch-row"><div class="t"><b id="sw-i">🌙 Исламские ценности</b><p>Скромная одежда героев на картинках, редкие слова «Бисмиллях» и «Альхамдулиллях», никакой магии и волшебных существ.</p></div>' +
          '<button type="button" class="switch" role="switch" aria-checked="' + S.a.islamic + '" aria-labelledby="sw-i" data-act="switch" data-field="islamic"></button></div>' +
          (S.a.islamic && girl ? '<div class="switch-row"><div class="t"><b id="sw-h">🧕 Героиня в платке</b><p>Необязательно: на картинках героиня будет в платке.</p></div>' +
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
          { id: 'ru', html: '<span class="big em" aria-hidden="true">📗</span><b>Русский</b><small>Книга на русском</small>' },
          { id: 'ky', html: '<span class="big em" aria-hidden="true">📘</span><b>Кыргызча</b><small>Китеп кыргызча</small>' },
        ], 'tile') + '</div>' +
        '<p class="sum-note">Кыргызский текст пишет нейросеть, и пока в нём возможны неточности — его обязательно вычитывает носитель языка 🙏</p>',
      valid: () => !!S.a.language,
    },
    dedication: {
      optional: true,
      title: () => 'Что напишем на странице посвящения?',
      hint: () => 'Страница будет называться «Для ' + nameShown() + '», а под ней — ваши тёплые слова.',
      body: () => '<label class="field"><span class="lbl" id="l-ded">Посвящение</span><textarea class="textarea" id="in-ded" data-field="dedication" maxlength="120" rows="4" aria-labelledby="l-ded" aria-describedby="c-ded" placeholder="Например: Любимому сыну от мамы и папы 💛">' + esc(S.a.dedication) + '</textarea></label>' +
        '<div class="counter" id="c-ded">' + S.a.dedication.length + '/120</div>',
      isEmpty: () => !S.a.dedication.trim(),
      valid: () => true,
      mount() { focusField('in-ded'); },
    },
    summary: {
      title: () => 'Всё готово к созданию! 🎉',
      hint: () => 'Проверьте ответы — любой можно поправить.',
      cta: () => '✨ Создать книгу',
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
      { e: '🚜', label: 'Экскаватор', text: 'Хочу, чтобы ' + nm + (girl ? ' водила экскаватор и помогала зайчику.' : ' водил экскаватор и помогал зайчику.') },
      { e: '🦕', label: 'Динозавр', text: 'Пусть в книге будет большой добрый динозавр.' },
      { e: '🪥', label: 'Зубки и врач', text: 'Про то, как ' + nm + ' чистит зубки и не боится идти к врачу.' },
      { e: '👵', label: 'Бабушка', text: 'Пусть в книге будут бабушка с дедушкой и тёплые лепёшки.' },
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
    const promise = S.photo ? '<div class="notice promise" role="note"><span class="em" aria-hidden="true">🔒</span><b>' + esc(PHOTO_PROMISE) + '</b></div>' : '';
    const acc = S.cfg.access;
    const cost = acc && acc.closed && !isAdmin() && typeof acc.credits === 'number'
      ? 'Будет использована 1 книга по вашей ссылке (доступно: ' + acc.credits + '). '
      : (S.cfg.free_in_test ? 'Сейчас тест: книга бесплатна (осталось ' + left + ' из ' + S.cfg.limits.books_per_day + ' на сегодня). ' : 'Цена: ' + esc(S.cfg.price_text) + '. ');
    return warn + promise + '<ul class="summary">' + rows.filter((r) => S.steps.includes(r[0])).map((r) => {
      const m = STEP_META[r[0]] || ['✨', '#7a5cff'];
      return '<li><span class="e em" style="--hue:' + m[1] + '" aria-hidden="true">' + m[0] + '</span><span class="k">' + r[1] + '</span><span class="v' + (r[1] === 'Пожелания' || r[1] === 'Любимые мультики' ? ' clamp' : '') + '">' + esc(r[2]) + '</span>' +
        '<button type="button" class="edit" data-act="edit" data-step="' + r[0] + '" aria-label="Изменить: ' + r[1] + '">Изменить</button></li>';
    }).join('') + '</ul>' +
      '<p class="sum-note">' + cost + 'Готовую книгу пришлём в этот чат 💌</p>';
  }

  /* --- чипы --- */
  function chipItems(kind) {
    if (kind === 'likes') {
      const preset = opts().likes;
      return preset.concat(S.a.likes.filter((x) => !preset.includes(x))).map((x) => ({ id: x, label: x, e: LIKE_EMOJI[x] || '✨' }));
    }
    return opts().traits.map((t) => ({ id: t.id, label: traitLabel(t), e: TRAIT_EMOJI[t.id] || '⭐' }));
  }

  function refreshChips(kind) {
    const box = document.getElementById('chips-' + kind);
    if (!box) return;
    const selected = S.a[kind];
    box.innerHTML = chipItems(kind).map((it) => {
      const on = selected.includes(it.id);
      const dis = !on && selected.length >= 3;
      return '<button type="button" class="chip" data-act="toggle" data-kind="' + kind + '" data-id="' + esc(it.id) + '" aria-pressed="' + on + '"' + (dis ? ' aria-disabled="true"' : '') + '>' +
        (on ? icon('check') : '<span class="e em" aria-hidden="true">' + it.e + '</span>') + esc(it.label) + '</button>';
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
      box.innerHTML = '<div class="notice world-note" role="note"><span class="em" aria-hidden="true">✏️</span><span>Свой мир можно описать словами на шаге «Что ещё добавить?»</span></div>';
    }
  }

  /* --- фото --- */
  function refreshPhoto() {
    const box = document.getElementById('photo-box');
    if (!box) return;
    const note = '<p class="privacy-note"><span class="em" aria-hidden="true">🔒</span> ' + esc(PHOTO_PROMISE) + '</p>';
    if (!S.photo) {
      box.innerHTML = '<div class="photo-btns"><label class="photo-pick" for="file-cam" tabindex="0"><span class="big em" aria-hidden="true">📸</span>Сфотографировать</label>' +
        '<label class="photo-pick alt" for="file" tabindex="0"><span class="big em" aria-hidden="true">🖼️</span>Выбрать из галереи</label></div>' +
        '<input type="file" class="vh" id="file-cam" accept="image/*" capture="user"><input type="file" class="vh" id="file" accept="image/*">' + note;
    } else {
      box.innerHTML = '<div class="photo-prev"><img src="' + S.photoUrl + '" alt="Выбранное фото"><div class="t">Фото добавлено 👍</div><button type="button" class="btn ghost small" data-act="photo-remove">Убрать</button></div>' +
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
    setHeader('bg_color');
    const id = S.steps[S.idx];
    const st = STEP[id];
    const total = S.steps.length;
    const meta = STEP_META[id] || ['✨', '#7a5cff'];
    normalize();
    const segs = S.steps.map((_, i) => '<i class="' + (i < S.idx ? 'on' : (i === S.idx ? 'now' : '')) + '"></i>').join('');
    app.innerHTML = '<section class="screen wizard" data-step="' + id + '">' +
      '<header class="topbar"><button type="button" class="back" data-act="back">' + icon('back') + 'Назад</button>' +
      '<span class="step-count">Шаг ' + (S.idx + 1) + ' из ' + total + '</span></header>' +
      '<div class="seg" role="progressbar" aria-label="Шаг ' + (S.idx + 1) + ' из ' + total + '" aria-valuemin="1" aria-valuemax="' + total + '" aria-valuenow="' + (S.idx + 1) + '">' + segs + '</div>' +
      '<main class="main enter-' + (dir || 'fwd') + '"><div class="sticker em" style="--hue:' + meta[1] + '" aria-hidden="true">' + meta[0] + '</div>' +
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
    btn.innerHTML = st.cta ? esc(st.cta()) : (skip ? 'Пропустить' : 'Дальше') + icon('arrow');
    hideFormError();
  }

  function showFormError(text) {
    const el = document.getElementById('form-error');
    if (el) { el.textContent = text; el.hidden = false; }
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
  const STAGES = [['✍️', 'Пишу книгу'], ['🖌️', 'Рисую обложку'], ['🎨', 'Иллюстрации'], ['📖', 'Собираю книгу']];
  const TIPS = {
    '-1': ['Вы в очереди — скоро начнём 🌟', 'Совсем чуть-чуть, и мы возьмёмся за дело ✨'],
    0: ['Подбираю самые тёплые слова 💛', 'Придумываю, как герой сделает правильный выбор 🧭', 'Выбираю добрый и интересный сюжет 🌙', 'Проверяю, чтобы у книги был светлый конец ✨'],
    1: ['Рисую героя с любовью 🎨', 'Выбираю самые тёплые краски для обложки 🌅'],
    2: ['Раскрашиваю горы и джайлоо 🏔️', 'Дорисовываю улыбку нашему герою 😊', 'Расставляю звёзды по местам ⭐', 'Добавляю в картинки уютные детали 🏕️'],
    3: ['Складываю страницы в красивую книгу 📖', 'Почти готово — проверяю каждую страницу 🔍'],
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
    setHeader('bg_color');
    const eta = S.cfg.mock ? 'В тестовом режиме это быстрее минуты.' : 'Обычно 5–15 минут. Можно закрыть приложение — PDF придёт в чат 💌';
    const rows = rowHtml('cover', 'Обложка') + Array.from({ length: pagesCount() }, (_, i) => rowHtml('p' + (i + 1), 'Страница ' + (i + 1))).join('');
    app.innerHTML = '<section class="screen wait">' +
      '<div class="scene">' + bookScene() + '</div>' +
      '<h1>Пишем вашу книгу ✍️</h1><p class="tip" id="tip" aria-live="polite">' + TIPS[0][0] + '</p>' +
      '<div class="bar" role="progressbar" aria-label="Готовность книги" aria-valuemin="0" aria-valuemax="100" aria-valuenow="2"><i></i></div>' +
      '<ol class="stages">' + STAGES.map((s, i) => '<li data-stage="' + i + '"><span class="dot">' + icon('check') + '</span><span class="em" aria-hidden="true">' + s[0] + '</span><span class="lbl">' + s[1] + '</span></li>').join('') + '</ol>' +
      '<p class="stay">' + eta + '</p>' +
      '<div id="conn"></div><h2 class="sub">Страницы появляются по мере готовности 👇</h2><ul class="preview">' + rows + '</ul></section>';
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
    setHeader('bg_color');
    const detail = o.error_detail ? '<details><summary>Подробности для администратора</summary><pre>' + esc(o.error_detail) + '</pre></details>' : '';
    stateScreen('😔', 'Ой, книга не получилась', o.error || 'Что-то пошло не так. Попробуйте ещё раз через несколько минут.',
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
    if (o.delivered === true) return '<p class="status" id="status">' + icon('check') + 'PDF уже в вашем чате 💌</p>';
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
    return '<section class="print" id="print-offer"><div class="print-head"><span class="big em" aria-hidden="true">🎁</span><h2>' + esc(p.title || 'Хотите заказать печатную версию?') + '</h2></div>' +
      '<ul class="print-rows"><li><b>' + esc(p.pdf_price || S.cfg.price_text) + '</b> — PDF</li>' +
      '<li><b>' + esc(p.print_price) + '</b> — мягкая фотокнига 21×21 см</li></ul>' +
      (p.whatsapp_url ? '<button type="button" class="btn" data-act="print-order">' + icon('send') + 'Заказать в WhatsApp</button>' : '') + '</section>';
  }

  function feedbackHtml() {
    const f = S.fb;
    if (f.sent) return '<section class="feedback" id="feedback"><p class="thanks"><span class="big em" aria-hidden="true">💛</span>Спасибо! Ваш отзыв помогает книгам становиться лучше.</p></section>';
    const price = esc(S.cfg.price_text);
    return '<section class="feedback" id="feedback"><h2>Как вам книга? 💬</h2>' +
      '<div class="rate" role="radiogroup" aria-label="Оценка">' +
      '<button type="button" class="opt" role="radio" aria-checked="' + (f.rating === 'up') + '" data-act="fb-rate" data-v="up"><span class="big em" aria-hidden="true">😍</span><b>Понравилась</b></button>' +
      '<button type="button" class="opt" role="radio" aria-checked="' + (f.rating === 'down') + '" data-act="fb-rate" data-v="down"><span class="big em" aria-hidden="true">😕</span><b>Не понравилась</b></button></div>' +
      '<label class="field"><span class="lbl" id="l-fb">Комментарий (необязательно)</span><textarea class="textarea" id="fb-comment" maxlength="1000" rows="3" aria-labelledby="l-fb" placeholder="Что понравилось или что можно улучшить?">' + esc(f.comment) + '</textarea></label>' +
      '<p class="buy" id="l-buy">Купили бы такую книгу за ' + price + '? 🛒</p>' +
      '<div class="buy-row" role="radiogroup" aria-labelledby="l-buy">' + [['yes', 'Да'], ['maybe', 'Возможно'], ['no', 'Нет']].map((x) =>
        '<button type="button" class="chip" role="radio" aria-checked="' + (f.would_pay === x[0]) + '" data-act="fb-buy" data-v="' + x[0] + '">' + x[1] + '</button>').join('') + '</div>' +
      '<p class="form-error" id="fb-error" role="alert" hidden></p>' +
      '<button type="button" class="btn" data-act="fb-send" id="fb-send"' + ((f.rating || f.would_pay) ? '' : ' disabled') + '>Отправить отзыв</button></section>';
  }

  function confetti() {
    if (reduceMotion) return;
    const box = $('.confetti');
    if (!box) return;
    const colors = ['#ffc24d', '#ff7b6b', '#6b4cff', '#36d6a8', '#ff9ccf', '#3fa9f5'];
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
    setHeader('bg_color');
    haptic.ok();
    const count = 2 + o.pages.length + 1;
    app.innerHTML = '<section class="screen result"><div class="confetti" aria-hidden="true"></div>' +
      '<header class="r-head"><h1>Ура! Книга готова 🎉</h1><p class="bt">' + esc(o.book.title) + '</p>' + deliveryHtml(o) + '</header>' +
      '<div class="pager-wrap"><div class="pager-nav"><button type="button" class="pn" data-act="pager-prev" aria-label="Предыдущая страница">' + icon('back') + '</button>' +
      '<span class="count" id="pager-count" aria-live="polite">1 / ' + count + '</span>' +
      '<button type="button" class="pn" data-act="pager-next" aria-label="Следующая страница">' + icon('next') + '</button></div>' +
      '<div class="pager" id="pager" tabindex="0" role="region" aria-roledescription="карусель" aria-label="Страницы книги">' + slidesHtml(o) + '</div>' +
      '<p class="pager-cap">В PDF страница идёт разворотом: картинка на оба листа, текст на ней.</p></div>' +
      printHtml() + feedbackHtml() +
      '<button type="button" class="btn secondary again" data-act="again">🎁 Сделать ещё одну, для брата или сестры</button>' +
      '<footer class="footer"><button type="button" class="btn gold" data-act="download">' + icon('download') + 'Скачать PDF</button></footer></section>';
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
      err.textContent = e.message; err.hidden = false;
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
    setHeader('bg_color');
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
      ? '<div class="pay-state" role="status"><span class="em big" aria-hidden="true">⏳</span><div><b>Чек получен — проверяем оплату</b><span>Обычно это занимает несколько минут. Как только мы подтвердим, книга начнёт создаваться, а в чат придёт сообщение. Приложение можно закрыть 💌</span></div></div>'
      : '';
    app.innerHTML = '<section class="screen pay">' +
      '<header class="pay-head"><span class="em big" aria-hidden="true">🪙</span><h1>Оплата книги</h1>' +
      '<p>Книга для ' + esc(pay.child) + ' — <b>' + esc(pay.price_text) + '</b></p></header>' +
      '<div class="pay-body">' + note + state + (sent ? '' : qr) +
      (sent ? '' : '<p class="amount">К оплате: <b>' + esc(pay.price_text) + '</b></p>') +
      (sent || !pay.qr_url ? '' : '<button type="button" class="btn secondary small qr-save" data-act="qr-save">' + icon('download') + 'Сохранить QR в телефон</button>') +
      (sent ? '' : '<ol class="pay-steps"><li><span class="n">1</span><span>' + esc(pay.instructions) + '</span></li>' +
        '<li><span class="n">2</span><span>Переведите точную сумму и сделайте скриншот или фото чека.</span></li>' +
        '<li><span class="n">3</span><span>Нажмите «Отправить чек» внизу. Мы проверим оплату и сразу начнём писать книгу ✨</span></li></ol>') +
      '</div>' +
      '<footer class="footer"><p class="form-error" id="pay-error" role="alert" hidden></p>' +
      '<input type="file" class="vh" id="receipt-file" accept="image/*">' +
      (pay.qr_url ? '<label class="btn" id="receipt-btn" for="receipt-file" tabindex="0">' + icon('clip') + (sent ? 'Отправить другой чек' : 'Отправить чек') + '</label>' : '') +
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
    if (el) { el.textContent = text; el.hidden = false; }
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
    setHeader('bg_color');
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
    app.innerHTML = '<section class="screen admin"><header class="a-head"><h1>' + icon('gear') + 'Админка</h1>' +
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
      '<span>Книга для ' + esc(p.child) + '</span><span class="ago">Чек ' + esc(ago(p.receipt_at)) + '</span></div>' +
      '<div class="ract"><button type="button" class="btn small" data-act="approve" data-id="' + esc(p.id) + '">' + icon('check') + 'Подтвердить</button>' +
      '<button type="button" class="btn small secondary" data-act="reject-open" data-id="' + esc(p.id) + '">Отклонить</button></div>' +
      '<div class="reject" hidden><div class="chips">' + ['Сумма не совпадает', 'Платёж не найден', 'Чек не читается'].map((r) =>
        '<button type="button" class="chip" data-act="reject-reason" data-text="' + esc(r) + '">' + esc(r) + '</button>').join('') + '</div>' +
      '<input class="input" type="text" maxlength="200" placeholder="Причина (покупатель её увидит)" aria-label="Причина отказа">' +
      '<button type="button" class="btn small danger" data-act="reject" data-id="' + esc(p.id) + '">Отправить отказ</button></div></article>').join('');
    const empty = '<div class="a-empty"><span class="em big" aria-hidden="true">🌿</span><p>Новых чеков нет. Как только покупатель отправит чек, он появится здесь и придёт вам в чат.</p></div>';
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
      ? '<div class="link-card" role="status"><b>Ссылка создана ✨</b><p class="url" id="inv-url">' + esc(iv.fresh.url) + '</p>' +
        '<div class="btnrow"><button type="button" class="btn small" data-act="inv-copy">Скопировать</button>' +
        '<button type="button" class="btn small secondary" data-act="inv-share">Отправить</button></div></div>' : '';
    let rows;
    if (iv.list === null) rows = '<p class="a-hint">Загружаю список…</p>';
    else if (!iv.list.length) rows = '<p class="a-hint">' + (iv.listError ? esc(iv.listError) : 'Ссылок пока нет. Создайте первую выше.') + '</p>';
    else rows = '<ul class="mini invites">' + iv.list.map((inv) => {
      const used = inv.used_by !== null && inv.used_by !== undefined;
      return '<li' + (used ? ' class="used"' : '') + '><div><b>' + esc(inv.note || 'без заметки') + '</b><span>' + esc(inviteMeta(inv)) + '</span></div>' +
        (used ? '' : '<div class="btnrow">' +
          (inv.url ? '<button type="button" class="btn small secondary" data-act="inv-copy" data-url="' + esc(inv.url) + '">' + icon('clip') + 'Скопировать</button>' : '') +
          '<button type="button" class="btn small secondary" data-act="inv-revoke" data-token="' + esc(inv.token) + '">Отозвать</button></div>') + '</li>';
    }).join('') + '</ul>';
    return '<div class="set">' +
      '<div class="switch-row stepper-row"><div class="t"><b id="l-credits">Сколько книг даёт ссылка</b></div>' +
      '<div class="stepper" role="group" aria-labelledby="l-credits">' +
      '<button type="button" class="pn" data-act="inv-minus" aria-label="Меньше"' + (iv.credits <= 1 ? ' disabled' : '') + '>' + icon('minus') + '</button>' +
      '<output class="val" id="inv-credits" aria-live="polite">' + iv.credits + '</output>' +
      '<button type="button" class="pn" data-act="inv-plus" aria-label="Больше"' + (iv.credits >= 5 ? ' disabled' : '') + '>' + icon('plus') + '</button></div></div>' +
      '<label class="field"><span class="lbl" id="l-inv-note">Заметка (видите только вы)</span><input class="input" id="inv-note" type="text" maxlength="80" autocomplete="off" aria-labelledby="l-inv-note" placeholder="Для кого, например: Айгуль, Instagram" value="' + esc(iv.note) + '"></label>' +
      '<p class="form-error" id="inv-error" role="alert"' + (iv.error ? '' : ' hidden') + '>' + esc(iv.error) + '</p>' +
      '<button type="button" class="btn" data-act="inv-create" id="inv-create">Создать ссылку</button></div>' +
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
      if (err) { err.textContent = e.message; err.hidden = false; }
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
    showAdminToast(ok ? 'Ссылка скопирована ✓' : 'Не получилось скопировать. Ссылка: ' + url);
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
      '<div class="switch-row"><div class="t"><b id="sw-closed">🔒 Закрытый бот</b><p>Книги создают только по личным ссылкам из вкладки «Ссылки». Вам доступ открыт всегда.</p></div>' +
      '<button type="button" class="switch" role="switch" aria-labelledby="sw-closed" aria-checked="' + closedOn(st) + '" data-act="closed-switch"></button></div>' +
      '<div class="switch-row"><div class="t"><b id="sw-pay">💳 Приём оплаты по QR</b><p>' + (st.has_qr ? 'Когда включено, книга создаётся только после вашего подтверждения.' : 'Сначала загрузите QR-код ниже.') + '</p></div>' +
      '<button type="button" class="switch" role="switch" aria-labelledby="sw-pay" aria-checked="' + !!st.enabled + '" data-act="pay-switch"' + (st.has_qr ? '' : ' disabled') + '></button></div>' +
      '<h2 class="a-sub">Ваш QR-код</h2>' + qr +
      '<input type="file" class="vh" id="qr-file" accept="image/*">' +
      '<label class="btn secondary small" id="qr-btn" for="qr-file" tabindex="0">' + icon('upload') + (st.has_qr ? 'Заменить QR-код' : 'Загрузить QR-код') + '</label>' +
      '<label class="field"><span class="lbl">Цена (показывается покупателю)</span><input class="input" id="set-price" type="text" maxlength="40" value="' + esc(st.price_text) + '" placeholder="499 сом"></label>' +
      '<label class="field"><span class="lbl">Цена печатной книги</span><input class="input" id="set-print" type="text" maxlength="40" value="' + esc(st.print_price || '') + '" placeholder="1 290 сом"></label>' +
      '<label class="field"><span class="lbl">Номер WhatsApp</span><input class="input" id="set-wa" type="tel" inputmode="numeric" maxlength="20" value="' + esc(st.whatsapp || '') + '" placeholder="996555123456" aria-describedby="h-wa"><span class="help" id="h-wa">Номер с кодом страны, например 996555123456. На него придут заказы печатной версии; пустое поле скрывает предложение печати.</span></label>' +
      '<label class="field"><span class="lbl">Подсказка для покупателя</span><textarea class="textarea" id="set-text" maxlength="400" rows="4" placeholder="' + esc(st.default_instructions) + '">' + esc(st.instructions) + '</textarea></label>' +
      '<p class="form-error" id="set-error" role="alert" hidden></p><p class="saved" id="set-saved" role="status" hidden>Сохранено ✓</p>' +
      '<button type="button" class="btn" data-act="settings-save">Сохранить настройки</button></div>';
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
      err.textContent = e.message; err.hidden = false; haptic.bad();
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
