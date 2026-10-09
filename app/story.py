"""Книга в виде проверенного JSON.

Книгу собирает код из плана «режиссёра» и текста «автора» (см. writer.py); сюда она приходит как словарь такого вида:
название, описание героя и стиля для художника, актёры (cast), рефрен, 8 страниц (текст и сцена для картинки),
короткая мысль для родителей (moral) и пожелание. validate_story проверяет структуру; текст ошибки возвращается
модели при повторе. Длину текста страниц по возрасту проверяет writer.check_story, здесь только общая рамка.

Старые книги (созданные до появления актёров и рефрена) читаются так же: cast и refrain необязательны.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .errors import StoryValidationError
from .textutil import cyrillic_ratio, word_count

log = logging.getLogger(__name__)

PAGES = 8           # страниц в книге (решение владельца); картинок на одну больше (обложка)

ROLES = ("hero", "helper", "obstacle", "world", "teammate", "family")     # кто в cast: герой, помощник (лидер), препятствие, друзья мира, остальные друзья команды

# Лимиты из задания и допуск 30%: модели часто чуть превышают длину, а повтор запроса стоит денег.
LIMITS = {
    "title": (50, 65),
    "moral": (140, 180),
    "wish": (200, 260),
    "page_text": (1200, 1200),
    "scene": (700, 700),
    "hero_visual": (900, 900),
    "style_note": (400, 400),
    "refrain": (80, 120),
    "cast_name": (40, 60),
    "cast_look": (500, 700),
}
MAX_CAST = 8


@dataclass(frozen=True)
class Page:
    text: str
    scene: str           # что нарисовать на этой странице (по-английски, одно предложение из плана режиссёра)


@dataclass(frozen=True)
class Character:
    """Герой книги для художника: роль (hero | helper | obstacle) и одинаковое на всех страницах описание внешности."""
    name: str
    role: str
    look: str            # по-английски: как выглядит, во что одет, цвета

    def to_dict(self) -> dict:
        return {"name": self.name, "role": self.role, "look": self.look}


@dataclass(frozen=True)
class Story:
    title: str
    hero_visual: str
    style_note: str
    pages: tuple[Page, ...]
    moral: str
    wish: str
    cast: tuple[Character, ...] = ()       # актёры: герой, помощник, препятствие (в старых книгах пусто)
    refrain: str = ""                      # повторяющаяся строка книги (в старых книгах пусто)

    def character(self, role: str) -> Character | None:
        for c in self.cast:
            if c.role == role:
                return c
        return None

    def characters(self, role: str) -> list[Character]:
        """Все актёры роли (у команды друзей несколько teammate)."""
        return [c for c in self.cast if c.role == role]

    def to_dict(self) -> dict:
        data = {
            "title": self.title,
            "hero_visual": self.hero_visual,
            "style_note": self.style_note,
            "pages": [{"text": p.text, "scene": p.scene} for p in self.pages],
            "moral": self.moral,
            "wish": self.wish,
        }
        if self.cast:
            data["cast"] = [c.to_dict() for c in self.cast]
        if self.refrain:
            data["refrain"] = self.refrain
        return data

    @classmethod
    def from_dict(cls, data: dict, language: str | None = None) -> "Story":
        """Читает уже сохранённую книгу (story.json). Число страниц не проверяется строго: книги, созданные
        после смены числа страниц (раньше было 8, потом 10), остаются доступными для просмотра и повторной отправки.
        Старые книги без cast и refrain читаются как есть."""
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
        log.warning("После JSON книги модель дописала лишнее (%s символов) — отброшено", len(text.rstrip()) - end)
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


def _cast(raw, *, strict: bool) -> tuple[Character, ...]:
    """Актёры книги. strict=False (чтение старых сохранённых книг): всё непонятное молча отбрасывается."""
    if raw is None:
        return ()
    try:
        if not isinstance(raw, list):
            raise StoryValidationError("Поле cast должно быть списком [{name, role, look}].")
        if len(raw) > MAX_CAST:
            raise StoryValidationError(f"В поле cast не больше {MAX_CAST} персонажей.")
        cast: list[Character] = []
        for i, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                raise StoryValidationError(f"cast[{i}] должен быть объектом {{\"name\", \"role\", \"look\"}}.")
            role = item.get("role")
            if role not in ROLES:
                raise StoryValidationError(f"cast[{i}].role должно быть одним из: {', '.join(ROLES)}.")
            name = _text_field(item, "name", f"cast[{i}].name", "cast_name")
            look = _text_field(item, "look", f"cast[{i}].look", "cast_look")
            if cyrillic_ratio(look) > 0.2:
                raise StoryValidationError(f"Поле cast[{i}].look должно быть по-английски.")
            if word_count(look) < 3:
                raise StoryValidationError(f"Поле cast[{i}].look слишком короткое: опиши внешность по-английски.")
            cast.append(Character(name=name, role=role, look=look))
        roles = [c.role for c in cast]
        if cast and roles.count("hero") != 1:
            raise StoryValidationError("В cast должен быть ровно один герой (role = hero).")
        if any(roles.count(r) > 1 for r in ("helper", "obstacle", "world", "family")):
            raise StoryValidationError("В cast не больше одного помощника, одного препятствия, одного мира и одного взрослого (family).")
        if roles.count("teammate") > 3:
            raise StoryValidationError("В cast не больше трёх друзей команды сверх лидера-помощника.")
        return tuple(cast)
    except StoryValidationError as e:
        if strict:
            raise
        log.warning("Актёры старой книги не прочитаны, продолжаю без них: %s", e)
        return ()


def validate_story(data: dict, language: str | None = None, *, exact_pages: bool = True) -> Story:
    """Проверяет JSON книги. language ('ru'/'ky') включает проверку, что текст написан кириллицей.
    exact_pages=False разрешает любое непустое число страниц и несовершенные cast/refrain (только для чтения
    старых сохранённых книг)."""
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

    cast = _cast(data.get("cast"), strict=exact_pages)
    refrain = ""
    if data.get("refrain") is not None:
        value = data.get("refrain")
        if not isinstance(value, str):
            if exact_pages:
                raise StoryValidationError("Поле refrain должно быть строкой.")
        else:
            refrain = value.strip()
            if len(refrain) > LIMITS["refrain"][1]:
                if exact_pages:
                    raise StoryValidationError(
                        f"Поле refrain слишком длинное: {len(refrain)} символов, нужно не больше {LIMITS['refrain'][0]}.")
                refrain = ""

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
            raise StoryValidationError(f"Поле pages[{i}].scene слишком короткое: нужно одно предложение по-английски "
                                       "(место, действие, помощник, свет).")
        if language in ("ru", "ky") and cyrillic_ratio(text) < 0.6:
            raise StoryValidationError(
                f"Текст страницы {i} должен быть на языке книги ({'русском' if language == 'ru' else 'кыргызском'})."
            )
        pages.append(Page(text=text, scene=scene))

    return Story(title=title, hero_visual=hero_visual, style_note=style_note,
                 pages=tuple(pages), moral=moral, wish=wish, cast=cast, refrain=refrain)
