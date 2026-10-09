"""PDF-фотокнига: PAGES + 2 разворотов 420×210 мм, шрифты Nunito и Comfortaa, буквы ү ө ң, подбор размера текста,
широкая картинка на весь разворот, текст поверх неё (нечётные страницы справа, чётные слева), оформление под фон
(свечение, fade, подложка), красные акценты, пометка о заглушках."""
import io
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ContentStream
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont

from app import overlay
from app.layout import PAGE_SIZE, text_side
from app.pdfbook import (FONTS_DIR, HARD_MIN_PT, LEADING, OVERLAY_MAX_PT, OVERLAY_MIN_PT, SPREADS, SQ, TEXT_MAX_PT,
                         TEXT_MIN_PT, TA_LEFT, F_REG, _Book, build_pdf, fit_paragraph)
from app.placeholder import draw_placeholder
from app.profile import Profile
from app.providers.text_mock import build_mock_story
from app.story import PAGES, validate_story

from .conftest import SAMPLE

KY_LETTERS = "үөңҮӨҢ"
PT = 72 / 25.4                                  # пунктов в миллиметре
_WIDE_CACHE: dict[tuple, bytes] = {}


def wide_placeholder(i: int) -> bytes:
    key = ("wide", i)
    if key not in _WIDE_CACHE:
        _WIDE_CACHE[key] = draw_placeholder(f"Страница {i}", "test scene", f"p{i}", size=PAGE_SIZE,
                                            calm_side=text_side(i), sky="day")
    return _WIDE_CACHE[key]


