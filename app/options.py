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

# О чём книга: одна тема на выбор (id -> подпись, эмодзи, короткая подсказка под кнопкой).
# «custom» — своя тема: человек описывает её сам (topic_custom).
DEFAULT_TOPIC = "adventure"
TOPICS: dict[str, dict] = {
    "adventure": {"label": "Приключение", "emoji": "🧭", "hint": "Путешествие, поиски и открытия"},
    "dinosaurs": {"label": "Динозавры", "emoji": "🦕", "hint": "Добрые динозавры и древний мир"},
    "space": {"label": "Космос", "emoji": "🚀", "hint": "Звёзды, планеты и ракета"},
    "animals": {"label": "Звери и лес", "emoji": "🦊", "hint": "Друзья-животные в лесу и в горах"},
    "superheroes": {"label": "Супергерои", "emoji": "🦸", "hint": "Герой со своей суперсилой"},
    "pirates": {"label": "Пираты и клад", "emoji": "🏴\u200d☠️", "hint": "Карта, корабль и сокровища"},
    "sea": {"label": "Море", "emoji": "🌊", "hint": "Подводный мир, корабли и острова"},
    "friends": {"label": "Друзья", "emoji": "🤝", "hint": "Дружба и общие дела"},
    "kindness": {"label": "Добрые дела", "emoji": "💛", "hint": "Как помочь тому, кому трудно"},
    "life_lesson": {"label": "Учимся жизни", "emoji": "🦷", "hint": "Зубки, сон, садик, врач"},
    "custom": {"label": "Своя тема", "emoji": "✏️", "hint": "Опишите сами"},
}

# Мир книги: «как в любимом мультфильме», но без чужих героев. Каждый мир опирается на оригинального героя-архетипа
# (app/writer_data.py, ARCHETYPES): характеры и роли похожи по духу, имена, одежда и внешность свои. archetype_key — id архетипа,
# у «Свой вариант» его нет (мир описывают поля request, favorites и cartoons). Мир необязателен: по умолчанию его нет.
WORLDS: dict[str, dict] = {
    "forest_house": {"label": "Лесной дом", "emoji": "🏡", "hint": "Добродушный медведь и непоседа-проказница",
                     "archetype_key": "honey"},
    "rescue_team": {"label": "Малыши-спасатели", "emoji": "🚒", "hint": "Команда, которая спешит на помощь",
                    "archetype_key": "rescue"},
    "workshop_helpers": {"label": "Мастерята-помощники", "emoji": "🔧", "hint": "Крошки с инструментами чинят всё вокруг",
                         "archetype_key": "tinkers"},
    "ninja_animals": {"label": "Звери-ниндзя", "emoji": "🥷", "hint": "Ловкие друзья с разноцветными повязками",
                      "archetype_key": "cubs"},
    "caped_hero": {"label": "Супергерой с плащом", "emoji": "🦸", "hint": "Герой и верный напарник",
                   "archetype_key": "cape"},
    "kingdom": {"label": "Королевство", "emoji": "👑", "hint": "Принцессы, замок и добрые драконы",
                "archetype_key": "kingdom"},
    "dino_friend": {"label": "Добрый динозаврик", "emoji": "🦖", "hint": "Динозавры и их весёлые друзья",
                    "archetype_key": "donut"},
    "space_crew": {"label": "Космический экипаж", "emoji": "🚀", "hint": "Лис-пилот, корабль и робот",
                   "archetype_key": "crew"},
    "builders": {"label": "Стройка и машины", "emoji": "🏗️", "hint": "Экскаватор, поезд и дружная стройка",
                 "archetype_key": "builders"},
    "mountain_friends": {"label": "Горные друзья Кыргызстана", "emoji": "🏔️",
                         "hint": "Барсёнок, жеребёнок и птенец орла", "archetype_key": "mountain"},
    "custom": {"label": "Свой вариант", "emoji": "✏️", "hint": "Опишите любимый мир сами", "archetype_key": None},
}

# Стиль иллюстраций: родитель выбирает один из трёх (id -> подпись, подсказка, эмодзи). Блоки для художника — app/prompts.py.
# Профиль без стиля или с неизвестным стилем рисуется в стиле по умолчанию (cartoon3d), ошибки нет.
DEFAULT_STYLE = "cartoon3d"
STYLES: list[dict] = [
    {"id": "cartoon3d", "label": "3D-мультик", "hint": "яркий, как в кино про зверят", "emoji": "🧸"},
    {"id": "flat2d", "label": "2D-мультик", "hint": "плоская цветная иллюстрация как в детских книжках", "emoji": "✏️"},
    {"id": "realistic", "label": "Реалистичный", "hint": "кинематографичные кадры, ребёнок как на вашем фото", "emoji": "📷"},
]
STYLE_IDS = tuple(item["id"] for item in STYLES)


def style_label(style_id: str) -> str:
    return next((item["label"] for item in STYLES if item["id"] == style_id), STYLES[0]["label"])


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
        "topics": [{"id": k, "label": v["label"], "emoji": v["emoji"], "hint": v["hint"]} for k, v in TOPICS.items()],
        "default_topic": DEFAULT_TOPIC,
        "styles": [dict(item) for item in STYLES],
        "default_style": DEFAULT_STYLE,
        "worlds": [{"id": k, "label": v["label"], "hint": v["hint"], "emoji": v["emoji"]} for k, v in WORLDS.items()],
        "values": [{"id": k, "label": v["label"], "emoji": v["emoji"]} for k, v in VALUES.items()],
        "traits": [{"id": k, "boy": m, "girl": f} for k, (m, f) in TRAITS.items()],
        "likes": LIKES,
        "languages": [{"id": k, "label": v["label"]} for k, v in LANGUAGES.items()],
    }
