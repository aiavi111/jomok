"""Mock-провайдер картинок: Pillow рисует заглушку с подписью и кратким описанием сцены. Сети нет."""
from __future__ import annotations

import asyncio
from typing import Sequence

from ..placeholder import draw_placeholder
from .base import ImageProvider


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
        return await asyncio.to_thread(draw_placeholder, label or "Иллюстрация", prompt, prompt, caption=caption)
