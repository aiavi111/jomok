"""Движок писателя: зёрна, план режиссёра, сборка книги, код-валидатор текста, правки редактора.

Конвейер (TextProvider.generate_story в providers/base.py):
    режиссёр (план JSON) → автор (текст страниц) → редактор (правки только плохих страниц) → этот валидатор.
Лимиты и бан-лист проверяет КОД, а не модель: при нарушении автору возвращают точный текст ошибки
(«стр.4: 31 слово, нужно 14–22»), до трёх попыток, потом StoryError.

Всё, что можно менять руками (списки, лимиты, примеры), лежит в writer_data.py.
"""
from __future__ import annotations

import json
import math
import os
import random
import re
from collections import Counter
from dataclasses import dataclass

from . import options
from . import writer_data as D
from .declension import KY_CASES, KY_CASE_LABELS, RU_CASES, RU_CASE_LABELS, ky_forms, ru_forms
from .errors import StoryValidationError
from .profile import Profile
from .story import PAGES, Page, Story, validate_story
from .textutil import clean_text, cut_words, cyrillic_ratio, ru_plural, word_count
from .translit import latin_variants

DEFAULT_STYLE_NOTE = D.PALETTES[1].en           # «радужное небо»: яркая палитра по умолчанию, если режиссёр не прислал свою


# ============================================================================ разбор текста
_WORD = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")
# конец предложения: знак, потом пробел и заглавная буква (возможно, после тире или кавычки); «— сказал» с маленькой — не конец
_SENT_BREAK = re.compile(r"(?<=[.!?…])[\"»”)]*\s+(?=(?:[—–-]\s*)?[«\"(]?[A-ZА-ЯЁӨҮҢ0-9])")
_EMOJI = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]")
_LATIN = re.compile(r"[A-Za-z]+")


def norm(text: str) -> str:
    """Для сравнения: нижний регистр, «ё» как «е»."""
    return text.lower().replace("ё", "е")


def words(text: str) -> list[str]:
    """Слова текста: тире и знаки не считаются, слово через дефис («туда-сюда») — одно слово."""
    return _WORD.findall(text)


def sentences(text: str) -> list[str]:
    flat = " ".join(text.split())
    return [s for s in _SENT_BREAK.split(flat) if words(s)]


_ELLIPSIS_END = re.compile(r"(?:…|\.\.\.)[\"»”)]*\s*$")
_EXCLAIM_END = re.compile(r"(?:[!…]|\.\.\.)[\"»”)]*\s*$")


def counted_sentences(text: str, refrain: "RefrainMatcher | None" = None) -> list[str]:
    """Предложения для лимита «не больше N на странице». Страница с рефреном, который ломается, и с возгласами иначе
    считалась бы длиннее, чем читается:
    - кусок до многоточия, если он короткий (до 3 слов) или это начало рефрена («Раз, два…»), склеивается со следующим
      предложением: «Раз, два… Стоп!» — одно предложение;
    - возглас не длиннее двух слов («Щёлк!», «Стоп!», «Топ-топ, вместе!», «— Придумал!») в счёт не идёт.
    Длину отдельного предложения (sentence_long) по-прежнему меряют по sentences()."""
    merged: list[str] = []
    carry = ""
    for sentence in sentences(text):
        current = f"{carry} {sentence}" if carry else sentence
        carry = ""
        if _ELLIPSIS_END.search(current) and (len(words(current)) <= D.SHORT_FRAGMENT_WORDS
                                             or (refrain is not None and refrain.matches(current))):
            carry = current
            continue
        merged.append(current)
    if carry:
        merged.append(carry)
    main = [s for s in merged if not (len(words(s)) <= D.INTERJECTION_WORDS and _EXCLAIM_END.search(s))]
    return main or merged[:1]


def plural_words(n: int) -> str:
    return f"{n} {ru_plural(n, 'слово', 'слова', 'слов')}"


def plural_sentences(n: int) -> str:
    return f"{n} {ru_plural(n, 'предложение', 'предложения', 'предложений')}"


def plural_chars(n: int) -> str:
    return f"{n} {ru_plural(n, 'знак', 'знака', 'знаков')}"


def syllables(word: str) -> int:
    return sum(ch in "аеёиоуыэюяүө" for ch in word.lower())


def _compile_stems(stems) -> re.Pattern:
    return re.compile(r"(?<![а-яa-zөүң])(?:" + "|".join(re.escape(norm(s)) for s in stems) + ")")


_BRAND_RE = _compile_stems(D.BRAND_STEMS + D.BRAND_STEMS_KY)
_BRAND_EXACT_RE = re.compile(r"(?<![а-яa-zөүң])(?:" + "|".join(re.escape(norm(w)) for w in D.BRAND_EXACT) + r")(?:"
                             + "|".join(D.BRAND_EXACT_ENDINGS) + r")?(?![а-яa-zөүң])")
_BAN_PHRASES = [(re.compile(p), label) for p, label in D.BAN_PHRASES]
_BAN_PHRASES_KY = [(re.compile(p), label) for p, label in D.BAN_PHRASES_KY]
_CLICHE = [(re.compile(p), label) for p, label in D.BAN_CLICHE_CHARACTERS]
_LIMITED = [(re.compile(p), mx, label) for p, mx, label in D.LIMITED_PHRASES]
_EMOTION = re.compile(r"\b(?:" + D.EMOTION_WORDS + r")\b")
_EMOTION_KY = re.compile(r"\b(?:" + D.EMOTION_WORDS_KY + r")\b")
_VIOLENCE = [re.compile(p) for p in D.VIOLENCE_PATTERNS]
_VIOLENCE_KY = [re.compile(p) for p in D.VIOLENCE_PATTERNS_KY]
_ISLAMIC_RE = [re.compile(p) for p in D.ISLAMIC_FORBIDDEN_RU + D.ISLAMIC_FORBIDDEN_KY]
_ISLAMIC_EN_RE = [re.compile(p) for p in D.ISLAMIC_FORBIDDEN_EN]


