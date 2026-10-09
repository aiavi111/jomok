"""Правила код-валидатора книги (writer.py), которые легко сломать ложными срабатываниями или пропустить:
узнавание рефрена, проверка кыргызского языка, маленький каст, подсчёт предложений на странице с обрывом рефрена,
жёсткие и мелкие нарушения и «мягкая посадка» (книга с одними мелкими замечаниями принимается после всех попыток).

Сеть не нужна: модель текста поддельная (tests/writer_helpers.py)."""
import logging

import pytest

from app import writer
from app import writer_data as D
from app.errors import StoryError, StoryValidationError
from app.profile import Profile
from app.providers.text_mock import build_mock_story
from app.story import validate_story
from app.writer import (RefrainMatcher, Violation, assemble_story, check_story, counted_sentences, sentences, validate_plan,
                        violations_text)

from .conftest import SAMPLE
from .writer_helpers import ScriptedPipeline, author_dict, dump, plan_dict, seeds_for


def make(**over) -> Profile:
    return Profile.from_payload({**SAMPLE, **over})


def book(profile: Profile, mutate=None):
    """(план, книга) из верных ответов режиссёра и автора; mutate правит ответ автора до сборки."""
    seeds = seeds_for(profile)
    plan = validate_plan(plan_dict(profile, seeds), profile, seeds)
    data = author_dict(profile, seeds)
    if mutate:
        mutate(data)
    return plan, assemble_story(profile, plan, data)


def violations(profile: Profile, mutate=None) -> list[Violation]:
    plan, story = book(profile, mutate)
    return check_story(story, profile, plan)


def codes(profile: Profile, mutate=None) -> list[str]:
    return [v.code for v in violations(profile, mutate)]


def messages(profile: Profile, mutate=None) -> list[str]:
    return [str(v) for v in violations(profile, mutate)]


def set_pages(**pages):
    """set_pages(p2="…", p5="…"): заменить тексты страниц (номер с единицы)."""
    def mutate(data):
        for key, text in pages.items():
            data["pages"][int(key[1:]) - 1]["text"] = text
    return mutate


KY = {"language": "ky", "name": "Тимур"}


# ============================================================================ рефрен: общее слово рефреном не считается
@pytest.mark.parametrize("refrain, text", [
    ("Раз, два, три — прыг!", "Раз, два, три — прыг!"),
    ("Раз, два, три — прыг!", "Раз, два, три — Бом поднял его на плечи."),         # 3 слова из 4 по порядку
    ("Раз, два, три — прыг!", "Раз, два… стоп! Мальчик посмотрел на шарф."),         # рефрен ломается, но это он
    ("Раз, два, три — вперёд!", "Раз, два, три, и мальчик прыгнул вперёд."),         # лишнее слово посередине
    ("Бир, эки, үч — секир!", "Бир, эки… токто, бала жипке карады."),
    ("Бир, эки, үч — секир!", "Бир, эки, үч — Бом аркасын тосту."),
    ("Мур-мяу, ловим вора!", "— Мур-мяу, — улыбнулся Мурзик."),                      # составное первое слово
    ("Мур-мяу, ловим вора!", "— Мур… ш-ш-ш! — зашептал кот."),
    ("Туда-сюда, туда-сюда!", "Туда-сюда… стоп! — Я буду считать!"),
])
def test_refrain_is_recognised_in_whole_in_part_and_when_it_breaks(refrain, text):
    assert RefrainMatcher(refrain).matches(text)


@pytest.mark.parametrize("refrain, text", [
    ("Раз, два, три — прыг!", "Ещё раз он посмотрел на воду и вздохнул."),
    ("Раз, два, три — прыг!", "В который раз ручей разлился, и раз за разом вода шла выше."),
    ("Раз, два, три — прыг!", "Раз он прыгнул, и нога скользнула по мокрому камню."),
    ("Раз, два, три — прыг!", "Он нашёл два камня и три шишки."),
    ("Раз, два, три — вперёд!", "Раз за разом он шёл вперёд, и два дня, и три."),    # слова рефрена рассыпаны далеко друг от друга
    ("Бир, эки, үч — секир!", "Бир күнү ал бир нерсе көрдү, бир бала болчу."),        # «бир» — «один, какой-то» на каждой странице
    ("Бир, эки, үч — секир!", "Ал бир-эки күн жол жүрдү."),                          # «бир-эки» (пара) — одно слово
    ("Мур-мяу, ловим вора!", "Мурзик замурлыкал и поймал мышку."),
])
def test_one_common_word_or_a_chance_match_is_not_the_refrain(refrain, text):
    assert not RefrainMatcher(refrain).matches(text)


