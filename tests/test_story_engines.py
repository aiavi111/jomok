"""Разнообразие сюжетов: форм много, поиск и пропажи только в трёх, начало книги случайное и не ночное."""
import random

from app import story_engines as E
from app import simple_writer as sw
from app.profile import Profile
from app.writer import tech_hits

from .conftest import SAMPLE


def test_there_are_many_engines_and_only_three_are_about_searching():
    ids = [f.id for f in E.ENGINES]
    assert len(ids) == len(set(ids)) == 22
    assert E.SEARCH_IDS <= set(ids) and len(E.SEARCH_IDS) == 3
    assert "fear" not in ids and E.FEAR.id == "fear"
    for engine in E.ENGINES:
        assert len(engine.steps) == 3 and engine.pitch and engine.ru
        assert not tech_hits(engine.pitch + " " + " ".join(engine.steps)), engine.id
        assert "ночью" not in (engine.pitch + " ".join(engine.steps)).lower() or engine.id == "bedtime_helper", engine.id


def test_picks_are_varied_and_life_lesson_is_always_about_fear():
    rng = random.Random(7)
    seen = {E.pick_engine(None, rng).id for _ in range(300)}
    assert len(seen) >= 18
    assert {E.pick_engine("life_lesson", rng).id for _ in range(20)} == {"fear"}


def test_openings_vary_and_never_start_at_night():
    rng = random.Random(3)
    openings = {E.pick_opening(rng) for _ in range(200)}
    assert len(openings) >= 30
    assert not any("ноч" in o.lower() for o in openings)


def test_the_prompt_carries_the_engine_steps_and_the_opening_but_not_when_parents_asked_for_a_story():
    profile = Profile.from_payload(SAMPLE)
    engine = next(f for f in E.ENGINES if f.id == "grow_seed")
    prompt = sw.user_prompt(profile, engine, "Начало книги: яркий солнечный полдень. Первую фразу начни с вопроса.")
    assert "вырастить росток" in prompt and "1) " in prompt and "3) " in prompt and "Начало книги: яркий солнечный полдень" in prompt
    asked = Profile.from_payload({**SAMPLE, "request": "Артём находит динозаврика"})
    prompt = sw.user_prompt(asked, engine, "Начало книги: полдень.")
    assert "вырастить росток" not in prompt and "Начало книги" not in prompt          # просьба родителей важнее случайной формы


def test_the_writer_rules_do_not_force_a_search_story_and_the_sample_is_not_one():
    system = sw.system_prompt(Profile.from_payload(SAMPLE))
    assert "Не каждая книга про поиск" in system and "Каждая книга другая" in system
    assert "светлячок" not in sw._SAMPLE.lower() and "ночь" not in sw._SAMPLE.lower()


def test_made_up_requirements_are_not_checked_when_parents_wrote_nothing():
    """Модель принимала подсказку про начало или шаг формы за просьбу родителей, вписывала её в requirements, и книга перегенерировалась зря."""
    profile = Profile.from_payload(SAMPLE)
    pages = [{"text": "t", "scene": "the hero and the helper at a stream"} for _ in range(8)]
    data = {"requirements": [{"what": "Начало днём после дождя", "en": "puddles after rain"}]}
    sw._check_requirements(profile, data, pages, "a red jacket")                 # раньше: «Просьба родителей ... почти не видна»
    asked = Profile.from_payload({**SAMPLE, "request": "Айдар играет в футбол на стадионе"})
    import pytest
    with pytest.raises(Exception):
        sw._check_requirements(asked, {"requirements": [{"what": "стадион", "en": "stadium"}]}, pages, "a red jacket")


def test_flavor_gives_each_book_its_own_quirk_names_twist_and_places():
    rng = random.Random(5)
    flavors = {E.pick_flavor(with_story=True, rng=rng) for _ in range(100)}
    assert len(flavors) >= 95                                                  # почти каждая книга получает свой набор
    text = next(iter(flavors))
    assert "привычка помощника" in text and "неожиданный поворот" in text and "необычные места" in text and "имя помощника выбери из" in text
    assert "в requirements не пиши" in text
    # с просьбой родителей сюжет их, поэтому поворот и места не навязываем: остаётся привычка и имя
    asked = E.pick_flavor(with_story=False, rng=rng)
    assert "привычка помощника" in asked and "имя помощника" in asked and "поворот" not in asked and "места" not in asked


def test_flavor_names_come_from_the_helper_name_list():
    from app import writer_data as D
    known = {n.name for n in D.HELPER_NAMES}
    text = E.pick_flavor(with_story=True, rng=random.Random(1))
    names = text.split("имя помощника выбери из: ")[1].split(" (или своё")[0].split(", ")
    assert len(names) == 6 and set(names) <= known


def test_the_writer_brainstorms_three_ideas_and_avoids_stale_endings():
    system = sw.system_prompt(Profile.from_payload(SAMPLE))
    assert "три РАЗНЫЕ идеи" in system and '"ideas"' in system and "самую неожиданную" in system
    assert "поделились печеньем" in system and "не общая фраза вроде «доброта помогает»" in system
    profile = Profile.from_payload(SAMPLE)
    prompt = sw.user_prompt(profile, E.ENGINES[0], None, sw.pick_flavor(profile, random.Random(2)))
    assert "Изюминки этой книги" in prompt
    asked = Profile.from_payload({**SAMPLE, "request": "Айдар играет в футбол"})
    assert "поворот" not in sw.pick_flavor(asked, random.Random(2))


def test_the_sense_editor_retells_every_page_but_only_fixes_real_nonsense():
    system = sw.SENSE_SYSTEM
    assert '"retold"' in system and "Для КАЖДОЙ страницы" in system and "0–3 страницы" in system
    assert "смена места НЕ бессмыслица" in system and "живот на солнце" in system          # переходы между страницами не добавляем
    writer = sw.system_prompt(Profile.from_payload(SAMPLE))
    assert "то, что происходит (упал, чихнул, перепутал" in writer and "перепиши" in writer


def test_the_new_editor_answer_format_still_applies_fixes_and_ignores_the_retelling():
    import json
    from .test_sheet import _football
    profile, data = _football({"request": "Артём играет на стадионе"})
    story = sw.assemble(profile, data)
    good = "Артём шёл по тропинке с другом. Они искали мяч и смеялись. — Вот он! — крикнул Артём. Друг радостно кивнул."
    raw = json.dumps({"retold": [{"page": 1, "what": "герой идёт"}], "fixes": [{"page": 2, "text": good}]}, ensure_ascii=False)
    fixed, applied = sw.apply_sense_fixes(profile, story, raw)
    assert applied == [2] and fixed.pages[1].text == good                       # поле retold не мешает разбору
    assert sw.apply_sense_fixes(profile, story, '{"retold": [], "fixes": []}')[1] == []