def brand_hits(text: str, own: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """Известные персонажи и бренды в тексте (русские и английские названия). own — формы имени самого ребёнка:
    девочку могут звать Эльза, это не бренд."""
    low = norm(text)
    found: set[str] = set()
    for m in _BRAND_RE.finditer(low):
        start, end = m.start(), m.end()
        while end < len(low) and (low[end].isalpha() or low[end] == "-"):
            end += 1
        if low[start:end] in own:
            continue
        found.add(m.group(0))
    for m in _BRAND_EXACT_RE.finditer(low):            # короткие названия: «Лего», «Вспыш», но не «легонько» и не «вспышка»
        if m.group(0) not in own:
            found.add(m.group(0))
    return sorted(found)


_TECH = [(re.compile(p), label) for p, label in D.TECH_PATTERNS]


def tech_hits(text: str) -> list[str]:
    """Технические и «схемные» слова в тексте (механизм, рычаг, пластина, лента…): им нет места в простой детской книге."""
    low = norm(text)
    return sorted({label for pattern, label in _TECH if pattern.search(low)})


# ============================================================================ лимиты по возрасту
@dataclass(frozen=True)
class PageLimits:
    band: str
    language: str
    min_words: int
    max_words: int
    max_chars: int
    max_sentences: int
    max_sentence_words: int

    # Модели чуть промахиваются со счётом слов, а повтор запроса стоит денег: говорим модели лимит, отклоняем с допуском.
    @property
    def hard_max_words(self) -> int:
        return self.max_words + max(2, math.ceil(0.1 * self.max_words))

    @property
    def hard_min_words(self) -> int:
        return math.floor(0.75 * self.min_words)

    @property
    def hard_max_chars(self) -> int:
        return self.max_chars + math.ceil(0.1 * self.max_chars)

    def describe(self) -> str:
        return (f"{self.min_words}–{self.max_words} слов, не больше {self.max_chars} знаков, "
                f"не больше {self.max_sentences} предложений, в одном предложении не больше {self.max_sentence_words} слов")


def band_for_age(age: int) -> str:
    if age <= 4:
        return "3-4"
    return "5-6" if age <= 6 else "7-9"


def page_limits(age: int, language: str) -> PageLimits:
    band = band_for_age(age)
    row = D.PAGE_LIMITS[band]
    lang = language if language in ("ru", "ky") else "ru"
    low, high = row["words"][lang]
    return PageLimits(band, lang, low, high, row["chars"], row["sentences"], row["sentence_words"][lang])


# ============================================================================ формы имени
def first_name(name: str) -> str:
    """Для склонения и счёта берём первое слово имени: «Анна-Мария» → «Анна»."""
    parts = re.split(r"[\s-]+", name.strip())
    return parts[0] if parts and parts[0] else name.strip()


def name_forms_set(name: str, gender: str) -> set[str]:
    """Все формы имени (русские падежи и кыргызские), нормализованные для сравнения."""
    first = first_name(name)
    forms = set(ru_forms(first, gender).values()) | set(ky_forms(first).values()) | {first}
    return {norm(f) for f in forms}


def hero_forms_set(profile: Profile) -> set[str]:
    return name_forms_set(profile.name, profile.gender)


def forms_table(name: str, gender: str, language: str) -> str:
    """Готовая таблица падежей имени для автора: он не угадывает окончания, а берёт форму отсюда."""
    first = first_name(name)
    if language == "ky":
        forms = ky_forms(first)
        return "; ".join(f"{KY_CASE_LABELS[c]}: {forms[c]}" for c in KY_CASES)
    forms = ru_forms(first, gender)
    return "; ".join(f"{RU_CASE_LABELS[c]}: {forms[c]}" for c in RU_CASES)


# ============================================================================ зёрна
@dataclass(frozen=True)
class Seeds:
    """Случайные зёрна книги: код выбирает их сам, чтобы книги не повторялись (LLM сходятся на одних сценах и именах)."""
    setting: str
    obstacle: str
    helper_type: D.HelperType
    helper_name: D.HelperName
    refrain_type: D.RefrainType
    palette: D.Palette = D.PALETTES[1]       # палитра, которую режиссёр берёт по умолчанию (может выбрать другую из списка)
    team_names: tuple[str, ...] = ()         # имена остальных друзей, если помощник — команда (лидера зовут helper_name)
    framework: str = "find_lost"             # каркас истории по умолчанию (режиссёр может взять другой из списка)

    def to_dict(self) -> dict:
        return {
            "setting": self.setting, "obstacle": self.obstacle, "helper_type": self.helper_type.id,
            "helper_name": self.helper_name.name, "refrain_type": self.refrain_type.id, "palette": self.palette.id,
            "team_names": ", ".join(self.team_names), "framework": self.framework,
        }



def _helper_type_pool(profile: Profile) -> tuple[list[D.HelperType], list[D.HelperType], list[D.HelperType]]:
    """(типы под мир книги, типы под тему книги, общие типы); волшебных существ в исламском режиме нет."""
    types = [t for t in D.HELPER_TYPES if not (profile.islamic and t.magic)]
    world_ids = D.WORLD_HELPERS.get(profile.world or "", ())
    worldly = [t for t in types if t.id in world_ids]
    topical = [t for t in types if profile.topic in t.topics]
    general = [t for t in types if not t.topics and not t.world_only]
    return worldly, topical, general


def writer_syllables_ok(name: str) -> bool:
    return all(syllables(w) <= 2 for w in words(name))


def world_team_size(profile: Profile) -> int:
    """Сколько друзей в команде-помощнике обязан описать режиссёр у мира-команды (в исламском режиме тоже), иначе 0."""
    return D.WORLD_TEAM.get(profile.world or "", 0)


_NUMBERS = {"два": 2, "две": 2, "двое": 2, "двух": 2, "три": 3, "трое": 3, "трёх": 3, "трех": 3, "четыре": 4, "четверо": 4,
            "четырёх": 4, "четырех": 4, "пять": 4, "пятеро": 4, "пяти": 4, "2": 2, "3": 3, "4": 4, "5": 4}
_TEAM_THINGS = ("друз", "друг", "звер", "животн", "ниндзя", "черепаш", "спасател", "героя", "героев", "богатыр", "мастер",
                "помощник", "щен", "котят", "котов", "медвежат", "медвед", "зайц", "зайчат", "лисят", "лисёнк", "лисенк", "совят",
                "ёжик", "ежик", "ежат", "динозавр", "дракон", "робот", "пират", "космонавт", "пожарн", "рыцар", "принцесс", "малыш")
_TEAM_REQUEST = re.compile(r"(?<![а-яa-z0-9])(" + "|".join(_NUMBERS) + r")\s+(?:[а-яё-]+\s+){0,2}?(?:" + "|".join(_TEAM_THINGS) + r")")
_TEAM_WORD = re.compile(r"команд\w*(?:\s+из\s+(" + "|".join(_NUMBERS) + r"))?")


def requested_team_size(profile: Profile) -> int:
    """Просьба родителей в request и favorites: «четыре черепашки-ниндзя», «команда из трёх зверей», «три друга».
    Осторожно: нужно число (2–5) и рядом слово про друзей, зверей или героев, либо слово «команда». Число режется до 4.
    Cartoons не читаем: это только вдохновение. 0 — команду никто не просил."""
    text = norm(f"{profile.request} {profile.favorites}")
    sizes = [_NUMBERS[m.group(1)] for m in _TEAM_REQUEST.finditer(text)]
    for m in _TEAM_WORD.finditer(text):
        sizes.append(_NUMBERS.get(m.group(1), 3) if m.group(1) else 3)
    return max(sizes, default=0)


def team_size_needed(profile: Profile) -> int:
    """Команда какого размера обязательна: больше из требования мира и просьбы родителей (0 — один помощник)."""
    return max(world_team_size(profile), requested_team_size(profile))


def pick_palette(profile: Profile, rng: random.Random) -> D.Palette:
    """Палитра книги: под тему или место (аквамарин для моря, изумруд для зверей), иначе любая из пяти."""
    keys = {profile.topic, profile.place}
    matching = [p for p in D.PALETTES if keys & set(p.topics)]
    if matching and rng.random() < 0.6:
        return rng.choice(matching)
    return rng.choice(D.PALETTES)


def pick_seeds(profile: Profile, rng: random.Random | None = None) -> Seeds:
    """setting × obstacle × helper type × refrain type × palette (+ имя помощника из списка 40 коротких имён).
    Выбранный мир книги подбирает помощника из его архетипа и место действия из его мира."""
    rng = rng or random.SystemRandom()
    if profile.topic in D.SETTINGS_BY_TOPIC:
        settings = D.SETTINGS_BY_TOPIC[profile.topic]
    elif profile.world in D.SETTINGS_BY_WORLD:
        settings = D.SETTINGS_BY_WORLD[profile.world]
    else:
        settings = D.SETTINGS_BY_PLACE.get(profile.place) or D.SETTINGS_BY_PLACE["custom"]
    worldly, topical, general = _helper_type_pool(profile)
    if worldly:
        pool = worldly
    else:
        pool = topical if topical and rng.random() < 0.7 else general
    helper_type = rng.choice(pool or general or list(D.HELPER_TYPES))
    taken = hero_forms_set(profile)
    names = [n for n in D.HELPER_NAMES if n.gender in (helper_type.gender, "n") and norm(n.name) not in taken]
    setting = rng.choice(settings)
    obstacle = rng.choice(D.OBSTACLES_BY_TOPIC.get(profile.topic) or D.OBSTACLES)
    helper_name = rng.choice(names or list(D.HELPER_NAMES))
    refrain_type = rng.choice(D.REFRAIN_TYPES)
    palette = pick_palette(profile, rng)
    spare = [n for n in D.HELPER_NAMES if norm(n.name) not in taken and n.name != helper_name.name
             and writer_syllables_ok(n.name)]
    team_names = tuple(n.name for n in rng.sample(spare, D.TEAM_EXTRA_NAMES))
    framework = "fear" if profile.topic == "life_lesson" else rng.choice([f.id for f in D.FRAMEWORKS if f.id != "fear"])
    return Seeds(setting=setting, obstacle=obstacle, helper_type=helper_type, helper_name=helper_name,
                 refrain_type=refrain_type, palette=palette, team_names=team_names, framework=framework)


# ============================================================================ план режиссёра
@dataclass(frozen=True)
class TeamMember:
    """Друг из команды-помощника: свой цвет, одна черта, внешность по-английски для художника (у лидера look пустой:
    его внешность — character_bible.helper)."""
    name: str
    kind: str
    trait: str
    look: str = ""


@dataclass(frozen=True)
class Family:
    """Взрослый или родной в сюжете (мама потерявшегося малыша, бабушка, которую ждут): находится и ВИДЕН на последних кадрах.
    Взрослые в книге спокойные и добрые: не боятся, не застревают."""
    role: str        # английское слово роли: mother, father, parent, grandmother, grandfather, sibling
    kind: str        # по-русски кто это («мама-динозавр»)
    look: str        # внешность по-английски

    def to_dict(self) -> dict:
        return {"role": self.role, "kind": self.kind, "look": self.look}


@dataclass(frozen=True)
class Plan:
    premise: str
    want: str
    trait: str
    tool: str
    stakes: str
    helper_name: str
    helper_trait: str
    helper_kind: str
    obstacle: str
    attempts: tuple[tuple[str, str], ...]        # (действие, причина провала); третья — идея героя, она срабатывает
    solution: str
    plant: str
    payoff: str
    refrain: str
    refrain_break: str
    hero_look: str
    helper_look: str
    obstacle_look: str
    style_note: str
    image_brief: tuple[str, ...]
    team: tuple[TeamMember, ...] = ()     # помощник — команда из 2–4 друзей; первый — лидер (helper_name). Пусто — помощник один
    framework: str = "find_lost"          # id каркаса истории (writer_data.FRAMEWORKS)
    logline: str = ""                     # весь сюжет ОДНИМ предложением до 14 слов, без технических слов
    meaning: str = ""                     # чему учит книга, ОДНОЙ фразой простыми словами (из неё вытекает moral)
    retell: str = ""                      # пересказ сюжета от начала до конца одной фразой: что потеряно, что нашли, кто рад
    family: Family | None = None          # взрослый или родной, которого ищут и находят (мама малыша): он добрый и виден в конце

    def helper_dict(self) -> dict:
        helper = {"name": self.helper_name, "trait": self.helper_trait, "kind": self.helper_kind}
        if self.team:
            helper["team"] = [{"name": m.name, "kind": m.kind, "trait": m.trait, **({"look": m.look} if m.look else {})}
                              for m in self.team]
        return helper

    @property
    def member_names(self) -> tuple[str, ...]:
        """Все, кого в книге называют по имени как помощников: лидер и (если есть) вся команда."""
        return tuple(dict.fromkeys((self.helper_name, *(m.name for m in self.team))))

    @property
    def teammates(self) -> tuple[TeamMember, ...]:
        """Члены команды без лидера: у них отдельные имена и внешность в cast."""
        return tuple(m for m in self.team if m.name != self.helper_name)

    def to_dict(self) -> dict:
        return {
            "framework": self.framework, "logline": self.logline, "meaning": self.meaning, "retell": self.retell,
            **({"family": self.family.to_dict()} if self.family else {}),
            "premise": self.premise, "want": self.want, "trait": self.trait, "tool": self.tool, "stakes": self.stakes,
            "helper": self.helper_dict(),
            "obstacle": self.obstacle,
            "attempts": [{"action": a, "fail_reason": r} for a, r in self.attempts],
            "solution": self.solution,
            "plant_payoff": {"plant": self.plant, "payoff": self.payoff},
            "refrain": {"text": self.refrain, "break": self.refrain_break},
            "character_bible": {"hero": self.hero_look, "helper": self.helper_look, "obstacle": self.obstacle_look},
            "style_note": self.style_note,
            "image_brief": list(self.image_brief),
        }

    def for_author(self) -> dict:
        """Что видит автор: сюжет и рефрен без английских описаний героев; картинки — как «что уже нарисовано»."""
        data = self.to_dict()
        data.pop("character_bible")
        data.pop("style_note")
        if "team" in data["helper"]:                                   # внешность друзей нужна художнику, автору она ни к чему
            data["helper"]["team"] = [{k: v for k, v in m.items() if k != "look"} for m in data["helper"]["team"]]
        if "family" in data:
            data["family"] = {"role": self.family.role, "kind": self.family.kind}
        data["на_картинках_уже_нарисовано"] = data.pop("image_brief")
        return data


def _plan_text(data: dict, key: str, label: str, *, obj: dict | None = None, limit: int = 400, minimum: int = 3) -> str:
    src = data if obj is None else obj
    value = src.get(key)
    if isinstance(value, str):
        value = clean_text(value)                 # план попадёт в промт автора: угловые скобки и невидимые знаки вырезаем
    if not isinstance(value, str) or len(value) < minimum:
        raise StoryValidationError(f"В плане поле {label} должно быть непустой строкой.")
    if len(value) > limit:
        raise StoryValidationError(f"В плане поле {label} слишком длинное: {len(value)} символов, нужно не больше {limit}.")
    return value


def _english(value: str, label: str, *, min_words: int, limit: int) -> str:
    if cyrillic_ratio(value) > 0.2:
        raise StoryValidationError(f"В плане {label} должно быть по-английски.")
    if word_count(value) < min_words:
        raise StoryValidationError(f"В плане {label} слишком короткое: нужно не меньше {min_words} слов по-английски.")
    if len(value) > limit:
        raise StoryValidationError(f"В плане {label} слишком длинное: {len(value)} символов, нужно не больше {limit}.")
    return value


def ban_name_hits(text: str, profile: Profile | None = None, *, allow_moon: bool = False) -> list[str]:
    """Имена-штампы моделей (Элара, Лира, Мара, Луна…). Имя самого ребёнка можно: вдруг его так зовут.
    allow_moon: в книге про космос Луна — это Луна, а не имя героини."""
    own = hero_forms_set(profile) if profile else set()
    found: list[str] = []
    for name in D.BAN_NAMES_CERTAIN:
        forms = {norm(f) for f in ru_forms(name, "boy" if name.endswith("с") else "girl").values()}
        if forms - own and any(norm(t) in forms - own for t in words(text)):
            found.append(name)
    ambiguous = {name: {norm(f) for f in ru_forms(name, "girl").values()} for name in D.BAN_NAMES_AMBIGUOUS}
    for sentence in sentences(text):
        for idx, token in enumerate(words(sentence)):
            if idx == 0 or not token[:1].isupper():
                continue
            for name, forms in ambiguous.items():
                if name == "Луна" and allow_moon:
                    continue
                if norm(token) in forms - own and name not in found:
                    found.append(name)
    return found


def _check_plan_text(text: str, profile: Profile, label: str, *, english: bool = False) -> None:
    brands = brand_hits(text, hero_forms_set(profile))
    if brands:
        raise StoryValidationError(
            f"В плане ({label}) названы известные персонажи или бренды: {', '.join(brands)}. Никаких имён и названий: "
            "создай оригинального персонажа по функции (архетип из списка).")
    if not english:
        names = ban_name_hits(text, profile, allow_moon=profile.topic == "space" or profile.place == "space")
        if names:
            raise StoryValidationError(f"В плане ({label}) имя-штамп «{names[0]}». Придумай обычное, неожиданное имя.")
        tech = tech_hits(text)
        if tech:
            raise StoryValidationError(
                f"В плане ({label}) технические слова: {', '.join(tech)}. Сюжет должен быть простым и понятным пятилетнему: "
                "без механизмов, ключей-замков, схем, пластин, лент и выдуманных устройств. Назови каждый предмет простым "
                "словом, а решение сделай добрым или смелым делом героя.")
    if profile.islamic:
        low = norm(text)
        patterns = _ISLAMIC_EN_RE if english else _ISLAMIC_RE
        for pat in patterns:
            m = pat.search(low)
            if m:
                raise StoryValidationError(
                    f"В плане ({label}) «{m.group(0)}»: в режиме «Исламские ценности» это нельзя. Замени на обычное животное или вещь.")


def _check_ky_refrain(refrain: str) -> None:
    """Рефрен кыргызской книги автор обязан держать дословно, поэтому он сам должен быть кыргызским: без русского счёта и
    служебных слов, с буквами ү, ө, ң или с кыргызским счётом, кличем и звукоподражанием."""
    tokens = [norm(part) for w in words(refrain) for part in w.split("-")]
    russian = [t for t in dict.fromkeys(tokens) if t in D.RU_REFRAIN_WORDS]
    example = "«Бир, эки, үч — жүр!»"
    if russian:
        raise StoryValidationError(
            f"В плане refrain.text «{refrain}» содержит русские слова ({', '.join(russian[:4])}): рефрен кыргызской "
            f"книги должен быть по-кыргызски, например {example}.")
    idiophones = {part for item in D.KY_IDIOPHONES for part in item.split("-")}
    if not (any(ch in refrain.lower() for ch in _KY_LETTERS) or any(t in D.KY_REFRAIN_MARKERS | idiophones for t in tokens)):
        raise StoryValidationError(
            f"В плане refrain.text «{refrain}» не похож на кыргызский: напиши его кыргызскими словами (с буквами ү, ө, ң, "
            f"кыргызским счётом или звукоподражанием), например {example}.")


_LOCATIVE = frozenset("in inside at on onto near by beside behind under beneath over across along through among above below "
                      "around outside into between beyond atop within".split())
_PLACE_STOP = frozenset("with while and as where who that which holding carrying looking waving but from to for of toward towards "
                        "its his her their when so then".split()) | _LOCATIVE
_DETERMINERS = frozenset("a an the some this that these those same other another his her its their".split())
_TEAM_SHOWN = re.compile(r"\b(?:team|helpers|friends|all (?:two|three|four|\d)|everyone)\b", re.I)


def brief_places(brief: str) -> set[str]:
    """Место кадра по image_brief (английское предложение): главные слова после «in / at / on / near / behind…».
    Свет, время суток, герои и ракурс местом не считаются (D.BRIEF_GENERIC_PLACES). Два соседних кадра с общим словом
    места считаются «в одном и том же месте»."""
    tokens = re.findall(r"[a-z'’-]+|[,.;:()]", brief.lower())
    heads: set[str] = set()
    i = 0
    while i < len(tokens):
        if tokens[i] in _LOCATIVE:
            phrase: list[str] = []
            j = i + 1
            while j < len(tokens) and (tokens[j] == "of" or tokens[j] not in _PLACE_STOP) and tokens[j] not in ",.;:()":
                if tokens[j] not in _DETERMINERS and tokens[j] != "of":     # «at the edge of the stream» — место это stream
                    phrase.append(tokens[j])
                j += 1
            if phrase and phrase[-1] not in D.BRIEF_GENERIC_PLACES:
                heads.add(phrase[-1])
            i = j
        else:
            i += 1
    return heads


_FAMILY_SHOWN = re.compile(r"\b(?:parent|parents|mother|mom|mum|mommy|father|dad|daddy|grandmother|grandma|grandfather|grandpa|"
                           r"sibling|brother|sister|family)\b", re.I)
FAMILY_SHOWN = _FAMILY_SHOWN             # слова, по которым видно, что на кадре взрослый или родной (prompts.py берёт его на страницу)
FAMILY_ROLES = ("mother", "father", "parent", "grandmother", "grandfather", "sibling")
FAMILY_LAST_BRIEFS = 2                  # на стольких последних кадрах взрослого обязательно видно


def _check_briefs(briefs: list[str], team: bool, family: bool = False) -> None:
    if family:
        for i in range(len(briefs) - FAMILY_LAST_BRIEFS, len(briefs)):
            if not _FAMILY_SHOWN.search(briefs[i]):
                raise StoryValidationError(
                    f"В плане image_brief[{i + 1}]: в сюжете есть взрослый или родной (family), и на последних кадрах его надо "
                    'ВИДЕТЬ: напиши в кадре его слово ("the mother", "the parent", "the grandmother") и где он стоит рядом с героем.')
    for i, brief in enumerate(briefs, start=1):
        if team and not _TEAM_SHOWN.search(brief):
            raise StoryValidationError(
                f"В плане image_brief[{i}]: помощник — команда, и на КАЖДОМ кадре вся команда рядом с героем. Напиши в кадре "
                'слова "the helper team" или "all four friends" и где они стоят.')
    for i in range(len(briefs) - 1):
        shared = brief_places(briefs[i]) & brief_places(briefs[i + 1])
        if shared:
            raise StoryValidationError(
                f"В плане image_brief[{i + 1}] и image_brief[{i + 2}] в одном и том же месте («{sorted(shared)[0]}»): каждая "
                "страница — НОВОЕ место или явно новый момент (другое место, масштаб, свет, время суток). Назови для "
                f"кадра {i + 2} другое место.")


def _family(raw) -> Family | None:
    """Поле family (необязательное): взрослый или родной, которого находят. Роль — английское слово, внешность — по-английски."""
    if raw in (None, {}, "", []):
        return None
    if not isinstance(raw, dict):
        raise StoryValidationError('В плане поле family должно быть объектом {"role", "kind", "look"} (или его не должно быть).')
    role = raw.get("role")
    if role not in FAMILY_ROLES:
        raise StoryValidationError(f"В плане family.role должно быть одним из: {', '.join(FAMILY_ROLES)}.")
    kind = _plan_text(raw, "kind", "family.kind (кто это по-русски, например «мама-динозавр»)", limit=60)
    look = _english(_plan_text(raw, "look", "family.look", limit=240, minimum=10), "family.look", min_words=6, limit=240)
    return Family(role=role, kind=kind, look=look)


def _team_members(helper: dict, helper_name: str, seeds: Seeds | None, profile: Profile) -> tuple[TeamMember, ...]:
    """helper.team: команда из 2–4 друзей. Первый — лидер (helper.name), у остальных имя из seeds.team_names (выбрал код),
    своя внешность по-английски, один цвет и одна короткая черта. Мир-команда требует команды нужного размера."""
    raw = helper.get("team")
    need = team_size_needed(profile)
    why = ""
    if need:
        why = (f"мир «{options.WORLDS[profile.world]['label']}» — это команда" if world_team_size(profile) >= requested_team_size(profile)
               else f"родители просят команду (request, favorites): {profile.request or profile.favorites}")
    if raw in (None, [], ""):
        if need:
            raise StoryValidationError(
                f"В плане helper.team нужна команда из {need} разных друзей: {why}. У каждого своё имя, цвет и внешность. "
                "Опиши всех в helper.team, первый — helper.name; просьба родителей важнее правила «один помощник».")
        return ()
    if not isinstance(raw, list) or not D.TEAM_MIN <= len(raw) <= D.TEAM_MAX:
        raise StoryValidationError(f"В плане helper.team должен быть списком из {D.TEAM_MIN}–{D.TEAM_MAX} друзей "
                                   '[{"name", "kind", "trait", "look"}], первый — лидер helper.name.')
    if len(raw) < need:
        raise StoryValidationError(f"В плане в helper.team {len(raw)} друга, а нужна команда из {need} ({why}): опиши всех {need}.")
    members: list[TeamMember] = []
    allowed = {norm(helper_name)} | {norm(n) for n in (seeds.team_names if seeds else ())}
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise StoryValidationError(f'В плане helper.team[{i}] должно быть объектом {{"name", "kind", "trait", "look"}}.')
        name = _plan_text(item, "name", f"helper.team[{i}].name", limit=30, minimum=2)
        if any(syllables(w) > 2 for w in words(name)):
            raise StoryValidationError(f"В плане имя helper.team[{i}] длиннее двух слогов: нужно короткое имя.")
        if i == 1 and norm(name) != norm(helper_name):
            raise StoryValidationError(f"В плане helper.team[1] должен быть лидер «{helper_name}» (то же имя, что helper.name).")
        if seeds and norm(name) not in allowed:
            spare = ", ".join(seeds.team_names)
            raise StoryValidationError(f"В плане helper.team[{i}].name «{name}» не из списка: имена друзей выбрал код, бери "
                                       f"их по порядку из «{spare}».")
        kind = _plan_text(item, "kind", f"helper.team[{i}].kind (какой это зверь или герой)", limit=60)
        trait = _plan_text(item, "trait", f"helper.team[{i}].trait (одна короткая черта)", limit=120)
        look = ""
        if i > 1:
            look = _english(_plan_text(item, "look", f"helper.team[{i}].look", limit=160, minimum=10),
                            f"helper.team[{i}].look", min_words=5, limit=160)
        members.append(TeamMember(name=name, kind=kind, trait=trait, look=look))
    if len({norm(m.name) for m in members}) != len(members):
        raise StoryValidationError("В плане у друзей из helper.team повторяются имена: у каждого своё имя и свой цвет.")
    return tuple(members)


def validate_plan(data, profile: Profile, seeds: Seeds | None = None) -> Plan:
    """Проверяет JSON режиссёра. Текст ошибки возвращается модели при повторе (как у текста книги)."""
    if not isinstance(data, dict):
        raise StoryValidationError("Корень JSON должен быть объектом {...}.")

    framework = data.get("framework")
    if framework not in D.FRAMEWORK_IDS:
        raise StoryValidationError(f"В плане поле framework должно быть одним из: {', '.join(D.FRAMEWORK_IDS)}.")
    if profile.topic == "life_lesson" and framework != "fear":
        raise StoryValidationError('Тема «Учимся жизни»: framework должен быть "fear" (победить страх вместе с помощником).')
    logline = _plan_text(data, "logline", "logline (весь сюжет ОДНИМ простым предложением)", limit=D.LOGLINE_MAX_CHARS, minimum=8)
    if len(words(logline)) > D.LOGLINE_MAX_WORDS:
        raise StoryValidationError(
            f"В плане logline из {plural_words(len(words(logline)))}, нужно не больше {D.LOGLINE_MAX_WORDS}: один простой сюжет, "
            "который пятилетний поймёт с первого раза («пропали звёзды, герой с друзьями находит их по одной»).")
    meaning = _plan_text(data, "meaning", "meaning (чему учит книга ОДНОЙ простой фразой)", limit=140, minimum=8)
    if len(words(meaning)) > D.MEANING_MAX_WORDS:
        raise StoryValidationError(f"В плане meaning из {plural_words(len(words(meaning)))}, нужно не больше {D.MEANING_MAX_WORDS}: "
                                   "одна простая мысль, которая вытекает из того, что сделал герой («помогать тому, кто в беде»).")
    retell = _plan_text(data, "retell", "retell (весь сюжет одной фразой: что потеряно, что нашли, кто рад)", limit=260, minimum=12)
    if len(words(retell)) > D.RETELL_MAX_WORDS:
        raise StoryValidationError(f"В плане retell из {plural_words(len(words(retell)))}, нужно не больше {D.RETELL_MAX_WORDS}: "
                                   "одна фраза от начала до конца.")
    family = _family(data.get("family"))
    premise = _plan_text(data, "premise", "premise", limit=240)
    want = _plan_text(data, "want", "want", limit=200)
    trait = _plan_text(data, "trait", "trait (одна черта ребёнка из анкеты)", limit=120)
    tool = _plan_text(data, "tool", "tool (любимая вещь как инструмент решения)", limit=200)
    stakes = _plan_text(data, "stakes", "stakes («если не…, то…»)", limit=240)
    obstacle = _plan_text(data, "obstacle", "obstacle (простое препятствие, которое можно нарисовать)", limit=200)
    solution = _plan_text(data, "solution", "solution", limit=260)

    helper = data.get("helper")
    if not isinstance(helper, dict):
        raise StoryValidationError('В плане поле helper должно быть объектом {"name", "trait", "kind"}.')
    helper_name = _plan_text(helper, "name", "helper.name", limit=30, minimum=2)
    if seeds and norm(helper_name) != norm(seeds.helper_name.name):
        raise StoryValidationError(
            f"В плане helper.name должно быть «{seeds.helper_name.name}»: имя помощника выбрал код, менять его нельзя.")
    if any(syllables(w) > 2 for w in words(helper_name)):
        raise StoryValidationError("В плане имя помощника длиннее двух слогов: нужно короткое имя.")
    helper_trait = _plan_text(helper, "trait", "helper.trait (одна черта помощника)", limit=200)
    helper_kind = clean_text(helper.get("kind") or (seeds.helper_type.ru if seeds else "помощник"))[:120] or "помощник"
    team = _team_members(helper, helper_name, seeds, profile)

    raw_attempts = data.get("attempts")
    if not isinstance(raw_attempts, list) or len(raw_attempts) != 3:
        raise StoryValidationError("В плане поле attempts должно быть списком ровно из 3 шагов "
                                   '[{"action", "fail_reason"}]: три НОВЫХ места, в каждом находка или шаг героя.')
    attempts: list[tuple[str, str]] = []
    for i, item in enumerate(raw_attempts, start=1):
        if not isinstance(item, dict):
            raise StoryValidationError(f'В плане attempts[{i}] должно быть объектом {{"action", "fail_reason"}}.')
        action = _plan_text(item, "action", f"attempts[{i}].action", limit=220)
        reason = item.get("fail_reason")
        if i < 3:
            reason = _plan_text(item, "fail_reason", f"attempts[{i}].fail_reason (что мешало, простой фразой)", limit=160)
        else:
            reason = clean_text(reason) if isinstance(reason, str) else ""
        attempts.append((action, reason))

    pp = data.get("plant_payoff")
    if isinstance(pp, str) and clean_text(pp):
        plant = payoff = clean_text(pp)
    elif isinstance(pp, dict):
        plant = _plan_text(pp, "plant", "plant_payoff.plant (любимая вещь, показанная на стр. 1–3)", limit=240)
        payoff = _plan_text(pp, "payoff", "plant_payoff.payoff (как она слегка помогла)", limit=240)
    else:
        raise StoryValidationError('В плане поле plant_payoff должно быть объектом {"plant", "payoff"}: '
                                   "любимая вещь со стр. 1–3 и то, как она слегка помогла.")

    ref = data.get("refrain")
    if isinstance(ref, str):
        ref = {"text": ref, "break": ""}
    if not isinstance(ref, dict):
        raise StoryValidationError('В плане поле refrain должно быть объектом {"text", "break"}.')
    refrain = _plan_text(ref, "text", "refrain.text", limit=80, minimum=3)
    n_ref = len(words(refrain))
    if not 2 <= n_ref <= 8:
        raise StoryValidationError(f"В плане refrain.text из {plural_words(n_ref)}: нужен рефрен из 3–6 слов.")
    refrain_break = _plan_text(ref, "break", "refrain.break (как рефрен ломается на третий раз)", limit=200)
    if profile.language == "ky":
        _check_ky_refrain(refrain)

    bible = data.get("character_bible")
    if not isinstance(bible, dict):
        raise StoryValidationError('В плане поле character_bible должно быть объектом {"hero", "helper", "obstacle"}.')
    hero_look = _english(_plan_text(bible, "hero", "character_bible.hero", limit=700, minimum=10),
                         "character_bible.hero", min_words=12, limit=700)
    helper_look = _english(_plan_text(bible, "helper", "character_bible.helper", limit=500, minimum=10),
                           "character_bible.helper", min_words=6, limit=500)
    obstacle_look = _english(_plan_text(bible, "obstacle", "character_bible.obstacle", limit=500, minimum=6),
                             "character_bible.obstacle", min_words=4, limit=500)

    style = data.get("style_note")
    style_note = DEFAULT_STYLE_NOTE
    if isinstance(style, str) and clean_text(style) and cyrillic_ratio(style) <= 0.2 and len(clean_text(style)) <= 400:
        style_note = clean_text(style)

    brief_raw = data.get("image_brief")
    if not isinstance(brief_raw, list) or len(brief_raw) != PAGES:
        got = len(brief_raw) if isinstance(brief_raw, list) else "не список"
        raise StoryValidationError(f"В плане поле image_brief должно быть списком ровно из {PAGES} предложений, а пришло {got}.")
    briefs: list[str] = []
    for i, item in enumerate(brief_raw, start=1):
        if not isinstance(item, str) or not item.strip():
            raise StoryValidationError(f"В плане image_brief[{i}] должно быть непустой строкой.")
        briefs.append(_english(clean_text(item), f"image_brief[{i}]", min_words=6, limit=D.BRIEF_MAX_CHARS))
    _check_briefs(briefs, team=bool(team), family=bool(family))

    ru_fields = {"logline": logline, "meaning": meaning, "retell": retell, "premise": premise, "want": want, "trait": trait, "tool": tool, "stakes": stakes,
                 "obstacle": obstacle, "solution": solution, "helper.trait": helper_trait,
                 "plant_payoff": plant + " " + payoff, "refrain": refrain + " " + refrain_break}
    for i, (action, reason) in enumerate(attempts, start=1):
        ru_fields[f"attempts[{i}]"] = action + " " + reason
    for i, member in enumerate(team, start=1):
        ru_fields[f"helper.team[{i}]"] = f"{member.name} {member.kind} {member.trait}"
    if family:
        ru_fields["family.kind"] = family.kind
    for label, text in ru_fields.items():
        _check_plan_text(text, profile, label)
    en_fields = {"character_bible.hero": hero_look, "character_bible.helper": helper_look,
                 "character_bible.obstacle": obstacle_look, "style_note": style_note}
    for i, member in enumerate(team, start=1):
        if member.look:
            en_fields[f"helper.team[{i}].look"] = member.look
    if family:
        en_fields["family.look"] = family.look
    for i, text in enumerate(briefs, start=1):
        en_fields[f"image_brief[{i}]"] = text
    for label, text in en_fields.items():
        _check_plan_text(text, profile, label, english=True)

    return Plan(framework=framework, logline=logline, premise=premise, want=want, trait=trait, tool=tool, stakes=stakes,
                helper_name=helper_name, helper_trait=helper_trait, helper_kind=helper_kind, obstacle=obstacle,
                attempts=tuple(attempts), solution=solution, plant=plant, payoff=payoff, refrain=refrain,
                refrain_break=refrain_break, hero_look=hero_look, helper_look=helper_look, obstacle_look=obstacle_look,
                style_note=style_note, image_brief=tuple(briefs), team=team, meaning=meaning, retell=retell, family=family)


# ============================================================================ сборка книги из плана и текста автора
def _world_cast(profile: Profile) -> list[dict]:
    """Мир книги в «библии героев»: внешность архетипа выбранного мира (английский текст для художника), чтобы друзья мира
    выглядели одинаково на всех страницах и на обложке. Мира нет (или он «Свой вариант») — ничего не добавляем."""
    archetype = D.archetype_for_world(profile.world, islamic=profile.islamic)
    if archetype is None:
        return []
    return [{"name": cut_words(options.WORLDS[profile.world]["label"], 40), "role": "world", "look": archetype.look}]


def assemble_story(profile: Profile, plan: Plan, author: dict) -> Story:
    """План даёт художнику всё (герой, помощник, сцены), автор — только слова. Результат проверяет validate_story."""
    if not isinstance(author, dict):
        raise StoryValidationError("Корень JSON должен быть объектом {...}.")
    raw_pages = author.get("pages")
    pages: list[dict] = []
    if isinstance(raw_pages, list):
        for i, item in enumerate(raw_pages):
            text = item.get("text") if isinstance(item, dict) else item
            scene = plan.image_brief[i] if i < len(plan.image_brief) else ""
            pages.append({"text": text if isinstance(text, str) else "", "scene": scene})
    else:
        pages = raw_pages  # пусть validate_story объяснит, что не так
    data = {
        "title": author.get("title"),
        "hero_visual": plan.hero_look,
        "style_note": plan.style_note,
        "cast": [
            {"name": profile.name, "role": "hero", "look": plan.hero_look},
            {"name": plan.helper_name, "role": "helper", "look": plan.helper_look},
            *({"name": m.name, "role": "teammate", "look": m.look} for m in plan.teammates),
            *([{"name": cut_words(plan.family.kind, 40), "role": "family", "look": plan.family.look}] if plan.family else []),
            {"name": cut_words(plan.obstacle, 40), "role": "obstacle", "look": plan.obstacle_look},
            *_world_cast(profile),
        ],
        "refrain": plan.refrain,
        "pages": pages,
        "moral": author.get("moral"),
        "wish": author.get("wish"),
    }
    return validate_story(data, profile.language)


# ============================================================================ код-валидатор текста
@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    page: int | None = None

    def __str__(self) -> str:
        return f"стр.{self.page}: {self.message}" if self.page else self.message

    @property
    def soft(self) -> bool:
        """Мелкое замечание (см. D.SOFT_VIOLATIONS): если остались только такие, книгу после всех попыток принимаем."""
        return self.code in D.SOFT_VIOLATIONS


def violations_text(violations: list[Violation], limit: int = 12) -> str:
    """Список для автора: жёсткие нарушения идут первыми, чтобы они не пропали за обрезкой по limit."""
    ordered = sorted(violations, key=lambda v: v.soft)
    lines = [f"- {v}" for v in ordered[:limit]]
    if len(ordered) > limit:
        lines.append(f"- … и ещё {len(ordered) - limit}")
    return "\n".join(lines)


def hard_violations(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if not v.soft]


_example_grams: set[str] | None = None
_example_names: set[str] | None = None


def _grams(tokens: list[str], n: int = 5):
    for i in range(len(tokens) - n + 1):
        yield " ".join(tokens[i:i + n])


def example_grams() -> set[str]:
    """Все пятёрки подряд идущих слов из примеров в инструкции: если автор их повторил, он списал пример."""
    global _example_grams
    if _example_grams is None:
        grams: set[str] = set()
        references = [ex for ex in (D.REFERENCE, D.REFERENCE_KY) if ex]
        for ex in references + [e for table in (D.EXAMPLES, D.EXAMPLES_KY) for examples in table.values() for e in examples]:
            for page in ex.pages:
                grams.update(_grams([norm(t) for t in words(page)]))
        _example_grams = grams
    return _example_grams


def example_name_forms() -> set[str]:
    """Имена героев из примеров во всех падежах: автор не должен брать их себе."""
    global _example_names
    if _example_names is None:
        _example_names = set()
        for name, gender in zip(D.EXAMPLE_NAMES, D.EXAMPLE_NAME_GENDERS):
            _example_names |= name_forms_set(name, gender)
    return _example_names


def _parent_words(profile: Profile) -> set[str]:
    text = " ".join([profile.request, profile.favorites, profile.topic_custom, " ".join(profile.likes), profile.name])
    return {norm(t) for t in words(text)}


def _check_limits(pages: list[str], limits: PageLimits, matcher: RefrainMatcher | None = None) -> list[Violation]:
    out: list[Violation] = []
    for i, text in enumerate(pages, start=1):
        n = len(words(text))
        if n > limits.hard_max_words:
            out.append(Violation("words_max", f"{plural_words(n)}, нужно {limits.min_words}–{limits.max_words}: "
                                 "оставь одно действие и убери лишнее", i))
        elif n < limits.hard_min_words:
            out.append(Violation("words_min", f"{plural_words(n)}, слишком коротко: нужно {limits.min_words}–{limits.max_words}", i))
        chars = len(" ".join(text.split()))
        if chars > limits.hard_max_chars:
            out.append(Violation("chars", f"{plural_chars(chars)}, лимит {limits.max_chars}", i))
        counted = counted_sentences(text, matcher)
        if len(counted) > limits.max_sentences:
            out.append(Violation("sentences", f"{plural_sentences(len(counted))}, лимит {limits.max_sentences}", i))
        for s in sentences(text):
            sw = len(words(s))
            if sw > limits.max_sentence_words:
                out.append(Violation("sentence_long", f"предложение из {plural_words(sw)} слишком длинное, лимит "
                                     f"{limits.max_sentence_words}: «{cut_words(s, 50)}…» — сделай его короче", i))
                break
    return out


def _check_name_count(pages: list[str], profile: Profile) -> list[Violation]:
    forms = hero_forms_set(profile)
    total = sum(norm(t) in forms for text in pages for t in words(text))
    if total > D.NAME_MAX_USES:
        return [Violation("name_count", f"имя героя «{first_name(profile.name)}» встречается {total} раз во всей книге, "
                          f"лимит {D.NAME_MAX_USES}: замени часть на «он/она», «мальчик/девочка», «малыш» или убери подлежащее")]
    return []


def _units(story: Story) -> list[tuple[str, int | None, str]]:
    """(как назвать место в сообщении, номер страницы, текст)."""
    units: list[tuple[str, int | None, str]] = [("в названии", None, story.title)]
    units += [("", i, p.text) for i, p in enumerate(story.pages, start=1)]
    units += [("в строке moral", None, story.moral), ("в пожелании", None, story.wish)]
    return units


def _msg(where: str, text: str) -> str:
    return f"{where} {text}".strip()


def _check_banlist(story: Story, profile: Profile, plan: Plan | None) -> list[Violation]:
    out: list[Violation] = []
    allowed = _parent_words(profile)
    asked = norm(f"{profile.request} {profile.topic_label}")         # родители сами просят про Луну или космос: «Луна» в тексте не имя героини
    topic_space = profile.topic == "space" or profile.place == "space" or any(w in asked for w in ("лун", "космос", "ракет", "звёзд", "звезд"))
    own = hero_forms_set(profile)
    phrases = _BAN_PHRASES + (_BAN_PHRASES_KY if profile.language == "ky" else [])
    violence = _VIOLENCE + (_VIOLENCE_KY if profile.language == "ky" else [])
    for where, page, text in _units(story):
        low = norm(text)
        for token in brand_hits(text, own):
            out.append(Violation("brand", _msg(where, f"известный персонаж или бренд «{token}»: замени оригинальным образом"), page))
        for pat, label in phrases:
            m = pat.search(low)
            if m and not ({w for w in words(m.group(0)) if len(w) >= 4} & allowed):
                out.append(Violation("ban_phrase", _msg(where, f"запрещённый оборот «{label}»: скажи это конкретным действием"), page))
        for pattern, cliche in _CLICHE:
            m = pattern.search(low)
            if m and not ({w for w in words(m.group(0)) if len(w) >= 4} & allowed):
                out.append(Violation("cliche", _msg(where, f"шаблонный персонаж «{cliche}»: придумай другого"), page))
        for label in tech_hits(text):
            out.append(Violation("tech", _msg(where, f"техническое слово «{label}»: книга простая, предмет назови обычным словом, "
                                                     "а дело героя пусть будет добрым или смелым"), page))
        for name in ban_name_hits(text, profile, allow_moon=topic_space):
            out.append(Violation("ban_name", _msg(where, f"имя-штамп «{name}» (так называют героев все нейросети): придумай другое имя"), page))
        for pat in violence:
            m = pat.search(low)
            if m:
                out.append(Violation("violence", _msg(where, f"недетская лексика «{m.group(0)}»: конфликты только мягкие"), page))
        if _EMOJI.search(text):
            out.append(Violation("emoji", _msg(where, "эмодзи: убери их, только слова"), page))
    book = " ".join(norm(u[2]) for u in _units(story))
    for pat, maximum, label in _LIMITED:
        n = len(pat.findall(book))
        if n > maximum:
            out.append(Violation("limited_phrase", f"«{label}» встречается {n} раз(а), можно не больше {maximum} на всю книгу"))
    return out


def _check_latin(story: Story, profile: Profile) -> list[Violation]:
    """Латиница в тексте запрещена. Исключение одно: ребёнка зовут латиницей (Emma), тогда его имя можно писать так."""
    out: list[Violation] = []
    own = norm(first_name(profile.name))
    latin_name = own if own.isascii() and len(own) >= 2 else ""
    for where, page, text in _units(story):
        found = [w for w in _LATIN.findall(text) if not (latin_name and norm(w).startswith(latin_name))]
        if found:
            out.append(Violation("latin", _msg(where, f"латинские буквы («{found[0]}»): весь текст только кириллицей"), page))
    return out


def _check_title_moral(story: Story) -> list[Violation]:
    out: list[Violation] = []
    n = len(words(story.title))
    if n > D.TITLE_MAX_WORDS:
        out.append(Violation("title", f"название из {plural_words(n)}, нужно не больше {D.TITLE_MAX_WORDS}"))
    n = len(words(story.moral))
    if n > D.MORAL_MAX_WORDS:
        out.append(Violation("moral", f"moral из {plural_words(n)}, нужно не больше {D.MORAL_MAX_WORDS}: "
                             "короткое пожелание или поступок, не лекция"))
    return out


def _lcs(a: list[str], b: list[str]) -> int:
    """Длина наибольшей общей подпоследовательности: сколько слов рефрена стоит в тексте по порядку (могут быть вставки)."""
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, start=1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


class RefrainMatcher:
    """Узнаёт рефрен плана в тексте. Одно общее слово («раз», «бир») рефреном не считается: в русском «ещё раз», а
    в кыргызском «бир» («один, какой-то») на каждой странице. Рефрен виден, когда
      1) по порядку стоят не меньше 70% его слов, не дальше двух лишних слов друг от друга («Раз, два, три — Бом
         поднял его»: 3 из 4); или
      2) подряд стоят два его первых слова («Раз, два… стоп!»: рефрен ломается, но это он); или
      3) первое слово рефрена составное («Мур-мяу», «Туда-сюда»): оно само по себе, и его первая половина перед
         многоточием («Мур… ш-ш-ш!»).
    Слова сравниваются без регистра и без «ё»; слово через дефис («бир-эки» = «пара») остаётся одним словом."""

    def __init__(self, refrain: str):
        self.words = [norm(w) for w in words(refrain)]
        n = len(self.words)
        self.need = max(2, math.ceil(D.REFRAIN_NEAR_WHOLE * n)) if n >= 2 else 1
        self.lead = self.words[:2] if n >= 3 else []
        first = self.words[0] if self.words else ""
        self.compound_first = "-" in first
        self.break_re = (re.compile(r"(?<![^\W\d_])" + re.escape(first.split("-")[0]) + r"\s*(?:…|\.\.\.)")
                         if self.compound_first else None)

    def matches(self, text: str) -> bool:
        tokens = [norm(t) for t in words(text)]
        if not tokens or not self.words:
            return False
        if self._near_whole(tokens):
            return True
        if self.lead and any(tokens[i:i + 2] == self.lead for i in range(len(tokens) - 1)):
            return True
        if self.compound_first and self.words[0] in tokens:
            return True
        return bool(self.break_re and self.break_re.search(norm(text)))

    def _near_whole(self, tokens: list[str]) -> bool:
        wanted = set(self.words)
        window = len(self.words) + 2
        return any(t in wanted and _lcs(self.words, tokens[i:i + window]) >= self.need for i, t in enumerate(tokens))


def _matcher(plan: Plan | None) -> RefrainMatcher | None:
    return RefrainMatcher(plan.refrain) if plan and plan.refrain else None


def _check_refrain(pages: list[str], plan: Plan | None, matcher: RefrainMatcher | None = None) -> list[Violation]:
    if not plan:
        return []
    matcher = matcher or RefrainMatcher(plan.refrain)
    count = sum(matcher.matches(text) for text in pages)
    low, high = D.REFRAIN_PAGES
    if count < low:
        return [Violation("refrain", f"рефрен «{plan.refrain}» встречается на {count} стр., нужно на 3–4: "
                          f"он возвращается и на третий раз ломается ({plan.refrain_break})")]
    if count > high:
        return [Violation("refrain", f"рефрен «{plan.refrain}» встречается на {count} стр., слишком часто: нужно 3–4")]
    return []


def _check_repeats(pages: list[str], profile: Profile, plan: Plan | None,
                   matcher: RefrainMatcher | None = None) -> list[Violation]:
    out: list[Violation] = []
    skip = hero_forms_set(profile)
    refrain_tokens: set[str] = set()
    if plan:
        refrain_tokens = {norm(t) for t in words(plan.refrain)}
        skip |= {norm(plan.helper_name)}
    skip |= refrain_tokens
    for i, text in enumerate(pages, start=1):
        counts = Counter(norm(t) for t in words(text) if len(t) >= 4 and norm(t) not in skip)
        for token, n in counts.most_common(1):
            if n >= 3:
                out.append(Violation("repeat", f"слово «{token}» повторяется {n} раза: найди другое слово или убери повтор", i))
    seen: dict[str, int] = {}
    for i, text in enumerate(pages, start=1):
        for s in sentences(text):
            tokens = [norm(t) for t in words(s)]
            if len(tokens) < 3 or (matcher and matcher.matches(s)):
                continue
            k = " ".join(tokens)
            if k in seen and seen[k] != i:
                out.append(Violation("same_sentence", f"такое же предложение уже было на стр. {seen[k]}: «{cut_words(s, 50)}»", i))
            seen.setdefault(k, i)
    return out


def _rare_stem(token: str) -> str:
    """Основа слова для подсчёта повторов: «глина», «глину», «глиной» — одно слово (у коротких слов берём 4 буквы, у длинных до 6)."""
    return token[:max(4, min(6, len(token) - 2))]


def _is_common(token: str) -> bool:
    return any(token[:n] in D.COMMON_STEMS for n in range(3, min(len(token), 8) + 1))


def _check_rare_words(pages: list[str], profile: Profile, plan: Plan | None) -> list[Violation]:
    """Нечастое слово («глина», «ленточка») не больше RARE_WORD_MAX раз на всю книгу: иначе страницы про одно и то же. Не считаются имя
    героя, помощника и друзей, рефрен, частые слова рассказа (COMMON_STEMS), звуки через дефис, слова короче пяти букв. Слова
    сравниваются по основе (_rare_stem), падежи не мешают."""
    names = set(hero_forms_set(profile))
    if plan:
        for name in plan.member_names:
            names |= name_forms_set(name, "boy") | name_forms_set(name, "girl")
        names |= {norm(t) for t in words(plan.refrain)}
    skip = {_rare_stem(t) for t in names}
    counts: Counter[str] = Counter()
    shown: dict[str, str] = {}
    pages_of: dict[str, set[int]] = {}
    for i, text in enumerate(pages, start=1):
        for token in words(text):
            t = norm(token)
            stem = _rare_stem(t)
            if len(t) < D.RARE_WORD_STEM or "-" in t or stem in skip or _is_common(t):
                continue
            counts[stem] += 1
            shown.setdefault(stem, t)
            pages_of.setdefault(stem, set()).add(i)
    return [Violation("repeat", f"слово «{shown[stem]}» встречается {n} раз на страницах {', '.join(map(str, sorted(pages_of[stem])))}: "
                                f"одно и то же слово не больше 2 раз за книгу, назови предмет иначе или скажи через «он/она/это»")
            for stem, n in counts.most_common() if n > D.RARE_WORD_MAX]


def _mask_refrain(tokens: list[str], refrain_tokens: list[str]) -> list[str]:
    """Полный рефрен в тексте заменяется одним значком: сам рефрен (даже совпавший с рефреном примера) списыванием не считается."""
    if len(refrain_tokens) < 2:
        return tokens
    out: list[str] = []
    i, n = 0, len(refrain_tokens)
    while i < len(tokens):
        if tokens[i:i + n] == refrain_tokens:
            out.append("§")
            i += n
        else:
            out.append(tokens[i])
            i += 1
    return out


def _check_echo(story: Story, profile: Profile, plan: Plan | None) -> list[Violation]:
    out: list[Violation] = []
    grams = example_grams()
    refrain_tokens = [norm(t) for t in words(plan.refrain)] if plan else (
        [norm(t) for t in words(story.refrain)] if story.refrain else [])
    allowed = hero_forms_set(profile) | {norm(c.name) for c in story.cast}
    if plan:
        allowed |= {norm(plan.helper_name)}
    for i, page in enumerate(story.pages, start=1):
        tokens = [norm(t) for t in words(page.text)]
        hit = next((g for g in _grams(_mask_refrain(tokens, refrain_tokens)) if g in grams), None)
        if hit:
            out.append(Violation("echo", f"фраза «{hit}» списана с примера из инструкции: пиши своими словами", i))
            continue
        name = next((t for t in tokens if t in example_name_forms() and t not in allowed), None)
        if name:
            out.append(Violation("echo", f"имя «{name}» взято из примера: придумай своё", i))
    return out


def _check_style(pages: list[str], plan: Plan | None, language: str = "ru",
                 matcher: RefrainMatcher | None = None) -> list[Violation]:
    out: list[Violation] = []
    emotion_re = _EMOTION_KY if language == "ky" else _EMOTION
    questions, ellipsis, emotions = [], 0, 0
    for i, text in enumerate(pages, start=1):
        for s in sentences(text):
            if s.rstrip().endswith("?") and "—" not in s and "«" not in s:
                questions.append(i)
        low = norm(text)
        for s in sentences(text):
            if ("…" in s or "..." in s) and not (matcher and matcher.matches(s)):
                ellipsis += s.count("…") + s.count("...")
        emotions += len(emotion_re.findall(low))
    if len(questions) > 2:
        out.append(Violation("question", "вопросы читателю в тексте (стр. " + ", ".join(map(str, questions[:4])) +
                             "): оставь не больше двух, остальное сделай репликой героя с тире"))
    if ellipsis > 1:
        out.append(Violation("ellipsis", f"многоточий {ellipsis}, можно не больше одного вне рефрена"))
    if emotions > D.EMOTION_MAX:
        out.append(Violation("emotion", f"слов-чувств («радостно», «грустно», «удивился»…) {emotions}, можно не больше "
                             f"{D.EMOTION_MAX}: покажи чувство телом и действием"))
    return out


def _check_islamic(story: Story, profile: Profile) -> list[Violation]:
    if not profile.islamic:
        return []
    out: list[Violation] = []
    own = norm(first_name(profile.name))                      # Аят, Ангелина: имя ребёнка не «запретное слово»
    for where, page, text in _units(story):
        low = norm(text)
        for pat in _ISLAMIC_RE:
            m = pat.search(low)
            if m and not (own and m.group(0).startswith(own)):
                out.append(Violation("islamic", _msg(where, f"«{m.group(0)}»: в режиме «Исламские ценности» это нельзя"), page))
    return out


_KY_LETTERS = "үөң"


def _check_language(story: Story, profile: Profile) -> list[Violation]:
    """Кыргызская книга написана по-кыргызски. cyrillic_ratio русский текст за кыргызский принимает, поэтому тут две
    проверки: в тексте есть ү, ө, ң хотя бы у небольшой доли слов (в русском их нет совсем) и русских служебных слов
    (и, в, на, что, это, как, но…) не больше нескольких."""
    if profile.language != "ky":
        return []
    own = hero_forms_set(profile)
    total = with_letters = ru_total = 0
    ru_by_unit: list[tuple[str, int | None, list[str]]] = []
    for where, page, text in _units(story):
        tokens = [norm(t) for t in words(text)]
        total += len(tokens)
        with_letters += sum(any(ch in t for ch in _KY_LETTERS) for t in tokens)
        found = [t for t in tokens if t in D.RU_FUNCTION_WORDS and t not in own]
        ru_total += len(found)
        if found:
            ru_by_unit.append((where, page, found))
    out: list[Violation] = []
    if total >= D.KY_LETTER_MIN_WORDS and with_letters / total < D.KY_LETTER_SHARE_MIN:
        out.append(Violation("wrong_language", "в тексте почти нет букв ү, ө, ң: это не кыргызский язык. Пиши всю книгу "
                                               "по-кыргызски, русский текст не годится"))
    if ru_total > D.KY_RU_WORDS_MAX:
        for where, page, found in ru_by_unit:
            shown = ", ".join(f"«{w}»" for w in dict.fromkeys(found).keys())
            out.append(Violation("wrong_language", _msg(where, f"русские слова ({shown}): в кыргызской книге весь текст "
                                                               "по-кыргызски"), page))
    return out


def _helper_matcher(name: str, language: str):
    """Узнаёт имя помощника в любой форме. Роду помощника код не знает, поэтому берём падежи обоих родов; в кыргызском
    к имени добавляется много суффиксов (множественное, принадлежность), поэтому там годится и слово, начинающееся с имени."""
    first = norm(first_name(name))
    forms = name_forms_set(name, "boy") | name_forms_set(name, "girl")

    def is_helper(token: str) -> bool:
        if token in forms:
            return True
        return language == "ky" and len(first) >= 3 and token.startswith(first) and len(token) <= len(first) + 5
    return is_helper


_OPENERS = ("«", '"', "“", "„", "(", ":")
_DASHES = ("—", "–", "-")


def _starts_speech(before: str) -> bool:
    """Заглавная буква здесь — начало прямой речи или цитаты: после кавычки, скобки, двоеточия или тире, которое стоит после
    знака препинания («сказал: — Придумал!»). Тире сразу после слова («Раз, два, три — Бом поднял его») речь не открывает."""
    if before.endswith(_OPENERS):
        return True
    if before.endswith(_DASHES):
        earlier = before[:-1].rstrip()
        return not earlier or earlier[-1] in ":,.!?…»\"”"
    return False


def _mid_capitals(text: str) -> list[str]:
    """Слова с заглавной буквы не в начале предложения и не в начале речи или цитаты: имена и названия."""
    out: list[str] = []
    for s in sentences(text):
        for idx, m in enumerate(_WORD.finditer(s)):
            token = m.group(0)
            if idx == 0 or len(token) < 3 or not token[0].isupper() or token.isupper() or token.isascii():
                continue
            if _starts_speech(s[:m.start()].rstrip()):
                continue
            out.append(token)
    return out


def _same_name(a: str, b: str) -> bool:
    """Рекс / Рекса / Рексу — одно имя: общее начало не короче трёх букв и почти всего короткого слова."""
    return len(os.path.commonprefix([a, b])) >= max(3, min(len(a), len(b)) - 1)


def _is_place(token: str) -> bool:
    return token in D.PLACE_WORDS or any(token.startswith(s) and len(token) <= len(s) + 5 for s in D.PLACE_STEMS)


def _check_cast(pages: list[str], story: Story, profile: Profile, plan: Plan | None) -> list[Violation]:
    """Каст маленький: герой, ОДИН помощник (или одна команда друзей) и препятствие. Помощник виден по имени хотя бы на трёх
    страницах, а новых именованных персонажей («по одному на страницу») нет. Если помощник — команда, КАЖДЫЙ друг из неё хотя бы
    раз назван в тексте (код team: жёсткое нарушение). Без помощника в книге (старые книги) проверять нечего."""
    if plan:
        helper, obstacle = plan.helper_name, plan.obstacle
        members = list(plan.member_names)
    else:
        found_helper, found_obstacle = story.character("helper"), story.character("obstacle")
        helper = found_helper.name if found_helper else ""
        obstacle = found_obstacle.name if found_obstacle else ""
        members = [helper] + [c.name for c in story.characters("teammate")] if helper else []
    if not helper:
        return []
    matchers = {name: _helper_matcher(name, profile.language) for name in members}

    def is_helper(token: str) -> bool:
        return any(match(token) for match in matchers.values())

    out: list[Violation] = []
    present = sum(any(is_helper(norm(t)) for t in words(text)) for text in pages)
    if present < D.HELPER_MIN_PAGES:
        out.append(Violation("cast", f"помощник «{first_name(helper)}» назван по имени на {present} стр., нужно не меньше "
                                     f"{D.HELPER_MIN_PAGES}: он рядом с героем почти всю книгу, называй его по имени"))
    for name in members[1:]:
        if not any(matchers[name](norm(t)) for text in pages for t in words(text)):
            out.append(Violation("team", f"друг из команды «{first_name(name)}» ни разу не назван в тексте: каждый из команды "
                                         "участвует в сюжете (делает или говорит одно короткое), назови его по имени"))
    known = hero_forms_set(profile) | _parent_words(profile) | {norm(w) for w in words(obstacle)}
    first = first_name(profile.name)
    known |= {v for v in latin_variants(first)}
    names: list[str] = []
    for text in pages:
        for token in _mid_capitals(text):
            t = norm(token)
            if t in known or is_helper(t) or _is_place(t) or any(_same_name(norm(n), t) for n in names):
                continue
            names.append(token)
    if len(names) > D.NEW_NAMES_MAX:
        team = "и друзья из команды" if len(members) > 1 else ""
        out.append(Violation("cast", f"новые персонажи: {', '.join(names[:5])}. В книге только герой, "
                                     f"«{first_name(helper)}» {team} и препятствие: замени их помощником или словами «он/она»"))
    return out


def check_story(story: Story, profile: Profile, plan: Plan | None = None) -> list[Violation]:
    """Все нарушения книги. Пустой список — текст принят."""
    limits = page_limits(profile.age, profile.language)
    pages = [p.text for p in story.pages]
    matcher = _matcher(plan)
    out: list[Violation] = []
    out += _check_limits(pages, limits, matcher)
    out += _check_name_count(pages, profile)
    out += _check_title_moral(story)
    out += _check_banlist(story, profile, plan)
    out += _check_latin(story, profile)
    out += _check_language(story, profile)
    out += _check_islamic(story, profile)
    out += _check_echo(story, profile, plan)
    out += _check_repeats(pages, profile, plan, matcher)
    out += _check_rare_words(pages, profile, plan)
    out += _check_refrain(pages, plan, matcher)
    out += _check_cast(pages, story, profile, plan)
    out += _check_style(pages, plan, profile.language, matcher)
    return out


def require_valid(story: Story, profile: Profile, plan: Plan | None = None) -> None:
    violations = check_story(story, profile, plan)
    if violations:
        raise StoryValidationError("найдены ошибки в тексте:\n" + violations_text(violations))


def new_violations(before: list[Violation], after: list[Violation]) -> list[Violation]:
    """Что появилось в after и не было в before (для правок редактора и корректора)."""
    known = Counter((v.code, v.page) for v in before)
    out = []
    for v in after:
        key = (v.code, v.page)
        if known[key] > 0:
            known[key] -= 1
        else:
            out.append(v)
    return out


# ============================================================================ редактор: правки только плохих страниц
@dataclass(frozen=True)
class Fix:
    page: int
    problem: str
    fixed_text: str


def parse_json_loose(raw: str):
    """Первый полный JSON-объект или список из ответа модели (допускает ```json и мусор вокруг)."""
    if not isinstance(raw, str) or not raw.strip():
        raise StoryValidationError("Ответ пустой.")
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw.strip()).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise StoryValidationError("Ответ не является JSON.")
    try:
        data, _ = json.JSONDecoder().raw_decode(text, min(starts))
    except json.JSONDecodeError as e:
        raise StoryValidationError(f"JSON повреждён: {e.msg} (позиция {e.pos}).")
    return data