def test_russian_book_with_raz_on_three_pages_and_no_refrain_is_reported():
    profile = make()
    msgs = messages(profile, set_pages(
        p1="Мальчик нёс бабушке лепёшки.", p2="Ещё раз он посмотрел на ручей и вздохнул.",
        p3="В который раз ручей разлился, и мальчик замер.", p4="Помощник сказал: — Раз ручей широкий, надо думать.",
        p5="Мальчик пробовал раз за разом, но вода шумела.", p6="Он посмотрел на шнурок и палку.",
        p7="Он привязал шнурок к палке.", p8="Бабушка налила всем чая."))
    assert any("рефрен «Раз, два, три — прыг!» встречается на 0 стр." in m for m in msgs), msgs


def test_kyrgyz_book_with_bir_on_most_pages_is_not_told_the_refrain_is_overused():
    profile = make(**KY)
    plan, story = book(profile)
    matcher = RefrainMatcher(plan.refrain)
    assert sum(matcher.matches(p.text) for p in story.pages) == 5                    # заглушка: рефрен на 5 страницах (потолок)
    natural = {
        "p1": "Бир күнү Тимур чоң энесине бир себет ысык боорсок алып чыкты. Жол бир аз узак эле.",
        "p2": "Алдынан бир кең суу чыкты. Бир көпүрөнүн ордунда бир гана жыгач калган экен.",
        "p7": "Ал бир жипти бир таякка байлап, бир учун суунун аркы өйүзүнө ыргытты. Таяк илинип калды.",
    }
    found = [v for v in violations(profile, set_pages(**natural)) if v.code == "refrain"]
    assert not found, [str(v) for v in found]
    assert sum(RefrainMatcher(plan.refrain).matches(t) for t in natural.values()) == 0


def test_a_refrain_missing_from_a_kyrgyz_book_is_still_reported():
    profile = make(**KY)
    plain = {f"p{i}": "Бала бир нерсени көрүп, бир аз токтоп калды." for i in range(1, 9)}
    assert any(c == "refrain" for c in codes(profile, set_pages(**plain)))


def test_the_break_of_the_refrain_is_not_an_extra_ellipsis():
    profile = make()
    plan, story = book(profile)
    assert "ellipsis" not in [v.code for v in check_story(story, profile, plan)]     # «Раз, два… стоп» на странице 6
    extra = set_pages(p2="Ручей шумел… и мостика не было.", p3="Мальчик ждал… и смотрел на воду.")
    assert "ellipsis" in codes(profile, extra)


# ============================================================================ подсчёт предложений
def test_counted_sentences_merges_the_refrain_break_and_skips_one_or_two_word_exclamations():
    refrain = RefrainMatcher("Раз, два, три — вперёд!")
    assert len(sentences("Раз, два… Стоп! Мальчик посмотрел на шарф.")) == 3                  # «сырой» счёт не меняется
    assert len(counted_sentences("Раз, два… Стоп! Мальчик посмотрел на шарф.", refrain)) == 2
    assert len(counted_sentences("Раз, два… Мальчик замолчал.", refrain)) == 1
    assert len(counted_sentences("Раз, два… Стоп! Мальчик посмотрел на шарф. Придумал!", refrain)) == 2
    assert len(counted_sentences("Щёлк! Змей застрял на ёлке.")) == 1
    assert len(counted_sentences("Топ-топ, вместе! Бом и Тимур побежали.")) == 1
    assert len(counted_sentences("Раз, два, три, четыре… Стоп! Он замер.", refrain)) == 2    # начало рефрена длиннее трёх слов
    assert len(counted_sentences("Он шёл. Он бежал. Он прыгал.")) == 3                       # короткие, но не возгласы
    assert len(counted_sentences("Щёлк! Он шёл. Он бежал. Он прыгал.")) == 3                 # возгласами не прикроешь длинную страницу
    assert len(counted_sentences("Бом! Бом! Бом!")) == 1                                     # страница из одних возгласов — одна


