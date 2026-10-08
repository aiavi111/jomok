"""Варианты ответов в анкете. Один источник правды: сервер проверяет по ним,
а Mini App получает их из /api/config и рисует кнопки."""
from __future__ import annotations

# id -> (подпись на кнопке, эмодзи, описание места по-английски для картинок)
PLACES: dict[str, dict] = {
    "mountains": {
        "label": "Горы Кыргызстана", "emoji": "🏔️",
        "en": "the snow-capped Tien Shan mountains of Kyrgyzstan with green alpine meadows and a clear mountain stream",
    },
    "yurt": {
        "label": "Юрта на джайлоо", "emoji": "🏕️",
        "en": "a green summer pasture (jailoo) in Kyrgyzstan with a white felt yurt, grazing horses and distant mountains",
    },
    "issykkul": {
        "label": "Иссык-Куль", "emoji": "🌊",
        "en": "the shore of the deep blue lake Issyk-Kul in Kyrgyzstan with pebbly beach and snowy peaks across the water",
    },
    "silkroad": {
        "label": "Шёлковый путь и базар", "emoji": "🐪",
        "en": "a lively Silk Road bazaar in Central Asia with colourful stalls, fresh bread, melons and a passing camel caravan",
    },
    "space": {
        "label": "Космос", "emoji": "🚀",
        "en": "outer space with friendly glowing stars, a ringed planet and a small cozy spaceship",
    },
    "underwater": {
        "label": "Подводный мир", "emoji": "🐠",
        "en": "a warm underwater world with colourful coral, schools of fish and sunbeams from above",
    },
    "custom": {
        "label": "Свой вариант", "emoji": "✏️",
        "en": "a place described by the parent",
    },
}

VALUES: dict[str, dict] = {
    "kindness": {"label": "Доброта", "emoji": "💛"},
    "honesty": {"label": "Честность", "emoji": "🌟"},
    "help_parents": {"label": "Помощь родителям", "emoji": "🏡"},
    "gratitude": {"label": "Благодарность", "emoji": "🙏"},
    "animals": {"label": "Забота о животных", "emoji": "🐑"},
    "respect_elders": {"label": "Уважение к старшим", "emoji": "👵"},
    "courage": {"label": "Смелость", "emoji": "🦁"},
}

# id -> (форма для мальчика, форма для девочки)
TRAITS: dict[str, tuple[str, str]] = {
    "kind": ("добрый", "добрая"),
    "brave": ("смелый", "смелая"),
    "curious": ("любопытный", "любопытная"),
    "funny": ("весёлый", "весёлая"),
    "shy": ("застенчивый", "застенчивая"),
    "stubborn": ("упрямый", "упрямая"),
    "caring": ("заботливый", "заботливая"),
}

LIKES: list[str] = [
    "Лошади", "Животные", "Динозавры", "Машинки", "Рисование", "Музыка",
    "Футбол", "Куклы", "Космос", "Конструктор", "Книги", "Сладости",
]

LANGUAGES: dict[str, dict] = {
    "ru": {"label": "Русский", "name_in_prompt": "русском"},
    "ky": {"label": "Кыргызча", "name_in_prompt": "кыргызском"},
}

GENDERS = ("boy", "girl")


def trait_label(trait_id: str, gender: str) -> str:
    m, f = TRAITS[trait_id]
    return f if gender == "girl" else m


def public_options() -> dict:
    """Что отдаём Mini App в /api/config."""
    return {
        "places": [{"id": k, "label": v["label"], "emoji": v["emoji"]} for k, v in PLACES.items()],
        "values": [{"id": k, "label": v["label"], "emoji": v["emoji"]} for k, v in VALUES.items()],
        "traits": [{"id": k, "boy": m, "girl": f} for k, (m, f) in TRAITS.items()],
        "likes": LIKES,
        "languages": [{"id": k, "label": v["label"]} for k, v in LANGUAGES.items()],
    }
