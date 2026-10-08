"""PDF: страницы, буквы ү ө ң Ү Ө Ң, подбор размера текста, пометка о заглушках."""
from pathlib import Path

from pypdf import PdfReader
from reportlab.pdfbase.ttfonts import TTFont

from app.pdfbook import FONTS_DIR, TEXT_MAX_PT, TEXT_MIN_PT, build_pdf, fit_paragraph, F_REG
from app.pdfbook import TA_LEFT
from app.placeholder import draw_placeholder
from app.profile import Profile
from app.providers.text_mock import build_mock_story
from app.story import validate_story

from .conftest import SAMPLE

KY_LETTERS = "үөңҮӨҢ"


def make_images(folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    images = {}
    for name in ["cover"] + [f"p{i}" for i in range(1, 9)]:
        path = folder / f"{name}.jpg"
        path.write_bytes(draw_placeholder(name, "test scene", name))
        images[name] = path
    return images


def text_of(pdf: Path) -> list[str]:
    return [page.extract_text() for page in PdfReader(str(pdf)).pages]


def test_all_kyrgyz_letters_exist_in_every_font_file():
    for font_file in FONTS_DIR.glob("DejaVuSerif*.ttf"):
        cmap = TTFont("probe-" + font_file.stem, str(font_file)).face.charToGlyph
        for letter in KY_LETTERS:
            assert ord(letter) in cmap, f"{letter} нет в {font_file.name}"


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
    assert "Ү Ө Ң ү ө ң" in pages[1]                      # страница посвящения
    assert "Аягы" in pages[-1]                             # финал на кыргызском
    assert "үчүн" in pages[0]                              # подпись на обложке


def test_book_has_cover_dedication_eight_pages_and_finale(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    pdf = build_pdf(story, profile, make_images(tmp_path / "img"), tmp_path / "ru.pdf")
    reader = PdfReader(str(pdf))
    assert len(reader.pages) == 11
    for page in reader.pages:
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        assert abs(width / 72 * 25.4 - 210) < 0.5 and abs(height / 72 * 25.4 - 265) < 0.5
    pages = text_of(pdf)
    assert "Сказка для Айдара" in pages[0] and "Для Айдара" in pages[1]
    assert pages[2].strip().endswith("1 —") and "Конец" in pages[10]
    assert "Эта сказка создана специально для Айдара" in pages[10]
    assert reader.metadata.title == story.title


def test_mock_caption_only_when_mock(tmp_path, profile):
    story = validate_story(build_mock_story(profile), "ru")
    images = make_images(tmp_path / "img")
    with_note = text_of(build_pdf(story, profile, images, tmp_path / "a.pdf", mock=True))
    without = text_of(build_pdf(story, profile, images, tmp_path / "b.pdf", mock=False))
    assert "Тестовая сборка: заглушки" in with_note[1] and "Тестовая сборка: заглушки" in with_note[10]
    assert not any("Тестовая сборка" in p for p in without)


def test_long_text_shrinks_but_not_below_eleven_points_when_it_fits():
    short, size_short, _ = fit_paragraph("Короткий текст.", F_REG, 453, 176, max_pt=TEXT_MAX_PT, min_pt=TEXT_MIN_PT, align=TA_LEFT)
    assert size_short == TEXT_MAX_PT
    long_text = " ".join(["Это довольно длинное предложение сказки про героя и его приключения."] * 9)
    _, size_long, height = fit_paragraph(long_text, F_REG, 453, 176, max_pt=TEXT_MAX_PT, min_pt=TEXT_MIN_PT, align=TA_LEFT)
    assert TEXT_MIN_PT <= size_long < TEXT_MAX_PT and height <= 176


def test_every_age_fits_the_text_area_at_readable_size(tmp_path):
    for age in range(3, 10):
        profile = Profile.from_payload({**SAMPLE, "age": age})
        story = validate_story(build_mock_story(profile), "ru")
        from app.pdfbook import _Book
        book = _Book(tmp_path / f"{age}.pdf", profile, story, False)
        images = make_images(tmp_path / "img")
        for i in range(1, 9):
            book.story_page(i, images[f"p{i}"])
        assert book.min_pt_used >= TEXT_MIN_PT, f"возраст {age}: шрифт {book.min_pt_used}"