@pytest.mark.parametrize("age, language, text", [
    (4, "ru", "Раз, два… Стоп! Мальчик посмотрел на шарф."),
    (4, "ru", "Раз, два… Мальчик замолчал."),
    (4, "ru", "Раз, два, три — прыг! Щёлк! Не достал."),
    (6, "ru", "Раз, два… Стоп! Он посмотрел на палку и на длинный шарф. Придумал!"),
    (6, "ru", "Раз, два… Стоп! Он посмотрел на шарф. Щёлк! Придумал!"),
    (8, "ru", "Раз, два… Стоп! Он долго смотрел на палку. Потом на шарф. Придумал!"),
    (6, "ky", "Бир, эки… Токто! Бала жипке жана таякка карады. Ойлоп таптым!"),
])
def test_the_refrain_break_page_fits_the_sentence_limit_in_every_age_band(age, language, text):
    profile = make(age=age, **(KY if language == "ky" else {}))
    assert "sentences" not in codes(profile, set_pages(p6=text))


def test_a_really_long_page_still_breaks_the_sentence_limit():
    profile = make(age=4)
    msgs = messages(profile, set_pages(p6="Щёлк! Он шёл. Он бежал. Он прыгал. Он ждал."))
    assert any(m.startswith("стр.6: 4 предложения, лимит 3") for m in msgs)


# ============================================================================ кыргызская книга пишется по-кыргызски
RUSSIAN_PAGES = [p["text"] for p in build_mock_story(make(name="Тимур"))["pages"]]


def russian_text(data):
    data["title"] = "Тимур и Бом"
    data["moral"] = "Доброта делает мир теплее."
    data["wish"] = "Тимур, пусть твоё сердце всегда остаётся тёплым!"
    for page, text in zip(data["pages"], RUSSIAN_PAGES):
        page["text"] = text


def test_a_russian_story_ordered_in_kyrgyz_fails_as_the_wrong_language():
    profile = make(**KY)
    found = [v for v in violations(profile, russian_text) if v.code == "wrong_language"]
    assert found and not found[0].soft
    assert any("ү, ө, ң" in v.message for v in found) and any("русские слова" in v.message for v in found)
    assert "wrong_language" not in codes(make(name="Тимур"), russian_text)           # для русской книги это нормальный текст


def test_a_few_stray_russian_words_in_kyrgyz_text_are_tolerated_but_not_many():
    profile = make(**KY)
    assert "wrong_language" not in codes(profile, set_pages(p2="Алдынан кең суу чыкты, бирок мостика жок эле, и бала токтоду."))
    many = set_pages(p2="Бала сказал: — Мы идём на ручей, и это очень хорошо, потому что он был рядом.")
    assert "wrong_language" in codes(profile, many)


def test_a_kyrgyz_book_without_kyrgyz_letters_fails_even_without_russian_function_words():
    profile = make(**KY)
    flat = {f"p{i}": "Бала жолго чыкты, суу кечип барды, таш үстүнөн секирди." .replace("ү", "у").replace("ө", "о")
            for i in range(1, 9)}
    assert any("почти нет букв" in m for m in messages(profile, set_pages(**flat)))


def test_the_mock_kyrgyz_book_has_enough_kyrgyz_letters_at_every_age():
    for age in (3, 5, 8):
        assert "wrong_language" not in codes(make(age=age, **KY))


@pytest.mark.parametrize("refrain", ["Раз, два, три — вперёд!", "Бир, два, три — жүр!", "Давай, давай, вместе!", "Хорошо, хорошо, хорошо!"])
def test_a_kyrgyz_plan_rejects_a_russian_or_unmarked_refrain(refrain):
    profile = make(**KY)
    seeds = seeds_for(profile)
    data = plan_dict(profile, seeds)
    data["refrain"]["text"] = refrain
    with pytest.raises(StoryValidationError) as err:
        validate_plan(data, profile, seeds)
    assert "refrain.text" in str(err.value) and "Бир, эки, үч — жүр!" in str(err.value)


