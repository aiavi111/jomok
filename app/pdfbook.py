"""Сборка PDF-книги (reportlab): квадратная фотокнига, показанная разворотами.

Страница PDF — разворот из двух квадратов 210×210 мм рядом: 420×210 мм (так книга печатается как фотокнига 21×21 см).
Всего PAGES + 2 разворотов:
  1. Обложка. Слева бумажная страница «Для …» с посвящением, справа иллюстрация на весь квадрат
     с названием на скруглённой полупрозрачной плашке.
  2…. Страницы сказки (PAGES). Один квадрат — иллюстрация до самого края, другой — бумажная страница
     с крупным текстом, орнаментом и номером. Картинка чередуется: нечётные страницы слева, чётные справа.
  Последний. Финал. Слева «Конец» и мораль в рамке, справа пожелание и подпись.
Бумага #FBF6EA, текст тёмно-коричневый. Шрифты из fonts/: Nunito (текст), Comfortaa (заголовки), оба OFL
с кириллицей и буквами ү ө ң; DejaVu Serif остаётся запасным, если файлов Nunito или Comfortaa нет.
"""
from __future__ import annotations

import logging
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from .bookinfo import book_labels
from .imaging import band_color
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

TEXT_MAX_PT, TEXT_MIN_PT = 20.0, 13.0
HARD_MIN_PT = 8.0     # аварийный минимум, если текст не влез даже в 13 pt
LEADING = 1.4         # межстрочный интервал: 1,4 размера шрифта


def register_fonts() -> None:
    """Регистрирует шрифты; если файла Nunito или Comfortaa нет, берёт запасной DejaVu Serif."""
    registered = pdfmetrics.getRegisteredFontNames()
    for name, filename in _FONT_FILES.items():
        if name in registered:
            continue
        path = FONTS_DIR / filename
        if not path.exists():
            log.warning("Нет шрифта %s, беру запасной DejaVu Serif", filename)
            path = FONTS_DIR / _FALLBACK_FILES[name]
        pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily(F_REG, normal=F_REG, bold=F_BOLD, italic=F_REG, boldItalic=F_BOLD)


def _markup(text: str) -> str:
    return escape(text).replace("\n", "<br/>")


def fit_paragraph(text: str, font: str, max_w: float, max_h: float, *, max_pt: float, min_pt: float,
                  align=TA_LEFT, color=INK, leading: float = LEADING):
    """Подбирает самый крупный размер шрифта, при котором текст помещается в max_h."""
    size = max_pt
    while True:
        style = ParagraphStyle("p", fontName=font, fontSize=size, leading=size * leading,
                               alignment=align, textColor=color)
        para = Paragraph(_markup(text), style)
        _, height = para.wrap(max_w, 10_000_000)
        if height <= max_h or size <= min_pt + 1e-6:
            break
        size = max(min_pt, size - 0.5)
    if height > max_h and min_pt > HARD_MIN_PT:      # аварийно: уменьшаем ниже минимума
        return fit_paragraph(text, font, max_w, max_h, max_pt=min_pt, min_pt=HARD_MIN_PT,
                             align=align, color=color, leading=leading)
    return para, size, height


class _Book:
    def __init__(self, path: Path, profile: Profile, story: Story, mock: bool, cover_has_title: bool = False):
        register_fonts()
        self.c = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
        self.c.setTitle(story.title)
        self.c.setAuthor("Персональная сказка")
        self.c.setSubject("Персональная сказка")
        self.profile, self.story, self.mock = profile, story, mock
        self.cover_has_title = cover_has_title      # название уже нарисовано на обложке: плашку не кладём
        self.labels = book_labels(story, profile)
        self.min_pt_used = TEXT_MAX_PT
        self.picture_sides: list[str] = []      # на какой стороне картинка у каждой страницы сказки: left | right

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

    def page_number(self, cx: float, number: int) -> None:
        """Внизу бумажной страницы: золотой кружок с номером и линии по сторонам."""
        c = self.c
        y, r = 15 * mm, 5.6 * mm
        c.setStrokeColor(ACCENT)
        c.setFillColor(ACCENT)
        c.setLineWidth(0.9)
        c.line(cx - 44 * mm, y, cx - r - 4 * mm, y)
        c.line(cx + r + 4 * mm, y, cx + 44 * mm, y)
        c.circle(cx - r - 4 * mm, y, 1.1 * mm, stroke=0, fill=1)
        c.circle(cx + r + 4 * mm, y, 1.1 * mm, stroke=0, fill=1)
        c.setFillColor(SUN)
        c.circle(cx, y, r, stroke=0, fill=1)
        self.centered(str(number), F_TITLE, 13, cx, y - 1.7 * mm, color=INK)

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

    def story_page(self, number: int, image_path: Path) -> None:
        """Разворот страницы сказки: картинка слева у нечётных и справа у чётных, на другой стороне — текст."""
        picture_left = number % 2 == 1
        self.picture_sides.append("left" if picture_left else "right")
        paper_x = RIGHT if picture_left else LEFT
        self.paper(paper_x)
        self.picture(LEFT if picture_left else RIGHT, image_path)
        margin, top, bottom = 24 * mm, SQ - 24 * mm, 34 * mm
        width = SQ - 2 * margin
        para, size, h = fit_paragraph(self.story.pages[number - 1].text, F_REG, width, top - bottom,
                                      max_pt=TEXT_MAX_PT, min_pt=TEXT_MIN_PT)
        self.min_pt_used = min(self.min_pt_used, size)
        block_top = (top + bottom) / 2 + h / 2          # текст по центру области над номером
        self.para_at(para, paper_x + margin, block_top, h)
        self.sparkles(paper_x, outer_left=picture_left is False)
        self.page_number(paper_x + SQ / 2, number)
        self.c.showPage()

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


def build_pdf(story: Story, profile: Profile, images: dict[str, Path], out_path: Path, *, mock: bool = False,
              cover_has_title: bool = False) -> Path:
    """images: {'cover': путь, 'p1'..'pN': путь}. Возвращает путь к PDF из PAGES + 2 разворотов 420×210 мм."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".pdf.tmp")
    book = _Book(tmp, profile, story, mock, cover_has_title)
    book.cover(images["cover"])
    for i in range(1, PAGES + 1):
        book.story_page(i, images[f"p{i}"])
    book.finale()
    book.c.save()
    tmp.replace(out_path)
    log.info("PDF собран (%s разворотов)", SPREADS)
    return out_path
