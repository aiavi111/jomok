"""Картинка-заглушка (Pillow): яркий мультяшный пейзаж с подписью и кратким описанием сцены.

Используется mock-провайдером и как запасная иллюстрация, если страница не нарисовалась.
Размер любой: обложка квадратная (1024×1024), страницы истории широкие (2048×1024, 2:1). У широкой заглушки
«герои» (юрта, горы, солнце, подпись) стоят на одной половине, а на другой, спокойной, только небо и мягкий луг:
там в PDF ляжет текст. Небо бывает дневным (светлым), вечерним (тёмным) и «пёстрым» (много мелких пятен):
по ним видно, как текст подстраивается под фон.
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
FINAL = 1024          # высота (и ширина квадрата) по умолчанию
SQUARE = (FINAL, FINAL)


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def _hsv(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0, min(1, s)), max(0, min(1, v)))
    return int(r * 255), int(g * 255), int(b * 255)


def sky_kind(seed_text: str) -> str:
    """Какое небо у широкой заглушки с таким зерном: day | dusk | busy (по хэшу, стабильно)."""
    pick = int(hashlib.sha1(("sky:" + seed_text).encode()).hexdigest()[:6], 16) % 6
    return "dusk" if pick == 0 else "busy" if pick == 1 else "day"


def draw_placeholder(label: str, description: str, seed_text: str = "", *, caption: str | None = None,
                     size: tuple[int, int] = SQUARE, calm_side: str | None = None,
                     sky: str | None = None) -> bytes:
    """JPEG ровно size=(ширина, высота). label — «Обложка» / «Страница 3», description — описание сцены.

    calm_side ('left' | 'right') — половина широкой картинки, которую оставляем спокойной (под текст).
    sky ('day' | 'dusk' | 'busy') принудительно задаёт небо широкой картинки (иначе по зерну)."""
    fw, fh = size
    wide = fw >= fh * 1.5
    rnd = random.Random(int(hashlib.sha1((seed_text or description or label).encode()).hexdigest()[:12], 16))
    scale = 2 if fw * fh <= FINAL * FINAL else 1          # рисуем крупнее и уменьшаем: края гладкие
    w, h = fw * scale, fh * scale
    kind = (sky or sky_kind(seed_text or description or label)) if wide else "day"
    if wide and calm_side not in ("left", "right"):
        calm_side = None
    act_x0, act_x1 = (0, w)                                # где стоит «действие»
    if wide and calm_side == "right":
        act_x1 = w // 2
    elif wide and calm_side == "left":
        act_x0 = w // 2
    base_hue = rnd.random()
    img = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(img)

    # небо: вертикальный градиент
    if kind == "dusk":
        top, bottom = _hsv(0.64, 0.75, 0.16), _hsv(0.74 + base_hue * 0.06, 0.5, 0.36)
    else:
        top, bottom = _hsv(base_hue, 0.55, 1.0), _hsv(base_hue + 0.08, 0.18, 1.0)
    for y in range(h):
        t = y / h
        px.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))

    # солнце (луна) и облака — на стороне действия
    ax0, ax1 = act_x0, act_x1
    sr = int(h * .075)
    sx = rnd.randint(ax0 + int((ax1 - ax0) * .55), ax0 + int((ax1 - ax0) * .85))
    sy = rnd.randint(int(h * .12), int(h * .26))
    px.ellipse([sx - sr * 2, sy - sr * 2, sx + sr * 2, sy + sr * 2],
               fill=_hsv(base_hue + 0.12, 0.10, 0.5 if kind == "dusk" else 1.0))
    px.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=_hsv(0.12, 0.2 if kind == "dusk" else 0.35, 1.0))
    for _ in range(3):
        cx, cy = rnd.randint(ax0, ax1), rnd.randint(int(h * .08), int(h * .3))
        cw = rnd.randint(int(h * .12), int(h * .22))
        for dx, dy, k in ((0, 0, 1), (-.55, .1, .7), (.6, .12, .75)):
            r = int(cw * .35 * k)
            px.ellipse([cx + dx * cw - r, cy + dy * cw - r, cx + dx * cw + r, cy + dy * cw + r],
                       fill=(120, 110, 160) if kind == "dusk" else (255, 255, 255))

    # три слоя гор: острые вершины только на стороне действия, на спокойной стороне — ровная линия
    horizon = int(h * .62)
    for layer in range(3):
        hue = base_hue + 0.02 * layer
        color = _hsv(hue + .55, 0.45 + .12 * layer, (0.42 if kind == "dusk" else 0.92) - .12 * layer)
        base_y = horizon + layer * int(h * .05)
        pts = [(0, h), (0, base_y - int(h * .03))]
        x = 0
        while x <= w:
            if ax0 <= x <= ax1:
                pts.append((x, base_y - rnd.randint(int(h * .04), int(h * (.20 - .04 * layer)))))
            else:
                pts.append((x, base_y - int(h * .03)))
            x += rnd.randint(int(h * .10), int(h * .20))
        pts += [(w, base_y - int(h * .03)), (w, h)]
        px.polygon(pts, fill=color)

    # луг
    px.rectangle([0, int(h * .78), w, h], fill=_hsv(0.28 + rnd.random() * .05, 0.55, 0.38 if kind == "dusk" else 0.88))
    # юрта: купол, стены, дверь — на стороне действия
    yw = int(h * .17)
    yx, yy = rnd.randint(ax0 + int((ax1 - ax0) * .1), max(ax0 + int((ax1 - ax0) * .1) + 1, ax1 - yw - int((ax1 - ax0) * .1))), int(h * .74)
    px.rectangle([yx, yy, yx + yw, yy + int(yw * .5)], fill=(250, 244, 230))
    px.pieslice([yx - 6, yy - int(yw * .5), yx + yw + 6, yy + int(yw * .5)], 180, 360, fill=(246, 238, 220))
    px.rectangle([yx + int(yw * .4), yy + int(yw * .12), yx + int(yw * .6), yy + int(yw * .5)], fill=_hsv(.04, .55, .62))
    px.line([(yx, yy + int(yw * .18)), (yx + yw, yy + int(yw * .18))], fill=_hsv(.04, .5, .7), width=8)

    # «пёстрое» небо: на спокойной стороне много мелких разноцветных пятен
    if kind == "busy" and wide:
        cx0, cx1 = (w // 2, w) if calm_side == "right" else (0, w // 2) if calm_side == "left" else (0, w)
        for _ in range(900):
            r = rnd.randint(int(h * .006), int(h * .02))
            x, y = rnd.randint(cx0, cx1), rnd.randint(0, int(h * .95))
            px.ellipse([x - r, y - r, x + r, y + r], fill=_hsv(rnd.random(), rnd.uniform(.5, .95), rnd.uniform(.35, 1.0)))

    if (w, h) != (fw, fh):
        img = img.resize((fw, fh), Image.LANCZOS)
    draw = ImageDraw.Draw(img, "RGBA")

    # подпись: полупрозрачная плашка внизу (у широкой — на стороне действия, чтобы не мешать тексту)
    if wide and calm_side:
        bx0, bx1 = (40, fw // 2 - 40) if calm_side == "right" else (fw // 2 + 40, fw - 40)
    elif wide:
        bx0, bx1 = fw // 2 - 330, fw // 2 + 330
    else:
        bx0, bx1 = 40, fw - 40
    band_top = 640 if not wide else fh - 330
    draw.rounded_rectangle([bx0, band_top, bx1, fh - 40], radius=36, fill=(40, 30, 22, 170))
    draw.text((bx0 + 32, band_top + 24), label, font=_font("DejaVuSerif-Bold.ttf", 46), fill=(255, 244, 220))
    small = _font("DejaVuSerif.ttf", 27)
    short = description.strip().replace("\n", " ")
    short = short if len(short) <= 190 else short[:187].rsplit(" ", 1)[0] + "…"
    per_line = max(16, int((bx1 - bx0 - 64) / 15.4))          # знаков в строке при этом кегле
    y = band_top + 92
    for line in textwrap.wrap(short, width=per_line)[:5 if not wide else 6]:
        draw.text((bx0 + 32, y), line, font=small, fill=(255, 250, 238, 235))
        y += 38

    # метка в углу (у широкой — в дальнем от текста верхнем углу)
    tag = caption or "ЗАГЛУШКА"
    tag_font = _font("DejaVuSerif-Bold.ttf", 26)
    tw = draw.textlength(tag, font=tag_font)
    tx1 = fw - 36 if not (wide and calm_side == "right") else 36 + int(tw) + 40
    draw.rounded_rectangle([tx1 - tw - 40, 36, tx1, 84], radius=20, fill=(255, 255, 255, 190))
    draw.text((tx1 - tw - 20, 44), tag, font=tag_font, fill=(90, 70, 50))

    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()
