"""Картинки: обрезка по центру до нужного соотношения сторон, заглушки 1:1 и 2:1, размеры и стороны текста."""
import io

import pytest
from PIL import Image, ImageDraw

from app.imaging import cover_crop, normalize_image
from app.layout import (COVER_SIZE, PAGE_SIZE, calm_side, hero_side, parse_size, size_str, text_side)
from app.overlay import measure_region
from app.placeholder import draw_placeholder, sky_kind
from app.providers.image_mock import MockImageProvider


def png(size, color=(200, 100, 50), mark=None) -> bytes:
    im = Image.new("RGB", size, color)
    if mark:
        ImageDraw.Draw(im).rectangle(mark, fill=(0, 0, 255))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


# ----------------------------------------------------------------------------- размеры и стороны
def test_book_format_constants():
    assert COVER_SIZE == (1024, 1024) and PAGE_SIZE == (2048, 1024)
    assert PAGE_SIZE[0] % 16 == 0 and PAGE_SIZE[1] % 16 == 0 and PAGE_SIZE[0] / PAGE_SIZE[1] <= 3     # условия OpenAI
    assert size_str(PAGE_SIZE) == "2048x1024" and size_str(COVER_SIZE) == "1024x1024"
    assert parse_size("2048x1024") == (2048, 1024) and parse_size("1024X1024") == (1024, 1024)


def test_text_lies_on_the_right_for_odd_pages_and_on_the_left_for_even_pages():
    assert [text_side(i) for i in range(1, 9)] == ["right", "left"] * 4
    assert [calm_side(i) for i in range(1, 9)] == [text_side(i) for i in range(1, 9)]
    assert [hero_side(i) for i in range(1, 9)] == ["left", "right"] * 4


# ----------------------------------------------------------------------------- normalize_image
@pytest.mark.parametrize("source, target", [
    ((1024, 1024), (1024, 1024)),         # обложка из квадрата
    ((1536, 1024), (1024, 1024)),         # широкая картинка → квадрат
    ((1024, 1536), (1024, 1024)),         # высокая → квадрат
    ((1024, 1024), (2048, 1024)),         # Cloudflare: квадрат → широкая страница (обрезка, масштаб)
    ((1536, 1024), (2048, 1024)),         # 3:2 → 2:1
    ((2048, 1024), (2048, 1024)),         # уже готовая
    ((3000, 1000), (2048, 1024)),         # шире 2:1
    ((700, 900), (2048, 1024)),
])
def test_normalize_gives_exactly_the_requested_size_as_jpeg(source, target):
    out = opened(normalize_image(png(source), target, 88))
    assert out.format == "JPEG" and out.size == target


def test_normalize_still_accepts_a_single_number_as_a_square():
    assert opened(normalize_image(png((800, 600)), 512)).size == (512, 512)
    assert opened(normalize_image(png((800, 600)))).size == (1024, 1024)            # по умолчанию квадрат 1024


def test_cover_crop_takes_the_centre_for_the_requested_aspect_without_stretching():
    # квадрат 1000×1000 с синей полосой по центру (высота 250..750): для 2:1 остаётся именно она
    data = png((1000, 1000), mark=(0, 250, 999, 749))
    out = opened(normalize_image(data, (2048, 1024), 95)).convert("RGB")
    assert out.getpixel((10, 10)) == pytest.approx((0, 0, 255), abs=12)
    assert out.getpixel((2037, 1013)) == pytest.approx((0, 0, 255), abs=12)         # весь кадр синий: срезаны верх и низ
    # широкая 2000×1000 → квадрат: срезаются бока
    wide = png((2000, 1000), mark=(500, 0, 1499, 999))
    sq = opened(normalize_image(wide, (1024, 1024), 95)).convert("RGB")
    assert sq.getpixel((5, 500)) == pytest.approx((0, 0, 255), abs=12) and sq.getpixel((1018, 500)) == pytest.approx((0, 0, 255), abs=12)


