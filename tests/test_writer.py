"""Движок писателя: конвейер режиссёр → автор → редактор → код-валидатор, зёрна, план, лимиты по возрасту,
бан-лист, падежи имён, кыргызский из плана, актёры в промтах для картинок, старые книги.

Сеть не нужна: модель текста поддельная (tests/writer_helpers.py)."""
import itertools
import json
import random

import pytest

from app import options, prompts, writer
from app import writer_data as D
from app.declension import ky_forms, ru_forms
from app.errors import StoryError, StoryValidationError
from app.layout import text_side
from app.profile import Profile
from app.providers.text_mock import MockTextProvider, build_mock_story
from app.story import PAGES, Story, validate_story
from app.writer import (Fix, Plan, apply_fixes, assemble_story, check_story, forms_table, page_limits, parse_fixes,
                        pick_seeds, plural_words, sentences, validate_plan, words)
from app.writer_prompts import (build_editor_prompts, build_planner_prompts, build_system_prompt, build_user_prompt,
                                limits_text)

from .conftest import SAMPLE
from .writer_helpers import (ScriptedPipeline, author_dict, dump, plan_dict, seeded, seeds_for, stage_of)


def make(**over) -> Profile:
    return Profile.from_payload({**SAMPLE, **over})


def story_of(profile: Profile, mutate=None) -> Story:
    data = build_mock_story(profile)
    if mutate:
        mutate(data)
    return validate_story(data, profile.language)


def codes(profile: Profile, mutate=None, plan: Plan | None = None) -> list[str]:
    return [v.code for v in check_story(story_of(profile, mutate), profile, plan)]


def messages(profile: Profile, mutate=None, plan: Plan | None = None) -> list[str]:
    return [str(v) for v in check_story(story_of(profile, mutate), profile, plan)]


def set_page(index: int, text: str):
    def mutate(data):
        data["pages"][index - 1]["text"] = text
    return mutate


