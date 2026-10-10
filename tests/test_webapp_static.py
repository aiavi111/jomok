"""Mini App (webapp/): без браузера проверяем то, что легко сломать правкой: слово «книга», новые поля анкеты,
широкие страницы 2:1 и акценты в тексте. Живую проверку в телефонной ширине делает человек по .impeccable/preview.sh."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEBAPP = Path(__file__).resolve().parent.parent / "webapp"
JS = (WEBAPP / "app.js").read_text(encoding="utf-8")
CSS = (WEBAPP / "style.css").read_text(encoding="utf-8")
HTML = (WEBAPP / "index.html").read_text(encoding="utf-8")


def between(text: str, start: str, end: str) -> str:
    a = text.index(start)
    return text[a:text.index(end, a)]


def test_javascript_has_no_syntax_errors():
    node = shutil.which("node")
    if not node:
        pytest.skip("node не установлен")
    done = subprocess.run([node, "--check", str(WEBAPP / "app.js")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_miniapp_says_book_not_tale():
    # «подсказка» содержит «сказ», поэтому ищем только слово, которое с этого начинается
    tale = re.compile(r"(?<![а-яё])(сказ|жомок)", re.IGNORECASE)
    for name, text in (("app.js", JS), ("style.css", CSS), ("index.html", HTML)):
        found = tale.search(text)
        assert not found, f"в {name} осталось слово «{text[found.start():found.start() + 12]}»"
    for phrase in ("Книга, где главный герой — <em>ваш малыш</em>", "Создать книгу", "Ура! Книга готова", "Пишем вашу книгу",
                   "Ой, книга не получилась", "Книга для "):
        assert phrase in JS, phrase
    assert "Персональная книга" in HTML


def test_questionnaire_has_topic_and_extras_steps_after_value():
    steps = between(JS, "function buildSteps()", "function startWizard")
    order = [steps.index(f"'{name}'") for name in ("value", "topic", "extras", "islamic", "language", "dedication", "summary")]
    assert order == sorted(order)
    assert "'place'" not in steps                                      # место родитель описывает в пожеланиях
    assert "'appearance'" in steps and "'photo'" not in steps          # фото живёт внутри шага «Внешность»
    for name in ("topic", "extras"):
        assert re.search(rf"^    {name}: \{{", JS, re.MULTILINE), f"нет шага {name}"


def test_topic_step_uses_server_topics_with_icons_and_custom_input():
    assert "topicList()" in JS and "options.topics" in JS and "default_topic" in JS
    for topic, icon in (("adventure", "compass"), ("dinosaurs", "dino"), ("space", "rocket"), ("animals", "fox"), ("superheroes", "hero"),
                        ("pirates", "chest"), ("sea", "boat"), ("friends", "friends"), ("kindness", "heart"), ("life_lesson", "tooth"),
                        ("custom", "pencil")):
        assert re.search(rf"{topic}: '{icon}'", between(JS, "const TOPIC_ICON", "\n")), topic
    assert "Какую книгу хотите?" in JS and "field: 'topic_custom'" in JS and "Например: строим снежную крепость" in JS


def test_extras_step_texts_and_limits():
    for text in ("Что обязательно должно быть в книге?", "Что вы хотите увидеть в книге?",
                 "Напишите, что важно: место (например, стадион), одежда (номер 7 на футболке), что делает герой. Всё это попадёт в книгу",
                 "Хочу, чтобы Алихан водил экскаватор и помогал зайчику"):
        assert text in JS, text
    for gone in ("Любимые герои, животные, игрушки", "Названия любимых мультиков", "Любимые мультики", "favorites_max", "cartoons_max"):
        assert gone not in JS, gone
    assert "request_max', 300" in JS
    assert len(re.findall(r"label: '[^']+', text:", between(JS, "function requestExamples()", "function syncExamples"))) == 4


def test_payload_sends_new_fields_in_contract_order():
    body = between(JS, "function payload()", "async function submit")
    positions = [body.index(key) for key in ("topic:", "topic_custom:", "request:")]
    assert positions == sorted(positions)
    assert "a.topic === 'custom' ? a.topic_custom.trim() : ''" in body       # свою тему шлём только при topic = custom
    for field in ("topic: 'topic'", "topic_custom: 'topic'", "request: 'extras'"):
        assert field in JS, field                                              # ошибка сервера возвращает на нужный шаг


def test_story_pages_are_wide_with_text_below_and_no_alternation():
    slide = between(JS, "function storySlide(", "function slidesHtml")
    assert 'class="art wide half"' in slide and "odd" not in slide and "even" not in slide
    assert slide.index('class="art wide half"') < slide.index('class="leaf"')  # картинка всегда первая
    assert re.search(r"\.slide\.page \.art\.wide \{ aspect-ratio: 2 / 1;", CSS)
    assert re.search(r"\.slide\.page \.art\.wide\.sq \{ aspect-ratio: 1 / 1;", CSS)  # старые квадратные страницы не режем
    assert re.search(r"\.slide \.art \{[^}]*aspect-ratio: 1 / 1", CSS)               # обложка осталась квадратом
    assert "naturalWidth / img.naturalHeight < 1.5" in JS
    text_rule = between(CSS, ".slide.page .txt p {", "}")
    assert "line-height: 1.4" in text_rule and "clamp(20px" in text_rule and "22px)" in text_rule
    assert re.search(r"\.acc \{ color: #D4472F; \}", CSS)
    assert "Здесь страницы листаются по одной. В PDF и в печатной книге это широкие развороты" in JS
    # на телефоне страница вертикальная: видна половина картинки с героями (с той стороны, где нет текста), чтобы хотелось листать дальше
    assert "page.text_side === 'left' ? '93%' : '7%'" in JS and 'class="art wide half"' in JS
    assert re.search(r"\.slide\.page \.art\.wide\.half \{ aspect-ratio: 5 / 6;", CSS) and "object-position: var(--hx, 50%) 50%" in CSS


def test_wait_thumbnails_are_wide_pages_and_square_cover():
    assert re.search(r"\.thumb \{[^}]*width: 120px; aspect-ratio: 2 / 1", CSS)
    assert re.search(r'\.prow\[data-k="cover"\] \.thumb \{ aspect-ratio: 1 / 1', CSS)


def test_old_ids_and_actions_still_exist():
    for act in ("start", "next", "back", "pick", "toggle", "edit", "download", "resend", "pager-prev", "pager-next", "fb-send",
                "again", "print-order", "wa-open", "inv-create", "approve", "settings-save", "qr-zoom", "zoom-img"):
        assert re.search(rf"(?:^|\s)'?{re.escape(act)}'?\s*[:,]", between(JS, "const ACTIONS = {", "function syncFeedback")), act
    assert "__V__" in HTML and "query.get('admin') === '1'" in JS


def test_style_step_sits_between_world_and_extras_and_is_optional_for_old_server():
    steps = between(JS, "function buildSteps()", "function startWizard")
    order = [steps.index(f"'{name}'") for name in ("topic", "world", "style", "extras", "summary")]
    assert order == sorted(order)
    assert "if (styleList().length) list.push('style')" in steps              # старый сервер без стилей: шаг пропускаем
    assert re.search(r"^    style: \{", JS, re.MULTILINE) and "options.styles" in JS
    step = between(JS, "    style: {", "    extras: {")
    assert "optional" not in step and "auto: true" in step                    # шаг обязательный
    assert "valid: () => !!stylePicked()" in step
    for style, icon in (("cartoon3d", "cube"), ("flat2d", "shapes"), ("realistic", "lens")):
        assert f"{style}: '{icon}'" in between(JS, "const STYLE_ICON", "\n"), style
    assert ".opt.style-opt" in CSS                                             # крупные карточки стилей


def test_style_is_preselected_cannot_be_unpicked_and_goes_into_order():
    assert "S.a.style = defaultStyle()" in between(JS, "function startWizard", "function normalize")
    assert "'cartoon3d'" in between(JS, "const defaultStyle", "const stylePicked")
    assert "field === 'style'" not in between(JS, "function pick(", "/* --- отправка анкеты")   # в отличие от мира, повторное нажатие не снимает
    body = between(JS, "function payload()", "async function submit")
    assert "if (styleList().length) body.style" in body                        # поле не шлём, если сервер не прислал стили
    assert "style: 'style'" in between(JS, "const STEP_BY_FIELD", "\n")
    assert "['style', 'Стиль'," in between(JS, "function summaryHtml()", "/* --- чипы --- */")


# ---------------------------------------------------------------- белый стиль, иконки, примеры книги

EMOJI = re.compile("[\u2600-\u27bf\u2b00-\u2bff\U0001F000-\U0001FFFF\u200d\ufe0f]")


def icon_names() -> set[str]:
    block = between(JS, "  const ICONS = {", "  function icon(")
    return set(re.findall(r"^    (\w+): '", block, re.MULTILINE))


def test_webapp_has_no_emoji_icons():
    for name, text in (("app.js", JS), ("style.css", CSS), ("index.html", HTML)):
        found = EMOJI.search(text)
        assert not found, f"в {name} остался эмодзи {text[found.start():found.start() + 2]!r}: иконки рисуем в ICONS"
    assert "emoji" not in JS.lower()                    # поле emoji с сервера клиент не использует


def test_every_used_icon_is_drawn_and_server_ids_have_icons():
    from app import options

    names = icon_names()
    assert {"back", "next", "arrow", "camera", "image", "trash", "download", "send", "share", "admin", "lock", "clock", "done", "error",
            "warn", "qr", "receipt", "link", "generic"} <= names
    used = set(re.findall(r"(?:icon\(|icon: |perk\(|stateScreen\()'(\w+)'", JS))
    mapped = set()
    for table in ("const TOPIC_ICON", "const WORLD_ICON", "const STYLE_ICON", "const LIKE_ICON", "const TRAIT_ICON"):
        mapped |= set(re.findall(r": '(\w+)'", between(JS, table, "\n")))
    mapped |= set(re.findall(r": '(\w+)'", between(JS, "const STEP_ICON", "};")))
    mapped |= set(re.findall(r"\bi: '(\w+)'", JS))
    assert used and mapped and (used | mapped) - names == set(), f"нет рисунка для: {sorted((used | mapped) - names)}"
    for ids, table in ((options.VALUES, "const VALUE_META"), (options.TOPICS, "const TOPIC_ICON"),
                       (options.WORLDS, "const WORLD_ICON"), (options.TRAITS, "const TRAIT_ICON")):
        block = between(JS, table, "\n  };") if table.endswith("META") else between(JS, table, "\n")
        for key in ids:
            assert re.search(rf"\b{key}: ", block), f"{table}: нет {key}"
    assert all(f"'{like}':" in between(JS, "const LIKE_ICON", "\n") for like in options.LIKES)
    assert all(f"{item['id']}: " in between(JS, "const STYLE_ICON", "\n") for item in options.STYLES)
    assert "ICONS.generic" in between(JS, "  function icon(", "\n  }")  # неизвестный id: нейтральная иконка, не эмодзи


def test_app_is_always_white_whatever_telegram_theme():
    assert "const WHITE = '#ffffff'" in JS and "tg.setBackgroundColor(WHITE)" in JS and "setHeader(WHITE)" in JS
    assert "bg_color" not in JS and "DEBUG_THEMES" not in JS and "NIGHT" not in JS
    assert 'name="color-scheme" content="light"' in HTML
    assert "prefers-color-scheme: dark" not in CSS and "--tg-theme" not in CSS
    assert re.search(r"--bg: #ffffff;", CSS) and "color-scheme: light;" in CSS
    for gone in ("heroScene", "bookScene", "starfield", "sparkle"):    # ночной hero с луной и юртой убран
        assert gone not in JS, gone


def test_welcome_example_images_are_the_photos_of_the_real_book():
    from PIL import Image

    img_dir = WEBAPP / "img"
    for name in ("shot-cover.jpg", "shot-p2.jpg", "shot-p3.jpg", "shot-p4.jpg", "shot-p6.jpg", "shot-p7.jpg"):
        with Image.open(img_dir / name) as pic:
            assert pic.size == (720, 960), name
        assert (img_dir / name).stat().st_size < 200_000, name          # лёгкие: грузятся в Telegram по мобильной сети
    with Image.open(img_dir / "logo.jpg") as logo:
        assert logo.size[0] == logo.size[1] >= 120
    assert not list(img_dir.glob("ex-*.jpg")) and not list(img_dir.glob("book-*.jpg")), "старые примеры должны быть удалены"
    assert "ex-cover" not in JS and "ex-p" not in JS and "book-cover" not in JS
    examples = between(JS, "const EXAMPLE = [", "\n  ];")
    assert examples.count("img: '/static/img/shot-") == 6
    assert "Примеры книги про Артёма и динозаврика" in JS
    rail = between(JS, "function exampleRail()", "function showWelcome()")
    assert "fetchpriority=\"high\"" in rail and "loading=\"lazy\"" in rail and "width=\"' + x.w + '\" height=\"' + x.h" in rail
    assert re.search(r"\.rail \{[^}]*scroll-snap-type: x mandatory", CSS) and ".pip[aria-current=true]" in CSS
    assert re.search(r"\.ex\.shot img \{ aspect-ratio: 3 / 4;", CSS)
    assert "/static/img/logo.jpg" in JS and ".logo-img" in CSS         # логотип Bala story в шапке вместо иконки


def test_welcome_has_light_hero_with_showcase_and_main_button_before_the_story():
    welcome = between(JS, "function showWelcome()", "function bindWelcome()")
    order = [welcome.index(part) for part in ("<h1>Книга, где главный герой", 'class="lead"', "exampleRail()", 'id="hero-cta"', 'class="sheet"', 'id="dock"')]
    assert order == sorted(order)                                   # заголовок, подзаголовок, витрина, кнопка, потом остальное
    assert ".hero {" in CSS and "night" not in CSS.lower()
    assert "new IntersectionObserver" in JS and "disconnect()" in JS     # нижняя кнопка появляется, когда главная ушла с экрана


def test_touch_targets_and_motion_floor_in_css():
    assert "min-height: 56px" in between(CSS, ".btn {", "}") and "min-height: 44px" in between(CSS, ".back {", "}")
    assert re.search(r"\.pip \{[^}]*width: 44px; height: 44px", CSS) and "inset: -6px -4px" in between(CSS, ".switch::before", "}")
    assert "@media (prefers-reduced-motion: reduce)" in CSS and ":focus-visible { outline: 3px solid var(--brand)" in CSS


def test_copyright_warning_on_world_extras_and_summary_without_duplicates():
    warning = "Нельзя заказывать реальных знаменитостей и героев мультфильмов и кино (их защищают авторские права). Вместо них мы придумаем похожего, но своего героя."
    assert JS.count(warning) == 1                                       # один текст, один источник
    assert "const copyrightNotice" in JS and 'class="notice warn copyright"' in JS and "icon('warn')" in between(JS, "const copyrightNotice", "\n")
    for step in ("world: {", "extras: {"):
        assert "copyrightNotice()" in between(JS, f"    {step}", "      valid: () => true"), step
    assert "a.request.trim() ? copyrightNotice()" in between(JS, "function summaryHtml()", "/* --- чипы")
    assert "чужих мультперсонажей использовать нельзя" not in JS
    assert "Героев известных мультфильмов мы заменяем" not in JS


def test_removed_fields_are_not_in_wizard_or_payload():
    body = between(JS, "function payload()", "async function submit")
    for gone in ("place", "favorites", "cartoons"):
        assert gone not in body, gone
    assert "['place'," not in JS and "'Место'" not in JS
