"""Mock-провайдер текста: шаблонная книга без сети.

Нужен, чтобы весь путь (форма → ожидание → просмотр → PDF) работал без единого ключа. Книга устроена как настоящая
(короткие страницы по возрасту, помощник с именем, рефрен, который ломается, герои для художника), поэтому проходит тот
же код-валидатор (writer.check_story), что и тексты моделей. Сюжет шаблонный: настоящие, уникальные книги пишут
модели openai и gemini. Кыргызский текст здесь — простой пример для проверки шрифтов и вёрстки, его должен вычитать носитель языка.

Каждая страница — четыре коротких весёлых предложения A, B, C, D (с возгласами и звуками, как в настоящей книге). Малышам
(3–4 года) идут A и B, детям 5–6 лет A, B и C, старшим все четыре: так длина страницы сама попадает в лимиты по возрасту.
"""
from __future__ import annotations

import asyncio

from .. import options
from ..profile import Profile
from ..story import PAGES, Story, validate_story
from ..textutil import cyrillic_ratio
from ..writer import band_for_age
from ..writer_data import PALETTES
from .base import TextProvider

# Помощник героя: (по-русски, по-кыргызски, по-английски, род по-русски m/f, имя)
HELPERS = {
    "mountains": ("белый ягнёнок", "ак козу", "a little white lamb with curly wool", "m", "Бом"),
    "yurt": ("рыжий жеребёнок", "кызыл кулун", "a ginger foal with a white star on the forehead", "m", "Топ"),
    "issykkul": ("маленькая птичка", "кичинекей куш", "a small blue songbird with a yellow chest", "f", "Тика"),
    "silkroad": ("добрый верблюжонок", "кичинекей төө", "a kind baby camel with long eyelashes", "m", "Пуф"),
    "space": ("маленький робот", "кичинекей робот", "a small round friendly robot on one wheel", "m", "Зум"),
    "underwater": ("золотая рыбка", "алтын балык", "a little golden fish with long flowing fins", "f", "Бася"),
    "custom": ("пушистый котёнок", "кичинекей мышык", "a fluffy grey kitten with white paws", "m", "Киви"),
}

WHERE_RU = {"mountains": "в горах", "yurt": "по джайлоо", "issykkul": "вдоль Иссык-Куля", "silkroad": "через базар",
            "space": "среди звёзд", "underwater": "по морскому дну", "custom": "по знакомой тропинке"}
WHERE_KY = {"mountains": "тоо арасынан", "yurt": "жайлоодон", "issykkul": "Ысык-Көлдүн жээги менен",
            "silkroad": "базар аркылуу", "space": "жылдыздардын арасынан", "underwater": "деңиздин түбүнөн",
            "custom": "тааныш жол менен"}

REFRAIN = {"ru": "Раз, два, три — прыг!", "ky": "Бир, эки, үч — секир!"}
REFRAIN_BREAK = {"ru": "Раз, два… стоп!", "ky": "Бир, эки… токто!"}

MORAL = {
    "ru": {
        "kindness": "Доброта делает мир теплее.",
        "honesty": "Честное слово дороже любой игрушки.",
        "help_parents": "Кто помогает родителям, тот приносит свет в дом.",
        "gratitude": "«Спасибо» — маленькое слово с большой силой.",
        "animals": "У того, кто заботится о животных, большое сердце.",
        "respect_elders": "Кто уважает старших, тому всегда светит удача.",
        "courage": "Смелость — это сделать доброе дело, даже когда страшновато.",
    },
    "ky": {
        "kindness": "Боорукерлик дүйнөнү жылытат.",
        "honesty": "Чынчылдык — эң чоң байлык.",
        "help_parents": "Ата-энеге жардам берген бала — үйдүн кубанычы.",
        "gratitude": "«Рахмат» — кичинекей сөз, бирок чоң күчү бар.",
        "animals": "Жаныбарларды сүйгөндүн жүрөгү кең.",
        "respect_elders": "Улууну сыйлаган өзү да сыйлуу болот.",
        "courage": "Эр жүрөктүк — коркконуңа карабай жакшылык кылуу.",
    },
}

