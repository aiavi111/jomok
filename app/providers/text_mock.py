"""Mock-провайдер текста: шаблонная сказка без сети.

Нужен, чтобы весь путь (форма → ожидание → просмотр → PDF) работал без единого ключа.
Сюжет шаблонный — настоящие, уникальные сказки пишут модели openai и gemini.
Кыргызский текст здесь — простой пример для проверки шрифтов и вёрстки, его должен
вычитать носитель языка.
"""
from __future__ import annotations

import asyncio

from .. import options
from ..profile import Profile
from ..story import Story, validate_story
from ..textutil import cap_first, cyrillic_ratio
from .base import TextProvider

# Помощник героя: (по-русски, по-кыргызски, по-английски, род по-русски m/f)
HELPERS = {
    "mountains": ("белый ягнёнок", "ак козу", "a little white lamb", "m"),
    "yurt": ("рыжий жеребёнок", "кызыл кулун", "a ginger foal", "m"),
    "issykkul": ("маленькая птичка", "кичинекей куш", "a small songbird", "f"),
    "silkroad": ("добрый верблюжонок", "кичинекей төө", "a kind baby camel", "m"),
    "space": ("маленький робот", "кичинекей робот", "a small round friendly robot", "m"),
    "underwater": ("золотая рыбка", "алтын балык", "a little golden fish", "f"),
    "custom": ("пушистый котёнок", "кичинекей мышык", "a fluffy kitten", "m"),
}

WHERE_RU = {
    "mountains": "высоко в горах Кыргызстана, где вершины блестят снегом",
    "yurt": "на зелёном джайлоо, рядом с белой юртой",
    "issykkul": "на берегу синего Иссык-Куля",
    "silkroad": "в городе на старом Шёлковом пути, где шумел большой базар",
    "space": "на маленьком космическом корабле среди звёзд",
    "underwater": "на дне тёплого моря, среди разноцветных кораллов",
}
WHERE_KY = {
    "mountains": "Кыргызстандын бийик тоолорунда",
    "yurt": "жайлоодо, ак боз үйдүн жанында",
    "issykkul": "Ысык-Көлдүн жээгинде",
    "silkroad": "Жибек жолундагы шаарда, чоң базар бар жерде",
    "space": "жылдыздардын арасында учкан космос кемесинде",
    "underwater": "жылуу деңиздин түбүндө, түстүү маржандардын арасында",
}

PATH_RU = {  # (где встречают помощника, преграда, как её прошли)
    "space": ("на звёздной дорожке", "облако блестящей космической пыли",
              "Вместе они нашли светящуюся тропу между пылинками."),
    "underwater": ("среди кораллов", "быстрое морское течение",
                   "Вместе они поплыли в обход, вдоль тихих кораллов."),
}
PATH_RU_DEFAULT = ("на тропинке", "быстрый ручей", "Вместе они нашли камни, по которым можно было перейти.")

ADV_RU = {
    "mountains": ["Тропа поднималась всё выше, и вокруг сверкали снежные вершины.",
                  "Внизу, в долине, серебрилась горная речка."],
    "yurt": ["Над джайлоо плыли белые облака, а по траве бежал тёплый ветерок.",
             "Вдалеке паслись лошади, и из юрт поднимался дымок."],
    "issykkul": ["Вода Иссык-Куля переливалась всеми оттенками синего.",
                 "На берегу блестела галька, и кричали чайки."],
    "silkroad": ["На базаре пахло специями, свежим хлебом и сладкой дыней.",
                 "Мимо шёл караван, и колокольчики на верблюдах звенели в такт."],
    "space": ["Мимо проплывали звёзды, словно золотые зёрнышки.",
              "Далёкая планета с кольцами мягко светилась в темноте."],
    "underwater": ["Мимо проплыла стайка разноцветных рыб.",
                   "Кораллы переливались, как драгоценные камни."],
    "custom": ["Вокруг было так интересно, что время летело незаметно.",
               "Каждый шаг открывал что-нибудь новое."],
}
ADV_KY = {
    "mountains": ["Жол барган сайын бийикке көтөрүлдү, айланада кар баскан чокулар жаркырады.",
                  "Төмөндө өрөөндө тоо суусу күмүштөй агып жатты."],
    "yurt": ["Жайлоодо ак булуттар сүзүп, жылуу шамал жашыл чөптү тербетти.",
             "Алыс жерде жылкылар оттоп, боз үйлөрдөн түтүн чыгып жатты."],
    "issykkul": ["Ысык-Көлдүн суусу көк түстүн бардык өңүндө жылтылдады.",
                 "Жээкте майда таштар жаркырап, чардактар үн салды."],
    "silkroad": ["Базарда жыпар жыттанып, жаңы нан жана таттуу коон жытташты.",
                 "Жанынан керван өттү, төөлөрдүн коңгуроолору шыңгырады."],
    "space": ["Жанынан жылдыздар алтын данектей сүзүп өттү.",
              "Алыстан шакектүү планета жумшак жарыгын чачты."],
    "underwater": ["Жанынан түстүү балыктардын тобу сүзүп өттү.",
                   "Маржандар кымбат таштардай жаркырады."],
    "custom": ["Айланада ушунчалык кызык болгондуктан, убакыт байкалбай өттү.",
               "Ар бир кадам жаңы нерсени ачты."],
}

