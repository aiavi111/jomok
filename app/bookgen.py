"""Сборка одной книги: текст → обложка (квадрат 1024×1024) → широкие иллюстрации страниц (PAGES, 2048×1024) → PDF разворотами.

Используется и сервером (с обновлением статуса в базе), и demo.py (без сервера).
Каждая готовая картинка сразу сохраняется на диск, чтобы Mini App показал её до сборки PDF.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from .errors import ProviderError
from .imaging import normalize_image
from .layout import COVER_QUALITY, COVER_SIZE, PAGE_QUALITY, PAGE_SIZE, calm_side, size_str
from .overlay import DEFAULT_MODE, MODES
from .pdfbook import build_pdf
from .placeholder import draw_placeholder
from .profile import Profile
from .prompts import (build_cover_prompt, build_page_prompt, build_sheet_prompt, has_sheet_characters, person_in_scene,
                      person_photo_family)
from .providers.base import ImageProvider, TextProvider
from .story import PAGES, Story

log = logging.getLogger(__name__)

IMAGE_ATTEMPTS = 3
RETRY_PAUSES = (2.0, 6.0)        # паузы между попытками одной картинки, секунды
PAGE_IMAGE_NAMES = [f"p{i}" for i in range(1, PAGES + 1)]    # p1..pN; вместе с обложкой PAGES + 1 картинок

StatusCb = Callable[[str], Awaitable[None]]
StoryCb = Callable[[Story], Awaitable[None]]


@dataclass
class BookResult:
    story: Story
    pdf_path: Path
    failed_pages: list[str] = field(default_factory=list)   # 'cover', 'p3', ...
    failure_notes: list[str] = field(default_factory=list)
    min_text_pt: float = 30.0
    cover_has_title: bool = False      # название нарисовано на самой обложке (иначе в PDF кладётся плашка)
    text_styles: list[str] = field(default_factory=list)   # оформление текста на каждой странице истории (app/overlay.py)


COVER_ATTEMPTS = 3                                 # сколько раз перерисовываем обложку, если в названии ошибка
COVER_META = "cover.meta.json"
LAYOUT_META = "layout.meta.json"                   # как лежит текст на страницах (для Mini App): стороны и оформление
_LOOKALIKE = str.maketrans({"a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к", "m": "м", "o": "о", "p": "р",
                            "t": "т", "x": "х", "y": "у", "i": "і", "ё": "е", "ү": "у", "ө": "о", "ң": "н"})


def title_key(text: str) -> str:
    """Название для сравнения: буквы без регистра, знаков и пробелов; похожие латинские буквы приравнены к кириллице.
    Ү/ү, Ө/ө, Ң/ң приравнены к у, о, н: модель при чтении нередко путает именно их, остальное сверяется строго."""
    return re.sub(r"[\W_]+", "", text.casefold().translate(_LOOKALIKE))


def read_cover_meta(out_dir: Path) -> dict:
    try:
        return json.loads((Path(out_dir) / COVER_META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_layout_meta(out_dir: Path) -> dict:
    try:
        return json.loads((Path(out_dir) / LAYOUT_META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


async def _noop(*_a, **_k) -> None:
    return None


async def _draw_with_retries(provider: ImageProvider, prompt: str, refs: list[bytes] | None, label: str,
                             sem: asyncio.Semaphore, size: tuple[int, int] = COVER_SIZE,
                             quality: int = COVER_QUALITY) -> bytes:
    """Одна картинка: до 3 попыток с паузами. Неисправимые ошибки (ключ, деньги) пробрасываются сразу.
    Провайдеру уходит размер «ШxВ» (обложка 1024x1024, страница 2048x1024); что бы он ни вернул, результат
    обрезается по центру до этого соотношения и приводится ровно к этому размеру."""
    last: Exception | None = None
    for attempt in range(IMAGE_ATTEMPTS):
        try:
            async with sem:
                raw = await provider.generate(prompt, refs or None, size_str(size), label=label)
            return await asyncio.to_thread(normalize_image, raw, size, quality)
        except ProviderError as e:
            if e.fatal:
                raise
            last = e
            if e.no_retry:
                break
        except Exception as e:                      # битая картинка и т.п.
            last = ProviderError(f"Сервис вернул не картинку или повреждённый файл ({type(e).__name__}).")
        if attempt < IMAGE_ATTEMPTS - 1:
            log.warning("%s: попытка %s не удалась, повторю", label, attempt + 1)
            await asyncio.sleep(RETRY_PAUSES[min(attempt, len(RETRY_PAUSES) - 1)])
    assert last is not None
    raise last


async def build_book(
    profile: Profile,
    text: TextProvider,
    image: ImageProvider,
    out_dir: Path,
    *,
    photo: bytes | None = None,
    person_photo: bytes | None = None,
    image_sem: asyncio.Semaphore | None = None,
    mock: bool = False,
    overlay_mode: str = DEFAULT_MODE,
    on_status: StatusCb = _noop,
    on_story: StoryCb = _noop,
) -> BookResult:
    if overlay_mode not in MODES:                 # до платных запросов: неверная настройка не должна стоить денег
        raise ValueError(f"overlay_mode должен быть одним из: {', '.join(MODES)}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = image_sem or asyncio.Semaphore(3)

    # 1. текст
    await on_status("writing")
    story = await text.generate_story(profile)
    (out_dir / "story.json").write_text(json.dumps(story.to_dict(), ensure_ascii=False), encoding="utf-8")
    await on_story(story)

    # 2. картинки
    await on_status("drawing")
    use_photo = bool(photo) and image.supports_reference
    use_parent = bool(person_photo) and image.supports_reference and person_photo_family(story)    # фото человека нужно, только если он есть в книге
    failed: list[str] = []
    notes: list[str] = []

    async def make(name: str, prompt: str, refs: list[bytes] | None, label: str, description: str) -> bytes:
        size, quality = (COVER_SIZE, COVER_QUALITY) if name == "cover" else (PAGE_SIZE, PAGE_QUALITY)
        try:
            data = await _draw_with_retries(image, prompt, refs, label, sem, size, quality)
            ok = True
        except ProviderError as e:
            if e.fatal:
                raise
            failed.append(name)
            notes.append(f"{label}: {e.message}")
            log.error("Не удалось нарисовать «%s»: %s", label, e.message)
            number = int(name[1:]) if name[1:].isdigit() else None
            data = await asyncio.to_thread(draw_placeholder, label, "Иллюстрация не получилась", description,
                                           caption="НЕ НАРИСОВАНО", size=size,
                                           calm_side=calm_side(number) if number else None)
            ok = False
        (out_dir / f"{name}.jpg").write_bytes(data)
        return data if ok else b""

    # лист героев: помощник, друзья и взрослый на чисто белом фоне (без фото: с фото модель тянет в кадр пейзаж). Обложка и
    # страницы берут его как образец внешности и рисуют своё место, а не копируют фон обложки. Не получился (или провайдер
    # без референсов) — работаем по-старому: образец — обложка.
    sheet_bytes = b""
    if image.supports_reference and getattr(image, "needs_character_sheet", False) and has_sheet_characters(story):
        try:
            sheet_bytes = await _draw_with_retries(image, build_sheet_prompt(story, profile), None, "Лист героев", sem,
                                                   COVER_SIZE, COVER_QUALITY)
            (out_dir / "sheet.jpg").write_bytes(sheet_bytes)
        except ProviderError as e:
            if e.fatal:
                raise
            log.warning("Лист героев не получился (%s), страницы будут брать образец с обложки", e.message)
            sheet_bytes = b""
    identity_refs = ([photo] if use_photo else []) + ([sheet_bytes] if sheet_bytes else [])
    cover_parent = use_parent and person_in_scene(story, story.pages[0].scene)
    cover_refs = (identity_refs + ([person_photo] if cover_parent else [])) or None    # фото человека всегда последнее
    cover_bytes = b""
    cover_has_title = False
    if image.renders_text:
        # название рисует сама модель; после каждой попытки другая модель читает надпись и сверяет с названием
        for attempt in range(1, COVER_ATTEMPTS + 1):
            prompt = build_cover_prompt(story, profile, photo_ref=use_photo, title_in_image=True, person_ref=cover_parent)
            cover_bytes = await make("cover", prompt, cover_refs, "Обложка", story.title)
            if not cover_bytes:
                break
            try:
                seen = await text.read_cover_text(cover_bytes)
            except Exception:          # проверка не должна ронять заказ
                log.exception("Не удалось проверить надпись на обложке")
                seen = None
            if seen is None or title_key(seen) == title_key(story.title):
                cover_has_title = True
                break
            log.warning("Обложка, попытка %s из %s: на ней прочитано «%s», ожидалось «%s»",
                        attempt, COVER_ATTEMPTS, seen, story.title)
        else:
            cover_bytes = b""          # все попытки с ошибкой в названии: рисуем без букв, название ляжет плашкой
            notes.append("Название на обложке дважды получилось с ошибкой, обложка нарисована без букв")
    if not cover_bytes and not (failed and "cover" in failed):
        cover_prompt = build_cover_prompt(story, profile, photo_ref=use_photo, person_ref=cover_parent)
        cover_bytes = await make("cover", cover_prompt, cover_refs, "Обложка", story.title)
        cover_has_title = False
    (out_dir / COVER_META).write_text(json.dumps({"title_in_image": cover_has_title}), encoding="utf-8")
    cover_is_real = bool(cover_bytes)

    page_refs: list[bytes] | None = None
    if image.supports_reference and sheet_bytes:
        page_refs = identity_refs
    elif image.supports_reference and cover_is_real:
        page_refs = [cover_bytes] + ([photo] if use_photo else [])

    async def page(i: int) -> None:
        with_parent = use_parent and person_in_scene(story, story.pages[i - 1].scene)
        refs = ((page_refs or []) + [person_photo]) if with_parent else page_refs      # кадры без этого человека его фото не получают
        prompt = build_page_prompt(story, profile, i, has_refs=bool(page_refs), person_ref=with_parent)
        await make(f"p{i}", prompt, refs, f"Страница {i}", story.pages[i - 1].scene)

    tasks = [asyncio.create_task(page(i)) for i in range(1, PAGES + 1)]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    # 3. PDF
    await on_status("assembling")
    images = {"cover": out_dir / "cover.jpg", **{name: out_dir / f"{name}.jpg" for name in PAGE_IMAGE_NAMES}}
    pdf_path = out_dir / "book.pdf"
    report: dict = {}
    await asyncio.to_thread(build_pdf, story, profile, images, pdf_path, mock=mock, cover_has_title=cover_has_title,
                            overlay_mode=overlay_mode, report=report)
    (out_dir / LAYOUT_META).write_text(json.dumps({k: report.get(k) for k in ("text_sides", "text_styles", "overlay_mode")},
                                                  ensure_ascii=False), encoding="utf-8")
    return BookResult(story=story, pdf_path=pdf_path, failed_pages=failed, failure_notes=notes,
                      cover_has_title=cover_has_title, text_styles=report.get("text_styles", []),
                      min_text_pt=report.get("min_text_pt", 20.0))
