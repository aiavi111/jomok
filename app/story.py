"""Сказка в виде проверенного JSON.

Модель текста обязана вернуть JSON такого вида (см. prompts.STORY_SCHEMA_TEXT).
validate_story проверяет структуру; текст ошибки возвращается модели при повторе.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .errors import StoryValidationError
from .textutil import cyrillic_ratio, word_count

log = logging.getLogger(__name__)

PAGES = 8           # страниц в сказке (максимум по решению владельца); картинок на одну больше (обложка)

# Лимиты из задания и допуск 30%: модели часто чуть превышают длину, а повтор запроса стоит денег.
LIMITS = {
    "title": (50, 65),
    "moral": (140, 180),
    "wish": (200, 260),
    "page_text": (1200, 1200),
    "scene": (700, 700),
    "hero_visual": (900, 900),
    "style_note": (400, 400),
}


@dataclass(frozen=True)
class Page:
    text: str
    scene: str


@dataclass(frozen=True)
class Story:
    title: str
    hero_visual: str
    style_note: str
    pages: tuple[Page, ...]
    moral: str
    wish: str

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "hero_visual": self.hero_visual,
            "style_note": self.style_note,
            "pages": [{"text": p.text, "scene": p.scene} for p in self.pages],
            "moral": self.moral,
            "wish": self.wish,
        }

    @classmethod
    def from_dict(cls, data: dict, language: str | None = None) -> "Story":
        """Читает уже сохранённую сказку (story.json). Число страниц не проверяется строго: книги, созданные
        после смены числа страниц (раньше было 8, потом 10), остаются доступными для просмотра и повторной отправки."""
        return validate_story(data, language, exact_pages=False)


_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def parse_story_json(raw: str) -> dict:
    """Достаёт JSON из ответа модели.

    Допускает обёртку ```json ... ```, пояснение перед JSON и мусор после него: модели (в том числе Gemini)
    иногда дописывают после готового объекта лишние символы, поэтому берётся первый полный объект."""
    if not isinstance(raw, str) or not raw.strip():
        raise StoryValidationError("Ответ пустой. Верни JSON по схеме.")
    text = _FENCE.sub("", raw.strip()).strip()
    start = text.find("{")
    if start == -1:
        raise StoryValidationError("Ответ не является JSON. Верни только JSON по схеме.")
    try:
        data, end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as e:
        raise StoryValidationError(f"JSON повреждён: {e.msg} (позиция {e.pos}). Верни только корректный JSON.")
    if end < len(text.rstrip()):
        log.warning("После JSON сказки модель дописала лишнее (%s символов) — отброшено", len(text.rstrip()) - end)
    if not isinstance(data, dict):
        raise StoryValidationError("Корень JSON должен быть объектом {...}.")
    return data


def _text_field(data: dict, key: str, path: str, limit_key: str | None = None) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StoryValidationError(f"Поле {path} должно быть непустой строкой.")
    value = value.strip()
    want, hard = LIMITS[limit_key or key]
    if len(value) > hard:
        raise StoryValidationError(f"Поле {path} слишком длинное: {len(value)} символов, нужно не больше {want}.")
    return value


def validate_story(data: dict, language: str | None = None, *, exact_pages: bool = True) -> Story:
    """Проверяет JSON сказки. language ('ru'/'ky') включает проверку, что текст написан кириллицей.
    exact_pages=False разрешает любое непустое число страниц (только для чтения старых сохранённых книг)."""
    if not isinstance(data, dict):
        raise StoryValidationError("Корень JSON должен быть объектом {...}.")

    title = _text_field(data, "title", "title")
    hero_visual = _text_field(data, "hero_visual", "hero_visual")
    style_note = _text_field(data, "style_note", "style_note")
    moral = _text_field(data, "moral", "moral")
    wish = _text_field(data, "wish", "wish")

    for key, value in (("hero_visual", hero_visual), ("style_note", style_note)):
        if cyrillic_ratio(value) > 0.2:
            raise StoryValidationError(f"Поле {key} должно быть по-английски.")
    if word_count(hero_visual) < 8:
        raise StoryValidationError("Поле hero_visual слишком короткое: нужно 40–80 слов по-английски.")

    pages_raw = data.get("pages")
    if not isinstance(pages_raw, list):
        raise StoryValidationError(f"Поле pages должно быть списком из {PAGES} страниц.")
    if len(pages_raw) != PAGES and (exact_pages or not pages_raw):
        raise StoryValidationError(f"В поле pages должно быть ровно {PAGES} страниц, а пришло {len(pages_raw)}.")

    pages: list[Page] = []
    for i, item in enumerate(pages_raw, start=1):
        if not isinstance(item, dict):
            raise StoryValidationError(f"Страница {i} должна быть объектом {{\"text\": ..., \"scene\": ...}}.")
        for need in ("text", "scene"):
            if need not in item:
                raise StoryValidationError(f"У страницы {i} нет поля {need}.")
        text = _text_field(item, "text", f"pages[{i}].text", "page_text")
        scene = _text_field(item, "scene", f"pages[{i}].scene", "scene")
        if cyrillic_ratio(scene) > 0.2:
            raise StoryValidationError(f"Поле pages[{i}].scene должно быть по-английски.")
        if word_count(scene) < 5:
            raise StoryValidationError(f"Поле pages[{i}].scene слишком короткое: нужно 25–60 слов по-английски.")
        if language in ("ru", "ky") and cyrillic_ratio(text) < 0.6:
            raise StoryValidationError(
                f"Текст страницы {i} должен быть на языке книги ({'русском' if language == 'ru' else 'кыргызском'})."
            )
        pages.append(Page(text=text, scene=scene))

    return Story(title=title, hero_visual=hero_visual, style_note=style_note,
                 pages=tuple(pages), moral=moral, wish=wish)