@pytest.mark.parametrize("refrain", ["Бир, эки, үч — жүр!", "Тык-тык, шыбыр-шыбыр!", "Бир, эки, али!", "Кана, баштайбыз!", "Алга, достор!"])
def test_a_kyrgyz_plan_accepts_a_kyrgyz_refrain(refrain):
    profile = make(**KY)
    seeds = seeds_for(profile)
    data = plan_dict(profile, seeds)
    data["refrain"]["text"] = refrain
    assert validate_plan(data, profile, seeds).refrain == refrain


def test_a_russian_plan_may_keep_a_russian_counting_refrain():
    profile = make()
    seeds = seeds_for(profile)
    data = plan_dict(profile, seeds)
    data["refrain"]["text"] = "Раз, два, три — вперёд!"
    assert validate_plan(data, profile, seeds).refrain == "Раз, два, три — вперёд!"


@pytest.mark.parametrize("text, code", [
    ("Ал бөрүнү өлтүрдү да, кан агып турду.", "violence"),
    ("Согуш башталды, баары курал алышты.", "violence"),
    ("Бала мылтык көтөрүп чыкты жана суунун жээгинде токтоду.", "violence"),
    ("Жөргөмүш адам чыгып, суунун үстүнөн өтүүгө жардам берди.", "brand"),
    ("Маша жана аюу суунун жээгинде отурушкан эле.", "brand"),
])
def test_kyrgyz_violence_and_brand_words_are_caught(text, code):
    assert code in codes(make(**KY), set_pages(p2=text))


def test_ordinary_kyrgyz_words_that_look_like_banned_stems_pass():
    profile = make(**KY)
    ok = set_pages(p2="Канат кагып, шамал кана жүр деп чакырды. Өлкө кең, бөлүм бөлүм болуп, кандай суу эле.")
    assert not {"violence", "emotion"} & set(codes(profile, ok))


def test_kyrgyz_emotion_words_are_counted_like_russian_ones():
    profile = make(**KY)
    feelings = set_pages(p2="Бала кубанды жана бактылуу болду.", p3="Ал капа болду, анан таң калды.")
    assert "emotion" in codes(profile, feelings)
    assert "emotion" not in codes(profile)                                           # в заглушке одно слово-чувство


# ============================================================================ маленький каст
def helper_of(profile: Profile) -> str:
    return seeds_for(profile).helper_name.name


NEW_NAMES = ["Рекс", "Мурка", "Борис", "Зарина", "Гром", "Клара", "Жук", "Фёдор"]


@pytest.mark.parametrize("extra", [{}, KY])
def test_a_new_named_helper_on_every_page_is_reported_as_new_characters(extra):
    profile = make(**extra)
    helper = helper_of(profile)

    def mutate(data):
        for page, name in zip(data["pages"], NEW_NAMES):
            page["text"] = page["text"].replace(helper, name)
    found = [v for v in violations(profile, mutate) if v.code == "cast"]
    assert any("новые персонажи:" in v.message and "Борис" in v.message and f"«{helper}»" in v.message for v in found), found
    assert any("назван по имени на 0 стр." in v.message for v in found)


@pytest.mark.parametrize("extra", [{}, KY])
def test_a_book_without_the_helper_by_name_is_reported(extra):
    profile = make(**extra)
    helper = helper_of(profile)
    msgs = messages(profile, lambda d: [p.update(text=p["text"].replace(helper, "друг" if not extra else "дос")) for p in d["pages"]])
    assert any(f"помощник «{helper}» назван по имени на 0 стр., нужно не меньше 3" in m for m in msgs), msgs


