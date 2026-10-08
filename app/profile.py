"""Анкета ребёнка: проверка данных, пришедших из Mini App.

Серверу нельзя верить ничему, что прислал клиент: всё проверяется заново.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import options
from .errors import ValidationError
from .textutil import clean_text

NAME_MAX = 30
TEXT_MAX = 120
LIKE_MAX = 60
LIST_MAX = 3
AGE_MIN, AGE_MAX = 3, 9


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
            raise ValidationError("Сказки подходят детям от 3 до 9 лет. Выберите возраст из этого диапазона.",
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
            if item not in options.TRAITS:
                raise ValidationError("Неизвестная черта характера. Обновите приложение и выберите заново.",
                                      field="traits")
            if item not in traits:
                traits.append(item)
        if len(traits) > LIST_MAX:
            raise ValidationError(f"Выберите не больше {LIST_MAX} черт характера.", field="traits")

        place = data.get("place")
        if place not in options.PLACES:
            raise ValidationError("Выберите, где происходит сказка.", field="place")
        place_custom = text("place_custom", "Место") if place == "custom" else ""
        if place == "custom" and not place_custom:
            raise ValidationError("Опишите, где происходит сказка, или выберите готовый вариант.",
                                  field="place_custom")

        value = data.get("value")
        if value not in options.VALUES:
            raise ValidationError("Выберите, чему учит сказка.", field="value")

        language = data.get("language")
        if language not in options.LANGUAGES:
            raise ValidationError("Выберите язык книги: русский или кыргызский.", field="language")

        islamic = _truthy(data.get("islamic"))
        headscarf = islamic and gender == "girl" and _truthy(data.get("headscarf"))

        dedication = text("dedication", "Посвящение")

        return cls(
            name=name, age=age, gender=gender, hair=hair, eyes=eyes, clothes=clothes,
            likes=likes, traits=traits, place=place, place_custom=place_custom, value=value,
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
        for key in ("name", "hair", "eyes", "clothes", "dedication", "place_custom"):
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
        }
        if self.islamic:
            child["исламские ценности"] = True
            if self.gender == "girl":
                child["героиня в платке"] = self.headscarf
        return child