def make_images(folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    images = {}
    cover = folder / "cover.jpg"
    cover.write_bytes(draw_placeholder("cover", "test scene", "cover"))
    images["cover"] = cover
    for i in range(1, PAGES + 1):
        path = folder / f"p{i}.jpg"
        path.write_bytes(wide_placeholder(i))
        images[f"p{i}"] = path
    return images


def solid_images(folder: Path, rgb, size=PAGE_SIZE, pages=None) -> dict:
    """Книга, у которой все страницы — однотонные картинки (чтобы знать, какой фон под текстом)."""
    images = make_images(folder)
    for i in range(1, PAGES + 1):
        im = Image.new("RGB", size, rgb)
        if pages and i in pages:
            im = pages[i](im)
        im.save(folder / f"p{i}.jpg", "JPEG", quality=88)
    return images


def text_of(pdf: Path) -> list[str]:
    return [page.extract_text() for page in PdfReader(str(pdf)).pages]


def text_chunks(page) -> list[tuple[str, float, float, float]]:
    """Куски текста на развороте: (текст, x мм, y мм базовой линии, размер pt)."""
    chunks: list[tuple[str, float, float, float]] = []

    def visit(text, cm, tm, font_dict, font_size):
        if text.strip():
            chunks.append((text.strip(), (cm[4] + tm[4]) / PT, (cm[5] + tm[5]) / PT, float(font_size)))

    page.extract_text(visitor_text=visit)
    return chunks


def image_boxes(reader: PdfReader, page) -> list[tuple[float, float, float, float]]:
    """Картинки на развороте: (x, y, ширина, высота) в мм. Мелкие служебные преобразования не считаются."""
    boxes = []
    for operands, op in ContentStream(page.get_contents(), reader).operations:
        if op == b"cm":
            a, b, c, d, e, f = (float(v) for v in operands)
            if b == 0 and c == 0 and a > 20 * PT and d > 20 * PT:
                boxes.append((e / PT, f / PT, a / PT, d / PT))
    return boxes


def fill_colors(reader: PdfReader, page) -> list[tuple[float, float, float]]:
    """Цвета заливки (rg) на развороте."""
    out = []
    for operands, op in ContentStream(page.get_contents(), reader).operations:
        if op == b"rg":
            out.append(tuple(round(float(v), 3) for v in operands))
    return out


def rgb01(hex_color: str) -> tuple[float, float, float]:
    r, g, b = overlay._rgb(hex_color)
    return round(r / 255, 3), round(g / 255, 3), round(b / 255, 3)


# ----------------------------------------------------------------------- шрифты
@pytest.mark.parametrize("font_file", ["Nunito-SemiBold.ttf", "Nunito-ExtraBold.ttf", "Comfortaa-Bold.ttf",
                                       "DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"])
def test_all_kyrgyz_and_russian_letters_exist_in_every_font_file(font_file):
    cmap = TTFont("probe-" + font_file, str(FONTS_DIR / font_file)).face.charToGlyph
    for letter in KY_LETTERS + "АЯаяЁё«»—№":
        assert ord(letter) in cmap, f"{letter} нет в {font_file}"


def test_fonts_have_their_licenses_next_to_them():
    assert (FONTS_DIR / "OFL-Nunito.txt").exists() and (FONTS_DIR / "OFL-Comfortaa.txt").exists()


def test_pdf_uses_nunito_and_comfortaa_not_dejavu(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    reader = PdfReader(str(build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "f.pdf")))
    names = set()
    for page in reader.pages:
        for font in (page["/Resources"].get("/Font") or {}).values():
            names.add(str(font.get_object()["/BaseFont"]))
    assert any("Nunito" in n for n in names) and any("Comfortaa" in n for n in names), names
    assert not any("DejaVu" in n for n in names), names


def test_kyrgyz_letters_are_written_into_pdf_and_readable(tmp_path):
    profile = Profile.from_payload({**SAMPLE, "name": "Үмүт", "language": "ky", "dedication": "Ү Ө Ң ү ө ң"})
    data = build_mock_story(profile)
    data["title"] = "Үнүм Өзөк Ңң"
    data["moral"] = "Ү Ө Ң үөң"
    data["pages"][0]["text"] = "Үмүт үйдөн чыкты. Ө Ң ү ө ң: «Мен ыраазымын!» — деди ал."
    story = validate_story(data, "ky")
    pdf = build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ky.pdf", mock=False)
    pages = text_of(pdf)
    joined = "\n".join(pages)
    for letter in KY_LETTERS:
        assert letter in joined, f"буква {letter} не нашлась в тексте PDF"
    assert "Ү Ө Ң ү ө ң" in pages[0]                       # посвящение на левой странице обложки
    assert "Үмүт үчүн" in pages[0] and "Үмүт үчүн китеп" in pages[0]
    assert "Үмүт үйдөн чыкты" in " ".join(pages[1].split()) and "ыраазымын" in pages[1]     # текст поверх картинки
    assert "Аягы" in pages[-1]                             # финал на кыргызском
    assert "Ү Ө Ң үөң" in pages[-1]                        # мораль


# ----------------------------------------------------------------------- структура книги
def test_book_is_spreads_of_420_by_210_mm(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    pdf = build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ru.pdf")
    reader = PdfReader(str(pdf))
    assert SPREADS == PAGES + 2 == 10 and len(reader.pages) == SPREADS     # обложка, страницы истории, финал
    for page in reader.pages:
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        assert abs(width / PT - 420) < 0.5 and abs(height / PT - 210) < 0.5
    assert reader.metadata.title == story.title
    assert "книга" in reader.metadata.subject.lower() and "сказка" not in reader.metadata.subject.lower()
    assert "сказка" not in (reader.metadata.author or "").lower()


def test_spread_contents_cover_story_pages_and_finale(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    pdf = build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ru.pdf")
    pages = text_of(pdf)
    cover = pages[0]
    assert "Для Айдара" in cover and "Для сына" in cover                      # слева: посвящение
    assert story.title.split()[0] in cover and "Книга для Айдара" in cover   # справа: название и подпись
    for number in range(1, PAGES + 1):
        spread = " ".join(pages[number].split())
        first_words = " ".join(story.pages[number - 1].text.split()[:3])
        assert first_words in spread, f"нет текста страницы {number}"
        assert spread.count(first_words) == 1                                # свечение и тень — картинки, текст один
        assert spread.endswith(str(number))                                  # номер внизу своей половины
    finale = " ".join(pages[-1].split())
    assert "Конец" in finale and story.moral in finale and "Эта книга создана специально для Айдара" in finale
    assert " ".join(story.wish.split()[:4]) in finale


def test_cover_spread_keeps_a_square_cover_on_the_right_and_paper_on_the_left(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    reader = PdfReader(str(build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ru.pdf")))
    assert image_boxes(reader, reader.pages[0]) == [pytest.approx((210, 0, 210, 210), abs=0.5)]
    assert image_boxes(reader, reader.pages[-1]) == []                          # в финале картинок нет


def test_every_story_spread_is_one_wide_picture_edge_to_edge_without_paper_pages(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    reader = PdfReader(str(build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ru.pdf")))
    for number in range(1, PAGES + 1):
        boxes = image_boxes(reader, reader.pages[number])
        assert boxes[0] == pytest.approx((0, 0, 420, 210), abs=0.5), f"страница {number}: картинка не на весь разворот"
        colors = fill_colors(reader, reader.pages[number])
        assert rgb01("#FBF6EA") not in colors, f"страница {number}: бумажный квадрат поверх картинки"


def test_a_square_or_odd_picture_is_cropped_to_fill_the_spread_not_stretched(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    images = make_images(tmp_path / "img")
    Image.new("RGB", (1024, 1024), (240, 230, 200)).save(images["p1"], "JPEG")              # квадрат от старой версии
    Image.new("RGB", (3000, 1000), (240, 230, 200)).save(images["p2"], "JPEG")              # слишком широкая
    reader = PdfReader(str(build_pdf(story, profile, images, tmp_path / "x.pdf")))
    for number in (1, 2):
        assert image_boxes(reader, reader.pages[number])[0] == pytest.approx((0, 0, 420, 210), abs=0.5)
    sizes = {(im.image.width, im.image.height) for p in (1, 2) for im in reader.pages[p].images}
    assert (1024, 512) in sizes and (2000, 1000) in sizes                      # обрезано до 2:1, не растянуто


def test_text_sits_on_the_calm_half_odd_pages_right_even_pages_left(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    reader = PdfReader(str(build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ru.pdf")))
    for number in range(1, PAGES + 1):
        body = [c for c in text_chunks(reader.pages[number]) if c[2] > 30]
        assert body, f"страница {number}: нет текста"
        lo, hi = (230, 400) if number % 2 == 1 else (20, 190)
        assert all(lo <= x <= hi for _, x, _, _ in body), f"страница {number}: текст не на своей половине"
        badge = [c for c in text_chunks(reader.pages[number]) if c[0] == str(number)]
        assert badge and (210 if number % 2 == 1 else 0) < badge[-1][1] < (420 if number % 2 == 1 else 210)


def test_text_sides_and_styles_are_recorded_while_building(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    book = _Book(tmp_path / "b.pdf", profile, story, False)
    images = make_images(tmp_path / "img")
    for i in range(1, PAGES + 1):
        book.story_page(i, images[f"p{i}"])
    assert book.text_sides == ["right" if i % 2 else "left" for i in range(1, PAGES + 1)]    # нечётные справа, чётные слева
    assert len(book.text_styles) == PAGES and set(book.text_styles) <= set(overlay.STYLES)


def test_text_is_large_dark_brown_and_centred_in_its_half(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    reader = PdfReader(str(build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ru.pdf")))
    for number in range(1, PAGES + 1):
        body = [c for c in text_chunks(reader.pages[number]) if c[2] > 30]
        sizes = {size for _, _, _, size in body}
        assert all(OVERLAY_MIN_PT - 1e-6 <= s <= OVERLAY_MAX_PT + 1e-6 for s in sizes), (number, sizes)
        top = max(y + size / PT for _, _, y, size in body)
        bottom = min(y for _, _, y, _ in body)
        assert abs((top + bottom) / 2 - 110) < 12, f"страница {number}: текст не по центру ({top:.0f}..{bottom:.0f} мм)"
        assert bottom > 34 - 6                                               # ниже начинается номер страницы
        assert rgb01(overlay.INK) in fill_colors(reader, reader.pages[number])


def test_mock_caption_only_when_mock(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    images = make_images(tmp_path / "img")
    with_note = text_of(build_pdf(story, profile, images, tmp_path / "a.pdf", mock=True))
    without = text_of(build_pdf(story, profile, images, tmp_path / "b.pdf", mock=False))
    assert "Тестовая сборка: заглушки" in with_note[0] and "Тестовая сборка: заглушки" in with_note[-1]
    assert not any("Тестовая сборка" in p for p in without)


# ----------------------------------------------------------------------- оформление текста под фон
LIGHT, DARK = (245, 240, 225), (25, 30, 60)


def build_with(tmp_path, profile, images, mode="auto"):
    story = validate_story(build_mock_story(profile), "ru")
    book = _Book(tmp_path / "m.pdf", profile, story, False, overlay_mode=mode)
    for i in range(1, PAGES + 1):
        book.story_page(i, images[f"p{i}"])
    book.c.save()
    return book, PdfReader(str(tmp_path / "m.pdf"))


def under_text(reader, number):
    """Картинки на развороте страницы number (книга без обложки: страницы с нуля) кроме самой широкой картинки."""
    return image_boxes(reader, reader.pages[number - 1])[1:]


def test_auto_light_calm_picture_gets_plain_text_with_a_soft_glow_and_no_plate(tmp_path, profile):
    book, reader = build_with(tmp_path, profile, solid_images(tmp_path / "i", LIGHT))
    assert book.text_styles == [overlay.STYLE_PLAIN_LIGHT] * PAGES
    for number in range(1, PAGES + 1):
        extra = under_text(reader, number)
        assert len(extra) == 1                                             # только свечение за буквами
        x, y, w, h = extra[0]
        assert w < 210 and h < 210                                         # не подложка на половину разворота


def test_auto_dark_picture_fades_into_cream_on_the_text_side(tmp_path, profile):
    book, reader = build_with(tmp_path, profile, solid_images(tmp_path / "i", DARK))
    assert book.text_styles == [overlay.STYLE_FADE] * PAGES
    for number in range(1, PAGES + 1):
        extra = under_text(reader, number)
        assert len(extra) == 1
        x, y, w, h = extra[0]
        assert (w, h) == pytest.approx((210, 210), abs=0.5) and x == pytest.approx(210 if number % 2 else 0, abs=0.5)
        assert rgb01(overlay.INK) in fill_colors(reader, reader.pages[number - 1])      # текст на fade тёмно-коричневый


def test_auto_busy_picture_fades_too(tmp_path, profile):
    from tests.test_overlay import noisy
    images = make_images(tmp_path / "i")
    for i in range(1, PAGES + 1):
        noisy().save(images[f"p{i}"], "JPEG", quality=88)
    book, _ = build_with(tmp_path, profile, images)
    assert book.text_styles == [overlay.STYLE_FADE] * PAGES


def test_only_the_text_half_is_measured(tmp_path, profile):
    """Тёмная половина героев не мешает: под текстом (правая у нечётных) светло — значит просто текст."""
    def dark_left(im):
        from PIL import ImageDraw
        ImageDraw.Draw(im).rectangle([0, 0, 1000, 1024], fill=DARK)
        return im
    images = solid_images(tmp_path / "i", LIGHT, pages={1: dark_left, 3: dark_left})
    book, _ = build_with(tmp_path, profile, images)
    assert book.text_styles[0] == overlay.STYLE_PLAIN_LIGHT and book.text_styles[2] == overlay.STYLE_PLAIN_LIGHT


def test_plate_mode_draws_a_soft_plate_under_every_text(tmp_path, profile):
    book, reader = build_with(tmp_path, profile, solid_images(tmp_path / "i", LIGHT), "plate")
    assert book.text_styles == [overlay.STYLE_PLATE_CREAM] * PAGES
    dark_book, dark_reader = build_with(tmp_path / "d", profile, solid_images(tmp_path / "d" / "i", DARK), "plate")
    assert dark_book.text_styles == [overlay.STYLE_PLATE_DARK] * PAGES
    for number in range(1, PAGES + 1):
        (x, y, w, h), = under_text(reader, number)
        assert 100 < w < 210 and 40 < h < 200                              # подложка вокруг текста, не на весь разворот
        assert rgb01(overlay.INK_ON_DARK) in fill_colors(dark_reader, dark_reader.pages[number - 1])   # кремовый текст на тёмной


def test_fade_mode_forces_fade_on_a_light_picture(tmp_path, profile):
    book, reader = build_with(tmp_path, profile, solid_images(tmp_path / "i", LIGHT), "fade")
    assert book.text_styles == [overlay.STYLE_FADE] * PAGES


def test_plain_mode_never_covers_the_picture_even_when_it_is_dark_or_busy(tmp_path, profile):
    book, reader = build_with(tmp_path, profile, solid_images(tmp_path / "i", DARK), "plain")
    assert book.text_styles == [overlay.STYLE_PLAIN_DARK] * PAGES
    for number in range(1, PAGES + 1):
        extra = under_text(reader, number)
        assert len(extra) == 1 and extra[0][2] < 210                       # только тень за буквами
        assert rgb01(overlay.INK_ON_DARK) in fill_colors(reader, reader.pages[number - 1])


def test_unknown_overlay_mode_is_refused(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    with pytest.raises(ValueError):
        build_pdf(story, profile, make_images(tmp_path / "i"), tmp_path / "x.pdf", overlay_mode="sticker")


def test_build_pdf_reports_sides_styles_and_smallest_size(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    report: dict = {}
    build_pdf(story, profile, solid_images(tmp_path / "i", LIGHT), tmp_path / "x.pdf", overlay_mode="auto", report=report)
    assert report["text_sides"] == [text_side(i) for i in range(1, PAGES + 1)]
    assert report["text_styles"] == [overlay.STYLE_PLAIN_LIGHT] * PAGES
    assert OVERLAY_MIN_PT <= report["min_text_pt"] <= OVERLAY_MAX_PT and report["overlay_mode"] == "auto"


# ----------------------------------------------------------------------- акценты: диалоги и «!»
def accent_book(tmp_path, profile, text, rgb=LIGHT, mode="auto"):
    data = build_mock_story(profile)
    data["pages"][0]["text"] = text
    story = validate_story(data, "ru")
    images = solid_images(tmp_path / "i", rgb)
    book = _Book(tmp_path / "a.pdf", profile, story, False, overlay_mode=mode)
    book.story_page(1, images["p1"])
    book.c.save()
    return PdfReader(str(tmp_path / "a.pdf"))


def test_dialogue_and_exclamations_are_drawn_in_the_accent_colour_the_rest_in_brown(tmp_path, profile):
    reader = accent_book(tmp_path, profile, "Айдар пошёл к реке. Ура, рыба!\n— Смотри, какая большая, — сказал он.\nВода тихо шумела.")
    colors = fill_colors(reader, reader.pages[0])
    assert rgb01(overlay.ACCENT) in colors and rgb01(overlay.INK) in colors
    text = " ".join(reader.pages[0].extract_text().split())
    assert "Ура, рыба!" in text and "— Смотри" in text


def test_text_without_dialogue_or_exclamations_has_no_accent_colour(tmp_path, profile):
    reader = accent_book(tmp_path, profile, "Айдар пошёл к реке. Вода тихо шумела. Он остановился.")
    colors = fill_colors(reader, reader.pages[0])
    assert rgb01(overlay.ACCENT) not in colors and rgb01(overlay.INK) in colors


def test_accent_is_brighter_when_the_text_sits_on_a_dark_background(tmp_path, profile):
    reader = accent_book(tmp_path, profile, "Тихо! Идём дальше.", rgb=DARK, mode="plain")
    colors = fill_colors(reader, reader.pages[0])
    assert rgb01(overlay.ACCENT_ON_DARK) in colors and rgb01(overlay.ACCENT) not in colors


def test_ampersand_and_angle_brackets_in_story_text_do_not_break_the_pdf(tmp_path, profile):
    reader = accent_book(tmp_path, profile, "Том & Джерри ждали <тебя> > всех! Они пели.")
    text = " ".join(reader.pages[0].extract_text().split())
    assert "Том & Джерри" in text and "<тебя>" in text


# ----------------------------------------------------------------------- размер текста
def test_text_size_range_on_paper_pages_is_twenty_down_to_thirteen_with_line_height_one_and_a_bit():
    assert (TEXT_MAX_PT, TEXT_MIN_PT) == (20.0, 13.0) and 1.3 <= LEADING <= 1.5 and HARD_MIN_PT < TEXT_MIN_PT


def test_text_over_the_picture_is_big_between_thirty_and_eighteen_points():
    assert (OVERLAY_MAX_PT, OVERLAY_MIN_PT) == (30.0, 18.0)


def test_long_text_shrinks_but_not_below_minimum_when_it_fits():
    box_w, box_h = 162 * PT, 152 * PT
    short, size_short, _ = fit_paragraph("Короткий текст.", F_REG, box_w, box_h, max_pt=TEXT_MAX_PT, min_pt=TEXT_MIN_PT, align=TA_LEFT)
    assert size_short == TEXT_MAX_PT
    long_text = " ".join(["Это довольно длинное предложение сказки про героя и его приключения."] * 14)
    _, size_long, height = fit_paragraph(long_text, F_REG, box_w, box_h, max_pt=TEXT_MAX_PT, min_pt=TEXT_MIN_PT, align=TA_LEFT)
    assert TEXT_MIN_PT <= size_long < TEXT_MAX_PT and height <= box_h


def test_emergency_minimum_is_used_only_when_even_the_minimum_does_not_fit():
    huge = " ".join(["Очень длинный текст."] * 400)
    _, size, height = fit_paragraph(huge, F_REG, 162 * PT, 152 * PT, max_pt=TEXT_MAX_PT, min_pt=TEXT_MIN_PT, align=TA_LEFT)
    assert HARD_MIN_PT <= size < TEXT_MIN_PT


def story_with_text(profile, text, language="ru"):
    data = build_mock_story(profile)
    data["pages"][0]["text"] = text
    return validate_story(data, language)


def test_a_few_short_lines_are_set_at_the_biggest_size(tmp_path, profile):
    book = _Book(tmp_path / "s.pdf", profile, story_with_text(profile, "Айдар побежал к реке.\nУра!\nРыба плеснула."), False)
    book.story_page(1, make_images(tmp_path / "img")["p1"])
    assert book.min_pt_used == OVERLAY_MAX_PT


@pytest.mark.parametrize("language", ["ru", "ky"])
def test_every_age_fits_the_text_area_at_readable_size(tmp_path, language):
    for age in range(3, 10):
        profile = Profile.from_payload({**SAMPLE, "age": age, "language": language})
        story = validate_story(build_mock_story(profile), language)
        book = _Book(tmp_path / f"{language}{age}.pdf", profile, story, False)
        images = make_images(tmp_path / "img")
        for i in range(1, PAGES + 1):
            book.story_page(i, images[f"p{i}"])
        assert book.min_pt_used >= OVERLAY_MIN_PT, f"возраст {age}: шрифт {book.min_pt_used}"


def test_a_long_page_shrinks_toward_eighteen_points_and_still_fits_the_text_zone(tmp_path, profile):
    text = ("Это длинная страница истории, где много слов и событий. " * 14)[:700].strip()
    book = _Book(tmp_path / "long.pdf", profile, story_with_text(profile, text), False)
    book.story_page(1, make_images(tmp_path / "img")["p1"])
    assert OVERLAY_MIN_PT <= book.min_pt_used < OVERLAY_MAX_PT


def test_the_longest_allowed_page_is_still_readable_in_an_emergency_size(tmp_path, profile):
    text = ("Это очень длинная страница истории, где много слов и событий. " * 30)[:1200].strip()
    book = _Book(tmp_path / "huge.pdf", profile, story_with_text(profile, text), False)
    book.story_page(1, make_images(tmp_path / "img")["p1"])
    book.c.save()
    assert HARD_MIN_PT <= book.min_pt_used < OVERLAY_MIN_PT                  # не влезло в 18 pt: аварийное уменьшение
    reader = PdfReader(str(tmp_path / "huge.pdf"))
    body = [c for c in text_chunks(reader.pages[0]) if c[2] > 25]
    top = max(y + size / PT for _, _, y, size in body)
    assert top < 210 - 15 and min(y for _, _, y, _ in body) > 30            # ничего не вылезло за зону текста


# ----------------------------------------------------------------------- самые длинные страницы радостных книг (36 слов, 250 знаков)
WIDE_WORDS = {
    "ru": ("Шумиха", "Жемчуг", "Щенята", "Юмористы", "Мышонок", "Шоколад", "Жужжащие", "Мамонты"),
    "ky": ("Үйдөгү", "Өңдөрү", "Жылдыздар", "Мышыктар", "Шамалдуу", "Чөмүчтөр", "Өмүрлөр", "Шүүдүрөк"),
}


def longest_page(language: str, age: int, *, tolerated: bool, lines: bool) -> str:
    """Самая длинная страница по лимитам возраста: максимум слов из самых широких букв, уложенный в максимум знаков.
    tolerated=True берёт допуск валидатора (слов +10%, знаков +10%). lines=True — несколько строк (реплики с новой строки)."""
    from app.writer import page_limits
    lim = page_limits(age, language)
    n_words, n_chars = (lim.hard_max_words, lim.hard_max_chars) if tolerated else (lim.max_words, lim.max_chars)
    pool = WIDE_WORDS[language]
    words = [pool[i % len(pool)] for i in range(n_words)]
    while len(" ".join(words)) > n_chars:                      # слишком длинно — укорачиваем самое длинное слово
        longest = max(range(len(words)), key=lambda j: len(words[j]))
        words[longest] = words[longest][:-1]
    if not lines:
        return " ".join(words)
    step = max(1, len(words) // 4)
    return "\n".join(" ".join(words[i:i + step]) for i in range(0, len(words), step))


@pytest.mark.parametrize("language", ["ru", "ky"])
@pytest.mark.parametrize("age", [4, 6, 8])
@pytest.mark.parametrize("tolerated", [False, True])
@pytest.mark.parametrize("lines", [False, True])
def test_the_longest_allowed_page_never_overflows_the_text_zone_and_stays_above_eighteen_points(
        tmp_path, language, age, tolerated, lines):
    from app.pdfbook import FADE_BOX_W, TEXT_BOX_W, TEXT_ZONE_BOTTOM, TEXT_ZONE_TOP
    from app.writer import page_limits
    profile = Profile.from_payload({**SAMPLE, "age": age, "language": language})
    text = longest_page(language, age, tolerated=tolerated, lines=lines)
    lim = page_limits(age, language)
    assert len(text.split()) == (lim.hard_max_words if tolerated else lim.max_words)         # проверяем, что текст и правда самый длинный
    assert len(" ".join(text.split())) <= (lim.hard_max_chars if tolerated else lim.max_chars)
    assert len(" ".join(text.split())) >= 0.9 * (lim.hard_max_chars if tolerated else lim.max_chars) - 12
    story = story_with_text(profile, text, language)
    book = _Book(tmp_path / "x.pdf", profile, story, False)
    zone = TEXT_ZONE_TOP - TEXT_ZONE_BOTTOM
    for style_name in (overlay.STYLE_PLAIN_LIGHT, overlay.STYLE_FADE):
        style = overlay.style_for(style_name)
        width = FADE_BOX_W if style.underlay == "fade" else TEXT_BOX_W
        _, size, height = book.story_fit(text, width, style)
        assert OVERLAY_MIN_PT <= size <= OVERLAY_MAX_PT and height <= zone, (style_name, size, height / mm, zone / mm)


@pytest.mark.parametrize("language", ["ru", "ky"])
@pytest.mark.parametrize("age", [4, 6, 8])
def test_a_book_of_the_longest_allowed_pages_keeps_every_text_inside_its_half_and_above_the_page_badge(tmp_path, language, age):
    profile = Profile.from_payload({**SAMPLE, "age": age, "language": language})
    data = build_mock_story(profile)
    for i, page in enumerate(data["pages"]):
        page["text"] = longest_page(language, age, tolerated=True, lines=bool(i % 2))
    story = validate_story(data, language)
    report: dict = {}
    pdf = build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "long.pdf", report=report)
    assert report["min_text_pt"] >= OVERLAY_MIN_PT
    reader = PdfReader(str(pdf))
    for number in range(1, PAGES + 1):
        page = reader.pages[number]                                        # 0 — обложка
        body = [c for c in text_chunks(page) if c[2] > 25]                  # без кружка с номером страницы
        assert body, number
        half = (210.0, 420.0) if text_side(number) == "right" else (0.0, 210.0)
        top = max(y + size / PT for _, _, y, size in body)
        assert top < 210 - 26 + 2 and min(y for _, _, y, _ in body) > 36 - 6, (number, top)
        assert all(half[0] + 25 <= x <= half[1] - 25 for _, x, _, _ in body), (number, [round(c[1]) for c in body][:4])


def test_a_page_of_narration_with_exclamation_marks_has_no_red_text(tmp_path, profile):
    reader = accent_book(tmp_path, profile, "Лиса прыгнула высоко над огромным пушистым облаком! Панда засмеялась и хлопнула в ладоши! "
                                           "Ёжик свернулся в колючий шарик и покатился вниз по холму!")
    colors = fill_colors(reader, reader.pages[0])
    assert rgb01(overlay.ACCENT) not in colors and rgb01(overlay.INK) in colors


def test_only_the_speech_and_short_exclamations_are_red_in_the_pdf(tmp_path, profile):
    reader = accent_book(tmp_path, profile, "Из-под лопуха выкатился колючий клубок. — Я Пуф, я помогу! — сказал он. Бам!")
    colors = fill_colors(reader, reader.pages[0])
    assert rgb01(overlay.ACCENT) in colors and rgb01(overlay.INK) in colors


# ----------------------------------------------------------------------- страница посвящения не пустая
def cover_book(tmp_path, dedication: str):
    profile = Profile.from_payload({**SAMPLE, "dedication": dedication})
    story = validate_story(build_mock_story(profile), "ru")
    book = _Book(tmp_path / "c.pdf", profile, story, False)
    book.cover(make_images(tmp_path / "img")["cover"])
    book.c.save()
    return book, PdfReader(str(tmp_path / "c.pdf"))


def left_text_bottom_mm(reader) -> float:
    """Нижний край текста на левой странице обложки (мм от низа)."""
    return min(y for _, x, y, _ in text_chunks(reader.pages[0]) if x < 210 and y > 25)


def test_the_dedication_page_has_clouds_and_stars_so_it_does_not_look_unfinished(tmp_path):
    book, reader = cover_book(tmp_path, "Для сына")
    kinds = [d[0] for d in book.decor]
    assert kinds.count("cloud") == 2 and kinds.count("star") == 4
    text_bottom = left_text_bottom_mm(reader)
    for kind, x, y, size in book.decor:
        assert 10 * mm < x - size < x + size < 200 * mm and 8 * mm < y - size and y + size < 70 * mm, (kind, x / mm, y / mm)
        assert y / mm + (size / mm if kind == "star" else size / mm * 0.3) < text_bottom - 6        # не заходит на текст
    assert "Для Айдара" in reader.pages[0].extract_text()


def test_the_longest_dedication_still_leaves_the_decoration_clear_of_the_text(tmp_path):
    book, reader = cover_book(tmp_path, "Нашему любимому сыну и внуку, который каждый вечер просит ещё одну сказку, "
                                        "самому доброму и весёлому на свете")
    text_bottom = left_text_bottom_mm(reader)
    assert book.decor and all(y / mm + size / mm < text_bottom - 4 for _, _, y, size in book.decor)


def test_when_the_text_comes_close_to_the_bottom_the_decoration_shrinks_to_small_stars_or_disappears(tmp_path):
    book, _ = cover_book(tmp_path, "Для сына")
    book.decor.clear()
    book.dedication_decor(0.0, 50 * mm)
    assert [d[0] for d in book.decor] == ["star", "star", "star"] and all(d[2] < 30 * mm for d in book.decor)
    book.decor.clear()
    book.dedication_decor(0.0, 30 * mm)
    assert book.decor == []


def test_the_dedication_decoration_does_not_change_the_page_count_or_other_spreads(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    pdf = build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "d.pdf")
    assert len(PdfReader(str(pdf)).pages) == SPREADS
