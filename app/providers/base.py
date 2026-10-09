"""Интерфейсы провайдеров. Каждый внешний сервис спрятан за таким интерфейсом."""
from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from typing import Callable, Sequence

from ..errors import ProviderError, StoryError, StoryValidationError
from ..profile import Profile
from ..story import Story, parse_story_json, validate_story
from ..writer import (ClarityProblem, Plan, Seeds, Violation, apply_fixes, assemble_story, check_story, hard_violations,
                      new_violations, parse_comprehension, parse_fixes, pick_seeds, validate_plan, violations_text)
from ..writer_prompts import (build_clarity_rewrite_prompt, build_comprehension_prompts, build_editor_prompts,
                              build_ky_proof_prompts, build_planner_prompts, build_system_prompt, build_user_prompt)

log = logging.getLogger(__name__)

PLAN_HINT = "Исправь ошибку и верни весь JSON плана заново — только JSON по схеме, без пояснений."
TEXT_HINT = ("Исправь ТОЛЬКО перечисленное, остальное оставь как было, и верни весь JSON заново — "
             "только JSON по схеме, без пояснений.")


class TextProvider(ABC):
    """Пишет книгу конвейером: режиссёр (план) → автор (текст) → редактор → код-валидатор.
    generate_story возвращает проверенную историю."""

    name = "base"
    max_retries = 2          # после первой попытки — ещё до 2 повторов с текстом ошибки (на каждом шаге: план и текст)
    polish = False           # проходы «понятность», «редактор» и (для кыргызского) «корректор»: у настоящих моделей включены, у заглушки нет
    clarity_rewrites = 2     # сколько раз автор переписывает непонятное по замечаниям «пятилетнего слушателя» (потом берём как есть)
    proof_model = ""         # отдельная модель для вычитки кыргызского (TEXT_PROOF_MODEL); пусто — основная
    rng: random.Random | None = None     # источник случайности для зёрен; в тестах random.Random(1), в работе SystemRandom
    simple_writer = False    # WRITER_MODE=simple: один запрос вместо конвейера (app/simple_writer.py); False — старый конвейер

    async def read_cover_text(self, image: bytes) -> str | None:
        """Читает крупную надпись на обложке (название), чтобы сверить её с настоящим названием.
        None — проверить нечем (заглушка, нет доступа к модели): тогда обложку принимаем как есть."""
        return None

    async def generate_story(self, profile: Profile) -> Story:
        if self.simple_writer:
            return await self._generate_simple(profile)
        seeds = pick_seeds(profile, self.rng)
        log.info("Зёрна книги: %s", seeds.to_dict())
        plan = await self._plan(profile, seeds)
        log.info("Режиссёр: план принят (помощник «%s», рефрен «%s»)", plan.helper_name, plan.refrain)
        story = await self._write(profile, plan, seeds)
        return await self._improved(profile, plan, story, seeds) if self.polish else story

    async def _generate_simple(self, profile: Profile) -> Story:
        """Простой писатель: один запрос с формой из 8 страниц и образцом тона, код проверяет только жёсткие правила,
        для кыргызского потом идёт корректор. Подробности и причины: app/simple_writer.py."""
        from .. import simple_writer as sw
        framework = sw.pick_framework(profile, self.rng)
        log.info("Простой писатель: форма сюжета «%s»", framework.ru if framework else "по пожеланию")
        story = await self._ask(sw.system_prompt(profile), sw.user_prompt(profile, framework),
                                lambda raw: sw.check(profile, raw, self.rng), what="текст книги", hint=TEXT_HINT)
        if profile.language == "ky" and self.polish:
            story = await self._proofread_ky(profile, None, story)
        return story

    async def _ask(self, system: str, user: str, check: Callable[[str], object], *, what: str, hint: str,
                   model: str | None = None, salvage: Callable[[], object | None] | None = None):
        """Один шаг конвейера: запрос, проверка ответа кодом, при ошибке повтор с ТОЧНЫМ текстом ошибки (до 1 + max_retries
        попыток). Если все попытки не прошли, salvage (если он есть) может достать из них лучший ответ с одними мелкими
        замечаниями; нет такого — StoryError."""
        messages: list[tuple[str, str]] = [("user", user)]
        attempts = 1 + self.max_retries
        last_error: StoryValidationError | None = None
        for attempt in range(attempts):
            raw = await (self._complete(system, messages, model) if model else self._complete(system, messages))
            try:
                return check(raw)
            except StoryValidationError as e:
                last_error = e
                log.warning("Ответ модели (%s) не прошёл проверку (попытка %s из %s): %s", what, attempt + 1, attempts, e)
                messages = messages + [
                    ("assistant", raw),
                    ("user", f"Твой ответ не прошёл проверку: {e}\n{hint}"),
                ]
        saved = salvage() if salvage else None
        if saved is not None:
            return saved
        raise StoryError(f"Модель {attempts} раза подряд вернула {what}, который не прошёл проверку: {last_error}")

    async def _plan(self, profile: Profile, seeds: Seeds) -> Plan:
        """Режиссёр: план книги JSON (сюжет, рефрен, герои для художника, сцены). Помощника и зёрна выбирает код."""
        system, user = build_planner_prompts(profile, seeds)
        return await self._ask(system, user, lambda raw: validate_plan(parse_story_json(raw), profile, seeds),
                               what="план книги", hint=PLAN_HINT)

    async def _write(self, profile: Profile, plan: Plan, seeds: Seeds) -> Story:
        """Автор: тексты страниц по плану на языке книги. Код проверяет лимиты по возрасту, бан-лист, имя героя и т.д.

        Нарушения бывают жёсткие (бренд, насилие, латиница, чужой язык, лимиты слов и знаков: такой текст нельзя отдавать)
        и мелкие (повтор слова, многоточие, чувства, длина названия, число страниц с рефреном: Violation.soft).
        Автору возвращаются все; но если после всех попыток остались только мелкие, берём лучшую из таких книг вместо того,
        чтобы ронять заказ (администратору уходит запись в лог)."""
        system = build_system_prompt(profile)
        user = build_user_prompt(profile, plan, seeds)
        acceptable: list[tuple[Story, list[Violation]]] = []      # книги без жёстких нарушений, по порядку попыток

        def check(raw: str) -> Story:
            story = assemble_story(profile, plan, parse_story_json(raw))
            violations = check_story(story, profile, plan)
            if not violations:
                return story
            if not hard_violations(violations):
                acceptable.append((story, violations))
            raise StoryValidationError("найдены ошибки в тексте:\n" + violations_text(violations))

        def salvage() -> Story | None:
            if not acceptable:
                return None
            # меньше всего замечаний; при равенстве — более поздняя попытка (автор уже видел замечания)
            story, left = min(reversed(acceptable), key=lambda item: len(item[1]))
            log.warning("Книга принята с мелкими замечаниями (%s): %s", len(left), "; ".join(str(v) for v in left[:6]))
            return story

        return await self._ask(system, user, check, what="текст книги", hint=TEXT_HINT, salvage=salvage)

    async def _improved(self, profile: Profile, plan: Plan, story: Story, seeds: Seeds | None = None) -> Story:
        """Проходы после черновика: «понятность» (пятилетний слушатель), «редактор» для всех языков, затем «корректор»
        только для кыргызского."""
        story = await self._clarified(profile, plan, story, seeds)
        story = await self._edited(profile, plan, story)
        if profile.language == "ky":
            story = await self._proofread_ky(profile, plan, story)
        return story

    async def _clarified(self, profile: Profile, plan: Plan, story: Story, seeds: Seeds | None = None) -> Story:
        """Понятно ли пятилетнему: отдельный запрос пересказывает каждую страницу одной фразой и называет непонятные слова,
        предметы и скачки логики. Есть замечания: автор переписывает страницы с проблемами (до clarity_rewrites раз), после
        каждой правки проверка идёт заново. Любой сбой проверки или правки оставляет текст как есть: заказ из-за этого не падает."""
        for attempt in range(self.clarity_rewrites + 1):
            try:
                system, user = build_comprehension_prompts(profile, story, plan)
                report = parse_comprehension(await self._complete(system, [("user", user)]))
            except (StoryValidationError, ProviderError, KeyError, TypeError, AttributeError, ValueError) as e:
                log.warning("Проверка понятности не удалась, оставляю текст: %s", e)
                return story
            log.info("Понятность: непонятного %s; суть: %s", len(report.problems), report.summary or "—")
            if report.clear:
                return story
            if attempt == self.clarity_rewrites:
                log.warning("Книга оставлена с замечаниями понятности (%s): %s", len(report.problems),
                            "; ".join(f"{p.page or 'вся'}: {p.what}" for p in report.problems[:5]))
                return story
            rewritten = await self._rewrite_for_clarity(profile, plan, seeds, story, report.problems)
            if rewritten is story:
                return story
            story = rewritten
        return story

    async def _rewrite_for_clarity(self, profile: Profile, plan: Plan, seeds: Seeds | None, story: Story,
                                   problems: Sequence[ClarityProblem]) -> Story:
        """Автор переписывает только страницы с проблемами. Новая книга не должна иметь жёстких нарушений валидатора;
        не вышло (в том числе после повторов с точным текстом ошибки) — остаётся прежний текст."""
        system = build_system_prompt(profile)
        user = build_clarity_rewrite_prompt(profile, plan, seeds, story, problems)

        def check(raw: str) -> Story:
            rewritten = assemble_story(profile, plan, parse_story_json(raw))
            violations = check_story(rewritten, profile, plan)
            if hard_violations(violations):
                raise StoryValidationError("найдены ошибки в тексте:\n" + violations_text(violations))
            return rewritten

        try:
            result = await self._ask(system, user, check, what="правка понятности", hint=TEXT_HINT)
        except (StoryError, ProviderError) as e:
            log.warning("Автор не смог переписать непонятное, оставляю текст: %s", e)
            return story
        log.info("Автор переписал непонятное (замечаний %s)", len(problems))
        return result

    async def _edited(self, profile: Profile, plan: Plan, story: Story) -> Story:
        """Редактор проверяет страницы по чек-листу и возвращает [{page, problem, fixed_text}] только для плохих. Правки
        вставляются по одной; принятая правка не должна добавлять нарушений валидатора. Один цикл; любая неудача (и
        ошибка сервиса тоже) — остаётся черновик: заказ из-за этого не падает."""
        system, user = build_editor_prompts(profile, story, plan)
        try:
            raw = await self._complete(system, [("user", user)])
            fixes = parse_fixes(raw)
            result, applied = apply_fixes(story, fixes, profile, plan)
        except (StoryValidationError, ProviderError, KeyError, TypeError, AttributeError, ValueError) as e:
            log.warning("Редактор не справился, оставляю черновик: %s", e)
            return story
        log.info("Редактор: предложено правок %s, принято %s (страницы %s)", len(fixes), len(applied), applied)
        return result

    async def _proofread_ky(self, profile: Profile, plan: Plan, story: Story) -> Story:
        """Строгий корректор-носитель кыргызского: правит орфографию, грамматику и кальки, не трогая сюжет.
        Идёт после редактора; любая неудача — остаётся текст редактора. Модель берётся из TEXT_PROOF_MODEL.
        Страницы короткие: после правки они обязаны остаться в лимитах (новые нарушения валидатора отклоняют правку)."""
        system, user = build_ky_proof_prompts(profile, story)
        return await self._rewrite_texts(profile, story, system, user, step="Корректор кыргызского",
                                         keep="прежний текст", min_ratio=0.8, max_ratio=1.25,
                                         model=self.proof_model or None, guard=_proof_guard(profile, plan))

    async def _rewrite_texts(self, profile: Profile, story: Story, system: str, user: str, *, step: str, keep: str,
                             min_ratio: float, max_ratio: float | None = None, model: str | None = None,
                             guard: Callable[[Story, Story], None] | None = None) -> Story:
        """Проход «корректор»: один запрос, из ответа берутся только тексты (название, страницы, мораль, пожелание),
        сцены, актёры и рефрен остаются прежними. Ответ проверяется как обычная книга; любая неудача возвращает story
        без изменений."""
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
        log.info("%s улучшил текст книги", step)
        return result

    @abstractmethod
    async def _complete(self, system: str, messages: list[tuple[str, str]], model: str | None = None) -> str:
        """Один запрос к модели. messages — пары (роль 'user'|'assistant', текст). Возвращает сырой текст.
        model — необязательная другая модель на этот запрос (вычитка кыргызского); провайдер без выбора модели его игнорирует."""


