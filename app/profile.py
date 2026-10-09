"""Анкета ребёнка: проверка данных, пришедших из Mini App.

Серверу нельзя верить ничему, что прислал клиент: всё проверяется заново.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import options
from . import writer_data
from .errors import ValidationError
from .textutil import clean_text

NAME_MAX = 30
TEXT_MAX = 120
LIKE_MAX = 60
LIST_MAX = 3
REQUEST_MAX = 300                    # «Что вы хотите увидеть в книге?»
FAVORITES_MAX = 120                  # «Любимые герои, животные, игрушки»
CARTOONS_MAX = 120                   # «Любимые мультфильмы или герои»: только вдохновение (роль и настроение, без имён и внешности)
# Пометка для писателя рядом с cartoons в <child>: из названий берётся только роль и функция героя
CARTOONS_NOTE = ("ТОЛЬКО ВДОХНОВЕНИЕ: бери роль, настроение и функцию героев (например, весёлая проказница и добрый большой "
                 "опекун), но НЕ имена, одежду, цвета и внешность; названий этих мультфильмов и героев в книге быть не должно")
AGE_MIN, AGE_MAX = 3, 9


def _known(value, allowed) -> bool:
    """value — один из ключей allowed. Клиент мог прислать список или объект: такое значение не ключ, а не повод для сбоя."""
    return isinstance(value, str) and value in allowed


def _truthy(value) -> bool:
    return value is True or value in (1, "1", "true", "True", "yes", "on")


@dataclass
class Profile:
    name: str
    age: int
    gender: str                      # boy | girl
    hair: str = ""
    eyes: str = ""
    clothes: str = ""
    likes: list[str] = field(default_factory=list)
    traits: list[str] = field(default_factory=list)   # id из options.TRAITS
    place: str = "mountains"
    place_custom: str = ""
    topic: str = options.DEFAULT_TOPIC   # id из options.TOPICS: о чём книга
    topic_custom: str = ""               # своя тема, если topic == "custom"
    request: str = ""                    # свободный текст: что хотят увидеть в книге
    favorites: str = ""                  # свободный текст: любимые герои, животные, игрушки
    world: str | None = None             # id из options.WORLDS: мир книги («как в любимом мультфильме»); None — мира нет
    cartoons: str = ""                   # свободный текст: любимые мультфильмы и герои (только вдохновение для писателя)
    style: str = options.DEFAULT_STYLE   # id из options.STYLES: стиль иллюстраций; неизвестный или пустой — по умолчанию
    value: str = "kindness"
    islamic: bool = False
    headscarf: bool = False
    language: str = "ru"
    dedication: str = ""
    has_photo: bool = False

    # ------------------------------------------------------------------ создание
    @classmethod
    def from_payload(cls, data, *, has_photo: bool = False) -> "Profile":
        if not isinstance(data, dict):
            raise ValidationError("Анкета пришла в неверном виде. Обновите приложение и попробуйте ещё раз.",
                                  field="profile")

        def text(key: str, label: str, limit: int = TEXT_MAX, source: dict | None = None) -> str:
            src = data if source is None else source
            value = clean_text(src.get(key))
            if len(value) > limit:
                raise ValidationError(f"Поле «{label}» слишком длинное: не больше {limit} символов.", field=key)
            return value

        if any(ch in str(data.get("name") or "") for ch in "<>"):
            raise ValidationError("В имени могут быть только буквы, пробел и дефис.", field="name")
        name = text("name", "Имя", NAME_MAX)
        if not name:
            raise ValidationError("Впишите имя ребёнка.", field="name")
        if not any(ch.isalpha() for ch in name) or not all(ch.isalpha() or ch in " -'’." for ch in name):
            raise ValidationError("В имени могут быть только буквы, пробел и дефис.", field="name")

        try:
            age = int(data.get("age"))
        except (TypeError, ValueError):
            raise ValidationError("Выберите возраст ребёнка от 3 до 9 лет.", field="age")
        if not AGE_MIN <= age <= AGE_MAX:
            raise ValidationError("Книги подходят детям от 3 до 9 лет. Выберите возраст из этого диапазона.",
                                  field="age")

        gender = data.get("gender")
        if gender not in options.GENDERS:
            raise ValidationError("Выберите: мальчик или девочка.", field="gender")

        appearance = data.get("appearance")
        if not isinstance(appearance, dict):
            appearance = data  # допускаем «плоские» поля hair/eyes/clothes
        hair = text("hair", "Волосы", source=appearance)
        eyes = text("eyes", "Глаза", source=appearance)
        clothes = text("clothes", "Одежда", source=appearance)

        raw_likes = data.get("likes") or []
        if not isinstance(raw_likes, list):
            raise ValidationError("Список увлечений пришёл в неверном виде.", field="likes")
        likes: list[str] = []
        for item in raw_likes:
            value = clean_text(item)
            if not value:
                continue
            if len(value) > LIKE_MAX:
                raise ValidationError(f"Каждое увлечение — не больше {LIKE_MAX} символов.", field="likes")
            if value.lower() not in [x.lower() for x in likes]:
                likes.append(value)
        if len(likes) > LIST_MAX:
            raise ValidationError(f"Выберите не больше {LIST_MAX} увлечений.", field="likes")

        raw_traits = data.get("traits") or []
        if not isinstance(raw_traits, list):
            raise ValidationError("Список черт характера пришёл в неверном виде.", field="traits")
        traits: list[str] = []
        for item in raw_traits:
            if not _known(item, options.TRAITS):
                raise ValidationError("Неизвестная черта характера. Обновите приложение и выберите заново.",
                                      field="traits")
            if item not in traits:
                traits.append(item)
        if len(traits) > LIST_MAX:
            raise ValidationError(f"Выберите не больше {LIST_MAX} черт характера.", field="traits")

        place = data.get("place")
        if not _known(place, options.PLACES):
            raise ValidationError("Выберите, где происходит действие книги.", field="place")
        place_custom = text("place_custom", "Место") if place == "custom" else ""
        if place == "custom" and not place_custom:
            raise ValidationError("Опишите, где происходит действие, или выберите готовый вариант.",
                                  field="place_custom")

        value = data.get("value")
        if not _known(value, options.VALUES):
            raise ValidationError("Выберите, чему учит книга.", field="value")

        topic = data.get("topic")
        if topic is None or topic == "":
            topic = options.DEFAULT_TOPIC                      # старые клиенты тему не присылают: приключение
        if not _known(topic, options.TOPICS):
            raise ValidationError("Выберите тему книги из списка.", field="topic")
        topic_custom = text("topic_custom", "Своя тема") if topic == "custom" else ""
        request = text("request", "Что вы хотите увидеть в книге", REQUEST_MAX)
        favorites = text("favorites", "Любимые герои, животные, игрушки", FAVORITES_MAX)
        if topic == "custom" and not (topic_custom or request):
            raise ValidationError("Опишите свою тему или напишите, что хотите увидеть в книге.",
                                  field="topic_custom")

        world = data.get("world")
        if world is None or world == "":
            world = None                                       # мир необязателен: старые клиенты его не присылают
        elif not _known(world, options.WORLDS):
            raise ValidationError("Выберите мир книги из списка.", field="world")
        cartoons = text("cartoons", "Любимые мультфильмы", CARTOONS_MAX)

        style = data.get("style")
        if not _known(style, options.STYLE_IDS):
            style = options.DEFAULT_STYLE                      # старые клиенты стиль не присылают, чужое значение — не повод для ошибки

        language = data.get("language")
        if not _known(language, options.LANGUAGES):
            raise ValidationError("Выберите язык книги: русский или кыргызский.", field="language")

        islamic = _truthy(data.get("islamic"))
        headscarf = islamic and gender == "girl" and _truthy(data.get("headscarf"))

        dedication = text("dedication", "Посвящение")

        return cls(
            name=name, age=age, gender=gender, hair=hair, eyes=eyes, clothes=clothes,
            likes=likes, traits=traits, place=place, place_custom=place_custom, topic=topic,
            topic_custom=topic_custom, request=request, favorites=favorites, world=world, cartoons=cartoons, style=style, value=value,
            islamic=islamic, headscarf=headscarf, language=language, dedication=dedication,
            has_photo=bool(has_photo),
        )

    # ------------------------------------------------------------------ хранение
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def scrubbed(self) -> dict:
        """Копия без личных данных — остаётся после удаления файлов, для статистики."""
        d = self.to_dict()
        for key in ("name", "hair", "eyes", "clothes", "dedication", "place_custom", "topic_custom", "request",
                    "favorites", "cartoons"):
            d[key] = ""
        d["likes"] = []
        d["scrubbed"] = True
        return d

    # ------------------------------------------------------------------ для промтов
    @property
    def gender_word(self) -> str:
        return "девочка" if self.gender == "girl" else "мальчик"

    @property
    def value_label(self) -> str:
        return options.VALUES[self.value]["label"].lower()

    @property
    def place_label(self) -> str:
        if self.place == "custom":
            return self.place_custom
        return options.PLACES[self.place]["label"]

    @property
    def topic_label(self) -> str:
        """Тема словами: для своей темы — то, что написал человек."""
        if self.topic == "custom" and self.topic_custom:
            return self.topic_custom
        return options.TOPICS.get(self.topic, options.TOPICS[options.DEFAULT_TOPIC])["label"]

    @property
    def style_label(self) -> str:
        return options.style_label(self.style)

    @property
    def world_label(self) -> str:
        return options.WORLDS[self.world]["label"] if self.world in options.WORLDS else ""

    def trait_labels(self) -> list[str]:
        return [options.trait_label(t, self.gender) for t in self.traits]

    def for_model(self) -> dict:
        """Данные для блока <child>: только то, что нужно писателю."""
        appearance = {k: v for k, v in
                      (("волосы", self.hair), ("глаза", self.eyes), ("одежда", self.clothes)) if v}
        child: dict = {
            "имя": self.name,
            "возраст": self.age,
            "пол": self.gender_word,
            "внешность": appearance,
            "любит": self.likes,
            "характер": self.trait_labels(),
            "место действия": self.place_label,
            "ценность": self.value_label,
            "язык книги": options.LANGUAGES[self.language]["label"],
            "topic_label": self.topic_label,
            "style_label": self.style_label,
        }
        if self.topic != "custom" and self.topic in options.TOPICS:
            child["topic_hint"] = options.TOPICS[self.topic]["hint"]
        if self.request:
            child["request"] = self.request
        if self.favorites:
            child["favorites"] = self.favorites
        if self.world in options.WORLDS:
            child["world_label"] = options.WORLDS[self.world]["label"]
            child["world_hint"] = options.WORLDS[self.world]["hint"]
            archetype = writer_data.archetype_for_world(self.world, islamic=self.islamic)
            if archetype is not None:
                child["archetype"] = archetype.title
        if self.cartoons:
            child["cartoons"] = self.cartoons
            child["cartoons_note"] = CARTOONS_NOTE
        if self.islamic:
            child["исламские ценности"] = True
            if self.gender == "girl":
                child["героиня в платке"] = self.headscarf
        return child