# палитра книги по месту (как её выбирает режиссёр): одна на всю книгу, её держат все картинки
PALETTE_BY_PLACE = {"mountains": "forest_emerald", "yurt": "sunset_gold", "issykkul": "aqua_sea", "silkroad": "sunset_gold",
                    "space": "neon_night", "underwater": "aqua_sea", "custom": "rainbow_sky"}


def style_note_for(place: str) -> str:
    wanted = PALETTE_BY_PLACE.get(place, "rainbow_sky")
    return next(p.en for p in PALETTES if p.id == wanted)


STYLE_NOTE = style_note_for("custom")
OBSTACLE_LOOK = "a wide shallow fast stream with smooth grey stones and the remains of a washed-away wooden bridge"


class _Ctx:
    """Склонения и роды: имя всегда в именительном падеже, остальное подбирается по полу."""

    def __init__(self, p: Profile):
        self.p = p
        self.n = p.name
        self.boy = p.gender == "boy"
        self.helper_ru, self.helper_ky, self.helper_en, self.helper_g, self.helper_name = HELPERS[p.place]

    def g(self, m: str, f: str) -> str:
        return m if self.boy else f

    def hv(self, m: str, f: str) -> str:
        return m if self.helper_g == "m" else f


def _pick(sentences: list[str], count: int) -> str:
    """Первые count предложений; реплики диалога («— …») начинаются с новой строки."""
    out = ""
    for sentence in sentences[:count]:
        if not out:
            out = sentence
        else:
            out += ("\n" if sentence.startswith("—") else " ") + sentence
    return out


def _sentence_count(age: int) -> int:
    return {"3-4": 2, "5-6": 3, "7-9": 4}[band_for_age(age)]


# ======================================================================= русский
def _pages_ru(c: _Ctx) -> list[list[str]]:
    p, n, g, hv = c.p, c.n, c.g, c.hv
    where = WHERE_RU[p.place]
    hn, hp = c.helper_name, c.helper_ru
    child = g("мальчик", "девочка")
    islamic = p.islamic
    return [
        [f"{n} {g('нёс', 'несла')} бабушке тёплые лепёшки в плетёной корзинке!",
         "К ручке корзинки был привязан красный шнурок.",
         f"Путь лежал {where}, и утро только начиналось.",
         "Топ-топ-топ, шагалось легко!"],
        ["На пути оказался широкий ручей, а мостик унесло водой.",
         "Бабушка ждала на том берегу.",
         "Вода громко шумела и катила по дну мелкие камешки.",
         "Плюх-плюх, булькали волны!"],
        [f"Тут из-за камня {hv('выглянул', 'выглянула')} {hp} по имени {hn}.",
         f"{hn} {hv('позвал', 'позвала')}: — Раз, два, три — прыг!",
         "Но он был слишком широким для прыжка.",
         "Вот это ширина!"],
        [f"Раз, два, три — прыг! — и {child} {g('скользнул', 'скользнула')} с камня.",
         "Ноги оказались в ледяной воде.",
         "Холодные брызги долетели до носа и до самых ушей.",
         "Бр-р-р, вот это вода!"],
        [f"Раз, два, три — {hn} {hv('подставил', 'подставила')} спину, но вода была глубокой.",
         "Мокрые ноги мёрзли, а берег был далеко.",
         "Холодный ветер дул в лицо.",
         "Хлюп-хлюп, хлюпало в ботинках!"],
        [f"Раз, два… стоп — {child} {g('смотрел', 'смотрела')} на шнурок и палку.",
         f"— {g('Придумал', 'Придумала')}! — тихо {g('сказал', 'сказала')} {g('он', 'она')}.",
         "Глаза заблестели, а пальцы уже искали нужный узел.",
         "Вот это идея!"],
        [f"{g('Он', 'Она')} {g('привязал', 'привязала')} шнурок к палке и {g('бросил', 'бросила')} её через ручей.",
         "Палка зацепилась за корень на том берегу.",
         "Получились перила, и они держали крепко.",
         "Ура, получилось!"],
        [f"Раз, два, три — прыг! — крикнули {n} и {hn}.",
         "Корзинка с лепёшками добралась до бабушки целой.",
         ("Бабушка сказала «Альхамдулиллях» и налила всем горячего чая." if islamic
          else "Бабушка засмеялась и налила всем горячего чая."),
         "Вот это был день!"],
    ]