TRAITS_KY = {"kind": "боорукер", "brave": "эр жүрөк", "curious": "кызыкчыл", "funny": "шайыр",
             "shy": "уялчаак", "stubborn": "өжөр", "caring": "камкор"}

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

# Английские сцены для картинок: (дилемма, выбор, результат)
VALUE_EN = {
    "kindness": ("a tired traveler resting by the road with nothing to eat",
                 "offers a warm flatbread to the traveler", "the traveler smiles gratefully as they share the food"),
    "honesty": ("a small purse of silver coins lying on the path",
                "holds up the purse and calls out to ask who lost it", "the owner runs up, thanking the child warmly"),
    "help_parents": ("friends playing ball by the road and calling the child to join",
                     "politely waves them off and keeps carrying the basket", "the child arrives on time, then plays happily with friends"),
    "gratitude": ("a kind woman at a stone well offering cool water",
                  "thanks her warmly with a hand on the heart and carries her bucket", "the woman beams and shares dried apricots with everyone"),
    "animals": ("a hungry little lamb crying alone by the path",
                "gives the lamb water and gently leads it back to the flock", "the mother sheep bleats happily and nuzzles her lamb"),
    "respect_elders": ("an elderly white-bearded man carrying a heavy bundle on a bridge",
                       "greets him politely and helps carry the bundle", "the elder blesses the child with a gentle hand on the head"),
    "courage": ("a dark rocky gorge echoing with strange sounds",
                "takes a deep breath and steps forward first", "the echo turns out to be their own voices and everyone laughs"),
}


class _Ctx:
    """Склонения и роды: имя всегда в именительном падеже, остальное подбирается по полу."""

    def __init__(self, p: Profile):
        self.p = p
        self.n = p.name
        self.boy = p.gender == "boy"
        h = HELPERS[p.place]
        self.helper_ru, self.helper_ky, self.helper_en, self.helper_g = h
        self.like = (p.likes[0].lower() if p.likes else "приключения")
        self.islamic = p.islamic

    def g(self, m: str, f: str) -> str:
        return m if self.boy else f

    def hv(self, m: str, f: str) -> str:
        return m if self.helper_g == "m" else f


def _pick(sentences: list[str], count: int) -> str:
    """Первые count предложений; реплики диалога («— …») начинаются с новой строки."""
    out = ""
    for sentence in (s for s in sentences[:count] if s):
        if not out:
            out = sentence
        else:
            out += ("\n" if sentence.startswith("—") else " ") + sentence
    return out


def _sentence_count(age: int) -> int:
    return {3: 2, 4: 3, 5: 3, 6: 4, 7: 4, 8: 5, 9: 6}.get(age, 4)


