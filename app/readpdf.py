"""Второй PDF, для телефона: вертикальные страницы 9:16, как карточки в просмотре книги в Mini App.

Первый PDF (app/pdfbook.py) остаётся прежним: широкие развороты 21×21. Этот листается по одной странице на экран телефона:
сверху картинка (половина широкой иллюстрации, где герои), под ней текст на кремовой бумаге, три точки и номер страницы.
Страницы: обложка, посвящение, 8 страниц истории, «Конец» с моралью и пожеланием.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from . import overlay
from .bookinfo import book_labels
from .layout import text_side
from .pdfbook import ACCENT, BG, CORAL, F_BOLD, F_REG, F_TITLE, GREY, INK, MUTED, SUN, fit_paragraph, register_fonts
from .profile import Profile
from .story import PAGES, Story

log = logging.getLogger(__name__)

W = 108 * mm                          # 9:16
H = 192 * mm
IMG_H = 100 * mm                      # картинка страницы истории на всю ширину
TEXT_W = 90 * mm
TEXT_MAX_PT = 20.0
TEXT_MIN_PT = 12.0
DIALOGUE = "#D4472F"
PAGES_IN_BOOK = 1 + 1 + PAGES + 1     # обложка, посвящение, страницы истории, конец


def _hero_part(path: Path, number: int) -> bytes:
    """Часть широкой картинки с героями: половина, где нет текста (layout.text_side), по центру по высоте под формат W×IMG_H."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        if w >= h * 1.5:                                          # широкая страница 2:1: берём половину с героями
            half = w // 2
            im = im.crop((w - half, 0, w, h) if text_side(number) == "left" else (0, 0, half, h))
            w = half
        target = W / IMG_H                                         # ширина к высоте
        if w / h > target:                                         # слишком широкая: срезаем с боков
            new_w = int(h * target)
            x0 = (w - new_w) // 2
            im = im.crop((x0, 0, x0 + new_w, h))
        else:                                                      # слишком высокая: срезаем сверху и снизу, герои чаще в верхней трети
            new_h = int(w / target)
            y0 = max(0, int((h - new_h) * 0.35))
            im = im.crop((0, y0, w, y0 + new_h))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=90)
        return out.getvalue()


