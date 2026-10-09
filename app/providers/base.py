"""Интерфейсы провайдеров. Каждый внешний сервис спрятан за таким интерфейсом."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Callable, Sequence

from ..errors import ProviderError, StoryError, StoryValidationError
from ..profile import Profile
from ..prompts import build_editor_prompts, build_ky_proof_prompts, build_system_prompt, build_user_prompt
from ..story import Page, Story, parse_story_json, validate_story

log = logging.getLogger(__name__)


class TextProvider(ABC):
    """Пишет сказку. generate_story возвращает проверенную историю."""

    name = "base"
    max_retries = 2          # после первой попытки — ещё до 2 повторов с текстом ошибки
    polish = False           # проходы «редактор» и (для кыргызского) «корректор»: у настоящих моделей включены, у заглушки нет
    proof_model = ""         # отдельная модель для вычитки кыргызского (TEXT_PROOF_MODEL); пусто — основная

    async def read_cover_text(self, image: bytes) -> str | None:
        """Читает крупную надпись на обложке (название), чтобы сверить её с настоящим названием.
        None — проверить нечем (заглушка, нет доступа к модели): тогда обложку принимаем как есть."""
        return None

    async def generate_story(self, profile: Profile) -> Story:
        system = build_system_prompt(profile)
        messages: list[tuple[str, str]] = [("user", build_user_prompt(profile))]
        last_error: StoryValidationError | None = None
        for attempt in range(1 + self.max_retries):
            raw = await self._complete(system, messages)
            try:
                story = validate_story(parse_story_json(raw), profile.language)
                return await self._improved(profile, story) if self.polish else story
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

    async def _improved(self, profile: Profile, story: Story) -> Story:
        """Проходы после черновика: «редактор» для всех языков, затем «корректор» только для кыргызского."""
        story = await self._polished(profile, story)
        if profile.language == "ky":
            story = await self._proofread_ky(profile, story)
        return story

    async def _polished(self, profile: Profile, story: Story) -> Story:
        """Редактор переписывает тексты (название, страницы, мораль, пожелание), картинки и описания героя
        остаются прежними. Любая неудача — берём черновик: заказ из-за этого не падает."""
        system, user = build_editor_prompts(profile, story)
        return await self._rewrite_texts(profile, story, system, user, step="Редактор", keep="черновик",
                                         min_ratio=0.6)

    async def _proofread_ky(self, profile: Profile, story: Story) -> Story:
        """Строгий корректор-носитель кыргызского: правит орфографию, грамматику и кальки, не трогая сюжет.
        Идёт после редактора; любая неудача — остаётся текст редактора. Модель берётся из TEXT_PROOF_MODEL."""
        system, user = build_ky_proof_prompts(profile, story)
        return await self._rewrite_texts(profile, story, system, user, step="Корректор кыргызского",
                                         keep="прежний текст", min_ratio=0.8, max_ratio=1.25,
                                         model=self.proof_model or None, guard=_still_kyrgyz)

    async def _rewrite_texts(self, profile: Profile, story: Story, system: str, user: str, *, step: str, keep: str,
                             min_ratio: float, max_ratio: float | None = None, model: str | None = None,
                             guard: Callable[[Story, Story], None] | None = None) -> Story:
        """Общая часть проходов «редактор» и «корректор»: один запрос, из ответа берутся только тексты
        (название, страницы, мораль, пожелание), сцены и описание героя остаются прежними. Ответ проверяется
        как обычная сказка; любая неудача возвращает story без изменений."""
        try:
            messages = [("user", user)]
            raw = await (self._complete(system, messages, model) if model else self._complete(system, messages))
            data = parse_story_json(raw)
            pages = data.get("pages")
            if not isinstance(pages, list) or len(pages) != len(story.pages):
                raise StoryValidationError(f"{step}: неверное число страниц")
            merged = story.to_dict()
            merged["title"] = data.get("title") or story.title
            merged["moral"] = data.get("moral") or story.moral
            merged["wish"] = data.get("wish") or story.wish
            for mp, ep in zip(merged["pages"], pages):
                text = ep.get("text") if isinstance(ep, dict) else None
                if not isinstance(text, str) or len(text.strip()) < min_ratio * len(mp["text"]):
                    raise StoryValidationError(f"{step}: страница сокращена слишком сильно")
                if max_ratio and len(text.strip()) > max_ratio * len(mp["text"]):
                    raise StoryValidationError(f"{step}: страница раздута слишком сильно")
                mp["text"] = text
            result = validate_story(merged, profile.language)
            if guard:
                guard(story, result)
        except (StoryValidationError, ProviderError, KeyError, TypeError, AttributeError) as e:
            log.warning("%s не справился, оставляю %s: %s", step, keep, e)
            return story
        log.info("%s улучшил текст сказки", step)
        return result

    @abstractmethod
    async def _complete(self, system: str, messages: list[tuple[str, str]], model: str | None = None) -> str:
        """Один запрос к модели. messages — пары (роль 'user'|'assistant', текст). Возвращает сырой текст.
        model — необязательная другая модель на этот запрос (вычитка кыргызского); провайдер без выбора модели его игнорирует."""


KY_LETTERS = "үөңҮӨҢ"


def _ky_letters(story: Story) -> int:
    texts = [story.title, story.moral, story.wish] + [p.text for p in story.pages]
    return sum(ch in KY_LETTERS for text in texts for ch in text)


def _still_kyrgyz(before: Story, after: Story) -> None:
    """Корректор не должен переводить сказку на русский: буквы ү, ө, ң есть только в кыргызском тексте.
    Если их стало вдвое меньше, а было достаточно много, это перевод или порча текста."""
    was = _ky_letters(before)
    if was >= 10 and _ky_letters(after) < was / 2:
        raise StoryValidationError("корректор, похоже, перевёл текст на русский")


class ImageProvider(ABC):
    """Рисует иллюстрацию. Возвращает байты картинки (PNG, JPEG или WebP)."""

    name = "base"
    supports_reference = False
    renders_text = False         # умеет ли аккуратно рисовать буквы (название на обложке)

    @abstractmethod
    async def generate(self, prompt: str, refs: Sequence[bytes] | None = None, size: str = "1024x1024",
                       *, label: str | None = None) -> bytes:
        """label — необязательная подпись («Обложка», «Страница 3»), её используют только заглушки."""