def test_cover_crop_helper_keeps_the_aspect_exactly():
    assert cover_crop(Image.new("RGB", (1000, 1000)), 2.0).size == (1000, 500)
    assert cover_crop(Image.new("RGB", (3000, 1000)), 2.0).size == (2000, 1000)
    assert cover_crop(Image.new("RGB", (2000, 1000)), 2.0).size == (2000, 1000)
    assert cover_crop(Image.new("RGB", (1000, 2000)), 1.0).size == (1000, 1000)


def test_transparent_picture_is_flattened_on_paper_not_black():
    rgba = io.BytesIO()
    Image.new("RGBA", (400, 400), (0, 0, 0, 0)).save(rgba, "PNG")
    out = opened(normalize_image(rgba.getvalue(), (2048, 1024))).convert("RGB")
    assert out.getpixel((100, 100)) == pytest.approx((251, 246, 234), abs=6)


# ----------------------------------------------------------------------------- заглушки
def test_placeholders_are_square_for_the_cover_and_two_to_one_for_pages():
    assert opened(draw_placeholder("Обложка", "scene", "a")).size == (1024, 1024)
    assert opened(draw_placeholder("Страница 1", "scene", "a", size=PAGE_SIZE, calm_side="right")).size == (2048, 1024)
    assert opened(draw_placeholder("Страница 2", "scene", "b", size=(1024, 512), calm_side="left")).size == (1024, 512)


def test_wide_placeholder_keeps_the_calm_half_free_of_the_caption_band():
    """На спокойной половине нет подписи и гор: там лежит текст. Подпись и юрта — на стороне героев."""
    for side, calm_box, busy_box in (("right", (240, 40, 390, 170), (30, 100, 180, 200)),
                                      ("left", (30, 40, 180, 170), (240, 100, 390, 200))):
        im = opened(draw_placeholder("Страница 1", "scene", "x", size=PAGE_SIZE, calm_side=side, sky="day"))
        calm = measure_region(im, calm_box, (420, 210))
        assert not calm.busy and calm.light
        band_zone = measure_region(im, busy_box, (420, 210))
        assert band_zone.detail > calm.detail                                    # подпись и горы с той стороны


def test_placeholder_skies_cover_all_three_cases_for_the_text():
    kinds = {sky_kind(f"prompt {i}") for i in range(60)}
    assert kinds == {"day", "dusk", "busy"}
    im = opened(draw_placeholder("Страница 1", "s", "dusk-test", size=PAGE_SIZE, calm_side="right", sky="dusk"))
    assert measure_region(im, (240, 40, 390, 170), (420, 210)).dark
    im = opened(draw_placeholder("Страница 1", "s", "busy-test", size=PAGE_SIZE, calm_side="right", sky="busy"))
    assert measure_region(im, (240, 40, 390, 170), (420, 210)).busy


async def test_mock_provider_draws_the_requested_size_and_knows_the_calm_side_from_the_page_label():
    provider = MockImageProvider()
    wide = opened(await provider.generate("scene", None, "2048x1024", label="Страница 3"))
    square = opened(await provider.generate("scene", None, "1024x1024", label="Обложка"))
    assert wide.size == (2048, 1024) and square.size == (1024, 1024)
    prompt = next(p for p in (f"day{i}" for i in range(80)) if sky_kind(p) == "day")
    calm_right = opened(await provider.generate(prompt, None, "2048x1024", label="Страница 1"))
    calm_left = opened(await provider.generate(prompt, None, "2048x1024", label="Страница 2"))
    assert calm_right.size == calm_left.size == (2048, 1024)
    # у страницы 1 тёмная подпись слева (герои слева, спокойная половина справа), у страницы 2 наоборот
    left_box, right_box = (20, 150, 190, 200), (230, 150, 400, 200)
    for im, loud, quiet in ((calm_right, left_box, right_box), (calm_left, right_box, left_box)):
        assert measure_region(im, loud, (420, 210)).luma < measure_region(im, quiet, (420, 210)).luma - 30
