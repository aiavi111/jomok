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

# Старые темы: остались только для чтения прежних заказов (в анкету и в /api/config не попадают).
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

# Каталог тем книги: родитель выбирает ровно одну (поле profile.world). Каждая тема опирается на оригинального героя-архетипа
# (app/writer_data.py, ARCHETYPES): роли и характеры «по духу» любимых историй, но имена, одежда и внешность свои, без чужих
# брендов. archetype_key — id архетипа. topic — служебная тема для зёрен писателя (по умолчанию «adventure»).
# Порядок = порядок карточек в Mini App: сначала самые частые.
DEFAULT_WORLD_TOPIC = "adventure"
WORLDS: dict[str, dict] = {
    "football": {"label": "Футбол", "emoji": "⚽", "hint": "Стадион, команда и придуманный чемпион", "archetype_key": "football"},
    "dino_friend": {"label": "Добрый динозаврик", "emoji": "🦖", "hint": "Динозавры и их весёлые друзья", "archetype_key": "donut", "topic": "dinosaurs"},
    "princess": {"label": "В стиле принцессы", "emoji": "👑", "hint": "Бал, замок и добрый дракончик", "archetype_key": "kingdom"},
    "space_crew": {"label": "Путешествие в космос", "emoji": "🚀", "hint": "Лис-пилот, корабль и робот", "archetype_key": "crew", "topic": "space"},
    "hero_agile": {"label": "Ловкий супергерой", "emoji": "🦸", "hint": "Герой в маске лазит по крышам и спасает город", "archetype_key": "climber"},
    "rescue_team": {"label": "Малыши-спасатели", "emoji": "🚒", "hint": "Команда, которая спешит на помощь", "archetype_key": "rescue"},
    "unicorns": {"label": "В мире единорогов", "emoji": "🦄", "hint": "Радужный мир, ленты и волшебные облачка", "archetype_key": "unicorns"},
    "race_cars": {"label": "Гоночные машинки", "emoji": "🏎️", "hint": "Говорящие машинки на трассе", "archetype_key": "racecars"},
    "dragon_friend": {"label": "Дружба с драконом", "emoji": "🐉", "hint": "Приручить маленького дракона добротой", "archetype_key": "sneezer"},
    "mermaid": {"label": "Подводное царство русалок", "emoji": "🧜", "hint": "Коралловый дворец, рыбки и черепаха", "archetype_key": "mermaid"},
    "hero_team": {"label": "Команда супергероев", "emoji": "🦸", "hint": "Герои в разных костюмах спасают мир", "archetype_key": "heroteam"},
    "blocks": {"label": "Кубический мир", "emoji": "🧱", "hint": "Строим из кубиков вместе с добрыми кубиками-существами", "archetype_key": "blocks"},
    "ice_kingdom": {"label": "Ледяное королевство", "emoji": "❄️", "hint": "Снежный замок, ледяная повелительница и олень", "archetype_key": "ice"},
    "wizard_school": {"label": "Школа волшебства", "emoji": "🪄", "hint": "Первый урок и говорящая сова", "archetype_key": "wizard"},
    "animal_city": {"label": "Город зверей", "emoji": "🏙️", "hint": "Лис-детектив и крольчиха-патрульная", "archetype_key": "animal_city"},
    "long_braid": {"label": "Башня и принцесса с длинной косой", "emoji": "🏰", "hint": "Сказка про башню, косу и смелость", "archetype_key": "braid"},
    "star_singers": {"label": "Поющие защитницы", "emoji": "🎤", "hint": "Девочки со звёздными микрофонами защищают музыку", "archetype_key": "singers"},
    "fast_pals": {"label": "Гонки быстрых зверят", "emoji": "🐆", "hint": "Зверята бегут наперегонки", "archetype_key": "fastpals"},
    "jump_land": {"label": "Страна прыжков", "emoji": "🍄", "hint": "Платформы, монетки и весёлый герой в красной кепке", "archetype_key": "jumpland"},
    "blue_tractor": {"label": "Трактор и стройка", "emoji": "🚜", "hint": "Дружный трактор, экскаватор и поезд", "archetype_key": "builders"},
    "forest_house": {"label": "Лесной дом", "emoji": "🏡", "hint": "Добродушный медведь и непоседа-проказница", "archetype_key": "honey"},
    "workshop_helpers": {"label": "Мастерята-помощники", "emoji": "🔧", "hint": "Крошки с инструментами чинят всё вокруг", "archetype_key": "tinkers"},
    "ninja_animals": {"label": "Звери-ниндзя", "emoji": "🥷", "hint": "Ловкие друзья с разноцветными повязками", "archetype_key": "cubs"},
    "mountain_friends": {"label": "Горные друзья Кыргызстана", "emoji": "🏔️", "hint": "Барсёнок, жеребёнок и птенец орла", "archetype_key": "mountain"},
}

# Старые заказы хранили прежние id миров: читаем их как новые (проверка новой анкеты их не принимает).
LEGACY_WORLDS: dict[str, str] = {"kingdom": "princess", "builders": "blue_tractor", "caped_hero": "hero_agile"}


def world_topic(world: str | None) -> str:
    """Служебная тема книги по выбранной теме каталога."""
    return (WORLDS.get(world or "") or {}).get("topic", DEFAULT_WORLD_TOPIC)

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
        "styles": [dict(item) for item in STYLES],
        "default_style": DEFAULT_STYLE,
        "worlds": [{"id": k, "label": v["label"], "hint": v["hint"], "emoji": v["emoji"]} for k, v in WORLDS.items()],
        "values": [{"id": k, "label": v["label"], "emoji": v["emoji"]} for k, v in VALUES.items()],
        "traits": [{"id": k, "boy": m, "girl": f} for k, (m, f) in TRAITS.items()],
        "likes": LIKES,
        "languages": [{"id": k, "label": v["label"]} for k, v in LANGUAGES.items()],
    }
