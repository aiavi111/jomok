"""Сборка PDF-книги (reportlab): обложка, посвящение, 8 страниц сказки, финал.

Формат страницы 210×265 мм, фон #FBF6EA, текст #3A2E25, шрифт DejaVu Serif из папки fonts/.
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
from .story import Story

log = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
F_REG, F_BOLD, F_ITAL, F_BOLDITAL = "DejaVuSerif", "DejaVuSerif-Bold", "DejaVuSerif-Italic", "DejaVuSerif-BoldItalic"
_FONT_FILES = {F_REG: "DejaVuSerif.ttf", F_BOLD: "DejaVuSerif-Bold.ttf",
               F_ITAL: "DejaVuSerif-Italic.ttf", F_BOLDITAL: "DejaVuSerif-BoldItalic.ttf"}

PAGE_W, PAGE_H = 210 * mm, 265 * mm
BG = HexColor("#FBF6EA")
INK = HexColor("#3A2E25")
MUTED = HexColor("#8A7A68")
ACCENT = HexColor("#C9A66B")
GREY = HexColor("#9A9A9A")

TEXT_MAX_PT, TEXT_MIN_PT = 17.0, 11.0
HARD_MIN_PT = 8.0     # аварийный минимум, если текст не влез даже в 11 pt


def register_fonts() -> None:
    for name, filename in _FONT_FILES.items():
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(FONTS_DIR / filename)))
    pdfmetrics.registerFontFamily(F_REG, normal=F_REG, bold=F_BOLD, italic=F_ITAL, boldItalic=F_BOLDITAL)


def _markup(text: str) -> str:
    return escape(text).replace("\n", "<br/>")


def fit_paragraph(text: str, font: str, max_w: float, max_h: float, *, max_pt: float, min_pt: float,
                  align=TA_LEFT, color=INK, leading: float = 1.38):
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
    if height > max_h and min_pt > HARD_MIN_PT:      # аварийно: уменьшаем ниже 11 pt
        return fit_paragraph(text, font, max_w, max_h, max_pt=min_pt, min_pt=HARD_MIN_PT,
                             align=align, color=color, leading=leading)
    return para, size, height


class _Book:
    def __init__(self, path: Path, profile: Profile, story: Story, mock: bool):
        register_fonts()
        self.c = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
        self.c.setTitle(story.title)
        self.c.setAuthor("Персональная сказка")
        self.c.setSubject("Персональная сказка")
        self.profile, self.story, self.mock = profile, story, mock
        self.labels = book_labels(story, profile)
        self.min_pt_used = TEXT_MAX_PT

    # --- общее
    def new_page(self, background=BG) -> None:
        self.c.setFillColor(background)
        self.c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    def mock_note(self) -> None:
        if self.mock:
            self.c.setFillColor(GREY)
            self.c.setFont(F_ITAL, 9)
            self.c.drawCentredString(PAGE_W / 2, 7 * mm, self.labels["mock_note"])

    def centered(self, text, font, size, y, color=INK) -> None:
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        self.c.drawCentredString(PAGE_W / 2, y, text)

    def para_at(self, para: Paragraph, x: float, top: float, height: float) -> None:
        para.drawOn(self.c, x, top - height)

    def rounded_image(self, source, x, y, size, radius) -> None:
        c = self.c
        c.saveState()
        path = c.beginPath()
        path.roundRect(x, y, size, size, radius)
        c.clipPath(path, stroke=0, fill=0)
        c.drawImage(ImageReader(str(source)), x, y, size, size)
        c.restoreState()
        c.setStrokeColor(HexColor("#E7DCC5"))
        c.setLineWidth(0.8)
        c.roundRect(x, y, size, size, radius, stroke=1, fill=0)

    def ornament(self, y: float) -> None:
        c = self.c
        c.setStrokeColor(ACCENT)
        c.setFillColor(ACCENT)
        c.setLineWidth(0.8)
        c.line(PAGE_W / 2 - 45 * mm, y, PAGE_W / 2 - 8 * mm, y)
        c.line(PAGE_W / 2 + 8 * mm, y, PAGE_W / 2 + 45 * mm, y)
        for dx, r in ((-3.2 * mm, 0.9 * mm), (0, 1.5 * mm), (3.2 * mm, 0.9 * mm)):
            c.circle(PAGE_W / 2 + dx, y, r, stroke=0, fill=1)

    # --- страницы
    def cover(self, cover_path: Path) -> None:
        c = self.c
        self.new_page()
        c.drawImage(ImageReader(str(cover_path)), 0, PAGE_H - 210 * mm, 210 * mm, 210 * mm)
        r, g, b = band_color(str(cover_path))
        c.setFillColor(Color(r, g, b))
        c.rect(0, 0, PAGE_W, 55 * mm, fill=1, stroke=0)
        title_box_h = 30 * mm
        para, _, h = fit_paragraph(self.labels["title"], F_BOLD, 186 * mm, title_box_h,
                                   max_pt=28, min_pt=16, align=TA_CENTER, color=white, leading=1.22)
        self.para_at(para, 12 * mm, 50 * mm - (title_box_h - h) / 2, h)
        self.centered(self.labels["caption"], F_ITAL, 13, 11 * mm, color=Color(1, 1, 1, alpha=0.88))
        c.showPage()

    def dedication(self) -> None:
        c = self.c
        self.new_page()
        self.centered(self.labels["dedication_title"], F_BOLD, 30, PAGE_H * 0.64)
        self.ornament(PAGE_H * 0.64 - 12 * mm)
        text = self.labels["dedication_text"]
        if text:
            box_h = 70 * mm
            para, _, h = fit_paragraph(text, F_ITAL, 150 * mm, box_h, max_pt=20, min_pt=12, align=TA_CENTER)
            self.para_at(para, 30 * mm, PAGE_H * 0.64 - 24 * mm, h)
        self.mock_note()
        c.showPage()

    def story_page(self, number: int, image_path: Path) -> None:
        c = self.c
        self.new_page()
        img = 160 * mm
        x = (PAGE_W - img) / 2
        self.rounded_image(image_path, x, PAGE_H - 15 * mm - img, img, 6 * mm)
        text_top = PAGE_H - 15 * mm - img - 8 * mm      # 82 мм от низа страницы
        text_bottom = 20 * mm
        para, size, h = fit_paragraph(self.story.pages[number - 1].text, F_REG, img, text_top - text_bottom,
                                      max_pt=TEXT_MAX_PT, min_pt=TEXT_MIN_PT)
        self.min_pt_used = min(self.min_pt_used, size)
        self.para_at(para, x, text_top, h)
        self.centered(f"— {number} —", F_REG, 10, 11 * mm, color=MUTED)
        c.showPage()

    def finale(self) -> None:
        c = self.c
        self.new_page()
        self.centered(self.labels["the_end"], F_BOLD, 36, PAGE_H - 66 * mm)
        self.ornament(PAGE_H - 76 * mm)

        frame_w, pad = 150 * mm, 9 * mm
        moral, _, mh = fit_paragraph(self.labels["moral"], F_ITAL, frame_w - 2 * pad, 55 * mm,
                                     max_pt=20, min_pt=13, align=TA_CENTER)
        frame_h = mh + 2 * pad
        frame_top = PAGE_H - 96 * mm
        fx = (PAGE_W - frame_w) / 2
        c.setStrokeColor(ACCENT)
        c.setLineWidth(1.6)
        c.setFillColor(HexColor("#FFF9EA"))
        c.roundRect(fx, frame_top - frame_h, frame_w, frame_h, 5 * mm, stroke=1, fill=1)
        self.para_at(moral, fx + pad, frame_top - pad, mh)

        wish_top = frame_top - frame_h - 14 * mm
        wish, _, wh = fit_paragraph(self.labels["wish"], F_REG, 150 * mm, wish_top - 34 * mm,
                                    max_pt=16, min_pt=11, align=TA_CENTER)
        self.para_at(wish, 30 * mm, wish_top, wh)

        self.centered(self.labels["signature"], F_ITAL, 11, 20 * mm, color=MUTED)
        self.mock_note()
        c.showPage()


def build_pdf(story: Story, profile: Profile, images: dict[str, Path], out_path: Path, *, mock: bool = False) -> Path:
    """images: {'cover': путь, 'p1'..'p8': путь}. Возвращает путь к PDF."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".pdf.tmp")
    book = _Book(tmp, profile, story, mock)
    book.cover(images["cover"])
    book.dedication()
    for i in range(1, 9):
        book.story_page(i, images[f"p{i}"])
    book.finale()
    book.c.save()
    tmp.replace(out_path)
    log.info("PDF собран (%s страниц)", 11)
    return out_path
