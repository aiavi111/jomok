/* Персональная сказка — Mini App. Одна страница, без сборки. */
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
  const LIKE_EMOJI = { 'Лошади': '🐴', 'Животные': '🐾', 'Динозавры': '🦖', 'Машинки': '🚗', 'Рисование': '🎨', 'Музыка': '🎵', 'Футбол': '⚽', 'Куклы': '🧸', 'Космос': '🚀', 'Конструктор': '🧱', 'Книги': '📚', 'Сладости': '🍬' };
  const TRAIT_EMOJI = { kind: '💛', brave: '🦁', curious: '🔍', funny: '😄', shy: '🌸', stubborn: '💪', caring: '🤗' };
  const STEP_META = {
    name: ['👶', '#7a5cff'], age: ['🎂', '#ff7b6b'], gender: ['🧸', '#3fa9f5'], appearance: ['🎨', '#ff6fb5'],
    likes: ['❤️', '#ff7b6b'], traits: ['🌟', '#ffb020'], place: ['🗺️', '#36d6a8'], value: ['🧭', '#7a5cff'],
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
      place: null, place_custom: '', value: null, islamic: false, headscarf: false, language: null,
      dedication: '', photo_consent: false,
    }, keep || {});
  }

  const S = {
    cfg: null, screen: 'boot', steps: [], idx: 0, returnToSummary: false, header: null,
    a: freshAnswers(), photo: null, photoUrl: null,
    orderId: null, order: null, pollId: 0, pollFails: 0, stage: 0, tipTimer: null, tipIndex: 0,
    fb: { rating: null, would_pay: null, comment: '', sent: false },
  };

  const opts = () => S.cfg.options;
  const traitLabel = (t) => (S.a.gender === 'girl' ? t.girl : t.boy);
  const placeLabel = () => {
    if (S.a.place === 'custom') return S.a.place_custom.trim();
    const p = opts().places.find((x) => x.id === S.a.place);
    return p ? p.label : '';
  };

  function leaveScreen() {
    clearInterval(S.tipTimer);
    S.tipTimer = null;
    clearTimeout(S.autoTimer);
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
      'Эта страница работает внутри Telegram. Найдите нашего бота и нажмите кнопку «Создать сказку» — там всё и случится ✨', [],
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

  /* ===================================================================== приветствие */
  const EXAMPLE = [
    { img: '/static/img/ex-cover.jpg', alt: 'Обложка: мальчик в синей жилетке с карандашом на джайлоо', cover: true, title: 'Айдар и Золотой Конь', sub: 'Сказка для Айдара' },
    { img: '/static/img/ex-p1.jpg', alt: 'Мальчик читает книгу у юрты', text: 'Шестилетний Айдар жил в уютной юрте на красивом зелёном джайлоо. Больше всего на свете мальчик любил рисовать весёлые картинки и любоваться быстрыми лошадьми.' },
    { img: '/static/img/ex-p3.jpg', alt: 'Мальчик и сурок на горной тропинке', text: 'Около горной тропинки Айдар встретил пушистого сурка. Зверёк сидел на камне и горько плакал, потому что потерял свой любимый круглый камушек.' },
    { img: '/static/img/ex-p4.jpg', alt: 'Мальчик на бревенчатом мостике над ручьём', text: 'Путь лежал через узкий мостик над весёлым журчащим ручьём. Айдар смело зашагал вперёд, рассматривая цветы и бабочек вокруг.' },
  ];

  function showWelcome() {
    leaveScreen();
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
    const priceLine = c.free_in_test
      ? 'Книга стоит <b>' + esc(c.price_text) + '</b>. Сейчас тест — <b>бесплатно</b> 🎉 Осталось ' + left + ' из ' + c.limits.books_per_day + ' на сегодня.'
      : 'Цена книги — <b>' + esc(c.price_text) + '</b> 💛';
    const rail = EXAMPLE.map((x) => x.cover
      ? '<article class="ex cover-ex"><img src="' + x.img + '" alt="' + esc(x.alt) + '" width="232" height="232" loading="lazy"><p>' + esc(x.title) + '<small>' + esc(x.sub) + '</small></p></article>'
      : '<article class="ex"><img src="' + x.img + '" alt="' + esc(x.alt) + '" width="232" height="232" loading="lazy"><p>' + esc(x.text) + '</p></article>').join('');
    const perk = (e, hue, b, d) => '<li><span class="e em" style="--hue:' + hue + '" aria-hidden="true">' + e + '</span><div><b>' + b + '</b><span class="d">' + d + '</span></div></li>';

    app.innerHTML = '<section class="screen welcome">' +
      '<header class="hero"><div class="hero-art">' + heroScene() + '</div>' +
      '<div class="hero-text"><div class="pills">' + pills.join('') + '</div>' +
      '<h1>Сказка, где главный герой — ваш малыш ✨</h1>' +
      '<p class="lead">Придумаем историю с добрым смыслом, нарисуем иллюстрации и пришлём красивую PDF-книгу прямо в Telegram.</p></div></header>' +
      '<div class="sheet">' +
      '<section class="block"><h2>Вот так выглядит книга 📖</h2><div class="rail" tabindex="0" aria-label="Страницы примера">' + rail + '</div>' +
      '<p class="cap">Пример: сказка для Айдара, шесть лет. Такую же вы получите для своего малыша.</p></section>' +
      '<section class="block"><h2>Чем она особенная 💫</h2><ul class="perks">' +
      perk('👶', '#7a5cff', 'Герой — ваш малыш', 'Имя, характер и увлечения вплетены в сюжет, а на картинках — похожая внешность') +
      perk('💛', '#ffb020', 'Добрый смысл без нравоучений', 'Герой сам делает выбор — и ребёнок понимает, что такое доброта, честность и смелость') +
      perk('🏔️', '#36d6a8', 'С любовью к Кыргызстану', 'Горы, джайлоо, юрта и Иссык-Куль. На русском или кыргызском') +
      perk('🌙', '#5b8def', 'Исламский режим — по желанию', 'Скромная одежда героев, светлые традиции и никакой магии') +
      '</ul></section>' +
      '<section class="block"><h2>Как это работает 🧭</h2><ol class="timeline">' +
      '<li><span class="n">1</span><div><b>Отвечаете на вопросы</b><span class="d">Всего 1–2 минуты: имя, возраст, любимое и характер</span></div></li>' +
      '<li><span class="n">2</span><div><b>Мы пишем и рисуем</b><span class="d">' + second + '</span></div></li>' +
      '<li><span class="n">3</span><div><b>Получаете книгу в чат 💌</b><span class="d">Обложка, посвящение, 8 страниц с иллюстрациями и тёплое пожелание</span></div></li>' +
      '</ol></section>' + (notice ? '<div class="block">' + notice + '</div>' : '') +
      '<p class="price">' + priceLine + '</p></div>' +
      '<footer class="footer">' +
      (left < 1 ? '<p class="form-error" role="alert">Лимит на сегодня исчерпан. Приходите завтра — малыша ждёт новая сказка 🌙</p>' : '') +
      '<button type="button" class="btn" data-act="start"' + (left < 1 ? ' disabled' : '') + '>✨ Создать сказку</button></footer>' +
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
      hint: () => 'Подберём длину и сложность сказки — чтобы было в самый раз.',
      auto: true,
      body: () => '<div class="age-grid" role="radiogroup" aria-label="Возраст">' +
        choiceButtons('age', [3, 4, 5, 6, 7, 8, 9].map((n) => ({ id: n, html: n })), 'age') + '</div>' +
        '<p class="age-note">Сказки подходят детям от 3 до 9 лет 🌈</p>',
      valid: () => S.a.age != null,
    },
    gender: {
      title: () => 'Кто у нас главный герой?',
      hint: () => 'Чтобы в сказке всё звучало правильно: «он пошёл» или «она пошла».',
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
      hint: () => 'Необязательно, но тогда герой на картинках будет очень похож на малыша.',
      body: () => [
        ['hair', 'Волосы', 'Например: тёмные кудряшки'],
        ['eyes', 'Глаза', 'Например: зелёные'],
        ['clothes', 'Одежда', 'Например: красная куртка и синие джинсы'],
      ].map((f) => '<label class="field"><span class="lbl">' + f[1] + '</span><input class="input" data-field="' + f[0] + '" maxlength="120" autocomplete="off" enterkeyhint="next" placeholder="' + f[2] + '" value="' + esc(S.a[f[0]]) + '"></label>').join(''),
      isEmpty: () => !S.a.hair.trim() && !S.a.eyes.trim() && !S.a.clothes.trim(),
      valid: () => true,
      mount() { focusField(null, 'input'); },
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
      mount() { refreshCustomPlace(false); },
    },
    value: {
      title: () => 'О чём будет сказка?',
      hint: () => 'Герой не станет читать нотации — он покажет это своим поступком.',
      auto: true,
      body: () => '<div class="opts" role="radiogroup" aria-label="Ценность">' +
        choiceButtons('value', opts().values.map((v) => {
          const m = VALUE_META[v.id] || VALUE_META.kindness;
          return { id: v.id, html: '<span class="e em" style="--hue:' + m.hue + '" aria-hidden="true">' + m.e + '</span><span class="t"><b>' + esc(v.label) + '</b><small>' + m.sub + '</small></span>' + icon('check', 'tick') };
        }), 'opt') + '</div>',
      valid: () => !!S.a.value,
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
          { id: 'ru', html: '<span class="big em" aria-hidden="true">📗</span><b>Русский</b><small>Сказка на русском</small>' },
          { id: 'ky', html: '<span class="big em" aria-hidden="true">📘</span><b>Кыргызча</b><small>Жомок кыргызча</small>' },
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
    photo: {
      optional: true,
      title: () => 'Добавим фото малыша?',
      hint: () => 'Необязательно. Художник нарисует героя похожим на ребёнка 📸',
      body: () => '<div class="photo-box" id="photo-box"></div>',
      isEmpty: () => !S.photo,
      valid: () => !S.photo || S.a.photo_consent,
      mount() { refreshPhoto(); },
    },
    summary: {
      title: () => 'Всё готово к созданию! 🎉',
      hint: () => 'Проверьте ответы — любой можно поправить.',
      cta: () => '✨ Создать сказку',
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

  function summaryHtml() {
    const a = S.a;
    const traits = opts().traits.filter((t) => a.traits.includes(t.id)).map(traitLabel).join(', ');
    const value = (opts().values.find((v) => v.id === a.value) || {}).label || '';
    const lang = (opts().languages.find((l) => l.id === a.language) || {}).label || '';
    const look = [a.hair, a.eyes, a.clothes].map((x) => x.trim()).filter(Boolean).join('; ');
    const rows = [
      ['name', 'Имя', nameClean()],
      ['age', 'Возраст', a.age + ' ' + plural(a.age, ['год', 'года', 'лет'])],
      ['gender', 'Герой', a.gender === 'girl' ? 'Девочка' : 'Мальчик'],
      ['appearance', 'Внешность', look || 'не указана'],
      ['likes', 'Любит', a.likes.join(', ')],
      ['traits', 'Характер', traits],
      ['place', 'Место', placeLabel()],
      ['value', 'О чём сказка', value],
      ['islamic', 'Исламский режим', a.islamic ? (a.gender === 'girl' && a.headscarf ? 'Да, героиня в платке' : 'Да') : 'Нет'],
      ['language', 'Язык', lang],
      ['dedication', 'Посвящение', a.dedication.trim() || 'нет'],
    ];
    if (S.steps.includes('photo')) rows.push(['photo', 'Фото', S.photo ? 'Добавлено' : 'Без фото']);
    const left = S.cfg.limits.remaining_today;
    const warn = S.cfg.privacy_warning ? '<div class="notice warn" role="note">' + icon('warn') + '<span>' + esc(S.cfg.privacy_warning) + '</span></div>' : '';
    return warn + '<ul class="summary">' + rows.map((r) => {
      const m = STEP_META[r[0]] || ['✨', '#7a5cff'];
      return '<li><span class="e em" style="--hue:' + m[1] + '" aria-hidden="true">' + m[0] + '</span><span class="k">' + r[1] + '</span><span class="v">' + esc(r[2]) + '</span>' +
        '<button type="button" class="edit" data-act="edit" data-step="' + r[0] + '" aria-label="Изменить: ' + r[1] + '">Изменить</button></li>';
    }).join('') + '</ul>' +
      '<p class="sum-note">' + (S.cfg.free_in_test ? 'Сейчас тест: книга бесплатна (осталось ' + left + ' из ' + S.cfg.limits.books_per_day + ' на сегодня). ' : 'Цена: ' + esc(S.cfg.price_text) + '. ') +
      'Готовую книгу пришлём в этот чат 💌</p>';
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

  /* --- место: свой вариант --- */
  function refreshCustomPlace(focus) {
    const box = document.getElementById('custom-place');
    if (!box) return;
    if (S.a.place !== 'custom') { box.innerHTML = ''; return; }
    if (!box.firstChild) {
      box.innerHTML = '<label class="field custom-place"><span class="lbl" id="l-cp">Опишите место</span><input class="input" id="in-cp" data-field="place_custom" maxlength="120" autocomplete="off" enterkeyhint="next" aria-labelledby="l-cp" placeholder="Например: сад у бабушки в деревне" value="' + esc(S.a.place_custom) + '"></label>';
    }
    if (focus) focusField('in-cp');
  }

  /* --- фото --- */
  function refreshPhoto() {
    const box = document.getElementById('photo-box');
    if (!box) return;
    const note = '<p class="privacy-note">Фото используется только для этой книги: его получает сервис, который рисует иллюстрации. Мы удаляем фото сразу после создания книги 🔒</p>';
    if (!S.photo) {
      box.innerHTML = '<button type="button" class="photo-pick" data-act="photo-pick"><span class="big em" aria-hidden="true">📸</span>Выбрать фото</button>' +
        '<input type="file" id="file" accept="image/*" hidden>' + note;
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

  async function onPhotoChosen(file) {
    if (!file) return;
    try {
      const blob = await downscale(file, 1024);
      if (S.photoUrl) URL.revokeObjectURL(S.photoUrl);
      S.photo = blob; S.photoUrl = URL.createObjectURL(blob); S.a.photo_consent = false;
      haptic.select();
      refreshPhoto();
    } catch (e) {
      showFormError('Не получилось открыть это фото. Выберите снимок в формате JPEG или PNG.');
    }
  }

  /* --- навигация по шагам --- */
  function buildSteps() {
    const list = ['name', 'age', 'gender', 'appearance', 'likes', 'traits', 'place', 'value', 'islamic', 'language', 'dedication'];
    if (S.cfg.photo_supported) list.push('photo');
    list.push('summary');
    return list;
  }

  function startWizard(keep) {
    S.a = freshAnswers(keep);
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
  }

  function pick(el) {
    const field = el.dataset.field;
    let value = el.dataset.value;
    if (field === 'age') value = Number(value);
    S.a[field] = value;
    haptic.select();
    $$('[data-field="' + field + '"]').forEach((b) => b.setAttribute('aria-checked', String(String(b.dataset.value) === String(value))));
    if (field === 'place') refreshCustomPlace(value === 'custom');
    updateFooter();
    const st = STEP[S.steps[S.idx]];
    if (st.auto && !(field === 'place' && value === 'custom')) {
      const stepId = S.steps[S.idx];
      clearTimeout(S.autoTimer);
      S.autoTimer = setTimeout(() => { if (S.screen === 'wizard' && S.steps[S.idx] === stepId && S.a[field] === value) next(); }, 260);
    }
  }

  /* --- отправка анкеты --- */
  function payload() {
    const a = S.a;
    return {
      name: nameClean(), age: a.age, gender: a.gender,
      appearance: { hair: a.hair.trim(), eyes: a.eyes.trim(), clothes: a.clothes.trim() },
      likes: a.likes, traits: a.traits, place: a.place, place_custom: a.place === 'custom' ? a.place_custom.trim() : '',
      value: a.value, islamic: a.islamic, headscarf: a.headscarf, language: a.language,
      dedication: a.dedication.trim(), photo_consent: !!(S.photo && a.photo_consent),
    };
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
      showWait(res.order_id);
    } catch (e) {
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
  const STEP_BY_FIELD = { name: 'name', age: 'age', gender: 'gender', likes: 'likes', traits: 'traits', place: 'place', place_custom: 'place', value: 'value', language: 'language', dedication: 'dedication', photo: 'photo', photo_consent: 'photo' };

  /* ===================================================================== ожидание */
  const STAGES = [['✍️', 'Пишу сказку'], ['🖌️', 'Рисую обложку'], ['🎨', 'Иллюстрации'], ['📖', 'Собираю книгу']];
  const TIPS = {
    '-1': ['Вы в очереди — скоро начнём 🌟', 'Совсем чуть-чуть, и сказочник за дело ✨'],
    0: ['Подбираю самые тёплые слова 💛', 'Придумываю, как герой сделает правильный выбор 🧭', 'Выбираю добрый и интересный сюжет 🌙', 'Проверяю, чтобы у сказки был светлый конец ✨'],
    1: ['Рисую героя с любовью 🎨', 'Выбираю самые тёплые краски для обложки 🌅'],
    2: ['Раскрашиваю горы и джайлоо 🏔️', 'Дорисовываю улыбку нашему герою 😊', 'Расставляю звёзды по местам ⭐', 'Добавляю в картинки уютные детали 🏕️'],
    3: ['Складываю страницы в красивую книгу 📖', 'Почти готово — проверяю каждую страницу 🔍'],
  };

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
    const rows = ['Обложка'].concat([1, 2, 3, 4, 5, 6, 7, 8].map((n) => 'Страница ' + n)).map((label, i) =>
      '<li class="prow" data-k="' + (i === 0 ? 'cover' : 'p' + i) + '"><div class="thumb shimmer"></div><div class="pt"><b>' + label + '</b><div class="skels"><span class="skel"></span><span class="skel s"></span></div></div></li>').join('');
    app.innerHTML = '<section class="screen wait">' +
      '<div class="scene">' + bookScene() + '</div>' +
      '<h1>Пишем вашу сказку ✍️</h1><p class="tip" id="tip" aria-live="polite">' + TIPS[0][0] + '</p>' +
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
    stateScreen('😔', 'Ой, сказка не получилась', o.error || 'Что-то пошло не так. Попробуйте ещё раз через несколько минут.',
      [{ act: 'retry-order', label: 'Попробовать ещё раз', icon: 'refresh' }, { act: 'home', label: 'Вернуться в начало', cls: 'ghost' }], detail);
  }

  /* ===================================================================== результат */
  function slidesHtml(o) {
    const b = o.book;
    const mock = o.mock ? '<p class="mock">' + esc(b.mock_note) + '</p>' : '';
    const out = [];
    out.push('<article class="slide cover" aria-label="Обложка"><div class="art"><img src="' + o.cover_url + '" alt="Обложка книги"></div>' +
      '<div class="band" style="background:' + esc(o.cover_color || '#34503f') + '"><h2>' + esc(b.title) + '</h2><p>' + esc(b.caption) + '</p></div></article>');
    out.push('<article class="slide center" aria-label="Посвящение"><h2>' + esc(b.dedication_title) + '</h2>' + ORNAMENT +
      (b.dedication_text ? '<p class="it">' + esc(b.dedication_text) + '</p>' : '') + mock + '</article>');
    o.pages.forEach((p, i) => out.push('<article class="slide page" aria-label="Страница ' + (i + 1) + '"><div class="art"><img src="' + p.image_url + '" alt="Иллюстрация к странице ' + (i + 1) + '"></div>' +
      '<div class="txt">' + esc(p.text) + '</div><div class="num">— ' + (i + 1) + ' —</div></article>'));
    out.push('<article class="slide center" aria-label="Конец"><h2>' + esc(b.the_end) + '</h2>' + ORNAMENT + '<div class="frame">' + esc(b.moral) + '</div>' +
      '<p class="wish">' + esc(b.wish) + '</p><p class="sig">' + esc(b.signature) + '</p>' + mock + '</article>');
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

  function feedbackHtml() {
    const f = S.fb;
    if (f.sent) return '<section class="feedback" id="feedback"><p class="thanks"><span class="big em" aria-hidden="true">💛</span>Спасибо! Ваш отзыв помогает сказкам становиться лучше.</p></section>';
    const price = esc(S.cfg.price_text);
    return '<section class="feedback" id="feedback"><h2>Как вам сказка? 💬</h2>' +
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
      '<header class="r-head"><h1>Ура! Сказка готова 🎉</h1><p class="bt">' + esc(o.book.title) + '</p>' + deliveryHtml(o) + '</header>' +
      '<div class="pager-wrap"><div class="pager-nav"><button type="button" class="pn" data-act="pager-prev" aria-label="Предыдущая страница">' + icon('back') + '</button>' +
      '<span class="count" id="pager-count" aria-live="polite">1 / ' + count + '</span>' +
      '<button type="button" class="pn" data-act="pager-next" aria-label="Следующая страница">' + icon('next') + '</button></div>' +
      '<div class="pager" id="pager" tabindex="0" role="region" aria-roledescription="карусель" aria-label="Страницы книги">' + slidesHtml(o) + '</div></div>' +
      feedbackHtml() +
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
        tg.downloadFile({ url, file_name: 'skazka.pdf' });
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
    const keep = { language: S.a.language, islamic: S.a.islamic };
    await refreshConfig();
    if (S.cfg.limits.remaining_today < 1) { showWelcome(); return; }
    startWizard(keep);
  }

  /* ===================================================================== события */
  const ACTIONS = {
    start: () => { haptic.tap(); startWizard(); },
    next, back,
    pick: (el) => pick(el),
    toggle: (el) => toggleChip(el.dataset.kind, el.dataset.id),
    'like-add': addCustomLike,
    edit: (el) => { S.returnToSummary = true; go(S.steps.indexOf(el.dataset.step), 'back'); },
    switch: (el) => {
      const field = el.dataset.field;
      S.a[field] = !S.a[field];
      if (field === 'islamic' && !S.a.islamic) S.a.headscarf = false;
      haptic.select();
      $('.body').innerHTML = STEP.islamic.body();
      const again = $('[data-field="' + field + '"]'); if (again) again.focus({ preventScroll: true });
    },
    'photo-pick': () => { const f = document.getElementById('file'); if (f) f.click(); },
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
    updateFooter();
  });

  document.addEventListener('change', (ev) => {
    if (ev.target.id === 'file') onPhotoChosen(ev.target.files && ev.target.files[0]);
  });

  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' || ev.isComposing) return;
    const el = ev.target;
    if (el.id === 'in-like') { ev.preventDefault(); addCustomLike(); return; }
    if (S.screen === 'wizard' && el.tagName === 'INPUT' && el.type === 'text') {
      ev.preventDefault();
      const btn = document.getElementById('next');
      if (btn && !btn.disabled) next();
    }
  });

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && S.screen === 'wait') { S.pollId += 1; poll(S.pollId); }
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
    if (S.cfg.active_order_id) { showWait(S.cfg.active_order_id); return; }
    showWelcome();
  }

  boot();
})();
