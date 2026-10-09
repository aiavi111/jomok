"""PDF-фотокнига: PAGES + 2 разворотов 420×210 мм, шрифты Nunito и Comfortaa, буквы ү ө ң, подбор размера текста,
чередование сторон картинки, пометка о заглушках."""
from pathlib import Path

import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont

from app.pdfbook import (FONTS_DIR, HARD_MIN_PT, LEADING, SPREADS, SQ, TEXT_MAX_PT, TEXT_MIN_PT, TA_LEFT, F_REG,
                         _Book, build_pdf, fit_paragraph)
from app.placeholder import draw_placeholder
from app.profile import Profile
from app.providers.text_mock import build_mock_story
from app.story import PAGES, validate_story

from .conftest import SAMPLE

KY_LETTERS = "үөңҮӨҢ"
PT = 72 / 25.4                                  # пунктов в миллиметре


def make_images(folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    images = {}
    for name in ["cover"] + [f"p{i}" for i in range(1, PAGES + 1)]:
        path = folder / f"{name}.jpg"
        path.write_bytes(draw_placeholder(name, "test scene", name))
        images[name] = path
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


def picture_x_mm(reader: PdfReader, page) -> list[float]:
    """x (мм) левого края каждой картинки-квадрата 210×210 мм на развороте."""
    xs = []
    for operands, op in ContentStream(page.get_contents(), reader).operations:
        if op == b"cm":
            a, b, c, d, e, _ = (float(v) for v in operands)
            if abs(a - SQ) < 0.5 and abs(d - SQ) < 0.5 and b == 0 and c == 0:
                xs.append(e / PT)
    return xs


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
    story = validate_story(data, "ky")
    pdf = build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ky.pdf", mock=False)
    pages = text_of(pdf)
    joined = "\n".join(pages)
    for letter in KY_LETTERS:
        assert letter in joined, f"буква {letter} не нашлась в тексте PDF"
    assert "Ү Ө Ң ү ө ң" in pages[0]                       # посвящение на левой странице обложки
    assert "Үмүт үчүн" in pages[0] and "Үмүт үчүн жомок" in pages[0]
    assert "Аягы" in pages[-1]                             # финал на кыргызском
    assert "Ү Ө Ң үөң" in pages[-1]                        # мораль


# ----------------------------------------------------------------------- структура книги
def test_book_is_square_spreads_of_420_by_210_mm(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    pdf = build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ru.pdf")
    reader = PdfReader(str(pdf))
    assert SPREADS == PAGES + 2 and len(reader.pages) == SPREADS     # обложка, страницы сказки, финал
    for page in reader.pages:
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        assert abs(width / PT - 420) < 0.5 and abs(height / PT - 210) < 0.5
    assert reader.metadata.title == story.title


def test_spread_contents_cover_story_pages_and_finale(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    pdf = build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ru.pdf")
    pages = text_of(pdf)
    cover = pages[0]
    assert "Для Айдара" in cover and "Для сына" in cover                      # слева: посвящение
    assert story.title.split()[0] in cover and "Сказка для Айдара" in cover  # справа: название и подпись
    for number in range(1, PAGES + 1):
        spread = pages[number]
        first_words = " ".join(story.pages[number - 1].text.split()[:3])
        assert first_words in " ".join(spread.split()), f"нет текста страницы {number}"
        assert spread.strip().endswith(str(number))                          # номер внизу бумажной страницы
    finale = " ".join(pages[-1].split())
    assert "Конец" in finale and story.moral in finale and "Эта сказка создана специально для Айдара" in finale
    assert " ".join(story.wish.split()[:4]) in finale


def test_pictures_alternate_sides_odd_pages_left_even_pages_right(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    pdf = build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ru.pdf")
    reader = PdfReader(str(pdf))
    assert picture_x_mm(reader, reader.pages[0]) == pytest.approx([210], abs=0.5)      # обложка справа
    for number in range(1, PAGES + 1):
        xs = picture_x_mm(reader, reader.pages[number])
        assert len(xs) == 1, f"страница {number}: картинок {len(xs)}"
        assert xs[0] == pytest.approx(0 if number % 2 == 1 else 210, abs=0.5), f"страница {number}"
    assert picture_x_mm(reader, reader.pages[-1]) == []                                # в финале картинок нет


def test_picture_sides_are_recorded_while_building(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    book = _Book(tmp_path / "b.pdf", profile, story, False)
    images = make_images(tmp_path / "img")
    for i in range(1, PAGES + 1):
        book.story_page(i, images[f"p{i}"])
    assert book.picture_sides == ["left" if i % 2 else "right" for i in range(1, PAGES + 1)]    # нечётные слева, чётные справа


def test_text_sits_on_the_paper_square_with_generous_margins_and_is_vertically_centred(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    reader = PdfReader(str(build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ru.pdf")))
    for number in range(1, PAGES + 1):
        paper_x = 210 if number % 2 == 1 else 0
        body = [c for c in text_chunks(reader.pages[number]) if c[3] >= TEXT_MIN_PT and c[2] > 30]
        assert body, f"страница {number}: нет текста"
        assert all(paper_x + 20 <= x <= paper_x + 210 - 20 for _, x, _, _ in body), f"страница {number}: поля"
        top = max(y + size / PT for _, _, y, size in body)
        bottom = min(y for _, _, y, _ in body)
        assert abs((top + bottom) / 2 - 110) < 9, f"страница {number}: текст не по центру ({top:.0f}..{bottom:.0f} мм)"
        assert bottom > 34 - 6                                               # ниже начинается номер страницы


def test_mock_caption_only_when_mock(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    images = make_images(tmp_path / "img")
    with_note = text_of(build_pdf(story, profile, images, tmp_path / "a.pdf", mock=True))
    without = text_of(build_pdf(story, profile, images, tmp_path / "b.pdf", mock=False))
    assert "Тестовая сборка: заглушки" in with_note[0] and "Тестовая сборка: заглушки" in with_note[-1]
    assert not any("Тестовая сборка" in p for p in without)


# ----------------------------------------------------------------------- размер текста
def test_text_size_range_is_twenty_down_to_thirteen_with_line_height_one_and_a_bit():
    assert (TEXT_MAX_PT, TEXT_MIN_PT) == (20.0, 13.0) and 1.3 <= LEADING <= 1.5 and HARD_MIN_PT < TEXT_MIN_PT


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


@pytest.mark.parametrize("language", ["ru", "ky"])
def test_every_age_fits_the_text_area_at_readable_size(tmp_path, language):
    for age in range(3, 10):
        profile = Profile.from_payload({**SAMPLE, "age": age, "language": language})
        story = validate_story(build_mock_story(profile), language)
        book = _Book(tmp_path / f"{language}{age}.pdf", profile, story, False)
        images = make_images(tmp_path / "img")
        for i in range(1, PAGES + 1):
            book.story_page(i, images[f"p{i}"])
        assert book.min_pt_used >= TEXT_MIN_PT, f"возраст {age}: шрифт {book.min_pt_used}"


def test_longest_allowed_page_still_fits_above_the_minimum(tmp_path, profile):
    data = build_mock_story(profile)
    data["pages"][0]["text"] = ("Это очень длинная страница сказки, где много слов и событий. " * 30)[:1200].strip()
    story = validate_story(data, "ru")
    book = _Book(tmp_path / "long.pdf", profile, story, False)
    book.story_page(1, make_images(tmp_path / "img")["p1"])
    assert TEXT_MIN_PT <= book.min_pt_used < TEXT_MAX_PT
