"""Текст поверх широкой иллюстрации: как подобрать оформление под фон и подготовить мягкие подложки (Pillow).

Текст страницы лежит прямо на картинке, на той половине разворота, которую картинка оставляет спокойной.
Чтобы он читался на любом фоне, под него меряется участок картинки (яркость и «шумность») и выбирается оформление:

  plain-light  спокойный светлый фон: тёмно-коричневый текст и очень мягкое светлое свечение за буквами, без подложки;
  plain-dark   спокойный тёмный фон (только при TEXT_OVERLAY_MODE=plain): кремовый текст с мягкой тёмной тенью;
  fade         картинка плавно «тает» в кремово-белый к краю книги (горизонтальный градиент), текст тёмный сверху;
  plate-cream  мягкая кремовая подложка с размытым краем (только при TEXT_OVERLAY_MODE=plate);
  plate-dark   мягкая тёмная полупрозрачная подложка с кремовым текстом (то же, для тёмного фона).

TEXT_OVERLAY_MODE: auto (по умолчанию: спокойный светлый фон → plain-light, всё остальное → fade),
fade / plate (всегда это), plain (никогда не закрывать картинку: только свечение или тень).

Подложки и свечение рисуются здесь заранее как PNG с прозрачностью; сам текст в PDF остаётся векторным
и выделяется мышью. Модуль не знает про reportlab.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat

MODES = ("auto", "fade", "plate", "plain")
DEFAULT_MODE = "auto"

STYLE_PLAIN_LIGHT = "plain-light"
STYLE_PLAIN_DARK = "plain-dark"
STYLE_FADE = "fade"
STYLE_PLATE_CREAM = "plate-cream"
STYLE_PLATE_DARK = "plate-dark"
STYLES = (STYLE_PLAIN_LIGHT, STYLE_PLAIN_DARK, STYLE_FADE, STYLE_PLATE_CREAM, STYLE_PLATE_DARK)

# --- цвета
CREAM = "#FFFDF6"                    # кремово-белая подложка («белый фон-тень»)
INK = "#3A2E25"                      # тёмно-коричневый текст
INK_ON_DARK = "#FFF6E0"              # кремовый текст на тёмном
ACCENT = "#D4472F"                   # тёплый красно-коралловый: диалоги и восклицания на светлом
ACCENT_ON_DARK = "#FF7A63"           # тот же оттенок ярче, если текст на тёмном
GLOW_RGB = (255, 252, 240)           # цвет светлого свечения
SHADOW_RGB = (24, 15, 10)            # цвет тёмной тени
PLATE_DARK_RGB = (30, 22, 18)

# --- пороги выбора оформления (яркость 0..255 по Rec.601, «деталь» — средний модуль высокочастотной составляющей)
LIGHT_MIN_LUMA = 150.0               # средняя яркость от этого значения — фон светлый
DARK_MAX_LUMA = 90.0                 # до этого значения — тёмный; между ними — «средний», для auto это не светлый
PLAIN_SPLIT_LUMA = 128.0             # в режиме plain: светлее — тёмный текст, темнее — кремовый
BUSY_DETAIL = 5.0                    # средняя «деталь» от этого значения — фон пёстрый
EDGE_STEP = 22                       # пиксель считается краем, если «деталь» больше
BUSY_EDGE_FRACTION = 0.06            # доля краёв от этого значения — фон пёстрый
MIX_LIGHT_LUMA, MIX_DARK_LUMA = 175, 70
MIXED_FRACTION = 0.20                # и светлых, и тёмных пикселей не меньше пятой части — «смешанный» (пёстрый) фон
ANALYSIS_PX_PER_MM = 1.0             # участок уменьшается до ~1 пикселя на миллиметр книги (толщина штриха буквы)
HIGHPASS_RADIUS = 2.0                # радиус размытия для высокочастотной составляющей, пикселей анализа

# --- градиент «fade»
FADE_A_MAX = 0.92                    # непрозрачность у внешнего края книги
FADE_RAMP_FRAC = 0.20                # длина нарастания в долях ширины разворота (от сгиба до почти непрозрачного)

PLATE_ALPHA_CREAM = 0.80
PLATE_ALPHA_DARK = 0.62

# разрешение заранее нарисованных PNG (пикселей на мм книги): подложки и свечение мягкие, им хватает ~100 dpi
FADE_PX_PER_MM = 3.0
PLATE_PX_PER_MM = 4.0
HALO_PX_PER_MM = 4.0


# ----------------------------------------------------------------------------- измерение фона
@dataclass(frozen=True)
class RegionStats:
    luma: float            # средняя яркость 0..255
    detail: float          # средний модуль высокочастотной составляющей (резкость мелких деталей)
    edge_fraction: float   # доля пикселей с сильными краями
    dark_fraction: float
    light_fraction: float

    @property
    def mixed(self) -> bool:
        """И заметная доля светлого, и заметная доля тёмного: ни тёмный, ни светлый текст не будет читаться везде."""
        return min(self.dark_fraction, self.light_fraction) >= MIXED_FRACTION

    @property
    def busy(self) -> bool:
        return self.detail >= BUSY_DETAIL or self.edge_fraction >= BUSY_EDGE_FRACTION or self.mixed

    @property
    def light(self) -> bool:
        return self.luma >= LIGHT_MIN_LUMA

    @property
    def dark(self) -> bool:
        return self.luma <= DARK_MAX_LUMA


def measure_region(im: Image.Image, box_mm: tuple[float, float, float, float],
                   page_mm: tuple[float, float]) -> RegionStats:
    """Статистика участка картинки. box_mm = (x0, y0, x1, y1) в миллиметрах книги, y считается сверху;
    page_mm — размер всей картинки в миллиметрах (420×210 для разворота)."""
    iw, ih = im.size
    x0, y0, x1, y1 = box_mm
    left, right = max(0, int(round(x0 / page_mm[0] * iw))), min(iw, int(round(x1 / page_mm[0] * iw)))
    top, bottom = max(0, int(round(y0 / page_mm[1] * ih))), min(ih, int(round(y1 / page_mm[1] * ih)))
    if right - left < 2 or bottom - top < 2:
        left, top, right, bottom = 0, 0, iw, ih
    region = im.crop((left, top, right, bottom)).convert("L")
    tw = max(8, int(round((x1 - x0) * ANALYSIS_PX_PER_MM)))
    th = max(8, int(round((y1 - y0) * ANALYSIS_PX_PER_MM)))
    small = region.resize((tw, th), Image.BOX)
    mean = ImageStat.Stat(small).mean[0]
    detail_img = ImageChops.difference(small, small.filter(ImageFilter.GaussianBlur(HIGHPASS_RADIUS)))
    detail = ImageStat.Stat(detail_img).mean[0]
    hist = small.histogram()
    total = float(sum(hist)) or 1.0
    edge_fraction = sum(detail_img.histogram()[EDGE_STEP + 1:]) / total
    dark_fraction = sum(hist[:MIX_DARK_LUMA + 1]) / total
    light_fraction = sum(hist[MIX_LIGHT_LUMA:]) / total
    return RegionStats(luma=mean, detail=detail, edge_fraction=edge_fraction,
                       dark_fraction=dark_fraction, light_fraction=light_fraction)


# ----------------------------------------------------------------------------- выбор оформления
@dataclass(frozen=True)
class TextStyle:
    name: str                  # одно из STYLES
    ink: str                   # цвет основного текста
    accent: str                # цвет диалогов и восклицаний
    underlay: str | None       # 'fade' | 'plate' | None — что кладётся под текст
    halo: str | None           # 'light' | 'dark' | None — свечение или тень прямо за буквами
    halo_gain: float = 1.0     # сила свечения (в режиме plain на пёстром фоне усиливается)


def style_for(name: str, *, strong_halo: bool = False) -> TextStyle:
    gain = 1.6 if strong_halo else 1.0
    if name == STYLE_PLAIN_LIGHT:
        return TextStyle(name, INK, ACCENT, None, "light", gain)
    if name == STYLE_PLAIN_DARK:
        return TextStyle(name, INK_ON_DARK, ACCENT_ON_DARK, None, "dark", gain)
    if name == STYLE_FADE:
        return TextStyle(name, INK, ACCENT, "fade", None)
    if name == STYLE_PLATE_CREAM:
        return TextStyle(name, INK, ACCENT, "plate", None)
    if name == STYLE_PLATE_DARK:
        return TextStyle(name, INK_ON_DARK, ACCENT_ON_DARK, "plate", None)
    raise ValueError(f"Неизвестное оформление текста: {name}")


def choose_style(stats: RegionStats, mode: str = DEFAULT_MODE) -> TextStyle:
    """Оформление текста под участок картинки.

    auto:  спокойный (не пёстрый) светлый фон → plain-light, всё остальное (тёмный, средний, пёстрый) → fade;
    fade:  всегда fade;  plate: всегда мягкая подложка (тёмная на тёмном фоне, иначе кремовая);
    plain: никогда ничего не накладывать на картинку: тёмный текст со светлым свечением на светлом фоне,
           кремовый текст с тёмной тенью на тёмном; на пёстром фоне свечение сильнее."""
    if mode not in MODES:
        raise ValueError(f"TEXT_OVERLAY_MODE должен быть одним из: {', '.join(MODES)}")
    if mode == "fade":
        return style_for(STYLE_FADE)
    if mode == "plate":
        return style_for(STYLE_PLATE_DARK if stats.dark else STYLE_PLATE_CREAM)
    if mode == "plain":
        name = STYLE_PLAIN_LIGHT if stats.luma >= PLAIN_SPLIT_LUMA else STYLE_PLAIN_DARK
        return style_for(name, strong_halo=stats.busy)
    if stats.light and not stats.busy:
        return style_for(STYLE_PLAIN_LIGHT)
    return style_for(STYLE_FADE)


# ----------------------------------------------------------------------------- разметка с акцентами
# Красный акцент — пряность, а не краска для всей страницы. Акцентом выделяются только:
#   1) прямая речь после тире (сама реплика; «— сказал он» остаётся обычным цветом) и цитата в «ёлочках» с «!» или «?»;
#   2) короткие возгласы: предложение с «!» из не больше ACCENT_EXCLAIM_WORDS слов («Ура!», «Ой, рыба!»).
# Длинные повествовательные предложения с «!» не красятся никогда. Если акцентных слов всё равно больше ACCENT_BUDGET
# страницы, самые длинные акценты возвращаются в обычный цвет. Те же правила использует Mini App через pages[].lines.
ACCENT_EXCLAIM_WORDS = 4
ACCENT_BUDGET = 0.6
ACCENT_BUDGET_MIN_WORDS = 10          # на совсем коротких страницах («Ура!») бюджет не считаем

_DASHES = ("—", "–", "―", "-")
_AFTER_SENTENCE = re.compile(r"(?<=[.!?…»”\"'’])(\s+)")
_CLOSERS = " »”\"'’)]"
_DASH_START = re.compile(r"^[—–―-]\s*")
_REMARK = re.compile(r"(?:(?<=[!?…])[»”\"]*|(?<=,))(\s+)[—–―-]\s+(?=[а-яёa-zөүң])")      # «… ! — сказал он»: слова автора после реплики
_REMARK_START = re.compile(r"^[—–―-]\s*[а-яёa-zөүң]")
_QUOTE = re.compile(r"«[^«»]*[!?][»”]?[^«»]*»|«[^«»]*[!?]»")


def is_dialogue(line: str) -> bool:
    """Строка-реплика: начинается с тире."""
    return line.lstrip()[:1] in _DASHES


def is_exclamation(sentence: str) -> bool:
    """Предложение, которое кончается восклицательным знаком (после него могут стоять кавычки, скобки, многоточие)."""
    return sentence.rstrip(_CLOSERS + ".…").endswith("!")


def _word_count(text: str) -> int:
    return sum(1 for t in text.split() if any(ch.isalpha() for ch in t))


def _segments(line: str) -> list[tuple[str, str]]:
    """Строка → [(пробел перед предложением, предложение)]. Слова автора после реплики («— сказал он.») приклеены к реплике."""
    pieces = _AFTER_SENTENCE.split(line)                      # предложение, пробелы, предложение, ...
    out: list[tuple[str, str]] = []
    for i in range(0, len(pieces), 2):
        gap = pieces[i - 1] if i else ""
        sentence = pieces[i]
        if out and _REMARK_START.match(sentence) and is_dialogue(out[-1][1]):
            out[-1] = (out[-1][0], out[-1][1] + gap + sentence)
        else:
            out.append((gap, sentence))
    return out


def _split_accent(sentence: str) -> list[tuple[str, bool]]:
    """Одно предложение → куски (текст, акцентный ли) по правилам выше."""
    if _DASH_START.match(sentence):                            # реплика: красим речь, слова автора после неё — нет
        m = _REMARK.search(sentence)
        if m:
            return [(sentence[:m.start(1)], True), (sentence[m.start(1):], False)]
        return [(sentence, True)]
    if is_exclamation(sentence) and _word_count(sentence) <= ACCENT_EXCLAIM_WORDS:
        return [(sentence, True)]
    quote = _QUOTE.search(sentence)
    if quote:                                                  # цитата в «ёлочках» с «!» или «?»
        return [(t, a) for t, a in ((sentence[:quote.start()], False), (quote.group(0), True),
                                    (sentence[quote.end():], False)) if t]
    return [(sentence, False)]


def _pieces(line: str) -> list[list]:
    """Строка → кусочки [текст, акцент, это_пробел_между_предложениями]. Предложения не склеены, чтобы бюджет снимал акцент
    с отдельных предложений, а не с целой серии возгласов."""
    line = line.strip()
    pieces: list[list] = []
    for gap, sentence in _segments(line) if line else []:
        if gap:
            pieces.append([gap, False, True])
        pieces.extend([text, accented, False] for text, accented in _split_accent(sentence))
    return pieces


def _merged(pieces: list[list]) -> list[tuple[str, bool]]:
    """Кусочки → куски строки. Пробел между двумя акцентами красится вместе с ними («Ура! Ура!» — один сплошной кусок)."""
    out: list[tuple[str, bool]] = []
    for i, (text, accented, is_gap) in enumerate(pieces):
        if is_gap:
            accented = 0 < i < len(pieces) - 1 and pieces[i - 1][1] and pieces[i + 1][1]
        if not text:
            continue
        if out and out[-1][1] == accented:
            out[-1] = (out[-1][0] + text, accented)
        else:
            out.append((text, accented))
    return out


def line_runs(line: str) -> list[tuple[str, bool]]:
    """Одна строка текста → куски (текст, акцентный ли). Пробелы между предложениями не красятся; соседние акценты
    («Ура! Ура!») склеиваются в один кусок вместе с пробелом между ними. Без бюджета страницы (его применяет emphasis_runs)."""
    return _merged(_pieces(line))


def emphasis_runs(text: str) -> list[list[tuple[str, bool]]]:
    """Текст страницы → строки (по переносам), у каждой куски (текст, акцентный ли). Так же размечает Mini App.
    Бюджет: акцентных слов не больше ACCENT_BUDGET страницы (страницы короче ACCENT_BUDGET_MIN_WORDS слов — без бюджета);
    лишнее снимается с самых длинных акцентов, текст при этом не меняется."""
    lines = [_pieces(line) for line in text.split("\n")]
    total = sum(_word_count(piece[0]) for line in lines for piece in line)
    if total >= ACCENT_BUDGET_MIN_WORDS:
        while True:
            spots = [(_word_count(piece[0]), li, pi) for li, line in enumerate(lines) for pi, piece in enumerate(line)
                     if piece[1] and not piece[2]]
            if not spots or sum(w for w, _, _ in spots) <= ACCENT_BUDGET * total:
                break
            _, li, pi = max(spots)
            lines[li][pi][1] = False
    return [_merged(line) for line in lines]


def _line_markup(runs: list[tuple[str, bool]], accent: str) -> str:
    return "".join(f'<font color="{accent}">{escape(text)}</font>' if accented else escape(text) for text, accented in runs)


def emphasis_markup(text: str, accent: str = ACCENT) -> str:
    """Текст страницы → разметка для reportlab Paragraph: реплики после тире и короткие возгласы красным акцентом,
    остальное — обычным цветом. Служебные знаки (& < >) экранируются, переносы строк → <br/>."""
    return "<br/>".join(_line_markup(runs, accent) for runs in emphasis_runs(text))


# ----------------------------------------------------------------------------- подложки (PNG с прозрачностью)
def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG", compress_level=1)
    return out.getvalue()


def _smoothstep(u: float) -> float:
    u = 0.0 if u < 0 else 1.0 if u > 1 else u
    return u * u * (3 - 2 * u)


def fade_alpha(distance_mm: float, spread_mm: float = 420.0) -> float:
    """Непрозрачность 0..FADE_A_MAX на расстоянии distance_mm от сгиба в сторону внешнего края (не убывает):
    у сгиба 0 (края нет), плавно (smoothstep) растёт на длине FADE_RAMP_FRAC ширины разворота, дальше FADE_A_MAX."""
    return FADE_A_MAX * _smoothstep(distance_mm / (FADE_RAMP_FRAC * spread_mm))


def fade_profile(width_px: int, width_mm: float = 210.0, spread_mm: float = 420.0) -> list[int]:
    """Значения альфа (0..255) по столбцам от сгиба к внешнему краю; не убывают."""
    return [round(255 * fade_alpha((i + 0.5) / width_px * width_mm, spread_mm)) for i in range(width_px)]


def render_fade_png(side: str, *, half_mm: float = 210.0, height_mm: float = 210.0,
                    px_per_mm: float = FADE_PX_PER_MM) -> bytes:
    """Кремово-белый градиент на половину разворота. side — на какой половине лежит текст ('right' | 'left'):
    прозрачный у сгиба, почти непрозрачный (FADE_A_MAX) у внешнего края книги, без жёсткой границы."""
    w, h = round(half_mm * px_per_mm), round(height_mm * px_per_mm)
    alphas = fade_profile(w, half_mm)
    if side == "left":
        alphas = alphas[::-1]
    row = Image.new("L", (w, 1))
    row.putdata(alphas)
    alpha = row.resize((w, h), Image.NEAREST)
    r, g, b = _rgb(CREAM)
    img = Image.new("RGBA", (w, h), (r, g, b, 0))
    img.putalpha(alpha)
    return _png(img)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def render_plate_png(width_mm: float, height_mm: float, *, dark: bool = False, feather_mm: float = 5.0,
                     px_per_mm: float = PLATE_PX_PER_MM) -> tuple[bytes, float]:
    """Мягкая скруглённая подложка width×height мм с размытым краем (без жёсткой границы).
    Возвращает (PNG, поля в мм): картинка больше подложки на поля со всех сторон, размытие уходит в них."""
    margin = feather_mm * 2.2
    w, h = round((width_mm + 2 * margin) * px_per_mm), round((height_mm + 2 * margin) * px_per_mm)
    mask = Image.new("L", (w, h), 0)
    m = round(margin * px_per_mm)
    ImageDraw.Draw(mask).rounded_rectangle([m, m, w - m, h - m], radius=round(min(width_mm, height_mm) * 0.16 * px_per_mm),
                                           fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(feather_mm * px_per_mm * 0.5))
    gain = PLATE_ALPHA_DARK if dark else PLATE_ALPHA_CREAM
    alpha = mask.point(lambda v: round(v * gain))
    r, g, b = PLATE_DARK_RGB if dark else _rgb(CREAM)
    img = Image.new("RGBA", (w, h), (r, g, b, 0))
    img.putalpha(alpha)
    return _png(img), margin


def render_halo_png(lines: list[tuple[str, float, float]], font_file: Path, size_pt: float, block_w_mm: float,
                    block_h_mm: float, *, kind: str = "light", gain: float = 1.0,
                    px_per_mm: float = HALO_PX_PER_MM) -> tuple[bytes, float]:
    """Размытый силуэт текста (Nunito через Pillow) как PNG с прозрачностью: его кладут под настоящий векторный текст.

    lines — (строка, x центра, y базовой линии) в мм от левого верхнего угла блока текста, y вниз.
    kind 'light': очень мягкое светлое свечение; 'dark': мягкая тёмная тень со смещением вниз.
    Возвращает (PNG, поля в мм): картинка больше блока на поля со всех сторон."""
    mm_per_pt = 25.4 / 72
    margin = max(4.0, size_pt * mm_per_pt * 0.6)
    w, h = round((block_w_mm + 2 * margin) * px_per_mm), round((block_h_mm + 2 * margin) * px_per_mm)
    font = ImageFont.truetype(str(font_file), max(6, round(size_pt * mm_per_pt * px_per_mm)))
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    shift = 0.0 if kind == "light" else size_pt * mm_per_pt * 0.07
    for text, cx, baseline in lines:
        if text.strip():
            draw.text(((margin + cx) * px_per_mm, (margin + baseline + shift) * px_per_mm), text, font=font, fill=255,
                      anchor="ms")
    sigma_mm = size_pt * mm_per_pt * (0.17 if kind == "light" else 0.13)
    mask = mask.filter(ImageFilter.GaussianBlur(max(1.0, sigma_mm * px_per_mm)))
    widen, cap = (2.0, 0.60) if kind == "light" else (2.8, 0.80)       # размытие слабое: усиливаем, как «растушёванный» контур
    alpha = mask.point(lambda v: round(min(255 * cap * min(1.0, gain), v * widen * gain)))
    r, g, b = GLOW_RGB if kind == "light" else SHADOW_RGB
    img = Image.new("RGBA", (w, h), (r, g, b, 0))
    img.putalpha(alpha)
    return _png(img), margin