def test_the_helper_must_be_named_on_three_pages_not_two():
    profile = make()
    helper = helper_of(profile)
    plan, story = book(profile)
    named = [i for i, p in enumerate(story.pages) if helper in p.text]
    assert len(named) >= 3 and "cast" not in [v.code for v in check_story(story, profile, plan)]

    def drop_one(data):
        data["pages"][named[0]]["text"] = data["pages"][named[0]]["text"].replace(helper, "друг")
    assert "cast" in codes(profile, drop_one)


@pytest.mark.parametrize("name, token, language, expected", [
    ("Бом", "бома", "ru", True), ("Бом", "бомом", "ru", True), ("Бом", "бому", "ru", True), ("Бом", "бомба", "ru", False),
    ("Бася", "басе", "ru", True), ("Бася", "басей", "ru", True), ("Тики", "тики", "ru", True),
    ("Бом", "бомго", "ky", True), ("Бом", "бомдор", "ky", True), ("Бом", "бомбардировка", "ky", False),
])
def test_helper_name_is_recognised_in_its_case_forms(name, token, language, expected):
    assert writer._helper_matcher(name, language)(token) is expected


def test_one_new_name_is_tolerated_in_any_case_two_are_not_and_speech_openers_are_not_names():
    profile = make()
    helper = helper_of(profile)
    plan, story = book(profile)
    cases = set_pages(p2="Мальчик сказал: — Привет! Они пошли вдоль Иссык-Куля, и Рекс побежал следом.",
                      p4="Рекса не было видно, потому что Рексу хотелось спать. «Привет!» — сказал он.")
    assert "cast" not in [v.code for v in violations(profile, cases)]
    found = [v for v in violations(profile, lambda d: [cases(d), set_pages(p6="Мальчик погладил Мурку по спине.")(d)]) if v.code == "cast"]
    assert len(found) == 1 and "Рекс, Мурку" in found[0].message and f"«{helper}»" in found[0].message


def test_names_the_parent_asked_for_and_places_are_not_new_characters():
    profile = make(favorites="Зайчик Бобо и Мурка")
    texts = set_pages(p2="Мальчик взял Бобо за лапу и показал Мурке ручей.", p4="По берегу Иссык-Куля шли Бобо и Мурка.")
    assert "cast" not in codes(profile, texts)
    stranger = set_pages(p2="Мальчик взял Бобо за лапу и показал Борису ручей.", p4="Фёдор ждал их у берега.")
    assert "cast" in codes(make(), stranger)


def test_a_dash_after_a_word_does_not_hide_a_name_but_dialogue_dashes_do():
    profile = make()
    hidden = set_pages(p2="Раз, два, три — Рекс подставил спину, но вода была глубокой.",
                       p4="Раз, два, три — Борис поднял его на плечи, и ноги стали сухими.")
    assert any("Борис" in m and "Рекс" in m for m in messages(profile, hidden) if m.startswith("новые персонажи"))
    dialogue = set_pages(p2="Мальчик остановился. — Помочь? — спросил кто-то. — Придумал! — сказал он.",
                         p4="Он крикнул: — Раз, два, три — прыг! — и прыгнул через камень.")
    assert "cast" not in codes(profile, dialogue)


def test_old_books_without_a_helper_and_the_mock_are_not_checked_for_the_cast():
    profile = make()
    data = build_mock_story(profile)
    data.pop("cast")
    story = validate_story(data, "ru")
    assert [v for v in check_story(story, profile) if v.code == "cast"] == []
    for age in (3, 6, 9):
        assert "cast" not in codes(make(age=age))
        assert "cast" not in codes(make(age=age, **KY))


# ============================================================================ жёсткие и мелкие нарушения
@pytest.mark.parametrize("code", ["repeat", "ellipsis", "question", "emotion", "limited_phrase", "same_sentence", "refrain",
                                  "title", "moral", "name_count", "ban_phrase", "cliche", "echo", "cast"])
def test_cosmetic_violations_are_soft(code):
    assert Violation(code, "x").soft


@pytest.mark.parametrize("code", ["brand", "ban_name", "violence", "islamic", "latin", "emoji", "wrong_language", "words_max",
                                  "words_min", "chars", "sentences", "sentence_long", "team"])
def test_unsafe_or_out_of_limits_violations_are_hard(code):
    assert not Violation(code, "x").soft


