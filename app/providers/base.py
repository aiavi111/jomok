"""Интерфейсы провайдеров. Каждый внешний сервис спрятан за таким интерфейсом."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Sequence

from ..errors import ProviderError, StoryError, StoryValidationError
from ..profile import Profile
from ..prompts import build_editor_prompts, build_system_prompt, build_user_prompt
from ..story import Page, Story, parse_story_json, validate_story

log = logging.getLogger(__name__)


class TextProvider(ABC):
    """Пишет сказку. generate_story возвращает проверенную историю."""

    name = "base"
    max_retries = 2          # после первой попытки — ещё до 2 повторов с текстом ошибки
    polish = False           # второй проход «редактор»: у настоящих моделей включён, у заглушки нет

    async def generate_story(self, profile: Profile) -> Story:
        system = build_system_prompt(profile)
        messages: list[tuple[str, str]] = [("user", build_user_prompt(profile))]
        last_error: StoryValidationError | None = None
        for attempt in range(1 + self.max_retries):
            raw = await self._complete(system, messages)
            try:
                story = validate_story(parse_story_json(raw), profile.language)
                return await self._polished(profile, story) if self.polish else story
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

    async def _polished(self, profile: Profile, story: Story) -> Story:
        """Редактор переписывает тексты (название, страницы, мораль, пожелание), картинки и описания героя
        остаются прежними. Любая неудача — берём черновик: заказ из-за этого не падает."""
        try:
            system, user = build_editor_prompts(profile, story)
            data = parse_story_json(await self._complete(system, [("user", user)]))
            pages = data.get("pages")
            if not isinstance(pages, list) or len(pages) != len(story.pages):
                raise StoryValidationError("редактор вернул неверное число страниц")
            merged = story.to_dict()
            merged["title"] = data.get("title") or story.title
            merged["moral"] = data.get("moral") or story.moral
            merged["wish"] = data.get("wish") or story.wish
            for mp, ep in zip(merged["pages"], pages):
                text = ep.get("text") if isinstance(ep, dict) else None
                if not isinstance(text, str) or len(text.strip()) < 0.6 * len(mp["text"]):
                    raise StoryValidationError("редактор сократил страницу слишком сильно")
                mp["text"] = text
            polished = validate_story(merged, profile.language)
        except (StoryValidationError, ProviderError, KeyError, TypeError, AttributeError) as e:
            log.warning("Редактор не справился, оставляю черновик: %s", e)
            return story
        log.info("Редактор улучшил текст сказки")
        return polished

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
