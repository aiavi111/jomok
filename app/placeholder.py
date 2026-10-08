"""Картинка-заглушка (Pillow): акварельный пейзаж с подписью и кратким описанием сцены.

Используется mock-провайдером и как запасная иллюстрация, если страница не нарисовалась.
"""
from __future__ import annotations

import colorsys
import hashlib
import io
import random
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "fonts"
SCALE = 2     # рисуем в 2048 и уменьшаем: края получаются гладкими
FINAL = 1024


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def _hsv(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0, min(1, s)), max(0, min(1, v)))
    return int(r * 255), int(g * 255), int(b * 255)


def draw_placeholder(label: str, description: str, seed_text: str = "", *, caption: str | None = None) -> bytes:
    """Возвращает JPEG 1024×1024. label — «Обложка» / «Страница 3», description — описание сцены."""
    rnd = random.Random(int(hashlib.sha1((seed_text or description or label).encode()).hexdigest()[:12], 16))
    size = FINAL * SCALE
    base_hue = rnd.random()
    img = Image.new("RGB", (size, size))
    px = ImageDraw.Draw(img)

    # небо: вертикальный градиент
    top, bottom = _hsv(base_hue, 0.30, 0.98), _hsv(base_hue + 0.08, 0.12, 1.0)
    for y in range(size):
        t = y / size
        px.line([(0, y), (size, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))

    # солнце и облака
    sx, sy, sr = rnd.randint(int(size * .55), int(size * .85)), rnd.randint(int(size * .12), int(size * .26)), int(size * .075)
    px.ellipse([sx - sr * 2, sy - sr * 2, sx + sr * 2, sy + sr * 2], fill=_hsv(base_hue + 0.12, 0.10, 1.0))
    px.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=_hsv(0.12, 0.35, 1.0))
    for _ in range(3):
        cx, cy = rnd.randint(0, size), rnd.randint(int(size * .08), int(size * .3))
        w = rnd.randint(int(size * .12), int(size * .22))
        for dx, dy, k in ((0, 0, 1), (-.55, .1, .7), (.6, .12, .75)):
            r = int(w * .35 * k)
            px.ellipse([cx + dx * w - r, cy + dy * w - r, cx + dx * w + r, cy + dy * w + r], fill=(255, 255, 255))

    # три слоя гор
    horizon = int(size * .62)
    for layer in range(3):
        hue = base_hue + 0.02 * layer
        color = _hsv(hue + .55, 0.30 + .10 * layer, 0.82 - .12 * layer)
        base_y = horizon + layer * int(size * .05)
        pts = [(0, size)]
        x = 0
        while x <= size:
            pts.append((x, base_y - rnd.randint(int(size * .04), int(size * (.20 - .04 * layer)))))
            x += rnd.randint(int(size * .10), int(size * .20))
        pts += [(size, base_y - int(size * .05)), (size, size)]
        px.polygon(pts, fill=color)

    # луг
    px.rectangle([0, int(size * .78), size, size], fill=_hsv(0.28 + rnd.random() * .05, 0.35, 0.80))
    # юрта: купол, стены, дверь
    yx, yy, yw = rnd.randint(int(size * .12), int(size * .6)), int(size * .74), int(size * .17)
    px.rectangle([yx, yy, yx + yw, yy + int(yw * .5)], fill=(250, 244, 230))
    px.pieslice([yx - 6, yy - int(yw * .5), yx + yw + 6, yy + int(yw * .5)], 180, 360, fill=(246, 238, 220))
    px.rectangle([yx + int(yw * .4), yy + int(yw * .12), yx + int(yw * .6), yy + int(yw * .5)], fill=_hsv(.04, .55, .62))
    px.line([(yx, yy + int(yw * .18)), (yx + yw, yy + int(yw * .18))], fill=_hsv(.04, .5, .7), width=8)

    img = img.resize((FINAL, FINAL), Image.LANCZOS)
    draw = ImageDraw.Draw(img, "RGBA")

    # подпись: полупрозрачная плашка снизу
    band_top = 640
    draw.rounded_rectangle([40, band_top, FINAL - 40, FINAL - 40], radius=36, fill=(40, 30, 22, 170))
    draw.text((72, band_top + 24), label, font=_font("DejaVuSerif-Bold.ttf", 46), fill=(255, 244, 220))
    small = _font("DejaVuSerif.ttf", 27)
    short = description.strip().replace("\n", " ")
    short = short if len(short) <= 190 else short[:187].rsplit(" ", 1)[0] + "…"
    lines = textwrap.wrap(short, width=44)[:5]
    y = band_top + 92
    for line in lines:
        draw.text((72, y), line, font=small, fill=(255, 250, 238, 235))
        y += 38

    # метка в углу
    tag = caption or "ЗАГЛУШКА"
    tag_font = _font("DejaVuSerif-Bold.ttf", 26)
    tw = draw.textlength(tag, font=tag_font)
    draw.rounded_rectangle([FINAL - tw - 76, 36, FINAL - 36, 84], radius=20, fill=(255, 255, 255, 190))
    draw.text((FINAL - tw - 56, 44), tag, font=tag_font, fill=(90, 70, 50))

    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()