# ======================================================================= русский
def _value_ru(c: _Ctx) -> dict:
    n, g = c.n, c.g
    return {
        "kindness": {
            "sit": ["У дороги сидел усталый путник, у которого не было еды.", "Он тихо вздыхал и смотрел вдаль."],
            "choice": [f"{n} {g('подошёл', 'подошла')} к путнику и {g('протянул', 'протянула')} ему самую румяную лепёшку.",
                       f"— Возьмите, пожалуйста, она тёплая, — {g('сказал', 'сказала')} {n}.",
                       "Лепёшек оставалось немного, но доброе сердце подсказало, что так правильно."],
            "result": ["Путник улыбнулся и поблагодарил от всего сердца.",
                       "Он поделился сладкой дыней, и все вместе повеселели.",
                       "Оказалось, что доброта делает лепёшки только вкуснее."]},
        "honesty": {
            "sit": [f"На тропинке {n} {g('нашёл', 'нашла')} кошелёк с серебряными монетами.",
                    "На эти монеты можно было купить сладости, и никто бы не узнал."],
            "choice": [f"{n} {g('покачал', 'покачала')} головой: «Это чужое».",
                       f"— Эй! Кто потерял кошелёк? — громко {g('крикнул', 'крикнула')} {n}.",
                       "Сердце стучало, но говорить правду было спокойно."],
            "result": ["Скоро из-за поворота выбежал торговец, который искал свою пропажу.",
                       "— Какой честный ребёнок! — обрадовался он и поблагодарил.",
                       "Честность оказалась дороже любых сладостей."]},
        "help_parents": {
            "sit": ["Возле дороги ребята играли в мяч и звали играть с собой.",
                    "Играть так хотелось, а корзинка тем временем ждала бабушку."],
            "choice": [f"{n} вежливо {g('отказался', 'отказалась')}: «Сначала помогу маме, потом поиграю».",
                       f"— Это важное дело, — {g('сказал', 'сказала')} {n}, крепче взявшись за корзинку.",
                       "Поручение мамы стало главным."],
            "result": ["Лепёшки добрались до бабушки ещё тёплыми.",
                       f"Когда мама узнала об этом, она крепко обняла {g('сына', 'дочку')}.",
                       "А вечером все ребята вместе играли в мяч."]},
        "gratitude": {
            "sit": ["У колодца добрая женщина дала путникам холодной воды.",
                    "Вода была чистой и вкусной, а женщина торопилась по своим делам."],
            "choice": [f"{n} {g('поблагодарил', 'поблагодарила')} её от всего сердца: «Спасибо вам огромное!»",
                       f"И ещё {g('помог', 'помогла')} донести ведро до дома.",
                       "Сказать «спасибо» и ответить добром — вот что значит быть благодарным."],
            "result": ["Женщина улыбнулась и угостила всех сладким урюком.",
                       "— Ваше спасибо дороже любого подарка, — сказала она.",
                       "Всем стало тепло на душе."]},
        "animals": {
            "sit": ["У дороги плакал маленький ягнёнок, потерявший маму.", "Он был голодный и очень испуганный."],
            "choice": [f"{n} {g('присел', 'присела')} рядом, {g('напоил', 'напоила')} ягнёнка водой и ласково {g('погладил', 'погладила')}.",
                       f"— Не бойся, я отведу тебя к стаду, — {g('пообещал', 'пообещала')} {n}.",
                       "Забота о малыше была важнее спешки."],
            "result": ["Вдали заблеяла мама-овца и побежала навстречу.", "Ягнёнок радостно прижался к ней.",
                       "Чабан издалека помахал рукой в знак благодарности."]},
        "respect_elders": {
            "sit": ["На мосту стоял седобородый аксакал с тяжёлой ношей.", "Он остановился, чтобы отдохнуть."],
            "choice": [f"{n} вежливо {g('поздоровался', 'поздоровалась')}, {g('уступил', 'уступила')} дорогу и {g('спросил', 'спросила')}: «Аксакал, можно вам помочь?»",
                       "Вместе они донесли тяжёлую ношу до конца моста.",
                       f"{n} внимательно {g('слушал', 'слушала')}, когда аксакал рассказывал старую историю."],
            "result": ["Аксакал погладил ребёнка по голове и пожелал добра.",
                       "— Кто уважает старших, тому всегда светит удача, — сказал он.",
                       "Эти слова согрели лучше горячего чая."]},
        "courage": {
            "sit": ["Дальше путь шёл через тёмное ущелье, откуда доносилось странное эхо.",
                    "Обойти было нельзя — иначе пришлось бы опоздать."],
            "choice": [f"{n} {g('глубоко вдохнул', 'глубоко вдохнула')} и {g('первым', 'первой')} {g('шагнул', 'шагнула')} в ущелье.",
                       f"— Я не боюсь, — {g('прошептал', 'прошептала')} {n}, хотя сердце стучало громко.",
                       "Друг пошёл следом, держась рядом."],
            "result": ["Из темноты донёсся смех: это было лишь эхо их собственных голосов!",
                       "Они рассмеялись и дальше пошли весело.",
                       f"{n} {g('понял', 'поняла')}: смелость — это шагнуть вперёд, даже когда страшновато."]},
    }[c.p.value]