# ================================================================== кыргызский
def _pages_ky(c: _Ctx) -> list[list[str]]:
    p, n = c.p, c.n
    where = WHERE_KY[p.place]
    hn, hk = c.helper_name, c.helper_ky
    islamic = p.islamic
    return [
        [f"{n} чоң энесине ысык боорсок алып баратты!",
         "Себеттин сабына кызыл жип байланган эле.",
         f"Жол {where} өтүп жатты, күн жаңы эле чыккан.",
         "Бала бат-бат басып барды."],
        ["Алдынан кең суу чыкты, көпүрөнү суу агызып кеткен.",
         "Чоң эне суунун аркы өйүзүндө күтүп турду.",
         "Суу шаркырап, майда таштарды дөңгөлөтүп агып жатты.",
         "Шалп-шалп, толкундар чайпалды!"],
        [f"Таштын артынан {hk} чыкты, анын аты {hn} эле.",
         f"{hn} чакырды: — Бир, эки, үч — секир!",
         "Бирок суу секирип өтө албаган кең эле.",
         "Ой, кандай кең суу!"],
        ["Бир, эки, үч — секир! — бала таштан тайды.",
         "Эки буту тең муздак сууга түштү.",
         "Чачыраган муздак суу мурдуна да, кулагына да жетти.",
         "Ух, сууну карачы!"],
        [f"Бир, эки, үч — {hn} аркасын тосту, суу терең эле.",
         "Суу буттарды үшүттү, жээк алыс эле.",
         "Себеттеги жип шамалда акырын термелди.",
         "Шылдыр-шылдыр, суу акты."],
        ["Бир, эки… токто, бала жипке жана таякка карады.",
         "— Ойлоп таптым! — деди акырын.",
         "Көздөрү жайнап, манжалары түйүндү издеди.",
         "Мына кандай ой!"],
        ["Ал жипти таякка байлап, суунун аркы өйүзүнө ыргытты.",
         "Таяк аркы өйүздөгү тамырга илинип калды.",
         "Жип тартылып, тик тутка болуп калды.",
         "Ураа, чыкты!"],
        [f"Бир, эки, үч — {hn} менен {n} суудан өттү.",
         "Боорсоктор чоң энеге ысык бойдон жетти.",
         ("Чоң эне «Алхамдулиллах» деп, баарына чай куюп берди." if islamic
          else "Чоң эне кубанып, баарына чай куюп берди."),
         "Кандай жакшы күн болду!"],
    ]


# =============================================================== общие части
def _latin_only(text: str) -> str:
    """Заглушка не умеет переводить: внешность по-русски пропускаем (настоящие модели переводят сами)."""
    return text if text and cyrillic_ratio(text) == 0 else ""


def _hero_visual(p: Profile) -> str:
    kid = "boy" if p.gender == "boy" else "girl"
    hair = _latin_only(p.hair) or ("short dark brown hair" if p.gender == "boy" else "dark brown hair in two soft braids")
    eyes = _latin_only(p.eyes) or "warm brown eyes"
    if _latin_only(p.clothes):
        outfit = p.clothes
    elif p.islamic:
        outfit = ("a sky-blue embroidered vest over a white long-sleeved shirt, long dark trousers and soft brown boots"
                  if p.gender == "boy" else
                  "a coral long-sleeved dress with a small embroidered pattern, long to the ankles, and little brown boots")
    else:
        outfit = ("a sky-blue embroidered vest over a white shirt, dark trousers and soft brown boots"
                  if p.gender == "boy" else
                  "a coral dress with a small embroidered pattern, white tights and little brown boots")
    scarf = " She wears a simple pastel headscarf." if p.headscarf else ""
    return (f"A {p.age}-year-old {kid} with a slim, energetic build, {hair}, {eyes}, rosy cheeks and a bright friendly "
            f"smile. Wearing {outfit}, exactly the same outfit on every page.{scarf} Gentle curious expression, "
            f"child proportions with a slightly large head, simple memorable features.")