class _Pages:
    def __init__(self, path: Path, profile: Profile, story: Story, mock: bool, cover_has_title: bool):
        register_fonts()
        self.c = canvas.Canvas(str(path), pagesize=(W, H))
        self.c.setTitle(story.title)
        self.c.setAuthor("Персональная книга")
        self.c.setSubject("Персональная книга")
        self.profile, self.story, self.mock, self.cover_has_title = profile, story, mock, cover_has_title
        self.labels = book_labels(story, profile)
        self.min_pt = TEXT_MAX_PT

    def paper(self) -> None:
        self.c.setFillColor(BG)
        self.c.rect(0, 0, W, H, fill=1, stroke=0)

    def para(self, text: str, font: str, width: float, max_h: float, *, max_pt: float, min_pt: float, markup: str | None = None):
        return fit_paragraph(text, font, width, max_h, max_pt=max_pt, min_pt=min_pt, align=TA_CENTER, color=INK, markup=markup)

    def at(self, para, top: float, height: float, width: float = TEXT_W) -> None:
        para.drawOn(self.c, (W - width) / 2, top - height)

    def ornament(self, y: float, half: float = 26 * mm) -> None:
        c = self.c
        cx = W / 2
        c.setStrokeColor(ACCENT)
        c.setFillColor(ACCENT)
        c.setLineWidth(0.9)
        c.line(cx - half, y, cx - 7 * mm, y)
        c.line(cx + 7 * mm, y, cx + half, y)
        for dx, r in ((-3.0 * mm, 0.8 * mm), (0, 1.4 * mm), (3.0 * mm, 0.8 * mm)):
            c.circle(cx + dx, y, r, stroke=0, fill=1)

    def heart(self, cx: float, cy: float, size: float) -> None:
        c = self.c
        path = c.beginPath()
        path.moveTo(cx, cy - size)
        path.curveTo(cx - 1.35 * size, cy - 0.15 * size, cx - 0.95 * size, cy + 0.95 * size, cx, cy + 0.35 * size)
        path.curveTo(cx + 0.95 * size, cy + 0.95 * size, cx + 1.35 * size, cy - 0.15 * size, cx, cy - size)
        path.close()
        c.setFillColor(CORAL)
        c.drawPath(path, stroke=0, fill=1)

    def mock_note(self) -> None:
        if self.mock:
            self.c.setFillColor(GREY)
            self.c.setFont(F_REG, 7)
            self.c.drawCentredString(W / 2, 4 * mm, self.labels["mock_note"])

    def cover(self, cover_path: Path) -> None:
        self.paper()
        side = W                                                   # обложка квадратом на всю ширину, сверху
        self.c.drawImage(ImageReader(str(cover_path)), 0, H - side, side, side)
        band = H - side
        if self.cover_has_title:
            self.ornament(band - 22 * mm)
            self.c.setFillColor(MUTED)
            self.c.setFont(F_TITLE, 11)
            self.c.drawCentredString(W / 2, band - 32 * mm, self.labels["caption"])
        else:
            title, _, th = self.para(self.labels["title"], F_TITLE, TEXT_W, 40 * mm, max_pt=22, min_pt=13)
            self.at(title, band - 10 * mm, th)
            self.ornament(band - 10 * mm - th - 6 * mm)
            self.c.setFillColor(MUTED)
            self.c.setFont(F_TITLE, 10)
            self.c.drawCentredString(W / 2, 10 * mm, self.labels["caption"])
        self.mock_note()
        self.c.showPage()

    def dedication(self) -> None:
        self.paper()
        title, _, th = self.para(self.labels["dedication_title"], F_TITLE, TEXT_W, 40 * mm, max_pt=26, min_pt=16)
        text = self.labels["dedication_text"]
        body, bh = None, 0.0
        if text:
            body, _, bh = self.para(text, F_REG, TEXT_W, 70 * mm, max_pt=16, min_pt=11)
        gap = 8 * mm
        total = th + (2 * gap + bh if body else gap)
        top = H / 2 + total / 2
        self.at(title, top, th)
        self.ornament(top - th - gap)
        if body:
            self.at(body, top - th - 2 * gap, bh)
        self.mock_note()
        self.c.showPage()

    def story_page(self, number: int, image_path: Path) -> None:
        c = self.c
        self.paper()
        c.drawImage(ImageReader(io.BytesIO(_hero_part(image_path, number))), 0, H - IMG_H, W, IMG_H)
        area_top = H - IMG_H - 10 * mm
        area_h = area_top - 34 * mm                                # снизу: точки и номер страницы
        text = self.story.pages[number - 1].text
        para, size, h = self.para(text, F_BOLD, TEXT_W, area_h, max_pt=TEXT_MAX_PT, min_pt=TEXT_MIN_PT,
                                  markup=overlay.emphasis_markup(text, DIALOGUE))
        self.min_pt = min(self.min_pt, size)
        self.at(para, area_top - (area_h - h) / 2, h)
        self.ornament(24 * mm, half=22 * mm)
        c.setFillColor(SUN)
        c.circle(W / 2, 14 * mm, 4.6 * mm, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont(F_BOLD, 10)
        c.drawCentredString(W / 2, 12.6 * mm, str(number))
        self.mock_note()
        c.showPage()

    def finale(self) -> None:
        c = self.c
        self.paper()
        end, _, eh = self.para(self.labels["the_end"], F_TITLE, TEXT_W, 26 * mm, max_pt=34, min_pt=20)
        frame_w, pad = TEXT_W, 6 * mm
        moral, _, mh = self.para(self.labels["moral"], F_BOLD, frame_w - 2 * pad, 44 * mm, max_pt=15, min_pt=10)
        frame_h = mh + 2 * pad
        wish, _, wh = self.para(self.labels["wish"], F_REG, TEXT_W, 50 * mm, max_pt=14, min_pt=10)
        gap = 7 * mm
        total = eh + gap + frame_h + gap + 10 * mm + wh + 14 * mm
        top = H - max(14 * mm, (H - total) / 2)
        self.at(end, top, eh)
        y = top - eh - gap
        c.setStrokeColor(ACCENT)
        c.setLineWidth(1.5)
        c.setFillColor(HexColor("#FFF9EA"))
        c.roundRect((W - frame_w) / 2, y - frame_h, frame_w, frame_h, 5 * mm, stroke=1, fill=1)
        self.at(moral, y - pad, mh, frame_w - 2 * pad)
        y = y - frame_h - gap
        self.heart(W / 2, y - 4 * mm, 4 * mm)
        y -= 11 * mm
        self.at(wish, y, wh)
        self.ornament(22 * mm)
        c.setFillColor(MUTED)
        c.setFont(F_REG, 9)
        c.drawCentredString(W / 2, 13 * mm, self.labels["signature"])
        self.mock_note()
        c.showPage()


def build_mobile_pdf(story: Story, profile: Profile, images: dict[str, Path], out_path: Path, *, mock: bool = False,
                     cover_has_title: bool = False) -> Path:
    """images: {'cover': путь, 'p1'..'pN': путь}. Возвращает PDF из PAGES_IN_BOOK вертикальных страниц 9:16."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".pdf.tmp")
    book = _Pages(tmp, profile, story, mock, cover_has_title)
    book.cover(images["cover"])
    book.dedication()
    for i in range(1, len(story.pages) + 1):                       # старые книги бывали из другого числа страниц
        book.story_page(i, images[f"p{i}"])
    book.finale()
    book.c.save()
    tmp.replace(out_path)
    log.info("PDF для телефона собран (%s страниц 9:16)", PAGES_IN_BOOK)
    return out_path