def _pages_ru(c: _Ctx, count: int) -> list[str]:
    p, n, g, hv = c.p, c.n, c.g, c.hv
    where = WHERE_RU.get(p.place) or f"в особенном месте — {p.place_custom}"
    traits = options.trait_label(p.traits[0], p.gender) if p.traits else g("добрый", "добрая")
    exclam = g(f"«Какой {traits} мальчик!»", f"«Какая {traits} девочка!»")
    path_loc, obstacle, crossing = PATH_RU.get(p.place, PATH_RU_DEFAULT)
    helper = c.helper_ru
    val = _value_ru(c)
    adv = ADV_RU[p.place]
    bism = c.islamic

    p1 = [f"{n} {g('жил', 'жила')} {where}.",
          f"Каждое утро {n} {g('просыпался', 'просыпалась')} с улыбкой и {g('бежал', 'бежала')} встречать новый день.",
          f"Все вокруг говорили: {exclam}",
          f"У {g('нашего героя', 'нашей героини')} была любимая забава: {c.like}.",
          f"А ещё {n} {g('умел', 'умела')} дружить даже с теми, кого {g('видел', 'видела')} впервые.",
          "Так начинается наша сказка."]
    p2 = ["Однажды утром мама испекла горячие лепёшки для бабушки.",
          "— Отнеси их, пожалуйста, — попросила мама. — Бабушка уже ждёт.",
          (f"«Бисмиллях!» — тихо {g('сказал', 'сказала')} {n} и {g('взял', 'взяла')} корзинку." if bism
           else f"{n} {g('взял', 'взяла')} корзинку и {g('отправился', 'отправилась')} в путь."),
          f"Дорога была долгой, но {n} ни капли не {g('боялся', 'боялась')}.",
          "В корзинке тёплым облачком пахли лепёшки.",
          "Бабушка ждала, и это придавало сил."]
    p3 = [f"Скоро {path_loc} {hv('появился', 'появилась')} {helper}.",
          f"— Здравствуй! Давай пойдём вместе, — {hv('предложил', 'предложила')} {hv('он', 'она')}.",
          f"Но тут путь преградил {obstacle}.",
          f"{n} {g('задумался', 'задумалась')}, как пройти дальше.",
          crossing,
          "Преграда осталась позади, а впереди ждало настоящее приключение."]
    p4 = [adv[0], adv[1],
          f"{n} {g('шёл', 'шла')} вперёд, а {helper} {hv('бежал', 'бежала')} рядом.",
          "Они пели песенки и считали облака.",
          f"{n} {g('вспомнил', 'вспомнила')}, что любит больше всего: {c.like}, — и от этого шагалось веселее.",
          "Дорога казалась всё короче."]
    p5 = [val["sit"][0], val["sit"][1],
          "Остановиться — значит задержаться в пути. Пройти мимо — гораздо проще.",
          f"{n} {g('замер', 'замерла')} и {g('задумался', 'задумалась')}.",
          "Решать нужно было самому — рядом не было взрослых.",
          f"{cap_first(helper)} молча {hv('ждал', 'ждала')} и {hv('смотрел', 'смотрела')} на друга."]
    p6 = [val["choice"][0], val["choice"][1], val["choice"][2],
          f"Никто не подсказывал — {n} {g('решил', 'решила')} сам{g('', 'а')}.",
          f"{cap_first(helper)} с уважением {hv('посмотрел', 'посмотрела')} на друга.",
          "И сразу стало легко на сердце."]
    p7 = [val["result"][0],
          (f"«Альхамдулиллях!» — {g('улыбнулся', 'улыбнулась')} {n}." if bism else val["result"][1]),
          val["result"][2] if not bism else val["result"][1],
          f"{n} {g('почувствовал', 'почувствовала')}, как радостно на сердце.",
          f"{cap_first(helper)} {hv('подпрыгнул', 'подпрыгнула')} от счастья.",
          "Солнце засияло ещё ярче."]
    p8 = [f"Когда солнце начало садиться, {n} {g('добрался', 'добралась')} до бабушкиного дома.",
          f"Бабушка {g('обняла внука', 'обняла внучку')} и угостила всех горячим чаем.",
          f"{n} {g('рассказал', 'рассказала')} о своём приключении, и все гордились {g('им', 'ею')}.",
          f"{cap_first(helper)} {hv('махал', 'махала')} на прощание.",
          f"Вечером {n} {g('вернулся', 'вернулась')} домой с лёгким сердцем.",
          "Вот и сказке конец, а кто слушал — молодец!"]
    return [_pick(pg, count) for pg in (p1, p2, p3, p4, p5, p6, p7, p8)]


