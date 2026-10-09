"""Текст поверх картинки: выбор оформления по синтетическим картинкам (светлая, тёмная, пёстрая), градиент fade,
подложка, свечение, разметка акцентов (диалоги и «!»)."""
import io
import re
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from app import overlay
from app.config import ConfigError, Settings
from app.overlay import (ACCENT, ACCENT_ON_DARK, BUSY_DETAIL, DARK_MAX_LUMA, FADE_A_MAX, LIGHT_MIN_LUMA, MODES,
                         STYLE_FADE, STYLE_PLAIN_DARK, STYLE_PLAIN_LIGHT, STYLE_PLATE_CREAM, STYLE_PLATE_DARK,
                         choose_style, emphasis_markup, fade_alpha, fade_profile, is_dialogue, is_exclamation,
                         measure_region, render_fade_png, render_halo_png, render_plate_png)
from app.pdfbook import FONTS_DIR

PAGE_MM = (420.0, 210.0)
BOX_RIGHT = (240.0, 40.0, 390.0, 170.0)          # где лежит текст у нечётной страницы, мм
BOX_LEFT = (30.0, 40.0, 180.0, 170.0)            # у чётной


# ----------------------------------------------------------------------------- синтетические картинки
def flat(rgb, size=(2048, 1024)) -> Image.Image:
    return Image.new("RGB", size, rgb)


def gradient_sky(size=(2048, 1024)) -> Image.Image:
    """Светлое небо с плавным переходом от голубого к почти белому: спокойное, хотя яркость меняется."""
    w, h = size
    column = Image.new("RGB", (1, h))
    column.putdata([(int(150 + 90 * y / h), int(205 + 40 * y / h), 255) for y in range(h)])
    return column.resize(size)


def noisy(size=(2048, 1024)) -> Image.Image:
    """Крупная пёстрая «шахматка» из ярких пятен: пёстрый фон."""
    im = Image.new("RGB", size)
    draw = ImageDraw.Draw(im)
    colors = [(230, 60, 60), (60, 160, 230), (250, 220, 70), (80, 190, 90), (240, 240, 240), (120, 60, 160)]
    step = 28
    for i, x in enumerate(range(0, size[0], step)):
        for j, y in enumerate(range(0, size[1], step)):
            draw.rectangle([x, y, x + step - 1, y + step - 1], fill=colors[(i * 3 + j * 5 + i * j) % len(colors)])
    return im


def half_light_half_dark(size=(2048, 1024)) -> Image.Image:
    im = flat((245, 240, 225), size)
    ImageDraw.Draw(im).rectangle([size[0] * 0.70, 0, size[0], size[1]], fill=(20, 25, 50))     # у текстовой половины
    return im


def stats_of(im: Image.Image, box=BOX_RIGHT):
    return measure_region(im, box, PAGE_MM)


# ----------------------------------------------------------------------------- измерение и выбор
def test_modes_and_thresholds_are_declared_as_constants():
    assert MODES == ("auto", "fade", "plate", "plain")
    assert 0 < DARK_MAX_LUMA < LIGHT_MIN_LUMA < 255 and BUSY_DETAIL > 0
    assert Settings().text_overlay_mode == "auto"


def test_flat_light_region_is_calm_and_light():
    s = stats_of(flat((245, 240, 225)))
    assert s.luma > LIGHT_MIN_LUMA and s.detail < 0.5 and s.edge_fraction == 0 and not s.busy and s.light


def test_flat_dark_region_is_calm_and_dark():
    s = stats_of(flat((25, 30, 60)))
    assert s.luma < DARK_MAX_LUMA and s.dark and not s.busy and not s.light


def test_smooth_gradient_sky_is_still_calm():
    s = stats_of(gradient_sky())
    assert s.light and not s.busy


def test_noisy_region_is_busy():
    s = stats_of(noisy())
    assert s.busy and (s.detail >= BUSY_DETAIL or s.edge_fraction > 0 or s.mixed)


def test_region_that_is_half_light_half_dark_counts_as_busy():
    s = stats_of(half_light_half_dark(), (240.0, 40.0, 420.0, 170.0))
    assert s.mixed and s.busy


def test_the_measured_box_is_where_the_text_goes_not_the_whole_picture():
    im = flat((245, 240, 225))
    ImageDraw.Draw(im).rectangle([0, 0, 900, 1024], fill=(10, 10, 10))              # тёмное только слева
    assert stats_of(im, BOX_RIGHT).light and stats_of(im, BOX_LEFT).dark


