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