# ================================================================== кыргызский
def _value_ky(c: _Ctx) -> dict:
    n, g = c.n, c.g
    return {
        "kindness": {
            "sit": ["Жолдун боюнда тамак-ашы жок чарчаган жолоочу отурган экен.", "Ал акырын үшкүрүп, алыска карады."],
            "choice": [f"{n} жолоочуга барып, эң кызарган боорсокту сунуп берди.", "— Алыңыз, ысык экен, — деди ал.",
                       "Боорсоктору аз калса да, боорукер жүрөк туура экенин айтты."],
            "result": ["Жолоочу жылмайып, ыраазычылык билдирди.", "Ал таттуу коонун бөлүшүп, баары кубанышты.",
                       "Боорукерлик боорсокту даамдуу кылган экен."]},
        "honesty": {
            "sit": [f"Жолдон {n} күмүш тыйындары бар капчыкты тапты.", "Ага таттуу алса болмок, бирок эч ким билбейт эле."],
            "choice": [f"{n} башын чайкады: «Бул башканыкы».", "— Ой! Капчыкты ким жоготту? — деп катуу кыйкырды.",
                       "Жүрөгү катуу согуп жатты, бирок чындыкты айтуу тынчтык берди."],
            "result": ["Көп өтпөй бурулуштан капчыгын издеген соодагер чуркап чыкты.",
                       "— Кандай чынчыл бала! — деп ал кубанып, рахмат айтты.", "Чынчылдык эң чоң байлык экен."]},
        "help_parents": {
            "sit": ["Жолдун четинде балдар топ ойноп, чакырып жатышты.",
                    "Ойногусу келди, бирок себеттеги боорсок чоң энени күтүп турду."],
            "choice": [f"{n} сыпайы баш тартты: «Адегенде апама жардам берейин, анан ойнойм».",
                       "— Бул маанилүү иш, — деди себетти бекем кармап.", "Апасынын тапшырмасы эң башкысы болуп калды."],
            "result": ["Боорсок чоң энеге дагы ысык бойдон жетти.",
                       f"Кийин апасы муну билип, {g('уулун', 'кызын')} бек кучактады.",
                       "Кечинде балдардын баары кошо топ ойношту."]},
        "gratitude": {
            "sit": ["Кудуктун жанында боорукер аял жолоочуларга муздак суу берди.",
                    "Суу таза жана даамдуу эле, аял болсо шашып жаткан."],
            "choice": [f"{n} аялга ыраазычылык билдирди: «Чоң рахмат сизге!»",
                       "Дагы чака көтөрүп, үйүнө чейин жеткирип берди.",
                       "«Рахмат» деп айтуу жана жакшылыкка жакшылык кылуу — ыраазы болуу дегенди билдирет."],
            "result": ["Аял жылмайып, баарына таттуу өрүк берди.", "— Сенин рахматың ар кандай белектен кымбат, — деди ал.",
                       "Баардын жүрөгү жылыды."]},
        "animals": {
            "sit": ["Жолдун боюнда энесинен адашкан кичинекей козу ыйлап жатты.", "Ал ач жана абдан коркуп калган эле."],
            "choice": [f"{n} жанына отуруп, козуга суу берип, жумшак сылады.", "— Коркпо, сени короого жеткирем, — деп убада берди.",
                       "Баланы камкордуктоо шашылуудан маанилүү болчу."],
            "result": ["Алыстан энеси кой маарап, каршы чуркады.", "Козу кубанып, ага жабышты.",
                       "Койчу алыстан кол булгап, ыраазычылык билдирди."]},
        "respect_elders": {
            "sit": ["Көпүрөдө оор жүк көтөргөн ак сакалдуу аксакал турду.", "Ал эс алуу үчүн токтоп калыптыр."],
            "choice": [f"{n} сыпайы салам берип, жол ачты: «Аксакал, жардам берейинби?»",
                       "Экөө оор жүктү көпүрөнүн аягына чейин чогуу алып барышты.",
                       "Аксакал эски окуяны айтып жатканда, ал кунт коюп укту."],
            "result": ["Аксакал баланын башын сылап, жакшылык тиледи.", "— Улууну сыйлагандын жолу ак болот, — деди ал.",
                       "Бул сөздөр ысык чайдан да жылуу болду."]},
        "courage": {
            "sit": ["Андан ары жол караңгы капчыгайдан өтүп, ал жактан кызыктай жаңырык угулду.",
                    "Айланып өтүүгө мүмкүн эмес эле — болбосо кечигип калат."],
            "choice": [f"{n} терең дем алып, биринчи болуп капчыгайга кирди.",
                       "— Мен корккон жокмун, — деп шыбырады, бирок жүрөгү катуу согуп жатты.", "Досу артынан жанаша басты."],
            "result": ["Караңгылыктан күлкү угулду: бул алардын өз үнүнүн жаңырыгы экен!",
                       "Экөө күлүп, андан ары шайыр басышты.",
                       f"Эр жүрөктүк — бул кичине коркуп турсаң да, алга кадам таштоо экенин {n} түшүндү."]},
    }[c.p.value]