def parse_fixes(raw: str) -> list[Fix]:
    """Ответ редактора: {"fixes": [{page, problem, fixed_text}]} или просто список таких объектов."""
    data = parse_json_loose(raw)
    items = data
    if isinstance(data, dict):
        items = next((data[k] for k in ("fixes", "pages", "issues") if isinstance(data.get(k), list)), None)
        if items is None and "page" in data:
            items = [data]
    if not isinstance(items, list):
        raise StoryValidationError('Нужен список правок: {"fixes": [{"page": 3, "problem": "...", "fixed_text": "..."}]}.')
    fixes: list[Fix] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            page = int(item.get("page"))
        except (TypeError, ValueError):
            continue
        text = item.get("fixed_text")
        if not isinstance(text, str) or not text.strip():
            continue
        fixes.append(Fix(page=page, problem=str(item.get("problem") or "")[:200], fixed_text=text.strip()))
    return fixes


# ============================================================================ проверка понятности («понятно ли пятилетнему»)
@dataclass(frozen=True)
class ClarityProblem:
    page: int | None        # номер страницы с 1; None — проблема всей книги
    kind: str               # word | object | logic | place
    what: str               # что именно непонятно


@dataclass(frozen=True)
class Comprehension:
    retell: tuple[str, ...]                 # пересказ каждой страницы одной фразой
    problems: tuple[ClarityProblem, ...]
    summary: str                            # что потеряли, что нашли, кто рад
    meaning: str = ""                       # в чём смысл книги одной фразой (по мнению проверяющего)

    @property
    def clear(self) -> bool:
        return not self.problems


