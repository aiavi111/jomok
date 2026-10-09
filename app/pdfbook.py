"""Сборка PDF-книги (reportlab): фотокнига разворотами 420×210 мм (два квадрата 210×210 мм рядом).

Всего PAGES + 2 разворотов:
  1. Обложка. Слева бумажная страница «Для …» с посвящением, справа квадратная обложка на весь квадрат
     (название нарисовано в самой картинке; если нет, ложится на скруглённую полупрозрачную плашку).
  2…. Страницы истории (PAGES). Одна широкая иллюстрация 2:1 на весь разворот, от края до края, без бумажной страницы.
     Текст лежит прямо на картинке, на спокойной половине: у нечётных страниц справа, у чётных слева. Оформление
     текста подбирается под фон (app/overlay.py): светлый спокойный фон — просто текст с мягким свечением,
     иначе картинка плавно «тает» в кремово-белый к краю (fade); TEXT_OVERLAY_MODE=plate даёт мягкую подложку.
     Текст крупный (30–18 pt), тёмно-коричневый, реплики (строки с тире) и «!» красным акцентом, внизу золотой номер.
  Последний. Финал: слева «Конец» и мораль в рамке, справа пожелание и подпись (две бумажные страницы).
Бумага #FBF6EA, текст тёмно-коричневый. Шрифты из fonts/: Nunito (текст), Comfortaa (заголовки), оба OFL
с кириллицей и буквами ү ө ң; DejaVu Serif остаётся запасным, если файлов Nunito или Comfortaa нет.
Текст остаётся векторным и выделяется мышью; подложки и свечение — PNG с прозрачностью, нарисованные Pillow.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from . import overlay
from .bookinfo import book_labels
from .imaging import band_color, cover_crop
from .layout import text_side
from .profile import Profile
from .story import PAGES, Story

log = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
F_REG, F_BOLD, F_TITLE = "Nunito-SemiBold", "Nunito-ExtraBold", "Comfortaa-Bold"   # текст, выделение, заголовки
_FONT_FILES = {F_REG: "Nunito-SemiBold.ttf", F_BOLD: "Nunito-ExtraBold.ttf", F_TITLE: "Comfortaa-Bold.ttf"}
_FALLBACK_FILES = {F_REG: "DejaVuSerif.ttf", F_BOLD: "DejaVuSerif-Bold.ttf", F_TITLE: "DejaVuSerif-Bold.ttf"}

SQ = 210 * mm                       # одна страница книги: квадрат 210×210 мм
PAGE_W, PAGE_H = 2 * SQ, SQ         # страница PDF — разворот 420×210 мм
LEFT, RIGHT = 0.0, SQ               # x левого края левого и правого квадрата
SPREADS = 1 + PAGES + 1             # обложка, страницы сказки, финал

BG = HexColor("#FBF6EA")            # бумага
INK = HexColor("#4A3326")           # тёмно-коричневый текст
MUTED = HexColor("#9A8670")
ACCENT = HexColor("#E3A94B")        # тёплое золото: линии, рамка
SUN = HexColor("#F6D58E")           # кружок с номером страницы
CORAL = HexColor("#EE7B62")         # сердечко в финале
GREY = HexColor("#9A9A9A")
SKY = HexColor("#CFE6F5")            # облачка на странице посвящения
SKY_LIGHT = HexColor("#EAF5FC")
STAR_GOLD = HexColor("#F2B84B")

TEXT_MAX_PT, TEXT_MIN_PT = 20.0, 13.0       # бумажные страницы: посвящение, мораль, пожелание
HARD_MIN_PT = 8.0     # аварийный минимум, если текст не влез даже в минимум
LEADING = 1.4         # межстрочный интервал: 1,4 размера шрифта

# текст страницы истории поверх картинки: всего несколько коротких строк, поэтому крупный
OVERLAY_MAX_PT, OVERLAY_MIN_PT = 30.0, 18.0
OVERLAY_LEADING = 1.3
TEXT_BOX_W = 150 * mm               # ширина блока текста внутри своей половины разворота
FADE_BOX_W = 140 * mm               # при fade блок чуть уже и сдвинут к внешнему краю, где градиент плотнее
FADE_SHIFT = 12 * mm
TEXT_ZONE_TOP, TEXT_ZONE_BOTTOM = SQ - 26 * mm, 36 * mm      # по вертикали текст центрируется между ними
BADGE_Y = 17 * mm                   # центр золотого кружка с номером страницы
MEASURE_PAD_X, MEASURE_PAD_Y = 8 * mm, 7 * mm                # запас вокруг текста при измерении фона
PLATE_PAD_X, PLATE_PAD_Y = 14 * mm, 10 * mm                  # поля подложки вокруг текста


_FONT_PATHS: dict[str, Path] = {}      # какой файл реально зарегистрирован под каждым именем (Pillow рисует свечение им же)


def register_fonts() -> None:
    """Регистрирует шрифты; если файла Nunito или Comfortaa нет, берёт запасной DejaVu Serif."""
    registered = pdfmetrics.getRegisteredFontNames()
    for name, filename in _FONT_FILES.items():
        if name in registered and name in _FONT_PATHS:
            continue
        path = FONTS_DIR / filename
        if not path.exists():
            log.warning("Нет шрифта %s, беру запасной DejaVu Serif", filename)
            path = FONTS_DIR / _FALLBACK_FILES[name]
        pdfmetrics.registerFont(TTFont(name, str(path)))
        _FONT_PATHS[name] = path
    pdfmetrics.registerFontFamily(F_REG, normal=F_REG, bold=F_BOLD, italic=F_REG, boldItalic=F_BOLD)


def _markup(text: str) -> str:
    return escape(text).replace("\n", "<br/>")


def fit_paragraph(text: str, font: str, max_w: float, max_h: float, *, max_pt: float, min_pt: float,
                  align=TA_LEFT, color=INK, leading: float = LEADING, markup: str | None = None):
    """Подбирает самый крупный размер шрифта, при котором текст помещается в max_h.
    markup — готовая разметка вместо экранированного text (например, с цветными акцентами)."""
    size = max_pt
    while True:
        style = ParagraphStyle("p", fontName=font, fontSize=size, leading=size * leading,
                               alignment=align, textColor=color)
        para = Paragraph(markup if markup is not None else _markup(text), style)
        _, height = para.wrap(max_w, 10_000_000)
        if height <= max_h or size <= min_pt + 1e-6:
            break
        size = max(min_pt, size - 0.5)
    if height > max_h and min_pt > HARD_MIN_PT:      # аварийно: уменьшаем ниже минимума
        return fit_paragraph(text, font, max_w, max_h, max_pt=min_pt, min_pt=HARD_MIN_PT,
                             align=align, color=color, leading=leading, markup=markup)
    return para, size, height


class _Book:
    def __init__(self, path: Path, profile: Profile, story: Story, mock: bool, cover_has_title: bool = False,
                 overlay_mode: str = overlay.DEFAULT_MODE):
        register_fonts()
        if overlay_mode not in overlay.MODES:
            raise ValueError(f"overlay_mode должен быть одним из: {', '.join(overlay.MODES)}")
        self.c = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
        self.c.setTitle(story.title)
        self.c.setAuthor("Персональная книга")
        self.c.setSubject("Персональная книга")
        self.profile, self.story, self.mock = profile, story, mock
        self.cover_has_title = cover_has_title      # название уже нарисовано на обложке: плашку не кладём
        self.overlay_mode = overlay_mode
        self.labels = book_labels(story, profile)
        self.min_pt_used = OVERLAY_MAX_PT           # самый мелкий кегль среди страниц истории
        self.text_sides: list[str] = []             # на какой половине разворота текст у каждой страницы: left | right
        self.text_styles: list[str] = []            # какое оформление выбрано (overlay.STYLES) у каждой страницы
        self.decor: list[tuple[str, float, float, float]] = []   # украшения страницы посвящения: (вид, x, y, половина размера) в пунктах

    # --- общее
    def paper(self, x0: float) -> None:
        """Бумажный квадрат (без картинки)."""
        self.c.setFillColor(BG)
        self.c.rect(x0, 0, SQ, SQ, fill=1, stroke=0)

    def picture(self, x0: float, source) -> None:
        """Иллюстрация на весь квадрат, до самого края страницы."""
        self.c.drawImage(ImageReader(str(source)), x0, 0, SQ, SQ)

    def mock_note(self, x0: float) -> None:
        if self.mock:
            self.c.setFillColor(GREY)
            self.c.setFont(F_REG, 9)
            self.c.drawCentredString(x0 + SQ / 2, 8 * mm, self.labels["mock_note"])

    def centered(self, text: str, font: str, size: float, cx: float, y: float, color=INK) -> None:
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        self.c.drawCentredString(cx, y, text)

    def para_at(self, para: Paragraph, x: float, top: float, height: float) -> None:
        para.drawOn(self.c, x, top - height)

    def centered_para(self, para: Paragraph, cx: float, top: float, height: float, width: float) -> None:
        self.para_at(para, cx - width / 2, top, height)

    def ornament(self, cx: float, y: float, half: float = 38 * mm) -> None:
        """Две тонкие линии и три точки между ними."""
        c = self.c
        c.setStrokeColor(ACCENT)
        c.setFillColor(ACCENT)
        c.setLineWidth(0.9)
        c.line(cx - half, y, cx - 9 * mm, y)
        c.line(cx + 9 * mm, y, cx + half, y)
        for dx, r in ((-3.4 * mm, 0.9 * mm), (0, 1.5 * mm), (3.4 * mm, 0.9 * mm)):
            c.circle(cx + dx, y, r, stroke=0, fill=1)

    def heart(self, cx: float, cy: float, size: float, color=CORAL) -> None:
        c = self.c
        path = c.beginPath()
        path.moveTo(cx, cy - size)
        path.curveTo(cx - 1.35 * size, cy - 0.15 * size, cx - 0.95 * size, cy + 0.95 * size, cx, cy + 0.35 * size)
        path.curveTo(cx + 0.95 * size, cy + 0.95 * size, cx + 1.35 * size, cy - 0.15 * size, cx, cy - size)
        path.close()
        c.setFillColor(color)
        c.drawPath(path, stroke=0, fill=1)

    def sparkle(self, cx: float, cy: float, r: float, color) -> None:
        """Четырёхлучевая искорка: четыре острых луча, стороны изогнуты к центру."""
        c = self.c
        k = 0.12 * r
        path = c.beginPath()
        path.moveTo(cx, cy + r)
        for tip, sx, sy in (((cx + r, cy), 1, 1), ((cx, cy - r), 1, -1), ((cx - r, cy), -1, -1), ((cx, cy + r), -1, 1)):
            path.curveTo(cx + sx * k, cy + sy * k, cx + sx * k, cy + sy * k, *tip)
        path.close()
        c.setFillColor(color)
        c.drawPath(path, stroke=0, fill=1)

    def sparkles(self, x0: float, outer_left: bool) -> None:
        """Горсть искорок в верхнем внешнем углу бумажной страницы (у края книги, не у сгиба)."""
        for dx, dy, r, color in ((15, 15, 4.4, SUN), (26, 12, 2.6, ACCENT), (8.5, 27, 2.1, ACCENT), (22.5, 24.5, 1.4, SUN)):
            x = x0 + dx * mm if outer_left else x0 + SQ - dx * mm
            self.sparkle(x, SQ - dy * mm, r * mm, color)

    def star(self, cx: float, cy: float, r: float, color=STAR_GOLD) -> None:
        """Пятиконечная звёздочка с мягкими углами (рисуется линиями, закрашена)."""
        import math
        c = self.c
        path = c.beginPath()
        for i in range(10):
            radius = r if i % 2 == 0 else r * 0.46
            angle = math.pi / 2 + i * math.pi / 5
            x, y = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        path.close()
        c.saveState()
        c.setFillColor(color)
        c.setStrokeColor(color)
        c.setLineWidth(r * 0.22)
        c.setLineJoin(1)                                   # скруглённые углы
        c.drawPath(path, stroke=1, fill=1)
        c.restoreState()
        self.decor.append(("star", cx, cy, r))

    def cloud(self, cx: float, cy: float, w: float) -> None:
        """Облачко: плоское основание и три круглые «шапки», бледно-голубое с белым бликом."""
        c = self.c
        h = w * 0.28
        c.saveState()
        c.setFillColor(SKY)
        c.roundRect(cx - w / 2, cy - h / 2, w, h, h / 2, stroke=0, fill=1)
        for dx, dy, r in ((-0.20, 0.10, 0.20), (0.02, 0.18, 0.27), (0.23, 0.08, 0.17)):
            c.circle(cx + dx * w, cy + dy * w, r * w, stroke=0, fill=1)
        c.setFillColor(SKY_LIGHT)
        c.circle(cx - 0.02 * w, cy + 0.27 * w, 0.10 * w, stroke=0, fill=1)
        c.restoreState()
        self.decor.append(("cloud", cx, cy, w / 2))

    def dedication_decor(self, x0: float, text_bottom: float) -> None:
        """Нижняя часть страницы посвящения не пустая: два облачка и звёздочки. Если посвящение длинное и подходит близко
        к низу, рисуем только маленькие звёздочки у края. text_bottom — y нижнего края текста (пункты)."""
        cx = x0 + SQ / 2
        if text_bottom > 62 * mm:
            self.cloud(cx - 34 * mm, 36 * mm, 50 * mm)
            self.cloud(cx + 38 * mm, 49 * mm, 34 * mm)
            self.star(cx - 6 * mm, 54 * mm, 4.6 * mm)
            self.star(cx + 12 * mm, 40 * mm, 3.0 * mm, SUN)
            self.star(cx - 58 * mm, 56 * mm, 2.6 * mm, SUN)
            self.star(cx + 62 * mm, 30 * mm, 3.6 * mm)
        elif text_bottom > 38 * mm:
            self.star(cx - 36 * mm, 24 * mm, 4.0 * mm)
            self.star(cx, 18 * mm, 3.0 * mm, SUN)
            self.star(cx + 36 * mm, 24 * mm, 4.0 * mm)

    # --- развороты
    def cover(self, cover_path: Path) -> None:
        """Разворот 1: слева посвящение на бумаге, справа обложка с названием на плашке."""
        c = self.c
        # левая страница
        self.paper(LEFT)
        cx = LEFT + SQ / 2
        title, _, th = fit_paragraph(self.labels["dedication_title"], F_TITLE, 150 * mm, 50 * mm,
                                     max_pt=38, min_pt=20, align=TA_CENTER, leading=1.2)
        text = self.labels["dedication_text"]
        body, bh = None, 0.0
        if text:
            body, _, bh = fit_paragraph(text, F_REG, 140 * mm, 80 * mm, max_pt=TEXT_MAX_PT, min_pt=TEXT_MIN_PT,
                                        align=TA_CENTER)
        gap = 9 * mm
        total = th + (2 * gap + bh if body else gap)
        top = SQ / 2 + total / 2 + 4 * mm
        self.sparkles(LEFT, outer_left=True)
        self.dedication_decor(LEFT, top - total)
        self.centered_para(title, cx, top, th, 150 * mm)
        self.ornament(cx, top - th - gap)
        if body:
            self.centered_para(body, cx, top - th - 2 * gap, bh, 140 * mm)
        self.mock_note(LEFT)
        # правая страница: картинка до краёв и плашка
        self.picture(RIGHT, cover_path)
        if self.cover_has_title:
            c.showPage()
            return
        rx = RIGHT + SQ / 2
        side, pad, bottom = 14 * mm, 9 * mm, 13 * mm
        plate_w = SQ - 2 * side
        tp, _, tph = fit_paragraph(self.labels["title"], F_TITLE, plate_w - 2 * pad, 56 * mm,
                                   max_pt=32, min_pt=16, align=TA_CENTER, color=white, leading=1.2)
        caption_h = 6 * mm
        plate_h = pad + tph + 4 * mm + caption_h + pad * 0.85
        r, g, b = band_color(str(cover_path))
        c.saveState()
        c.setFillColor(Color(r, g, b))
        c.setFillAlpha(0.85)
        c.roundRect(RIGHT + side, bottom, plate_w, plate_h, 8 * mm, stroke=0, fill=1)
        c.restoreState()
        self.centered_para(tp, rx, bottom + plate_h - pad, tph, plate_w - 2 * pad)
        self.centered(self.labels["caption"], F_TITLE, 13, rx, bottom + pad * 0.85, color=Color(1, 1, 1, alpha=0.92))
        c.setFillAlpha(1)
        c.showPage()

    # --- страница истории: широкая картинка на весь разворот и текст поверх
    def wide_picture(self, source) -> tuple[ImageReader, Image.Image]:
        """Картинка страницы для PDF и для измерения фона. Не 2:1 (старая квадратная книга, сбой) — обрезаем по центру."""
        with Image.open(str(source)) as opened:
            im = opened.convert("RGB")
        w, h = im.size
        if abs(w / h - PAGE_W / PAGE_H) <= 0.01:
            return ImageReader(str(source)), im
        im = cover_crop(im, PAGE_W / PAGE_H)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
        buf.seek(0)
        return ImageReader(buf), im

    def png_at(self, png: bytes, x: float, y: float, w: float, h: float) -> None:
        self.c.drawImage(ImageReader(io.BytesIO(png)), x, y, w, h, mask="auto")

    def story_fit(self, text: str, width: float, style: overlay.TextStyle):
        """Текст страницы по центру блока width: самый крупный кегль из 30–18 pt, при котором он влезает в зону."""
        markup = overlay.emphasis_markup(text, style.accent)
        return fit_paragraph(text, F_BOLD, width, TEXT_ZONE_TOP - TEXT_ZONE_BOTTOM, max_pt=OVERLAY_MAX_PT,
                             min_pt=OVERLAY_MIN_PT, align=TA_CENTER, color=HexColor(style.ink),
                             leading=OVERLAY_LEADING, markup=markup)

    def story_page(self, number: int, image_path: Path) -> None:
        """Разворот страницы истории: широкая картинка до краёв, текст на спокойной половине
        (нечётные страницы справа, чётные слева), оформление текста подбирается под фон."""
        c = self.c
        side = text_side(number)
        self.text_sides.append(side)
        reader, pil = self.wide_picture(image_path)
        c.drawImage(reader, 0, 0, PAGE_W, PAGE_H)
        half_x = RIGHT if side == "right" else LEFT
        cx = half_x + SQ / 2
        text = self.story.pages[number - 1].text

        # 1. предварительная раскладка, измерение фона под текстом, выбор оформления
        draft = overlay.style_for(overlay.STYLE_PLAIN_LIGHT)
        para, size, h = self.story_fit(text, TEXT_BOX_W, draft)
        widest = max(_line_widths(para, F_BOLD, size) or [TEXT_BOX_W])
        top = (TEXT_ZONE_TOP + TEXT_ZONE_BOTTOM) / 2 + h / 2
        box = (cx - widest / 2 - MEASURE_PAD_X, SQ - top - MEASURE_PAD_Y,
               cx + widest / 2 + MEASURE_PAD_X, SQ - (top - h) + MEASURE_PAD_Y)           # y сверху, в пунктах
        stats = overlay.measure_region(pil, tuple(v / mm for v in box), (PAGE_W / mm, PAGE_H / mm))
        style = overlay.choose_style(stats, self.overlay_mode)
        self.text_styles.append(style.name)
        log.debug("Страница %s: яркость %.0f, деталь %.1f, краёв %.3f → %s", number, stats.luma, stats.detail,
                  stats.edge_fraction, style.name)

        # 2. окончательная раскладка уже в цветах оформления
        width = FADE_BOX_W if style.underlay == "fade" else TEXT_BOX_W
        if style.underlay == "fade":
            cx += FADE_SHIFT if side == "right" else -FADE_SHIFT
        para, size, h = self.story_fit(text, width, style)
        self.min_pt_used = min(self.min_pt_used, size)
        top = (TEXT_ZONE_TOP + TEXT_ZONE_BOTTOM) / 2 + h / 2
        widths = _line_widths(para, F_BOLD, size)
        widest = max(widths or [width])

        # 3. подложка или свечение под текстом, потом сам текст
        if style.underlay == "fade":
            self.png_at(_fade_png(side), half_x, 0, SQ, SQ)
        elif style.underlay == "plate":
            w_mm, h_mm = widest / mm + 2 * PLATE_PAD_X / mm, h / mm + 2 * PLATE_PAD_Y / mm
            png, margin = overlay.render_plate_png(w_mm, h_mm, dark=style.name == overlay.STYLE_PLATE_DARK)
            m = margin * mm
            self.png_at(png, cx - widest / 2 - PLATE_PAD_X - m, top - h - PLATE_PAD_Y - m, w_mm * mm + 2 * m,
                        h_mm * mm + 2 * m)
        elif style.halo:
            self.halo(para, style, width, size, cx, top, h)
        self.centered_para(para, cx, top, h, width)
        self.page_number(cx, number, style)
        c.showPage()

    def halo(self, para: Paragraph, style: overlay.TextStyle, width: float, size: float, cx: float, top: float,
             h: float) -> None:
        """Размытый силуэт текста (Pillow, тот же Nunito) под настоящим текстом: свечение или тень."""
        lines = _line_texts(para)
        if not lines:
            return
        leading = size * OVERLAY_LEADING
        ascent = _first_ascent(para, F_BOLD, size)
        placed = [(text, width / mm / 2, (ascent + i * leading) / mm) for i, text in enumerate(lines)]
        png, margin = overlay.render_halo_png(placed, _FONT_PATHS[F_BOLD], size, width / mm, h / mm, kind=style.halo,
                                              gain=style.halo_gain)
        m = margin * mm
        self.png_at(png, cx - width / 2 - m, top - h - m, width + 2 * m, h + 2 * m)

    def page_number(self, cx: float, number: int, style: overlay.TextStyle) -> None:
        """Внизу своей половины разворота: небольшой золотой кружок с номером страницы."""
        c = self.c
        r = 5.6 * mm
        c.saveState()
        c.setFillColor(SUN)
        c.setStrokeColor(Color(1, 0.99, 0.96, alpha=0.9))
        c.setLineWidth(1.2)
        c.circle(cx, BADGE_Y, r, stroke=1, fill=1)
        c.restoreState()
        self.centered(str(number), F_TITLE, 13, cx, BADGE_Y - 1.7 * mm, color=INK)

    def finale(self) -> None:
        """Последний разворот: слева «Конец» и мораль в рамке, справа пожелание и подпись."""
        c = self.c
        # левая страница
        self.paper(LEFT)
        cx = LEFT + SQ / 2
        end, _, eh = fit_paragraph(self.labels["the_end"], F_TITLE, 150 * mm, 30 * mm,
                                   max_pt=46, min_pt=24, align=TA_CENTER, leading=1.2)
        frame_w, pad = 150 * mm, 10 * mm
        moral, _, mh = fit_paragraph(self.labels["moral"], F_BOLD, frame_w - 2 * pad, 80 * mm,
                                     max_pt=TEXT_MAX_PT, min_pt=TEXT_MIN_PT, align=TA_CENTER)
        frame_h = mh + 2 * pad
        gap = 10 * mm
        top = SQ / 2 + (eh + 2 * gap + frame_h) / 2 + 3 * mm
        self.sparkles(LEFT, outer_left=True)
        self.centered_para(end, cx, top, eh, 150 * mm)
        self.ornament(cx, top - eh - gap)
        frame_top = top - eh - 2 * gap
        c.setStrokeColor(ACCENT)
        c.setLineWidth(1.8)
        c.setFillColor(HexColor("#FFF9EA"))
        c.roundRect(cx - frame_w / 2, frame_top - frame_h, frame_w, frame_h, 7 * mm, stroke=1, fill=1)
        self.centered_para(moral, cx, frame_top - pad, mh, frame_w - 2 * pad)
        # правая страница
        self.paper(RIGHT)
        rx = RIGHT + SQ / 2
        wish, _, wh = fit_paragraph(self.labels["wish"], F_REG, 150 * mm, 100 * mm,
                                    max_pt=TEXT_MAX_PT, min_pt=TEXT_MIN_PT, align=TA_CENTER)
        heart_h = 16 * mm
        wish_top = SQ / 2 + (heart_h + 6 * mm + wh) / 2 + 6 * mm
        self.sparkles(RIGHT, outer_left=False)
        self.heart(rx, wish_top - 7 * mm, 6.5 * mm)
        self.centered_para(wish, rx, wish_top - heart_h - 6 * mm, wh, 150 * mm)
        self.ornament(rx, 31 * mm)
        self.centered(self.labels["signature"], F_REG, 12, rx, 21 * mm, color=MUTED)
        self.mock_note(RIGHT)
        c.showPage()


def _line_texts(para: Paragraph) -> list[str]:
    """Строки уже разбитого абзаца (после wrap) обычным текстом, для рисования свечения. Пусто, если не удалось."""
    try:
        out = []
        for line in para.blPara.lines:
            if isinstance(line, tuple):                       # простой абзац: (запас места, слова)
                out.append(" ".join(line[1]).strip())
            else:                                             # абзац с цветными кусками: FragLine
                out.append("".join(getattr(w, "text", str(w)) for w in line.words).strip())
        return out
    except Exception:                                         # свечение — украшение, из-за него книга не должна падать
        log.warning("Не удалось разобрать строки абзаца для свечения", exc_info=True)
        return []


def _line_widths(para: Paragraph, font: str, size: float) -> list[float]:
    return [pdfmetrics.stringWidth(text, font, size) for text in _line_texts(para) if text]


def _first_ascent(para: Paragraph, font: str, size: float) -> float:
    """Отступ первой базовой линии от верха абзаца (так её ставит reportlab)."""
    try:
        bp = para.blPara
        return float(bp.lines[0].ascent if not isinstance(bp.lines[0], tuple) else bp.ascent)
    except Exception:
        return size * 1.0


_FADE_CACHE: dict[str, bytes] = {}


def _fade_png(side: str) -> bytes:
    if side not in _FADE_CACHE:
        _FADE_CACHE[side] = overlay.render_fade_png(side)
    return _FADE_CACHE[side]


def build_pdf(story: Story, profile: Profile, images: dict[str, Path], out_path: Path, *, mock: bool = False,
              cover_has_title: bool = False, overlay_mode: str = overlay.DEFAULT_MODE,
              report: dict | None = None) -> Path:
    """images: {'cover': путь, 'p1'..'pN': путь}. Возвращает путь к PDF из PAGES + 2 разворотов 420×210 мм.

    overlay_mode: auto | fade | plate | plain (см. app/overlay.py). report, если передан, заполняется
    {'text_sides': [...], 'text_styles': [...], 'min_text_pt': ...} по страницам истории."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".pdf.tmp")
    book = _Book(tmp, profile, story, mock, cover_has_title, overlay_mode)
    book.cover(images["cover"])
    for i in range(1, PAGES + 1):
        book.story_page(i, images[f"p{i}"])
    book.finale()
    book.c.save()
    tmp.replace(out_path)
    if report is not None:
        report.update(text_sides=list(book.text_sides), text_styles=list(book.text_styles),
                      min_text_pt=book.min_pt_used, overlay_mode=overlay_mode)
    log.info("PDF собран (%s разворотов, оформление текста: %s)", SPREADS, ", ".join(book.text_styles))
    return out_path