def test_hard_violations_come_first_in_the_text_for_the_author_even_when_there_are_many():
    soft = [Violation("repeat", f"мелочь {i}", i) for i in range(1, 10)]
    hard = [Violation("brand", "бренд", 3), Violation("latin", "латиница", 4)]
    lines = violations_text(soft + hard, limit=3).splitlines()
    assert lines[0].endswith("бренд") and lines[1].endswith("латиница") and "мелочь 1" in lines[2]
    assert lines[-1] == "- … и ещё 8"


SOFT_BAD = "Ручей шумел, ручей бежал, ручей блестел в траве у самого берега."          # repeat: мелкое замечание
HARD_BAD = "Навстречу вышел Человек-паук и показал мостик у ручья, а потом ушёл."        # brand: жёсткое


def with_page(profile, text, index=2) -> str:
    data = author_dict(profile, seeds_for(profile))
    data["pages"][index - 1]["text"] = text
    return dump(data)


async def test_a_book_left_with_only_soft_violations_is_accepted_after_the_last_attempt(caplog):
    profile = make()
    soft = with_page(profile, SOFT_BAD)
    provider = ScriptedPipeline(profile, {"author": [soft]})
    with caplog.at_level(logging.WARNING):
        story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "author", "author"]                 # автору дали три попытки исправить
    assert story.pages[1].text == SOFT_BAD
    assert any("принята с мелкими замечаниями" in r.getMessage() and "ручей" in r.getMessage() for r in caplog.records)
    retry = provider.calls_of("author")[1]["messages"][-1][1]
    assert "повторяется 3 раза" in retry


async def test_the_author_who_fixes_the_soft_problem_on_a_retry_gets_the_fixed_book():
    profile = make()
    provider = ScriptedPipeline(profile, {"author": [with_page(profile, SOFT_BAD), None]})
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "author"]
    assert story.pages[1].text != SOFT_BAD


async def test_a_hard_violation_that_stays_fails_the_order_even_when_soft_ones_are_also_there():
    profile = make()
    provider = ScriptedPipeline(profile, {"author": [with_page(profile, HARD_BAD)]})
    with pytest.raises(StoryError) as err:
        await provider.generate_story(profile)
    assert provider.stages == ["planner"] + ["author"] * 3 and "бренд" in str(err.value)


async def test_an_earlier_book_with_soft_problems_beats_a_last_attempt_with_a_hard_one():
    profile = make()
    provider = ScriptedPipeline(profile, {"author": [with_page(profile, SOFT_BAD), with_page(profile, HARD_BAD)]})
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "author", "author"]
    assert story.pages[1].text == SOFT_BAD


async def test_the_book_with_the_fewest_soft_problems_is_chosen():
    profile = make()
    one = author_dict(profile, seeds_for(profile))
    one["pages"][1]["text"] = SOFT_BAD
    two = author_dict(profile, seeds_for(profile))
    two["pages"][1]["text"] = SOFT_BAD
    two["pages"][2]["text"] = "Мальчик шёл, мальчик ждал, мальчик думал у самой воды рядом."
    provider = ScriptedPipeline(profile, {"author": [dump(one), dump(two), dump(two)]})
    story = await provider.generate_story(profile)
    assert story.pages[1].text == SOFT_BAD and story.pages[2].text == author_dict(profile, seeds_for(profile))["pages"][2]["text"]


async def test_a_wrong_language_kyrgyz_book_is_never_accepted():
    profile = make(**KY)
    data = author_dict(profile, seeds_for(profile))
    russian_text(data)
    provider = ScriptedPipeline(profile, {"author": [dump(data)]})
    with pytest.raises(StoryError) as err:
        await provider.generate_story(profile)
    assert "русские слова" in str(err.value) or "ү, ө, ң" in str(err.value)


def test_soft_codes_in_the_data_file_all_exist_in_the_validator():
    emitted = {"repeat", "ellipsis", "question", "emotion", "limited_phrase", "same_sentence", "refrain", "title", "moral",
               "name_count", "ban_phrase", "cliche", "echo", "cast", "tech"}
    assert D.SOFT_VIOLATIONS == emitted