def parse_comprehension(raw: str) -> Comprehension:
    """Ответ проверяющего понятности: {"retell": [...], "problems": [{page, kind, what}], "summary": "..."}.
    Проблемой считается и строка вместо объекта. Пустой список problems — всё понятно."""
    data = parse_json_loose(raw)
    if not isinstance(data, dict):
        raise StoryValidationError('Нужен объект {"retell": [...], "problems": [...], "summary": "..."}.')
    raw_problems = data.get("problems")
    if raw_problems is None:
        raw_problems = []
    if not isinstance(raw_problems, list):
        raise StoryValidationError('Поле problems должно быть списком [{"page", "kind", "what"}].')
    problems: list[ClarityProblem] = []
    for item in raw_problems:
        if isinstance(item, str) and clean_text(item):
            problems.append(ClarityProblem(None, "logic", clean_text(item)[:240]))
        elif isinstance(item, dict) and isinstance(item.get("what"), str) and clean_text(item["what"]):
            try:
                page = int(item.get("page"))
            except (TypeError, ValueError):
                page = None
            kind = item.get("kind") if item.get("kind") in ("word", "object", "logic", "place", "sense") else "logic"
            problems.append(ClarityProblem(page if page and 1 <= page <= PAGES else None, kind, clean_text(item["what"])[:240]))
    retell = data.get("retell")
    retell = tuple(clean_text(x)[:240] for x in retell if isinstance(x, str)) if isinstance(retell, list) else ()
    summary = clean_text(data.get("summary"))[:300] if isinstance(data.get("summary"), str) else ""
    meaning = clean_text(data.get("meaning"))[:300] if isinstance(data.get("meaning"), str) else ""
    nonsense = data.get("nonsense")                          # «бессмыслицы» можно прислать и отдельным списком: это те же проблемы
    if isinstance(nonsense, list):
        for item in nonsense:
            text = item if isinstance(item, str) else (item.get("what") if isinstance(item, dict) else None)
            page = item.get("page") if isinstance(item, dict) else None
            if isinstance(text, str) and clean_text(text):
                page = page if isinstance(page, int) and 1 <= page <= PAGES else None
                problems.append(ClarityProblem(page, "sense", clean_text(text)[:240]))
    return Comprehension(retell=retell, problems=tuple(problems), summary=summary, meaning=meaning)


def apply_fixes(story: Story, fixes: list[Fix], profile: Profile, plan: Plan | None = None) -> tuple[Story, list[int]]:
    """Подставляет исправленные страницы по одной. Правка принимается, только если после неё в книге не стало
    новых нарушений валидатора; иначе эта страница остаётся из черновика. Возвращает книгу и номера принятых страниц."""
    current = story
    current_violations = check_story(current, profile, plan)
    applied: list[int] = []
    for fx in fixes:
        if not 1 <= fx.page <= len(current.pages) or fx.fixed_text == current.pages[fx.page - 1].text:
            continue
        pages = list(current.pages)
        pages[fx.page - 1] = Page(text=fx.fixed_text, scene=pages[fx.page - 1].scene)
        candidate = Story(title=current.title, hero_visual=current.hero_visual, style_note=current.style_note,
                          pages=tuple(pages), moral=current.moral, wish=current.wish, cast=current.cast,
                          refrain=current.refrain)
        try:
            validate_story(candidate.to_dict(), profile.language)
        except StoryValidationError:
            continue
        found = check_story(candidate, profile, plan)
        if new_violations(current_violations, found):
            continue
        current, current_violations = candidate, found
        applied.append(fx.page)
    return current, applied
