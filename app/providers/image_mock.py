"""Mock-провайдер картинок: Pillow рисует заглушку с подписью и кратким описанием сцены. Сети нет."""
from __future__ import annotations

import asyncio
import re
from typing import Sequence

from ..layout import calm_side, parse_size
from ..placeholder import draw_placeholder
from .base import ImageProvider

_PAGE_NUMBER = re.compile(r"(\d+)\s*$")


class MockImageProvider(ImageProvider):
    name = "mock"
    # Заглушка делает вид, что принимает референсы (фото), чтобы весь путь можно было проверить
    # без ключей. На рисунок референсы не влияют.
    supports_reference = True

    def __init__(self, delay: float = 0.0):
        self.delay = delay

    async def generate(self, prompt: str, refs: Sequence[bytes] | None = None, size: str = "1024x1024",
                       *, label: str | None = None) -> bytes:
        if self.delay:
            await asyncio.sleep(self.delay)
        caption = "ЗАГЛУШКА" + (f" · фото {len(refs)} шт." if refs else "")
        number = _PAGE_NUMBER.search(label or "")
        side = calm_side(int(number.group(1))) if number else None     # «Страница 3» → спокойная половина справа
        return await asyncio.to_thread(draw_placeholder, label or "Иллюстрация", prompt, prompt, caption=caption,
                                       size=parse_size(size), calm_side=side)
