"""Сборка одной книги: текст → обложка → 8 иллюстраций → PDF.

Используется и сервером (с обновлением статуса в базе), и demo.py (без сервера).
Каждая готовая картинка сразу сохраняется на диск, чтобы Mini App показал её до сборки PDF.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from .errors import ProviderError
from .imaging import normalize_image
from .pdfbook import build_pdf
from .placeholder import draw_placeholder
from .profile import Profile
from .prompts import build_cover_prompt, build_page_prompt
from .providers.base import ImageProvider, TextProvider
from .story import Story

log = logging.getLogger(__name__)

IMAGE_ATTEMPTS = 3
RETRY_PAUSES = (2.0, 6.0)        # паузы между попытками одной картинки, секунды
PAGE_IMAGE_NAMES = [f"p{i}" for i in range(1, 9)]

StatusCb = Callable[[str], Awaitable[None]]
StoryCb = Callable[[Story], Awaitable[None]]


@dataclass
class BookResult:
    story: Story
    pdf_path: Path
    failed_pages: list[str] = field(default_factory=list)   # 'cover', 'p3', ...
    failure_notes: list[str] = field(default_factory=list)
    min_text_pt: float = 17.0


async def _noop(*_a, **_k) -> None:
    return None


async def _draw_with_retries(provider: ImageProvider, prompt: str, refs: list[bytes] | None, label: str,
                             sem: asyncio.Semaphore) -> bytes:
    """Одна картинка: до 3 попыток с паузами. Неисправимые ошибки (ключ, деньги) пробрасываются сразу."""
    last: Exception | None = None
    for attempt in range(IMAGE_ATTEMPTS):
        try:
            async with sem:
                raw = await provider.generate(prompt, refs or None, "1024x1024", label=label)
            return await asyncio.to_thread(normalize_image, raw)
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
    image_sem: asyncio.Semaphore | None = None,
    mock: bool = False,
    on_status: StatusCb = _noop,
    on_story: StoryCb = _noop,
) -> BookResult:
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
    failed: list[str] = []
    notes: list[str] = []

    async def make(name: str, prompt: str, refs: list[bytes] | None, label: str, description: str) -> bytes:
        try:
            data = await _draw_with_retries(image, prompt, refs, label, sem)
            ok = True
        except ProviderError as e:
            if e.fatal:
                raise
            failed.append(name)
            notes.append(f"{label}: {e.message}")
            log.error("Не удалось нарисовать «%s»: %s", label, e.message)
            data = await asyncio.to_thread(draw_placeholder, label, "Иллюстрация не получилась", description,
                                           caption="НЕ НАРИСОВАНО")
            ok = False
        (out_dir / f"{name}.jpg").write_bytes(data)
        return data if ok else b""

    cover_prompt = build_cover_prompt(story, profile, photo_ref=use_photo)
    cover_bytes = await make("cover", cover_prompt, [photo] if use_photo else None, "Обложка", story.title)
    cover_is_real = bool(cover_bytes)

    page_refs: list[bytes] | None = None
    if image.supports_reference and cover_is_real:
        page_refs = [cover_bytes] + ([photo] if use_photo else [])

    async def page(i: int) -> None:
        prompt = build_page_prompt(story, profile, i, has_refs=bool(page_refs))
        await make(f"p{i}", prompt, page_refs, f"Страница {i}", story.pages[i - 1].scene)

    tasks = [asyncio.create_task(page(i)) for i in range(1, 9)]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    # 3. PDF
    await on_status("assembling")
    images = {"cover": out_dir / "cover.jpg", **{f"p{i}": out_dir / f"p{i}.jpg" for i in range(1, 9)}}
    pdf_path = out_dir / "book.pdf"
    await asyncio.to_thread(build_pdf, story, profile, images, pdf_path, mock=mock)
    return BookResult(story=story, pdf_path=pdf_path, failed_pages=failed, failure_notes=notes)