@pytest.mark.parametrize("image, side_box, expected", [
    (flat((245, 240, 225)), BOX_RIGHT, STYLE_PLAIN_LIGHT),            # (a) спокойный светлый: просто текст со свечением
    (gradient_sky(), BOX_LEFT, STYLE_PLAIN_LIGHT),
    (flat((25, 30, 60)), BOX_RIGHT, STYLE_FADE),                      # (b) тёмный: картинка тает в кремовый
    (flat((125, 125, 125)), BOX_RIGHT, STYLE_FADE),                   # средний тон: ни тёмный, ни светлый текст не годится
    (noisy(), BOX_RIGHT, STYLE_FADE),                                 # (c) пёстрый
    (half_light_half_dark(), BOX_RIGHT, STYLE_FADE),
])
def test_auto_mode_light_calm_is_plain_everything_else_fades(image, side_box, expected):
    style = choose_style(stats_of(image, side_box), "auto")
    assert style.name == expected
    assert style.underlay == ("fade" if expected == STYLE_FADE else None)
    assert style.ink == overlay.INK                                    # на fade и на светлом тёмно-коричневый текст
    if expected == STYLE_PLAIN_LIGHT:
        assert style.halo == "light" and style.accent == ACCENT


def test_auto_is_the_default_mode():
    assert overlay.DEFAULT_MODE == "auto"
    assert choose_style(stats_of(flat((245, 240, 225)))).name == STYLE_PLAIN_LIGHT


def test_fade_mode_always_fades():
    for image in (flat((245, 240, 225)), flat((25, 30, 60)), noisy()):
        assert choose_style(stats_of(image), "fade").name == STYLE_FADE


def test_plate_mode_is_cream_on_light_and_dark_translucent_on_dark():
    assert choose_style(stats_of(flat((245, 240, 225))), "plate").name == STYLE_PLATE_CREAM
    assert choose_style(stats_of(noisy()), "plate").name == STYLE_PLATE_CREAM
    dark = choose_style(stats_of(flat((25, 30, 60))), "plate")
    assert dark.name == STYLE_PLATE_DARK and dark.ink == overlay.INK_ON_DARK and dark.accent == ACCENT_ON_DARK
    assert dark.underlay == "plate" and dark.halo is None


def test_plain_mode_never_covers_the_picture_and_strengthens_the_halo_on_busy_backgrounds():
    light = choose_style(stats_of(flat((245, 240, 225))), "plain")
    dark = choose_style(stats_of(flat((25, 30, 60))), "plain")
    busy = choose_style(stats_of(noisy()), "plain")
    assert (light.name, dark.name) == (STYLE_PLAIN_LIGHT, STYLE_PLAIN_DARK)
    assert light.halo == "light" and dark.halo == "dark" and dark.ink == overlay.INK_ON_DARK
    assert dark.accent == ACCENT_ON_DARK
    for style in (light, dark, busy):
        assert style.underlay is None
    assert busy.halo_gain > light.halo_gain


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        choose_style(stats_of(flat((245, 240, 225))), "weird")


# ----------------------------------------------------------------------------- настройка TEXT_OVERLAY_MODE
@pytest.mark.parametrize("value, expected", [("", "auto"), ("auto", "auto"), ("FADE", "fade"), ("plate", "plate"),
                                              ("plain", "plain")])
def test_text_overlay_mode_setting_is_read_from_env(tmp_path, monkeypatch, value, expected):
    monkeypatch.setenv("TEXT_OVERLAY_MODE", value)
    env = tmp_path / ".env"
    env.write_text("")
    assert Settings.from_env(env).text_overlay_mode == expected


def test_wrong_text_overlay_mode_gives_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TEXT_OVERLAY_MODE", "sticker")
    env = tmp_path / ".env"
    env.write_text("")
    with pytest.raises(ConfigError, match="TEXT_OVERLAY_MODE"):
        Settings.from_env(env)


# ----------------------------------------------------------------------------- fade: градиент
def alphas_of(png: bytes, row: int | None = None) -> list[int]:
    with Image.open(io.BytesIO(png)) as im:
        assert im.mode == "RGBA"
        y = im.height // 2 if row is None else row
        return [im.getpixel((x, y))[3] for x in range(im.width)]


def test_fade_alpha_never_decreases_from_the_fold_to_the_outer_edge():
    values = [fade_alpha(mm_ / 2) for mm_ in range(0, 421)]              # 0..210 мм с шагом 0,5
    assert all(b >= a for a, b in zip(values, values[1:]))
    assert values[0] == 0 and values[-1] == pytest.approx(FADE_A_MAX)
    profile = fade_profile(630)
    assert all(b >= a for a, b in zip(profile, profile[1:])) and profile[0] <= 1 and profile[-1] == round(255 * FADE_A_MAX)


