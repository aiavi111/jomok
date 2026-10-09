"""Работа с картинками: приведение к нужному размеру (обложка 1024×1024, страница 2048×1024), фото ребёнка, цвета."""
from __future__ import annotations

import colorsys
import io

from PIL import Image, ImageOps

from .errors import ValidationError

SIZE = 1024
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_PHOTO_PIXELS = 40_000_000


def normalize_image(raw: bytes, size: tuple[int, int] | int = (SIZE, SIZE), quality: int = 90) -> bytes:
    """Любую картинку от провайдера → JPEG ровно size=(ширина, высота).

    Обрезка по центру до нужного соотношения сторон (cover-crop), потом масштабирование. Так квадрат от провайдера,
    который не умеет другие размеры (Cloudflare), превращается в широкую страницу 2:1, а широкая картинка
    для обложки обрезается до квадрата. size=1024 (число) — по-старому квадрат 1024×1024."""
    width, height = (size, size) if isinstance(size, int) else (int(size[0]), int(size[1]))
    with Image.open(io.BytesIO(raw)) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            background = Image.new("RGB", im.size, (251, 246, 234))
            background.paste(im, mask=im.getchannel("A"))
            im = background
        else:
            im = im.convert("RGB")
        im = cover_crop(im, width / height)
        if im.size != (width, height):
            im = im.resize((width, height), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=quality, optimize=True)
        return out.getvalue()


def cover_crop(im: Image.Image, aspect: float) -> Image.Image:
    """Обрезает по центру до соотношения сторон aspect (ширина / высота), ничего не растягивая."""
    w, h = im.size
    if abs(w / h - aspect) < 1e-3:
        return im
    if w / h > aspect:                       # слишком широкая: срезаем по бокам
        new_w = max(1, round(h * aspect))
        left = (w - new_w) // 2
        return im.crop((left, 0, left + new_w, h))
    new_h = max(1, round(w / aspect))        # слишком высокая: срезаем сверху и снизу
    top = (h - new_h) // 2
    return im.crop((0, top, w, top + new_h))


def prepare_photo(raw: bytes, max_side: int = 1024) -> bytes:
    """Фото ребёнка: проверяем, что это картинка, убираем метаданные (EXIF, геометки), уменьшаем."""
    if len(raw) > MAX_PHOTO_BYTES:
        raise ValidationError("Фото слишком большое. Выберите снимок поменьше (до 8 МБ).", field="photo")
    old_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PHOTO_PIXELS
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((max_side, max_side), Image.LANCZOS)
            out = io.BytesIO()
            im.save(out, "JPEG", quality=88)   # без exif=…: метаданные не сохраняются
            return out.getvalue()
    except ValidationError:
        raise
    except Exception:
        raise ValidationError("Не получилось открыть фото. Выберите снимок в формате JPEG или PNG.", field="photo")
    finally:
        Image.MAX_IMAGE_PIXELS = old_limit


def band_color(image_bytes_or_path) -> tuple[float, float, float]:
    """Тёмный оттенок среднего цвета картинки (0..1 для RGB): цвет плашки с названием на обложке."""
    with Image.open(image_bytes_or_path if not isinstance(image_bytes_or_path, bytes)
                    else io.BytesIO(image_bytes_or_path)) as im:
        small = im.convert("RGB").resize((1, 1), Image.BOX)
        r, g, b = (c / 255 for c in small.getpixel((0, 0)))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = min(1.0, max(0.35, s * 1.1 + 0.08))
    v = 0.30
    return colorsys.hsv_to_rgb(h, s, v)


def hex_color(rgb: tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in rgb)