KY_LETTERS = "үөңҮӨҢ"


def _ky_letters(story: Story) -> int:
    texts = [story.title, story.moral, story.wish] + [p.text for p in story.pages]
    return sum(ch in KY_LETTERS for text in texts for ch in text)


def _proof_guard(profile: Profile, plan: Plan | None) -> Callable[[Story, Story], None]:
    """Корректор не должен ни переводить книгу на русский, ни раздувать страницы за лимиты, ни ломать рефрен."""
    def guard(before: Story, after: Story) -> None:
        _still_kyrgyz(before, after)
        fresh = new_violations(check_story(before, profile, plan), check_story(after, profile, plan))
        if fresh:
            raise StoryValidationError("корректор нарушил правила текста:\n" + violations_text(fresh, 5))
    return guard


def _still_kyrgyz(before: Story, after: Story) -> None:
    """Корректор не должен переводить книгу на русский: буквы ү, ө, ң есть только в кыргызском тексте.
    Если их стало вдвое меньше, а было достаточно много, это перевод или порча текста."""
    was = _ky_letters(before)
    if was >= 10 and _ky_letters(after) < was / 2:
        raise StoryValidationError("корректор, похоже, перевёл текст на русский")


class ImageProvider(ABC):
    """Рисует иллюстрацию. Возвращает байты картинки (PNG, JPEG или WebP)."""

    name = "base"
    supports_reference = False
    renders_text = False         # умеет ли аккуратно рисовать буквы (название на обложке)
    needs_character_sheet = False   # нужен ли «лист героев»: герои на нейтральном фоне как образец для всех страниц (иначе страницы копируют фон обложки)

    @abstractmethod
    async def generate(self, prompt: str, refs: Sequence[bytes] | None = None, size: str = "1024x1024",
                       *, label: str | None = None) -> bytes:
        """label — необязательная подпись («Обложка», «Страница 3»), её используют только заглушки."""