def _scenes(c: _Ctx) -> list[str]:
    """Сцены для художника (image_brief): героев называем словами the hero / the helper / the obstacle."""
    p = c.p
    place_en = options.PLACES[p.place]["en"]
    if p.place == "custom":
        place_en = "a special place chosen by the family"
    helper = c.helper_en
    return [
        f"Wide shot: the hero walks along a sunny path in {place_en}, carrying a basket with a red cord on its handle, "
        "while the obstacle, a stream, glitters far ahead.",
        "Medium shot: the hero stops at the edge of the obstacle, a wide shallow stream with a washed-away wooden bridge, "
        "holding the basket with the red cord in soft morning light.",
        f"Medium shot: the helper, {helper}, peeks out from behind a rock and waves to the hero on the stream bank in warm light.",
        "Medium shot: the hero leaps onto a wet stone and slips with arms out while the helper watches from the bank, "
        "splashes sparkling in the sun.",
        "Wide shot: the helper offers its back in the water next to the hero, the obstacle too deep and the hero's feet wet, "
        "the red cord swaying on the basket.",
        "Close-up: the hero pauses on the bank, looking at the red cord and a long stick on the ground, while the helper "
        "waits nearby in soft light.",
        "Medium shot: the hero ties the red cord to the stick and throws it across the obstacle while the helper watches "
        "with wide eyes.",
        "Wide shot: the hero and the helper cross the obstacle holding the taut cord like a rail, the basket safe, and "
        "grandmother waves from the far bank in golden light.",
    ]


def build_mock_story(p: Profile) -> dict:
    c = _Ctx(p)
    count = _sentence_count(p.age)
    pages = _pages_ky(c) if p.language == "ky" else _pages_ru(c)
    texts = [_pick(sentences, count) for sentences in pages]
    scenes = _scenes(c)
    title = f"{p.name} жана {c.helper_name}" if p.language == "ky" else f"{p.name} и {c.helper_name}"
    moral = MORAL[p.language][p.value]
    if p.language == "ky":
        wish = f"{p.name}, жүрөгүң ар дайым жылуу болсун, жашооң жакшы жомокторго бай болсун!"
    else:
        wish = f"{p.name}, пусть твоё сердце всегда остаётся тёплым, а в жизни будет много добрых приключений!"
    hero_visual = _hero_visual(p)
    assert len(texts) == len(scenes) == PAGES
    return {
        "title": title,
        "hero_visual": hero_visual,
        "style_note": style_note_for(p.place),
        "cast": [
            {"name": p.name, "role": "hero", "look": hero_visual},
            {"name": c.helper_name, "role": "helper", "look": c.helper_en},
            {"name": "ручей" if p.language == "ru" else "суу", "role": "obstacle", "look": OBSTACLE_LOOK},
        ],
        "refrain": REFRAIN[p.language],
        "pages": [{"text": t, "scene": s} for t, s in zip(texts, scenes)],
        "moral": moral,
        "wish": wish,
    }


class MockTextProvider(TextProvider):
    name = "mock"

    def __init__(self, delay: float = 0.0):
        self.delay = delay

    async def generate_story(self, profile: Profile) -> Story:
        if self.delay:
            await asyncio.sleep(self.delay)
        return validate_story(build_mock_story(profile), profile.language)

    async def _complete(self, system, messages, model=None):  # pragma: no cover - mock не ходит в сеть; model игнорируется
        raise NotImplementedError