def _pages_ky(c: _Ctx, count: int) -> list[str]:
    p, n = c.p, c.n
    where = WHERE_KY.get(p.place) or f"өзгөчө жерде: {p.place_custom}"
    adj = TRAITS_KY.get(p.traits[0], "жакшы") if p.traits else "жакшы"
    helper = c.helper_ky
    val = _value_ky(c)
    adv = ADV_KY[p.place]
    bism = c.islamic

    p1 = [f"{n} {where} жашачу.",
          f"Күн сайын эртең менен {n} жылмайып ойгонуп, жаңы күндү тосуп алчу.",
          f"Баары: «Кандай {adj} бала!» — дешчү.",
          f"Анын сүйгөн оюну — {c.like}.",
          f"{n} жаңы достор табууну жакшы көрчү.",
          "Жомок ушундай башталат."]
    p2 = ["Бир күнү апасы чоң энеси үчүн ысык боорсок бышырды.",
          "— Муну чоң энеңе апарып бер, ал күтүп жатат, — деди апасы.",
          (f"«Бисмиллах!» — деди {n} жай үн менен жана себетти алды." if bism
           else f"{n} себетти алып, жолго чыкты."),
          f"Жол узак болчу, бирок {n} такыр корккон жок.",
          "Себеттен боорсоктун жыты аңкып турду.",
          "Чоң эне күтүп жатканы күч берди."]
    p3 = [f"Көп өтпөй жолдо {helper} жолукту.",
          "— Саламатсыңбы! Кел, чогуу барабыз, — деди ал.",
          "Бирок алдыда ылдам аккан суу бар эле.",
          f"{n} суудан кантип өтүүнү ойлонду.",
          "Экөө чогуу таштарды таап, аркы өйүзүнө өтүштү.",
          "Суу артта калды, алдыда чыныгы укмуш күтүп турду."]
    p4 = [adv[0], adv[1],
          f"{n} алдыга басты, {helper} жанында чуркады.",
          "Экөө ыр ырдап, булуттарды санашты.",
          f"{n} эң жакшы көргөнүн эстеди: {c.like}, ошондо жүрүү жеңилдеди.",
          "Жол кыска сезилди."]
    p5 = [val["sit"][0], val["sit"][1],
          "Токтосо — жолдон кечигет. Өтүп кетсе — оңой.",
          f"{n} токтоп, ойлонуп калды.",
          "Чечүү керек болчу — жанында чоңдор жок эле.",
          f"{helper.capitalize()} унчукпай күтүп турду."]
    p6 = [val["choice"][0], val["choice"][1], val["choice"][2],
          f"Эч ким айтып бербеди — {n} өзү чечти.",
          f"{helper.capitalize()} досун сыйлап карады.",
          "Жүрөк жеңил болду."]
    p7 = [val["result"][0],
          (f"«Алхамдулиллах!» — деди {n} жылмайып." if bism else val["result"][1]),
          val["result"][2] if not bism else val["result"][1],
          f"{n} жүрөгү кубанычка толду.",
          f"{helper.capitalize()} кубанганынан секирди.",
          "Күн дагы жаркырап чыкты."]
    p8 = [f"Күн батканда {n} чоң энесинин үйүнө жетти.",
          "Чоң эне кучактап, баарына ысык чай куюп берди.",
          f"{n} өзүнүн укмушун айтып берди, баары сыймыктанды.",
          f"{helper.capitalize()} коштошуп кол булгады.",
          f"Кечинде {n} жеңил жүрөк менен үйүнө кайтты.",
          "Жомок ушуну менен бүттү."]
    return [_pick(pg, count) for pg in (p1, p2, p3, p4, p5, p6, p7, p8)]


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
    p = c.p
    place_en = options.PLACES[p.place]["en"] if p.place != "custom" else f"a special place: {p.place_custom}"
    kid = "boy" if c.boy else "girl"
    hero = f"the {kid} hero"
    helper = c.helper_en
    dil, choice, result = VALUE_EN[p.value]
    mood = "Soft, gentle, welcoming mood"
    return [
        f"Wide establishing shot: {hero} stands cheerfully in {place_en}, morning light, a cozy family home nearby, a hint of the adventure to come. {mood}.",
        f"{hero.capitalize()} receives a woven basket of warm flatbreads from a smiling mother at the doorway of the home, soft morning glow, loving gesture, {place_en} behind them.",
        f"{hero.capitalize()} meets {helper} on a winding path; both look at a sparkling stream ahead; friendly curiosity, {place_en} in the background, {mood.lower()}.",
        f"The two friends walk together along the trail through {place_en}, {hero} holding the basket, drifting clouds and warm light, a sense of wonder and journey.",
        f"Close-up of {hero} pausing thoughtfully with the basket, noticing {dil}; {helper} waits nearby; the way onward is visible behind; gentle emotional tension without any fear.",
        f"{hero.capitalize()} kindly {choice}; {helper} watches with admiration; warm light highlights the decision, {place_en} softly behind.",
        f"Joyful moment: {result}; {hero} and {helper} smile, glowing golden light, celebratory warm mood, {place_en} around them.",
        f"Sunset: {hero} arrives at grandmother's cozy home and is embraced by smiling grandmother at the door; {helper} waves goodbye; golden light, warm ending.",
    ]


def build_mock_story(p: Profile) -> dict:
    c = _Ctx(p)
    count = _sentence_count(p.age)
    texts = _pages_ky(c, count) if p.language == "ky" else _pages_ru(c, count)
    scenes = _scenes(c)
    helper_title = c.helper_ky if p.language == "ky" else c.helper_ru
    title = f"{p.name} жана {helper_title}" if p.language == "ky" else f"{p.name} и {helper_title}"
    moral = MORAL[p.language][p.value]
    if p.language == "ky":
        wish = f"{p.name}, жүрөгүң ар дайым жылуу болсун, жашооң жакшы жомокторго бай болсун!"
    else:
        wish = f"{p.name}, пусть твоё сердце всегда остаётся тёплым, а в жизни будет много добрых приключений!"
    return {
        "title": title,
        "hero_visual": _hero_visual(p),
        "style_note": "Warm golden-hour light, soft sky-blue and apricot palette with fresh green accents.",
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

    async def _complete(self, system, messages):  # pragma: no cover - mock не ходит в сеть
        raise NotImplementedError
