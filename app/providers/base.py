"""Интерфейсы провайдеров. Каждый внешний сервис спрятан за таким интерфейсом."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Sequence

from ..errors import StoryError, StoryValidationError
from ..profile import Profile
from ..prompts import build_system_prompt, build_user_prompt
from ..story import Story, parse_story_json, validate_story

log = logging.getLogger(__name__)


class TextProvider(ABC):
    """Пишет сказку. generate_story возвращает проверенную историю."""

    name = "base"
    max_retries = 2          # после первой попытки — ещё до 2 повторов с текстом ошибки

    async def generate_story(self, profile: Profile) -> Story:
        system = build_system_prompt(profile)
        messages: list[tuple[str, str]] = [("user", build_user_prompt(profile))]
        last_error: StoryValidationError | None = None
        for attempt in range(1 + self.max_retries):
            raw = await self._complete(system, messages)
            try:
                return validate_story(parse_story_json(raw), profile.language)
            except StoryValidationError as e:
                last_error = e
                log.warning("Ответ модели не прошёл проверку (попытка %s из %s): %s",
                            attempt + 1, 1 + self.max_retries, e)
                messages = messages + [
                    ("assistant", raw),
                    ("user", f"Твой ответ не прошёл проверку: {e}\n"
                             "Исправь ошибку и верни весь JSON заново — только JSON по схеме, без пояснений."),
                ]
        raise StoryError(
            f"Модель {1 + self.max_retries} раза подряд вернула сказку, которая не прошла проверку: {last_error}"
        )

    @abstractmethod
    async def _complete(self, system: str, messages: list[tuple[str, str]]) -> str:
        """Один запрос к модели. messages — пары (роль 'user'|'assistant', текст). Возвращает сырой текст."""


class ImageProvider(ABC):
    """Рисует иллюстрацию. Возвращает байты картинки (PNG, JPEG или WebP)."""

    name = "base"
    supports_reference = False

    @abstractmethod
    async def generate(self, prompt: str, refs: Sequence[bytes] | None = None, size: str = "1024x1024",
                       *, label: str | None = None) -> bytes:
        """label — необязательная подпись («Обложка», «Страница 3»), её используют только заглушки."""