def test_fade_png_on_the_right_grows_to_about_92_percent_at_the_outer_edge_without_a_hard_edge():
    png = render_fade_png("right")
    a = alphas_of(png)
    assert len(a) == round(210 * overlay.FADE_PX_PER_MM) and a[0] <= 1 and abs(a[-1] - 0.92 * 255) <= 2
    assert all(y >= x for x, y in zip(a, a[1:]))                          # только растёт
    assert max(y - x for x, y in zip(a, a[1:])) <= 4                      # ни одного скачка: нет жёсткой границы
    with Image.open(io.BytesIO(png)) as im:
        assert im.size == (630, 630)
        assert im.getpixel((315, 10))[:3] == (255, 253, 246)             # кремово-белый #FFFDF6
        assert im.getpixel((315, 10))[3] == im.getpixel((315, 620))[3]   # градиент только горизонтальный


def test_fade_png_on_the_left_is_the_mirror_image():
    right, left = alphas_of(render_fade_png("right")), alphas_of(render_fade_png("left"))
    assert left == right[::-1] and left[0] > left[-1] and all(y <= x for x, y in zip(left, left[1:]))


def test_fade_is_almost_clear_next_to_the_fold_and_dense_where_the_text_sits():
    p = fade_profile(210)                        # по миллиметру от сгиба
    assert p[5] < 0.05 * 255 and p[60] > 0.6 * 255 and p[140] >= 0.9 * 255 * FADE_A_MAX