def distinct_words(n: int) -> str:
    """n разных трёхбуквенных «слов» кириллицей: считаются словами, но не повторами и не бан-листом."""
    return " ".join("".join(chr(1072 + (i // 26 ** k) % 26) for k in range(3)) for i in range(n))


# ============================================================================ лимиты по возрасту
@pytest.mark.parametrize("age, language, words_range, chars, sent, sent_words", [
    (3, "ru", (10, 18), 125, 3, 10), (4, "ru", (10, 18), 125, 3, 10), (5, "ru", (15, 28), 190, 4, 14),
    (6, "ru", (15, 28), 190, 4, 14), (7, "ru", (22, 36), 250, 4, 16), (9, "ru", (22, 36), 250, 4, 16),
    (3, "ky", (9, 15), 125, 3, 9), (6, "ky", (13, 24), 190, 4, 12), (8, "ky", (19, 31), 250, 4, 13),
])
def test_page_limits_follow_the_guide_table(age, language, words_range, chars, sent, sent_words):
    lim = page_limits(age, language)
    assert (lim.min_words, lim.max_words) == words_range and lim.max_chars == chars
    assert lim.max_sentences == sent and lim.max_sentence_words == sent_words


def test_kyrgyz_has_about_fifteen_percent_fewer_words_and_the_same_characters():
    for age in range(3, 10):
        ru, ky = page_limits(age, "ru"), page_limits(age, "ky")
        assert ky.max_chars == ru.max_chars
        assert 0.8 <= ky.max_words / ru.max_words <= 0.9


def test_word_and_sentence_counting_handles_dialogue_dashes_and_hyphens():
    assert words("Раз, два, три — вперёд!") == ["Раз", "два", "три", "вперёд"]
    assert words("Туда-сюда, туда-сюда!") == ["Туда-сюда", "туда-сюда"]
    assert len(sentences("— Помочь? — спросил медвежонок Бом.")) == 1
    assert len(sentences("Бом поднял его. — Держись! — крикнул он.")) == 2
    assert len(sentences("Раз, два… стоп! Мальчик посмотрел на шарф.")) == 2
    assert len(sentences("«Бисмиллях!» — тихо сказал Айдар. Он взял корзинку.")) == 2
    assert len(sentences("Раз, два… стоп — мальчик смотрел на шнурок.")) == 1


@pytest.mark.parametrize("age, language", [(a, lang) for a in (3, 4, 5, 6, 7, 9) for lang in ("ru", "ky")])
def test_too_long_page_reports_exact_numbers(age, language):
    profile = make(age=age, language=language)
    lim = page_limits(age, language)
    n = lim.hard_max_words + 1
    msgs = messages(profile, set_page(2, distinct_words(n) + "."))
    assert f"стр.2: {plural_words(n)}, нужно {lim.min_words}–{lim.max_words}" in " ".join(msgs)


@pytest.mark.parametrize("age, language", [(3, "ru"), (6, "ru"), (8, "ru"), (3, "ky"), (6, "ky"), (9, "ky")])
def test_page_at_the_limit_passes_and_slightly_over_is_tolerated_but_far_over_is_not(age, language):
    profile = make(age=age, language=language)
    lim = page_limits(age, language)
    ok = distinct_words(lim.max_words)
    assert not [c for c in codes(profile, set_page(2, ok + ".")) if c in ("words_max", "words_min")]
    over = distinct_words(lim.hard_max_words + 1)
    assert "words_max" in codes(profile, set_page(2, over + "."))


def test_short_page_is_rejected_and_says_so():
    profile = make(age=7)
    msgs = messages(profile, set_page(3, "Он пошёл домой."))
    assert any(m.startswith("стр.3:") and "слишком коротко" in m and "22–36" in m for m in msgs)


def test_too_many_sentences_and_characters_and_long_sentences_are_reported():
    profile = make(age=6)
    many = "Он шёл. Он бежал. Он прыгал. Он стоял. Он ждал. Он смотрел. Он пел. Он ел. Он пил. Он спал."
    msgs = " | ".join(messages(profile, set_page(1, many)))
    assert "стр.1: 10 предложений, лимит 4" in msgs
    long_sentence = distinct_words(20) + ". " + distinct_words(2).capitalize() + "."
    msgs = " | ".join(messages(profile, set_page(1, long_sentence)))
    assert "предложение из 20 слов слишком длинное, лимит 14" in msgs
    chars = ("а" * 14 + " ") * 15 + "бб."
    assert "chars" in codes(profile, set_page(1, chars))
    assert any(m.startswith("стр.1: 228 знаков, лимит 190") for m in messages(profile, set_page(1, chars)))


# ============================================================================ имя героя
def test_hero_name_is_limited_to_four_uses_in_all_pages_and_forms_are_counted():
    profile = make()
    def with_names(n):
        def mutate(data):
            forms = ["Айдар", "Айдара", "Айдару", "Айдаром", "Айдаре", "Айдар"]
            for i in range(8):
                data["pages"][i]["text"] = data["pages"][i]["text"].replace("Айдар", "мальчик")
            for i in range(n):
                data["pages"][i]["text"] = f"{forms[i]} шёл по тропинке с лепёшками в плетёной корзинке. Утро только начиналось."
        return mutate
    assert "name_count" not in codes(profile, with_names(4))
    msgs = messages(profile, with_names(5))
    assert any("имя героя «Айдар» встречается 5 раз во всей книге, лимит 4" in m for m in msgs)


def test_kyrgyz_name_forms_are_counted_too_and_the_title_is_not():
    profile = make(language="ky", name="Тимур")
    def mutate(data):
        data["title"] = "Тимур жана Топ"
        for i, form in enumerate(["Тимур", "Тимурга", "Тимурдун", "Тимурду", "Тимурдан"]):
            data["pages"][i]["text"] = f"{form} чоң энесине ысык боорсок алып баратты. Себеттин сабына кызыл жип байланган эле."
    assert "name_count" in codes(profile, mutate)


def test_child_named_like_a_banned_name_or_brand_is_allowed():
    for name, gender in (("Мара", "girl"), ("Эльза", "girl"), ("Лира", "girl")):
        profile = make(name=name, gender=gender)
        found = codes(profile, lambda d, n=name: d["pages"][0].update(text=f"{n} несла бабушке тёплые лепёшки в плетёной корзинке. "
                                                                          "К ручке корзинки был привязан красный шнурок."))
        assert "ban_name" not in found and "brand" not in found


# ============================================================================ бан-лист
@pytest.mark.parametrize("phrase, label", [
    ("Шёпот леса стал громче, и мальчик пошёл дальше по тропинке.", "шёпот леса"),
    ("Мальчик вошёл в волшебный лес и пошёл по тропинке дальше.", "волшебный лес/мир"),
    ("Сердце наполнилось радостью, и мальчик пошёл по тропинке дальше.", "сердце наполнилось"),
    ("В небе горели тысячи звёзд, и мальчик шёл по тропинке дальше.", "тысячи"),
    ("Это был хороший урок, и мальчик пошёл по тропинке дальше.", "урок"),
    ("Мальчик понял, что надо идти дальше по тропинке без остановок.", "понял(а), что"),
    ("Это настоящая дружба, и мальчик пошёл дальше по тропинке вместе.", "настоящая дружба"),
    ("Дружба важнее всего на свете, и мальчик пошёл по тропинке дальше.", "важнее всего"),
    ("Мальчик шёл каждый день и каждую ночь по этой тропинке вперёд.", "каждый день и каждую ночь"),
    ("В этот момент мальчик остановился на тропинке и посмотрел вокруг.", "в этот момент"),
    ("И они жили долго и счастливо, и мальчик пошёл по тропинке дальше.", "жили долго и счастливо"),
])
def test_banned_phrases_are_caught_with_their_name(phrase, label):
    msgs = messages(make(), set_page(2, phrase))
    assert any(f"запрещённый оборот «{label}»" in m for m in msgs), msgs


@pytest.mark.parametrize("name", ["Элара", "Элиас", "Лиора"])
def test_cliche_character_names_are_banned_anywhere(name):
    msgs = messages(make(), set_page(2, f"Навстречу вышла {name} и рассказала про мостик у ручья."))
    assert any(f"имя-штамп «{name}»" in m for m in msgs)


def test_ambiguous_names_only_count_when_capitalised_in_the_middle_of_a_sentence():
    profile = make()
    assert "ban_name" in codes(profile, set_page(2, "Навстречу вышла Луна и рассказала про мостик у ручья."))
    assert "ban_name" not in codes(profile, set_page(2, "Над ручьём светила луна, и мостик было хорошо видно."))
    assert "ban_name" not in codes(profile, set_page(2, "Луна светила над ручьём, и мостик было хорошо видно."))
    space = make(topic="space")
    assert "ban_name" not in codes(space, set_page(2, "Ракета летела к Луне и мостик было хорошо видно."))


def test_limited_phrases_may_appear_once():
    profile = make()
    one = set_page(2, "Налетел ветер, и вдруг ручей стал шире. Будто мостик унесло водой на самом деле.")
    assert "limited_phrase" not in codes(profile, one)
    def two(data):
        data["pages"][1]["text"] = "Налетел ветер и вдруг ручей стал шире. Словно мостик унесло водой на самом деле."
        data["pages"][3]["text"] = "Раз, два, три — прыг! И вдруг камень скользнул. Будто ноги сами поехали вперёд."
    msgs = messages(profile, two)
    assert any("«и вдруг» встречается 2" in m for m in msgs) and any("«словно/будто/как будто» встречается 2" in m for m in msgs)


def test_emoji_latin_letters_brands_and_violence_are_caught():
    profile = make()
    assert "emoji" in codes(profile, set_page(2, "Мальчик увидел ручей 🌊 и остановился на берегу у воды."))
    assert "latin" in codes(profile, set_page(2, "Мальчик сказал ok и остановился на берегу у воды рядом."))
    assert "brand" in codes(profile, set_page(2, "Навстречу вышел Человек-паук и показал мостик у ручья."))
    assert "brand" in codes(profile, set_page(2, "Навстречу выбежали фиксики и показали мостик у ручья."))
    assert "violence" in codes(profile, set_page(2, "Мальчик взял оружие и пошёл дальше по тропинке к ручью."))
    msgs = messages(profile, set_page(2, "Мальчик сказал hello и остановился на берегу у воды."))
    assert any("латинские буквы («hello»)" in m for m in msgs)
    assert "latin" in codes(profile, set_page(2, "Aidar побежал к ручью и остановился у самой воды рядом."))   # Айдара латиницей не пишем


def test_latin_name_of_the_child_is_not_a_latin_violation():
    profile = make(name="Emma", gender="girl")
    def mutate(data):
        data["pages"][0]["text"] = "Emma несла бабушке тёплые лепёшки в плетёной корзинке. К ручке корзинки был привязан шнурок."
    assert "latin" not in codes(profile, mutate)


def test_title_and_moral_have_word_limits():
    profile = make()
    msgs = messages(profile, lambda d: d.update(title="Айдар и его большое путешествие через ручей"))
    assert any("название из 7 слов, нужно не больше 5" in m for m in msgs)
    msgs = messages(profile, lambda d: d.update(moral="Пусть у тебя всегда найдётся хорошая идея и верный друг рядом на любой тропе"))
    assert any(m.startswith("moral из ") and "не больше 12" in m for m in msgs)


def test_repeated_words_identical_sentences_and_style_limits():
    profile = make()
    msgs = " | ".join(messages(profile, set_page(2, "Ручей шумел, ручей бежал, ручей блестел в траве у самого берега.")))
    assert "слово «ручей» повторяется 3 раза" in msgs
    def same(data):
        data["pages"][5]["text"] = data["pages"][1]["text"]
    assert "same_sentence" in codes(profile, same)
    def feelings(data):
        data["pages"][1]["text"] = "Мальчик грустно смотрел на ручей. Бабушка ждала на том берегу."
        data["pages"][2]["text"] = "Помощник радостно махнул рукой. Но ручей был слишком широким для прыжка."
        data["pages"][3]["text"] = "Мальчику было страшно и обидно. Ноги оказались в ледяной воде совсем сразу."
        data["pages"][4]["text"] = "Бабушка весело помахала рукой. Берег был далеко, а вода глубокая."
    assert "emotion" in codes(profile, feelings)
    def questions(data):
        for i in (1, 2, 3):
            data["pages"][i]["text"] = "Куда теперь идти мальчику? Бабушка ждала на том берегу ручья."
    assert "question" in codes(profile, questions)


def test_islamic_mode_rejects_magic_dragons_and_fairies():
    profile = make(islamic=True)
    assert "islamic" in codes(profile, set_page(2, "Из-за камня выглянул дракон и показал, где ручей."))
    assert "islamic" not in codes(make(), set_page(2, "Из-за камня выглянул большой кот и показал, где ручей."))


def test_cliche_characters_are_allowed_if_the_parent_asked_for_them():
    text = "Навстречу вышел пекарь с тёплыми лепёшками и показал, где ручей."
    assert "cliche" in codes(make(), set_page(2, text))
    assert "cliche" not in codes(make(favorites="пекарь Рустам"), set_page(2, text))


# ============================================================================ примеры-образцы и списанное
@pytest.mark.parametrize("band, age", [("3-4", 4), ("5-6", 6), ("7-9", 8)])
def test_few_shot_examples_obey_their_own_limits_and_rules(band, age):
    lim = page_limits(age, "ru")
    assert len(D.EXAMPLES[band]) == 3                                           # две книги на структуру и третья — эталон тона
    for example in D.EXAMPLES[band]:
        assert len(example.pages) == PAGES
        name = words(example.title)[0]
        profile = make(age=age, name=name, gender="girl" if name in ("Алина", "Айлин", "Дарина") else "boy")
        hero_scene = "Wide shot of the hero and the helper beside a tree in soft light."
        story = validate_story({
            "title": example.title, "hero_visual": "A small child in a bright jacket and warm boots with a happy face.",
            "style_note": "Bright sunny light.", "refrain": example.refrain, "moral": example.moral, "wish": "Пусть всё получится!",
            "pages": [{"text": t, "scene": hero_scene} for t in example.pages]}, "ru")
        helper = {"Тимур": "Бом", "Алина": "Тоша", "Айлин": "Мурзик", "Дарина": "Пуф"}[name]
        plan = Plan(premise="p", want="w", trait="t", tool="t", stakes="s", helper_name=helper, helper_trait="t", helper_kind="k",
                    obstacle="o", attempts=(("a", "r"), ("a", "r"), ("a", "")), solution="s", plant="p", payoff="p",
                    refrain=example.refrain, refrain_break="b", hero_look="x", helper_look="x", obstacle_look="x",
                    style_note="x", image_brief=tuple(hero_scene for _ in range(PAGES)))
        found = [v for v in check_story(story, profile, plan) if v.code != "echo"]
        assert not found, [str(v) for v in found]
        for text in example.pages:
            assert lim.hard_min_words <= len(words(text)) <= lim.hard_max_words


def test_copying_an_example_is_caught_but_the_refrain_itself_is_not():
    profile = make(age=6, name="Тимур")
    copied = set_page(2, "Налетел ветер. Щёлк! — и красный змей застрял на ёлке, а нитка повисла на ветке.")
    assert any("списана с примера" in m for m in messages(profile, copied))
    plan = Plan(premise="p", want="w", trait="t", tool="t", stakes="s", helper_name="Бом", helper_trait="t", helper_kind="k",
                obstacle="o", attempts=(("a", "r"), ("a", "r"), ("a", "")), solution="s", plant="p", payoff="p",
                refrain="Раз, два, три — вперёд!", refrain_break="b", hero_look="x", helper_look="x", obstacle_look="x",
                style_note="x", image_brief=("x",) * PAGES)
    own = set_page(4, "Раз, два, три — вперёд! Мальчик подпрыгнул на месте, но ветка так и не стала ближе к рукам.")
    assert "echo" not in [c for c in codes(profile, own, plan)]


def test_names_from_examples_are_not_allowed_unless_they_are_the_hero_or_the_helper():
    profile = make()
    msgs = messages(profile, set_page(2, "Навстречу вышел кот Мурзик и показал, где ручей."))
    assert any("имя «мурзик» взято из примера" in m for m in msgs)
    assert "echo" not in codes(make(name="Алина", gender="girl"),
                               set_page(2, "Алина нашла у ручья мостик, а за ним тропинку к дому."))


# ============================================================================ зёрна
def test_there_are_forty_short_helper_names_and_twelve_archetypes():
    names = [n.name for n in D.HELPER_NAMES]
    assert len(names) == 40 and len(set(names)) == 40
    assert all(writer.syllables(n) <= 2 for n in names), [n for n in names if writer.syllables(n) > 2]
    assert len(D.ARCHETYPES) == 12 and len({a.id for a in D.ARCHETYPES}) == 12
    assert len(D.OBSTACLES) >= 12 and len(D.REFRAIN_TYPES) >= 6 and len(D.HELPER_TYPES) >= 20


def test_seeds_are_deterministic_for_a_seeded_rng_and_vary_between_books():
    profile = make()
    assert pick_seeds(profile, random.Random(5)) == pick_seeds(profile, random.Random(5))
    combos = {tuple(pick_seeds(profile, random.Random(i)).to_dict().values()) for i in range(40)}
    assert len(combos) >= 30
    helper = {pick_seeds(profile, random.Random(i)).helper_name.name for i in range(80)}
    assert len(helper) >= 20 and helper <= {n.name for n in D.HELPER_NAMES}
    assert pick_seeds(profile).helper_name.name in {n.name for n in D.HELPER_NAMES}        # без rng: SystemRandom


def test_helper_name_matches_the_gender_of_the_helper_type_and_never_the_childs_name():
    profile = make(name="Топ")
    for i in range(120):
        seeds = pick_seeds(profile, random.Random(i))
        assert seeds.helper_name.gender in (seeds.helper_type.gender, "n")
        assert seeds.helper_name.name.lower() != "топ"


def test_islamic_books_never_get_a_magic_helper_and_topics_pull_matching_helpers():
    islamic = make(islamic=True)
    assert all(not pick_seeds(islamic, random.Random(i)).helper_type.magic for i in range(150))
    dinos = [pick_seeds(make(topic="dinosaurs"), random.Random(i)).helper_type.id for i in range(100)]
    assert sum(t in ("dino", "baby_trike") for t in dinos) >= 50
    lesson = {pick_seeds(make(topic="life_lesson"), random.Random(i)).obstacle for i in range(60)}
    assert lesson <= set(D.OBSTACLES_BY_TOPIC["life_lesson"])
    assert pick_seeds(make(topic="space"), random.Random(1)).setting in D.SETTINGS_BY_TOPIC["space"]


def test_planner_user_prompt_carries_seeds_child_topic_request_and_favorites():
    profile = make(topic="dinosaurs", request="Хочу доброго диплодока", favorites="Зайчик Бобо")
    seeds = seeds_for(profile)
    system, user = build_planner_prompts(profile, seeds)
    for text in (seeds.setting, seeds.obstacle, seeds.helper_name.name, seeds.refrain_type.ru, seeds.helper_type.ru):
        assert text in user
    child = json.loads(user.split("<child>")[1].split("</child>")[0])
    assert child["topic_label"] == "Динозавры" and child["request"] == "Хочу доброго диплодока"
    assert child["favorites"] == "Зайчик Бобо" and child["любит"] == ["Лошади"] and child["характер"] == ["добрый", "смелый"]
    assert child["место действия"] == "Юрта на джайлоо" and child["ценность"] == "доброта"
    assert "ОДНУ черту характера" in system and "именительный" not in user


def test_planner_prompt_lists_the_ten_archetypes_and_the_brand_rule():
    profile = make()
    system, _ = build_planner_prompts(profile, seeds_for(profile))
    assert all(a.title in system for a in D.ARCHETYPES)
    assert "ЗАПРЕЩЕНЫ" in system and "НИКОГДА не пиши его имя" in system and "ОРИГИНАЛЬНЫЙ образ" in system
    islamic = make(islamic=True)
    system_islamic, _ = build_planner_prompts(islamic, seeds_for(islamic))
    assert "Дракончик-чихалка" not in system_islamic and "Горные друзья" in system_islamic
    assert "Исламские ценности" in system_islamic


def test_planner_prompt_matches_the_plot_difficulty_to_the_age():
    for age, phrase in ((3, "самый простой сюжет"), (5, "три попытки и добрый юмор"), (8, "можно загадку или сюрприз")):
        profile = make(age=age)
        system = build_planner_prompts(profile, seeds_for(profile))[0]
        assert phrase in system
        assert sum(hint in system for hint in ("самый простой сюжет", "три попытки и добрый юмор", "можно загадку или сюрприз")) == 1


def test_life_lesson_topic_gets_the_lesson_arc_other_topics_the_adventure_arc():
    lesson = make(topic="life_lesson")
    assert "урок жизни" in build_planner_prompts(lesson, seeds_for(lesson))[0]
    adventure = make()
    assert "урок жизни" not in build_planner_prompts(adventure, seeds_for(adventure))[0]
    assert "Мир и желание" in build_planner_prompts(adventure, seeds_for(adventure))[0]


# ============================================================================ план режиссёра
def valid_plan(profile=None, seeds=None) -> dict:
    profile = profile or make()
    return plan_dict(profile, seeds or seeds_for(profile))


def test_valid_plan_is_accepted_and_keeps_every_field():
    profile = make()
    seeds = seeds_for(profile)
    plan = validate_plan(valid_plan(profile, seeds), profile, seeds)
    assert plan.helper_name == seeds.helper_name.name and len(plan.attempts) == 3 and len(plan.image_brief) == PAGES
    assert plan.refrain == "Раз, два, три — прыг!" and plan.tool and plan.trait
    again = validate_plan(plan.to_dict(), profile, seeds)
    assert again == plan                                                      # to_dict и обратно без потерь


@pytest.mark.parametrize("mutate, fragment", [
    (lambda p: p.pop("premise"), "premise"),
    (lambda p: p.update(trait=""), "trait"),
    (lambda p: p.update(helper="Бом"), "helper должно быть объектом"),
    (lambda p: p["helper"].update(name="Другое"), "helper.name должно быть «"),
    (lambda p: p.update(attempts=p["attempts"][:2]), "ровно из 3 шагов"),
    (lambda p: p["attempts"][0].update(fail_reason=""), "attempts[1].fail_reason"),
    (lambda p: p.update(refrain={"text": "Вперёд", "break": "x"}), "нужен рефрен из 3–6 слов"),
    (lambda p: p["refrain"].update(**{"break": ""}), "refrain.break"),
    (lambda p: p.update(plant_payoff=5), "plant_payoff"),
    (lambda p: p["character_bible"].update(hero="Мальчик с чёрными волосами и в синей жилетке, добрый и весёлый"), "по-английски"),
    (lambda p: p["character_bible"].update(helper="a small fox"), "слишком короткое"),
    (lambda p: p.update(image_brief=p["image_brief"][:7]), "ровно из 8 предложений"),
    (lambda p: p["image_brief"].__setitem__(2, "Мальчик у ручья с корзинкой"), "image_brief[3]"),
    (lambda p: p["image_brief"].__setitem__(0, "Short."), "image_brief[1]"),
    (lambda p: p.update(premise="Мальчик встречает Машу и Медведя и идёт к ручью"), "известные персонажи"),
    (lambda p: p["image_brief"].__setitem__(1, "The hero meets Spider-Man at the stream and waves, soft light"), "известные персонажи"),
    (lambda p: p.update(want="найти Элару у ручья"), "имя-штамп «Элара»"),
    (lambda p: p.update(helper=None), "helper"),
])
def test_bad_plans_are_rejected_with_a_readable_reason(mutate, fragment):
    profile = make()
    seeds = seeds_for(profile)
    data = valid_plan(profile, seeds)
    mutate(data)
    with pytest.raises(StoryValidationError) as err:
        validate_plan(data, profile, seeds)
    assert fragment in str(err.value)


def test_plan_for_islamic_book_may_not_have_dragons_or_fairies():
    profile = make(islamic=True)
    seeds = seeds_for(profile)
    data = valid_plan(profile, seeds)
    data["character_bible"]["helper"] = "a small green dragon with tiny wings and a gentle smile"
    with pytest.raises(StoryValidationError) as err:
        validate_plan(data, profile, seeds)
    assert "Исламские ценности" in str(err.value)
    data = valid_plan(profile, seeds)
    data["obstacle"] = "ворота, которые открывает добрый джинн"
    with pytest.raises(StoryValidationError):
        validate_plan(data, profile, seeds)


def test_plan_may_use_a_banned_name_when_it_is_the_childs_own_name():
    profile = make(name="Лира", gender="girl")
    seeds = seeds_for(profile)
    data = valid_plan(profile, seeds)
    data["want"] = "Лира хочет донести лепёшки бабушке"
    validate_plan(data, profile, seeds)


async def test_planner_retry_gets_the_exact_error_text():
    profile = make()
    provider = ScriptedPipeline(profile)
    bad = valid_plan(profile, provider.seeds)
    bad["helper"]["name"] = "Чужое"
    bad["image_brief"] = bad["image_brief"][:5]
    provider.replies["planner"] = [dump(bad), None]
    await provider.generate_story(profile)
    retry = provider.calls_of("planner")[1]["messages"][-1][1]
    assert f"helper.name должно быть «{provider.seeds.helper_name.name}»" in retry and "Твой ответ не прошёл проверку" in retry
    assert provider.stages == ["planner", "planner", "author"]


async def test_planner_gives_up_after_three_attempts_with_a_clear_error():
    profile = make()
    provider = ScriptedPipeline(profile, {"planner": ["{}"]})
    with pytest.raises(StoryError) as err:
        await provider.generate_story(profile)
    assert "3 раза" in str(err.value) and "план книги" in str(err.value) and "framework" in str(err.value)
    assert provider.stages == ["planner"] * 3


# ============================================================================ конвейер
async def test_pipeline_order_and_calls_for_russian():
    profile = make()
    provider = ScriptedPipeline(profile, polish=True)
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "editor"]
    assert [stage_of(c["system"]) for c in provider.calls] == provider.stages
    assert all(len(c["messages"]) == 1 for c in provider.calls)
    plan = json.loads(provider.calls[1]["messages"][0][1].split("<plan>")[1].split("</plan>")[0])
    assert plan["helper"]["name"] == provider.seeds.helper_name.name and "character_bible" not in plan
    assert story.refrain == "Раз, два, три — прыг!" and story.character("helper").name == provider.seeds.helper_name.name
    assert [p.scene for p in story.pages] == valid_plan(profile, provider.seeds)["image_brief"]
    assert story.hero_visual == story.character("hero").look


async def test_pipeline_without_polish_skips_the_editor():
    profile = make()
    provider = ScriptedPipeline(profile, polish=False)
    await provider.generate_story(profile)
    assert provider.stages == ["planner", "author"]


async def test_pipeline_for_kyrgyz_adds_the_proofreader_after_the_editor():
    profile = make(language="ky")
    provider = ScriptedPipeline(profile, polish=True)
    await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "editor", "proof"]


async def test_mock_provider_returns_a_validated_story_without_any_model_calls():
    profile = make()
    provider = MockTextProvider()
    story = await provider.generate_story(profile)          # _complete у заглушки бросает исключение: до него дело не доходит
    assert len(story.pages) == PAGES and story.cast and story.refrain
    assert [c.role for c in story.cast] == ["hero", "helper", "obstacle"]


@pytest.mark.parametrize("age, language", [(3, "ru"), (6, "ru"), (9, "ru"), (3, "ky"), (6, "ky"), (9, "ky")])
async def test_author_violations_come_back_with_the_exact_text_and_the_second_try_passes(age, language):
    profile = make(age=age, language=language)
    lim = page_limits(age, language)
    n = lim.hard_max_words + 3
    bad = author_dict(profile)
    bad["pages"][1]["text"] = distinct_words(n) + "."
    provider = ScriptedPipeline(profile, {"author": [dump(bad), None]})
    story = await provider.generate_story(profile)
    retry = provider.calls_of("author")[1]["messages"][-1][1]
    assert f"стр.2: {plural_words(n)}, нужно {lim.min_words}–{lim.max_words}" in retry
    assert "Твой ответ не прошёл проверку" in retry and "ТОЛЬКО перечисленное" in retry
    assert provider.calls_of("author")[1]["messages"][-2] == ("assistant", dump(bad))
    assert story.pages[1].text != bad["pages"][1]["text"]


async def test_author_gets_three_attempts_then_story_error():
    profile = make()
    bad = author_dict(profile)
    for i in range(5):
        bad["pages"][i]["text"] = bad["pages"][i]["text"].replace("мальчик", "Айдар").replace("девочка", "Айдар")
    bad["pages"][1]["text"] = "Айдар и Айдар и Айдар и Айдар и Айдар шли вместе по тропинке к ручью."
    bad["pages"][2]["text"] = "Айдара звали все, и Айдару это нравилось, а Айдаром гордились родители."
    bad["pages"][6]["text"] = "Навстречу вышел Человек-паук и показал мостик у ручья, а потом ушёл."     # жёсткое нарушение: бренд
    provider = ScriptedPipeline(profile, {"author": [dump(bad)]})
    with pytest.raises(StoryError) as err:
        await provider.generate_story(profile)
    assert provider.stages == ["planner"] + ["author"] * 3
    assert "текст книги" in str(err.value) and "имя героя" in str(err.value) and "бренд" in str(err.value)


async def test_author_reply_with_broken_json_or_wrong_page_count_is_retried():
    profile = make()
    short = author_dict(profile)
    short["pages"] = short["pages"][:6]
    provider = ScriptedPipeline(profile, {"author": ["не json", dump(short), None]})
    story = await provider.generate_story(profile)
    assert len(story.pages) == PAGES and provider.stages.count("author") == 3
    assert f"ровно {PAGES} страниц, а пришло 6" in provider.calls_of("author")[2]["messages"][-1][1]


async def test_refrain_missing_from_the_text_is_reported():
    profile = make()
    provider = ScriptedPipeline(profile)
    bad = author_dict(profile, provider.seeds)
    for page in bad["pages"]:
        page["text"] = page["text"].replace("Раз, два", "Одно, другое")
    provider.replies["author"] = [dump(bad), None]
    await provider.generate_story(profile)
    assert "рефрен «Раз, два, три — прыг!» встречается на 0 стр." in provider.calls_of("author")[1]["messages"][-1][1]


# ============================================================================ редактор
def assembled(profile=None):
    profile = profile or make()
    seeds = seeds_for(profile)
    plan = validate_plan(plan_dict(profile, seeds), profile, seeds)
    return profile, plan, assemble_story(profile, plan, author_dict(profile, seeds))


def test_parse_fixes_accepts_object_list_and_fenced_json():
    fx = [{"page": 3, "problem": "p", "fixed_text": "Новый текст."}]
    assert parse_fixes(dump({"fixes": fx})) == [Fix(3, "p", "Новый текст.")]
    assert parse_fixes(dump(fx)) == [Fix(3, "p", "Новый текст.")]
    assert parse_fixes("```json\n" + dump({"fixes": fx}) + "\n```")[0].page == 3
    assert parse_fixes(dump({"page": "4", "fixed_text": "Один."}))[0].page == 4
    assert parse_fixes(dump({"fixes": [{"page": "x", "fixed_text": "y"}, {"page": 2}, 5]})) == []
    with pytest.raises(StoryValidationError):
        parse_fixes("совсем не json")
    with pytest.raises(StoryValidationError):
        parse_fixes(dump({"fixes": "нет"}))


def test_apply_fixes_takes_good_pages_skips_unchanged_and_out_of_range_and_rule_breakers():
    profile, plan, story = assembled()
    good = "Раз, два, три — прыг! — и мальчик поскользнулся на мокром камне. Ноги сразу оказались в ледяной воде."
    fixes = [Fix(4, "", good), Fix(99, "", "Нет такой страницы вообще."), Fix(1, "", story.pages[0].text),
             Fix(5, "", "Сердце наполнилось радостью. " + story.pages[4].text),
             Fix(6, "", "Ок.")]
    result, applied = apply_fixes(story, fixes, profile, plan)
    assert applied == [4] and result.pages[3].text == good
    assert [p.text for i, p in enumerate(result.pages) if i != 3] == [p.text for i, p in enumerate(story.pages) if i != 3]
    assert result.cast == story.cast and result.refrain == story.refrain and result.title == story.title


def test_a_fix_may_leave_old_problems_in_place_but_must_not_add_new_ones():
    profile = make()
    def mutate(data):
        data["pages"][2]["text"] = distinct_words(40) + "."                  # у черновика уже есть нарушение на стр. 3
    seeds = seeds_for(profile)
    plan = validate_plan(plan_dict(profile, seeds), profile, seeds)
    draft_data = author_dict(profile, seeds)
    draft_data["pages"][2]["text"] = distinct_words(40) + "."
    draft = validate_story({**assemble_story(profile, plan, {**author_dict(profile, seeds)}).to_dict(),
                            "pages": [{"text": p["text"], "scene": s} for p, s in zip(draft_data["pages"], plan.image_brief)]},
                           "ru")
    better = distinct_words(30) + "."
    result, applied = apply_fixes(draft, [Fix(3, "", better)], profile, plan)
    assert applied == [3] and result.pages[2].text == better


def test_editor_prompt_has_the_twelve_question_checklist_and_asks_for_fixes_only():
    profile, plan, story = assembled()
    system, user = build_editor_prompts(profile, story, plan)
    for number in range(1, 13):
        assert f"\n{number}) " in system
    assert '"fixes"' in system and "fixed_text" in system and "problem" in system
    assert "Если страница в порядке, её в ответе нет" in system
    assert "<draft>" in user and "<plan>" in user and "Страница 8:" in user and "Название: " in user
    assert "hero_visual" not in user and "image_brief" not in user and "scene" not in user


async def test_editor_runs_one_cycle_and_falls_back_to_the_draft_on_garbage():
    profile = make()
    provider = ScriptedPipeline(profile, {"editor": ["совсем не json"]}, polish=True)
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "editor"]
    assert [p.text for p in story.pages] == [p["text"] for p in author_dict(profile, provider.seeds)["pages"]]


# ============================================================================ кыргызский из плана
async def test_kyrgyz_author_is_given_the_plan_and_forms_never_a_russian_text_to_translate():
    profile = make(language="ky", name="Тимур")
    provider = ScriptedPipeline(profile, polish=True)
    await provider.generate_story(profile)
    author = provider.calls_of("author")[0]
    system, user = author["system"], author["messages"][0][1]
    plan = valid_plan(profile, provider.seeds)
    assert plan["premise"] in user and plan["refrain"]["text"] in user and plan["solution"] in user
    assert "Пиши с нуля по плану, а НЕ переводи с русского" in system and "Язык книги — кыргызский" in system
    for token in D.KY_IDIOPHONES[:3] + D.KY_INTENSIFIERS[:3]:
        assert token in system
    # русского варианта страниц в промтах нет: книга пишется из плана, а не переводится
    russian_pages = [p["text"] for p in build_mock_story(make(language="ru", name="Тимур"))["pages"]]
    prompts_text = "\n".join(c["system"] + "\n" + "\n".join(m[1] for m in c["messages"]) for c in provider.calls)
    assert not any(page in prompts_text for page in russian_pages)
    assert "Образцы даны по-русски только как показ формы. Не переводи их" in system


def test_kyrgyz_author_gets_the_name_forms_table_for_hero_and_helper():
    profile = make(language="ky", name="Бермет", gender="girl")
    system = build_system_prompt(profile)
    for form in ("Берметтин", "Берметке", "Берметти", "Берметтен", "Берметте"):
        assert form in system
    seeds = seeds_for(profile)
    plan = validate_plan(plan_dict(profile, seeds), profile, seeds)
    user = build_user_prompt(profile, plan, seeds)
    assert f"Формы имени помощника «{seeds.helper_name.name}»" in user
    assert ky_forms(seeds.helper_name.name)["dat"] in user


def test_russian_author_gets_the_case_table_for_hero_and_helper():
    profile = make(name="Айдана", gender="girl")
    system = build_system_prompt(profile)
    for form in ("Айданы", "Айдане", "Айдану", "Айданой"):
        assert form in system
    assert "Схема JSON" in system and "кыргызский" not in system.split("Схема JSON")[0].split("Как писать")[0]


@pytest.mark.parametrize("name, expected", [
    ("Тимур", {"dat": "Тимурга", "gen": "Тимурдун", "acc": "Тимурду", "abl": "Тимурдан"}),
    ("Айлин", {"dat": "Айлинге", "gen": "Айлиндин", "acc": "Айлинди"}),
    ("Айгүл", {"dat": "Айгүлгө", "gen": "Айгүлдүн", "acc": "Айгүлдү"}),
    ("Бермет", {"dat": "Берметке", "gen": "Берметтин", "acc": "Берметти"}),
    ("Айдана", {"dat": "Айданага", "gen": "Айдананын"}),
    ("Нурбек", {"dat": "Нурбекке", "gen": "Нурбектин", "loc": "Нурбекте"}),
    ("Мирлан", {"dat": "Мирланга", "gen": "Мирландын", "abl": "Мирландан", "loc": "Мирланда"}),
    ("Бом", {"dat": "Бомго", "gen": "Бомдун"}),
    ("Үмүт", {"dat": "Үмүткө", "gen": "Үмүттүн", "acc": "Үмүттү"}),
    ("Анна-Мария", {"dat": "Анна-Марияга", "nom": "Анна-Мария"}),
])
def test_kyrgyz_name_forms_follow_vowel_harmony_and_consonant_assimilation(name, expected):
    forms = ky_forms(name)
    assert set(forms) == {"nom", "gen", "dat", "acc", "abl", "loc"}
    for case, form in expected.items():
        assert forms[case] == form, (name, case, forms)


def test_kyrgyz_forms_leave_latin_names_and_empty_input_alone():
    assert set(ky_forms("Emma").values()) == {"Emma"} and set(ky_forms("").values()) == {""}


@pytest.mark.parametrize("name, gender, expected", [
    ("Айдар", "boy", {"gen": "Айдара", "dat": "Айдару", "acc": "Айдара", "ins": "Айдаром", "prep": "Айдаре"}),
    ("Нурбек", "boy", {"gen": "Нурбека", "ins": "Нурбеком"}),
    ("Андрей", "boy", {"gen": "Андрея", "ins": "Андреем", "prep": "Андрее"}),
    ("Игорь", "boy", {"dat": "Игорю", "ins": "Игорем"}),
    ("Алина", "girl", {"gen": "Алины", "dat": "Алине", "acc": "Алину", "ins": "Алиной"}),
    ("Даша", "girl", {"gen": "Даши", "ins": "Дашей"}),
    ("Мария", "girl", {"gen": "Марии", "acc": "Марию", "ins": "Марией", "prep": "Марии"}),
    ("Айгүл", "girl", {"gen": "Айгүл", "dat": "Айгүл", "ins": "Айгүл"}),
    ("Бермет", "girl", {"acc": "Бермет"}),
    ("Тики", "girl", {"gen": "Тики", "ins": "Тики"}),
    ("Павел", "boy", {"gen": "Павла", "ins": "Павлом"}),
    ("Анна-Мария", "girl", {"gen": "Анна-Марии", "ins": "Анна-Марией"}),
])
def test_russian_name_forms_for_the_author(name, gender, expected):
    forms = ru_forms(name, gender)
    assert forms["nom"] == name and set(forms) == {"nom", "gen", "dat", "acc", "ins", "prep"}
    for case, form in expected.items():
        assert forms[case] == form, (name, case, forms)


def test_forms_table_text_lists_every_case_once():
    ru = forms_table("Айдар", "boy", "ru")
    assert ru.count(";") == 5 and "родительный: Айдара" in ru and "творительный: Айдаром" in ru
    ky = forms_table("Тимур", "boy", "ky")
    assert ky.count(";") == 5 and "барыш (дательный: кому? куда?): Тимурга" in ky


# ============================================================================ актёры в промтах для картинок
@pytest.fixture
def cast_story():
    return validate_story(build_mock_story(make()), "ru")


def test_story_carries_cast_and_refrain_and_roundtrips(cast_story):
    assert [c.role for c in cast_story.cast] == ["hero", "helper", "obstacle"] and cast_story.refrain
    again = Story.from_dict(json.loads(json.dumps(cast_story.to_dict(), ensure_ascii=False)))
    assert again == cast_story
    assert cast_story.hero_visual == cast_story.character("hero").look


def test_page_prompt_names_the_helper_look_but_the_hero_comes_from_the_reference(cast_story):
    profile = make()
    helper = cast_story.character("helper").look
    prompt = prompts.build_page_prompt(cast_story, profile, 3, has_refs=True)
    assert helper in prompt and prompts.SAME_CHARACTER in prompt and cast_story.hero_visual not in prompt
    without = prompts.build_page_prompt(cast_story, profile, 3, has_refs=False)
    assert helper in without and cast_story.hero_visual[:40] in without
    assert "The helper character, drawn the same on every page" in prompt


def test_obstacle_and_helper_appear_only_on_the_pages_whose_scene_names_them(cast_story):
    profile = make()
    helper, obstacle = cast_story.character("helper").look, cast_story.character("obstacle").look
    page2 = prompts.build_page_prompt(cast_story, profile, 2, has_refs=True)          # в сцене только препятствие
    assert obstacle in page2 and helper not in page2
    page4 = prompts.build_page_prompt(cast_story, profile, 4, has_refs=True)          # помощник на берегу, препятствия в сцене нет
    assert helper in page4 and "The obstacle in this scene" not in page4
    page5 = prompts.build_page_prompt(cast_story, profile, 5, has_refs=True)
    assert helper in page5 and obstacle in page5


def test_every_page_prompt_keeps_layout_legal_rule_style_and_length_with_the_cast(cast_story):
    profile = make()
    for index in range(1, PAGES + 1):
        for has_refs in (False, True):
            prompt = prompts.build_page_prompt(cast_story, profile, index, has_refs=has_refs)
            assert len(prompt) <= prompts.MAX_PROMPT
            assert prompts.page_layout_clause(index, has_refs=has_refs) in prompt
            assert prompts.LEGAL_CLAUSE in prompt and prompts.STYLE in prompt
            assert f"the {text_side(index)} half is a calm" in prompt.lower()


def test_cover_prompt_puts_the_helper_next_to_the_hero(cast_story):
    profile = make()
    helper = cast_story.character("helper").look
    for photo, title in itertools.product((False, True), (False, True)):
        prompt = prompts.build_cover_prompt(cast_story, profile, photo_ref=photo, title_in_image=title)
        assert "Right next to the hero stands the hero's helper" in prompt and helper in prompt
        assert prompts.LEGAL_CLAUSE in prompt and len(prompt) <= prompts.MAX_PROMPT
    assert f"«{cast_story.title}»" in prompts.build_cover_prompt(cast_story, profile, photo_ref=False, title_in_image=True)


def test_cast_looks_never_leak_the_childs_name_or_overflow_the_prompt():
    profile = make()
    data = build_mock_story(profile)
    data["cast"][1]["look"] = "A friend of Aidar, " + ("a fluffy kitten with white paws and a blue collar, " * 9)[:480]
    story = validate_story(data, "ru")
    for index in (3, 5):
        prompt = prompts.build_page_prompt(story, profile, index, has_refs=False)
        assert "aidar" not in prompt.lower() and "айдар" not in prompt.lower() and len(prompt) <= prompts.MAX_PROMPT
        assert prompts.LEGAL_CLAUSE in prompt and prompts.STYLE in prompt
    assert "aidar" not in prompts.build_cover_prompt(story, profile, photo_ref=False).lower()


def test_old_story_without_cast_gives_the_same_prompts_as_before():
    profile = make()
    data = build_mock_story(profile)
    data.pop("cast"); data.pop("refrain")
    old = validate_story(data, "ru")
    assert old.cast == () and old.refrain == "" and old.character("helper") is None
    page = prompts.build_page_prompt(old, profile, 3, has_refs=True)
    assert "helper character, drawn the same" not in page and "obstacle in this scene" not in page.lower()
    cover = prompts.build_cover_prompt(old, profile, photo_ref=False, title_in_image=True)
    assert "helper" not in cover.lower().replace("the helper character", "")
    assert "cast" not in old.to_dict() and "refrain" not in old.to_dict()


def test_old_saved_stories_still_load_even_with_long_pages_and_broken_cast():
    data = build_mock_story(make())
    data.pop("cast"); data.pop("refrain")
    data["pages"] = [{"text": "Очень длинный старый текст страницы. " * 20, "scene": p["scene"]} for p in data["pages"]]
    story = Story.from_dict(data)
    assert story.cast == () and len(story.pages) == PAGES
    data["cast"] = [{"name": "x", "role": "villain", "look": "short"}]
    data["refrain"] = ["не", "строка"]
    assert Story.from_dict(data).cast == ()                                  # непонятное при чтении старой книги отбрасывается
    data["pages"] = data["pages"][:6]
    assert len(Story.from_dict(data).pages) == 6                             # и число страниц при чтении не строгое


@pytest.mark.parametrize("bad, fragment", [
    ([{"name": "Бом", "role": "villain", "look": "a small friendly bear cub"}], "role"),
    ([{"name": "Бом", "role": "helper", "look": "маленький добрый медвежонок"}], "по-английски"),
    ([{"name": "Бом", "role": "helper", "look": "bear"}], "слишком короткое"),
    ([{"name": "Бом", "role": "helper", "look": "a small friendly bear cub"}], "ровно один герой"),
    ("not a list", "списком"),
])
def test_new_stories_reject_a_broken_cast(bad, fragment):
    data = build_mock_story(make())
    data["cast"] = bad
    with pytest.raises(StoryValidationError) as err:
        validate_story(data, "ru")
    assert fragment in str(err.value)


# ============================================================================ заглушка и тексты
@pytest.mark.parametrize("language", ["ru", "ky"])
def test_mock_story_obeys_the_same_validator_for_every_age_place_gender_and_mode(language):
    bad = []
    for age, place, gender, islamic in itertools.product(range(3, 10), options.PLACES, ("boy", "girl"), (False, True)):
        name = "Айдар" if gender == "boy" else "Айгүл"
        profile = make(language=language, age=age, place=place, gender=gender, name=name, islamic=islamic,
                       place_custom="во дворе" if place == "custom" else "")
        found = check_story(validate_story(build_mock_story(profile), language), profile)
        if found:
            bad.append((age, place, gender, [str(v) for v in found]))
    assert not bad, bad[:3]


def test_mock_pages_are_short_and_grow_with_the_age():
    sizes = {}
    for age in (3, 5, 8):
        story = validate_story(build_mock_story(make(age=age)), "ru")
        sizes[age] = max(len(words(p.text)) for p in story.pages)
    assert sizes[3] <= 18 < sizes[5] <= 28 and sizes[5] < sizes[8] <= 36


def test_limits_text_is_in_the_author_prompt_at_the_start_and_at_the_end():
    profile = make(age=4)
    system = build_system_prompt(profile)
    expected = limits_text(profile)
    assert system.count(expected) == 2                                        # в начале и ещё раз в самом конце
    assert system.index(expected) < 600 and system.rstrip().endswith("короткая страница лучше длинной.")
    assert "от 10 до 18 слов, не больше 125 знаков, не больше трёх предложений" in expected


def test_every_prompt_template_has_no_leftover_placeholders():
    profile = make(language="ky", islamic=True, gender="girl", headscarf=True)
    profile.has_photo = True
    story = validate_story(build_mock_story(profile), "ky")
    seeds = seeds_for(profile)
    plan = validate_plan(plan_dict(profile, seeds), profile, seeds)
    texts = list(build_planner_prompts(profile, seeds)) + [build_system_prompt(profile), build_user_prompt(profile, plan, seeds)]
    texts += list(build_editor_prompts(profile, story, plan)) + list(prompts.build_ky_proof_prompts(profile, story))
    import re
    for text in texts:
        assert not re.search(r"\{(pages|age|language|value|limits|forms|name_max|safety|data_note|checklist|gender|magic)\}", text)


# ============================================================================ сквозная проверка: книга из конвейера доходит до картинок
async def test_scripted_pipeline_book_goes_through_build_book_and_the_cast_reaches_every_image_prompt(tmp_path):
    import asyncio
    from app.bookgen import build_book
    from .conftest import ScriptedImage

    profile = make()
    text = ScriptedPipeline(profile, polish=True)
    image = ScriptedImage()
    result = await build_book(profile, text, image, tmp_path / "order", image_sem=asyncio.Semaphore(3), mock=True)
    stored = json.loads((tmp_path / "order" / "story.json").read_text(encoding="utf-8"))
    assert [c["role"] for c in stored["cast"]] == ["hero", "helper", "obstacle"] and stored["refrain"] == result.story.refrain
    assert Story.from_dict(stored) == result.story                                      # story.json читается обратно без потерь
    helper = result.story.character("helper").look
    pages = [c for c in image.calls if c["label"].startswith("Страница")]
    cover = next(c for c in image.calls if c["label"] == "Обложка")
    assert len(pages) == PAGES and helper in cover["prompt"] and "Right next to the hero" in cover["prompt"]
    with_helper = [c for c in pages if helper in c["prompt"]]
    assert len(with_helper) >= PAGES - 3                                                # помощник есть почти в каждом кадре
    assert all(prompts.LEGAL_CLAUSE in c["prompt"] and len(c["prompt"]) <= prompts.MAX_PROMPT for c in image.calls)
    assert all("айдар" not in c["prompt"].lower() and "aidar" not in c["prompt"].lower() for c in pages)
