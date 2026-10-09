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
    for phrase in ("Книга, где главный герой — ваш малыш", "✨ Создать книгу", "Ура! Книга готова", "Пишем вашу книгу",
                   "Ой, книга не получилась", "Книга для "):
        assert phrase in JS, phrase
    assert "Персональная книга" in HTML


def test_questionnaire_has_topic_and_extras_steps_after_value():
    steps = between(JS, "function buildSteps()", "function startWizard")
    order = [steps.index(f"'{name}'") for name in ("place", "value", "topic", "extras", "islamic", "language", "dedication", "summary")]
    assert order == sorted(order)
    assert "'appearance'" in steps and "'photo'" not in steps          # фото живёт внутри шага «Внешность»
    for name in ("topic", "extras"):
        assert re.search(rf"^    {name}: \{{", JS, re.MULTILINE), f"нет шага {name}"


def test_topic_step_uses_server_topics_with_emoji_and_custom_input():
    assert "topicList()" in JS and "options.topics" in JS and "default_topic" in JS
    for topic, emoji in (("adventure", "🧭"), ("dinosaurs", "🦖"), ("space", "🚀"), ("animals", "🐻"), ("superheroes", "🦸"),
                         ("pirates", "🏴‍☠️"), ("sea", "🌊"), ("friends", "🤝"), ("kindness", "💛"), ("life_lesson", "🪥"),
                         ("custom", "✏️")):
        assert re.search(rf"{topic}: \{{ e: '{re.escape(emoji)}'", JS), topic
    assert "Какую книгу хотите?" in JS and "field: 'topic_custom'" in JS and "Например: строим снежную крепость" in JS


def test_extras_step_texts_and_limits():
    for text in ("Что ещё добавить?", "Что вы хотите увидеть в книге?", "Любимые герои, животные, игрушки",
                 "Хочу, чтобы Алихан водил экскаватор и помогал зайчику", "например: зайчик, экскаватор, динозавр",
                 "Героев известных мультфильмов мы заменяем на похожих, но оригинальных персонажей"):
        assert text in JS, text
    assert "request_max', 300" in JS and "favorites_max', 120" in JS
    assert len(re.findall(r"label: '[^']+', text:", between(JS, "function requestExamples()", "function syncExamples"))) == 4


def test_payload_sends_new_fields_in_contract_order():
    body = between(JS, "function payload()", "async function submit")
    positions = [body.index(key) for key in ("topic:", "topic_custom:", "request:", "favorites:")]
    assert positions == sorted(positions)
    assert "a.topic === 'custom' ? a.topic_custom.trim() : ''" in body       # свою тему шлём только при topic = custom
    for field in ("topic: 'topic'", "topic_custom: 'topic'", "request: 'extras'", "favorites: 'extras'"):
        assert field in JS, field                                              # ошибка сервера возвращает на нужный шаг


def test_story_pages_are_wide_with_text_below_and_no_alternation():
    slide = between(JS, "function storySlide(", "function slidesHtml")
    assert 'class="art wide"' in slide and "odd" not in slide and "even" not in slide
    assert slide.index('class="art wide"') < slide.index('class="leaf"')       # картинка всегда первая
    assert re.search(r"\.slide\.page \.art\.wide \{ aspect-ratio: 2 / 1;", CSS)
    assert re.search(r"\.slide\.page \.art\.wide\.sq \{ aspect-ratio: 1 / 1;", CSS)  # старые квадратные страницы не режем
    assert re.search(r"\.slide \.art \{[^}]*aspect-ratio: 1 / 1", CSS)               # обложка осталась квадратом
    assert "naturalWidth / img.naturalHeight < 1.5" in JS
    text_rule = between(CSS, ".slide.page .txt p {", "}")
    assert "line-height: 1.4" in text_rule and "clamp(20px" in text_rule and "22px)" in text_rule
    assert re.search(r"\.acc \{ color: #D4472F; \}", CSS)
    assert "В PDF страница идёт разворотом: картинка на оба листа, текст на ней." in JS


def test_wait_thumbnails_are_wide_pages_and_square_cover():
    assert re.search(r"\.thumb \{[^}]*width: 120px; aspect-ratio: 2 / 1", CSS)
    assert re.search(r'\.prow\[data-k="cover"\] \.thumb \{ aspect-ratio: 1 / 1', CSS)


def test_old_ids_and_actions_still_exist():
    for act in ("start", "next", "back", "pick", "toggle", "edit", "download", "resend", "pager-prev", "pager-next", "fb-send",
                "again", "print-order", "wa-open", "inv-create", "approve", "settings-save", "qr-zoom", "zoom-img"):
        assert re.search(rf"(?:^|\s)'?{re.escape(act)}'?\s*[:,]", between(JS, "const ACTIONS = {", "function syncFeedback")), act
    assert "__V__" in HTML and "query.get('admin') === '1'" in JS and "DEBUG_THEMES" in JS


def test_style_step_sits_between_world_and_extras_and_is_optional_for_old_server():
    steps = between(JS, "function buildSteps()", "function startWizard")
    order = [steps.index(f"'{name}'") for name in ("topic", "world", "style", "extras", "summary")]
    assert order == sorted(order)
    assert "if (styleList().length) list.push('style')" in steps              # старый сервер без стилей: шаг пропускаем
    assert re.search(r"^    style: \{", JS, re.MULTILINE) and "options.styles" in JS
    step = between(JS, "    style: {", "    extras: {")
    assert "optional" not in step and "auto: true" in step                    # шаг обязательный
    assert "valid: () => !!stylePicked()" in step
    for style in ("cartoon3d", "flat2d", "realistic"):
        assert f"{style}: {{ e:" in JS and f".sty-{style}" in CSS, style


def test_style_is_preselected_cannot_be_unpicked_and_goes_into_order():
    assert "S.a.style = defaultStyle()" in between(JS, "function startWizard", "function normalize")
    assert "'cartoon3d'" in between(JS, "const defaultStyle", "const stylePicked")
    assert "field === 'style'" not in between(JS, "function pick(", "/* --- отправка анкеты")   # в отличие от мира, повторное нажатие не снимает
    body = between(JS, "function payload()", "async function submit")
    assert "if (styleList().length) body.style" in body                        # поле не шлём, если сервер не прислал стили
    assert "style: 'style'" in between(JS, "const STEP_BY_FIELD", "\n")
    assert "['style', 'Стиль'," in between(JS, "function summaryHtml()", "/* --- чипы --- */")