# ----------------------------------------------------------------------------- подложка и свечение
def test_plate_png_is_soft_feathered_and_cream_or_dark():
    png, margin = render_plate_png(120, 70, dark=False)
    a = alphas_of(png)
    with Image.open(io.BytesIO(png)) as im:
        assert im.size[0] == round((120 + 2 * margin) * overlay.PLATE_PX_PER_MM)
        centre = im.getpixel((im.width // 2, im.height // 2))
        assert centre[:3] == (255, 253, 246) and abs(centre[3] - 0.8 * 255) <= 3
        assert im.getpixel((0, 0))[3] == 0 and a[0] == 0 and a[-1] == 0          # у края пусто
    rise = a[: len(a) // 2]
    assert all(y >= x for x, y in zip(rise, rise[1:])) and max(y - x for x, y in zip(rise, rise[1:])) < 20   # плавно
    dark_png, _ = render_plate_png(120, 70, dark=True)
    with Image.open(io.BytesIO(dark_png)) as im:
        r, g, b, alpha = im.getpixel((im.width // 2, im.height // 2))
        assert max(r, g, b) < 60 and 0.5 * 255 < alpha < 0.75 * 255


def regular_font() -> Path:
    return FONTS_DIR / "Nunito-ExtraBold.ttf"


def test_halo_png_is_a_blurred_silhouette_of_the_text_in_cream_or_dark():
    lines = [("Айдар побежал", 60.0, 14.0), ("к реке!", 60.0, 28.0)]
    light, margin = render_halo_png(lines, regular_font(), 24, 120, 40, kind="light")
    with Image.open(io.BytesIO(light)) as im:
        k = overlay.HALO_PX_PER_MM
        assert im.size == (round((120 + 2 * margin) * k), round((40 + 2 * margin) * k))
        alpha = im.getchannel("A")
        assert alpha.getbbox() is not None and alpha.getpixel((0, 0)) == 0 and alpha.getpixel((im.width - 1, im.height - 1)) == 0
        assert max(alpha.getdata()) <= 0.61 * 255                                  # «очень мягкое»: не сплошная заливка
        band = alpha.crop((0, round((margin + 5) * k), im.width, round((margin + 16) * k)))   # первая строка текста
        assert max(band.getdata()) > 100 and im.getpixel((0, 0))[:3] == overlay.GLOW_RGB
    dark, _ = render_halo_png(lines, regular_font(), 24, 120, 40, kind="dark")
    with Image.open(io.BytesIO(dark)) as im:
        assert max(max(p[:3]) for p in im.getdata() if p[3] > 0) < 60


def test_halo_draws_kyrgyz_and_russian_letters():
    lines = [("Үмүт өңдүү ң Ү Ө Ң", 60.0, 14.0), ("Ёлка, щука, ъ", 60.0, 28.0)]
    png, _ = render_halo_png(lines, regular_font(), 24, 120, 40)
    with Image.open(io.BytesIO(png)) as im:
        assert im.getchannel("A").getbbox() is not None
    blank, _ = render_halo_png([("", 60.0, 14.0)], regular_font(), 24, 120, 40)
    with Image.open(io.BytesIO(blank)) as im:
        assert im.getchannel("A").getbbox() is None


# ----------------------------------------------------------------------------- акценты в тексте
def test_exclamations_are_accented_and_the_rest_is_plain():
    assert emphasis_markup("Привет, мир! Как дела? Хорошо.") == \
        f'<font color="{ACCENT}">Привет, мир!</font> Как дела? Хорошо.'
    assert emphasis_markup("Тихо, ночь. Лошадь заржала.") == "Тихо, ночь. Лошадь заржала."      # без акцентов — без разметки


def test_neighbouring_exclamations_share_one_colour_run():
    assert emphasis_markup("Вот и день. Ура! Ура! Побежали дальше.") == \
        f'Вот и день. <font color="{ACCENT}">Ура! Ура!</font> Побежали дальше.'


def test_dialogue_after_a_dash_is_accented_but_the_authors_words_after_it_are_not():
    text = "Айдар подошёл к реке.\n— Смотри, рыба, — сказал он.\n– Ой, большая.\n- Давай поймаем."
    markup = emphasis_markup(text)
    lines = markup.split("<br/>")
    assert lines[0] == "Айдар подошёл к реке."
    assert lines[1] == f'<font color="{ACCENT}">— Смотри, рыба,</font> — сказал он.'
    assert lines[2] == f'<font color="{ACCENT}">– Ой, большая.</font>'
    assert lines[3] == f'<font color="{ACCENT}">- Давай поймаем.</font>'
    assert is_dialogue("  — Привет") and not is_dialogue("Привет — друг")


def test_exclamation_detection_handles_quotes_and_trailing_dots():
    assert is_exclamation("«Какой добрый мальчик!»") and is_exclamation("Ой!..") and is_exclamation("Что?!")
    assert not is_exclamation("Что это?") and not is_exclamation("Тихо.") and not is_exclamation("")
    assert emphasis_markup("Все сказали: «Какой добрый мальчик!» Он улыбнулся.") == \
        f'Все сказали: <font color="{ACCENT}">«Какой добрый мальчик!»</font> Он улыбнулся.'


def test_runs_split_each_line_into_plain_and_accent_pieces_and_rebuild_the_text():
    from app.overlay import emphasis_runs
    text = "Тихо, ночь. Ура! Ура! Все бежали.\n— Смотри! — сказал он.\n\nКонец."
    runs = emphasis_runs(text)
    assert runs[0] == [("Тихо, ночь. ", False), ("Ура! Ура!", True), (" Все бежали.", False)]
    assert runs[1] == [("— Смотри!", True), (" — сказал он.", False)] and runs[2] == [] and runs[3] == [("Конец.", False)]
    assert "\n".join("".join(t for t, _ in line) for line in runs) == text


def test_runs_and_markup_always_agree():
    from app.overlay import emphasis_runs
    for text in ("Привет! Как дела?", "— Да!\nНет.", "Ой!.. Ой! Ну и ну.", "Просто текст без восклицаний.", "Ура!"):
        runs = emphasis_runs(text)
        accent_parts = [t for line in runs for t, a in line if a]
        markup = emphasis_markup(text)
        assert [m for m in re.findall(r'<font color="#D4472F">(.*?)</font>', markup)] == [escape_(t) for t in accent_parts]


def escape_(text: str) -> str:
    from xml.sax.saxutils import escape
    return escape(text)


def test_the_accent_colour_can_be_brighter_for_dark_backgrounds():
    assert f'color="{ACCENT_ON_DARK}"' in emphasis_markup("Ура!", ACCENT_ON_DARK)
    assert ACCENT_ON_DARK != ACCENT and ACCENT == "#D4472F"


def test_emphasis_keeps_special_characters_escaped():
    text = "Том & Джерри бежали <быстро> > всех! Они кричали: «A&B»."
    markup = emphasis_markup(text)
    assert "&amp;" in markup and "&lt;быстро&gt;" in markup and "&gt; всех" in markup
    assert not re.search(r"&(?!amp;|lt;|gt;)", markup)                      # ни одного голого &
    style = ParagraphStyle("t", fontName="Helvetica", fontSize=20)
    para = Paragraph(markup, style)                                          # разметка разбирается без ошибок
    para.wrap(400, 1000)
    assert "Том & Джерри" in para.getPlainText() and "<быстро>" in para.getPlainText()


def test_emphasis_works_for_kyrgyz_text_and_keeps_every_letter():
    text = "Үмүт чуркап барды. Ал: «Мен өзүм кылам!» деди.\n— Жүр, ыңгайлуу жерге барабыз!"
    markup = emphasis_markup(text)
    plain = re.sub(r"</?font[^>]*>", "", markup).replace("<br/>", "\n")
    assert plain == text
    assert markup.count("<font") == markup.count("</font>") >= 1                  # цитата или реплика покрашены, парных меток поровну


# ----------------------------------------------------------------------------- акцент — пряность, а не краска для страницы
def accent_texts(text: str) -> list[str]:
    from app.overlay import emphasis_runs
    return [t for line in emphasis_runs(text) for t, a in line if a]


NARRATION = ("Лиса прыгнула высоко над огромным пушистым облаком! Панда засмеялась и хлопнула в ладоши! "
             "Ёжик свернулся в колючий шарик и покатился вниз по холму!")


def test_long_narration_sentences_with_an_exclamation_mark_are_never_accented():
    from app.overlay import ACCENT_EXCLAIM_WORDS
    assert ACCENT_EXCLAIM_WORDS == 4
    assert accent_texts(NARRATION) == []
    assert emphasis_markup(NARRATION) == NARRATION                                  # ни одной метки <font>
    assert accent_texts("Вдруг все три фонарика вспыхнули ярким розовым светом! Тихо.") == []


def test_only_short_exclamations_up_to_four_words_are_accented():
    page = "Бам! Хлоп! Первый шарик застрял в яркой розовой тучке. Второй упал в пушистый сугроб. Ой, как высоко! Ого!"
    assert accent_texts(page) == ["Бам! Хлоп!", "Ой, как высоко! Ого!"]
    assert accent_texts("Вот это был чудесный день! Ура.") == []                                   # пять слов — уже не возглас
    assert accent_texts("Ого, какой огромный!") == ["Ого, какой огромный!"]


def test_speech_after_a_dash_is_accented_without_the_authors_words():
    text = "— Я Пуф, я помогу! — сказал он. — Раз, два, три — свети! — позвала девочка, но фонарики молчали."
    assert accent_texts(text) == ["— Я Пуф, я помогу!", "— Раз, два, три — свети!"]
    markup = emphasis_markup(text)
    assert f'<font color="{ACCENT}">— Я Пуф, я помогу!</font> — сказал он.' in markup and "позвала девочка" in markup
    assert f'<font color="{ACCENT}">— Раз, два, три — свети!</font> — позвала' in markup


def test_a_page_of_dialogue_keeps_at_most_half_of_its_words_in_colour():
    from app.overlay import ACCENT_BUDGET, emphasis_runs
    text = ("— Давай посмотрим на это огромное облако, — сказал Бом.\n— Давай, — согласилась девочка, — только не спеши.\n"
            "— Смотри, какой пушистый и красивый ветер дует с гор!\n— Ура! Мы нашли первую звезду!")
    runs = emphasis_runs(text)
    words = sum(len(t.split()) for line in runs for t, _ in line)
    accent = sum(len(t.split()) for line in runs for t, a in line if a)
    assert accent <= ACCENT_BUDGET * words
    assert "\n".join("".join(t for t, _ in line) for line in runs) == text                  # текст при этом не меняется
    assert any(a for line in runs for _, a in line)                                          # а что-то цветное осталось


def test_the_longest_accents_are_the_first_to_lose_their_colour_and_tiny_pages_are_exempt():
    text = "— Давай посмотрим на это огромное пушистое розовое облако и на все звёзды вокруг него!\n— Ура!\nМы пошли."
    assert accent_texts(text) == ["— Ура!"]
    assert accent_texts("Ура!") == ["Ура!"] and accent_texts("— Идём!") == ["— Идём!"]


def test_runs_lines_and_text_always_agree_with_the_new_rules():
    from app.overlay import emphasis_runs
    for text in (NARRATION, "— Я Пуф! — сказал он.\nБам! Хлоп!\n«Ого!» — подумала девочка.", "Тихо.\n\n— Да!",
                 "Раз, два… динь! Колокольчик звякнул. — Пуф, они слышат звон! — прошептала девочка."):
        runs = emphasis_runs(text)
        assert "\n".join("".join(t for t, _ in line) for line in runs) == text
        accents = [t for line in runs for t, a in line if a]
        assert re.findall(r'<font color="#D4472F">(.*?)</font>', emphasis_markup(text)) == [escape_(t) for t in accents]
        for line in runs:                                                                      # соседние куски разного цвета
            assert all(a[1] != b[1] for a, b in zip(line, line[1:]))
