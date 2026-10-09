"""Понятный сюжет: каркасы историй и logline, запрет технических слов, новое место на каждой странице, команда друзей в cast,
проход «понятно ли пятилетнему» (проверка и переписывание автором). Модель текста поддельная, сеть не нужна."""
import json
import random

import pytest

from app import prompts
from app import writer_data as D
from app.errors import ProviderError, StoryValidationError
from app.profile import Profile
from app.providers.text_mock import build_mock_story
from app.story import PAGES, Story, validate_story
from app.writer import (RefrainMatcher, assemble_story, brief_places, check_story, parse_comprehension, pick_seeds,
                        requested_team_size, team_size_needed, tech_hits, validate_plan, world_team_size)
from app.writer_prompts import (build_clarity_rewrite_prompt, build_comprehension_prompts, build_planner_prompts,
                                build_user_prompt, frameworks_text, team_text)

from .conftest import SAMPLE
from .writer_helpers import CLEAR, ScriptedPipeline, author_dict, dump, plan_dict, seeds_for, stage_of


def make(**extra) -> Profile:
    return Profile.from_payload({**SAMPLE, **extra})


def planned(profile: Profile, mutate=None, team: int | None = None):
    seeds = seeds_for(profile)
    data = plan_dict(profile, seeds, team)
    if mutate:
        mutate(data)
    return validate_plan(data, profile, seeds)


def rejected(profile: Profile, mutate, team: int | None = None) -> str:
    with pytest.raises(StoryValidationError) as err:
        planned(profile, mutate, team)
    return str(err.value)


# ============================================================================ каркасы и logline
def test_there_are_eight_simple_frameworks_each_retold_in_one_phrase_with_three_steps():
    assert [f.id for f in D.FRAMEWORKS] == ["find_lost", "rescue_friend", "reach_party", "mystery", "fear", "team_task",
                                            "restore_world", "race_flight"]
    for framework in D.FRAMEWORKS:
        assert len(framework.steps) == 3 and framework.pitch and framework.ru
        assert not tech_hits(framework.pitch + " " + " ".join(framework.steps)), framework.id
    assert D.LOGLINE_MAX_WORDS == 14 and D.FRAMEWORK_IDS == tuple(f.id for f in D.FRAMEWORKS)


def test_planner_prompt_lists_every_framework_and_asks_for_one_simple_sentence():
    profile = make()
    seeds = seeds_for(profile)
    system, user = build_planner_prompts(profile, seeds)
    for framework in D.FRAMEWORKS:
        assert f"- {framework.id} — {framework.ru}" in system
    assert "ПОНЯТЕН пятилетнему" in system and "logline" in system and "до 14 слов" in system
    assert "три НОВЫХ места" in system and "Никакой техники и механики" in system and "объяснён сразу, один раз" in system
    assert f"каркас по умолчанию" not in user and seeds.framework in frameworks_text(profile, seeds)
    assert "Шаги на страницах 4–6" in system and "доброе или смелое дело" in system


def test_life_lesson_topic_gets_only_the_fear_framework():
    profile = make(topic="life_lesson")
    seeds = seeds_for(profile)
    text = frameworks_text(profile, seeds)
    assert "- fear —" in text and "- find_lost —" not in text and "по умолчанию «fear»" in text
    assert seeds.framework == "fear"
    assert rejected(profile, lambda p: p.update(framework="find_lost")).count("fear") >= 1


def test_seeds_suggest_a_framework_and_never_fear_outside_the_lesson_topic():
    seen = {pick_seeds(make(), random.Random(i)).framework for i in range(80)}
    assert seen <= set(D.FRAMEWORK_IDS) - {"fear"} and len(seen) >= 6
    assert all(pick_seeds(make(topic="life_lesson"), random.Random(i)).framework == "fear" for i in range(10))


def test_plan_needs_a_known_framework_and_a_short_logline():
    profile = make()
    assert "framework" in rejected(profile, lambda p: p.pop("framework"))
    assert "framework" in rejected(profile, lambda p: p.update(framework="engineering"))
    assert "logline" in rejected(profile, lambda p: p.pop("logline"))
    assert "logline" in rejected(profile, lambda p: p.update(logline=""))
    long = "Ребёнок с другом идёт через три места, находит все пропавшие шарики, помогает каждому и возвращает их домой."
    message = rejected(profile, lambda p: p.update(logline=long))
    assert "logline из 17 слов" in message and "не больше 14" in message and "пятилетний" in message
    plan = planned(profile)
    assert plan.logline.startswith("Ребёнок несёт") and plan.framework in D.FRAMEWORK_IDS
    assert validate_plan(plan.to_dict(), profile, seeds_for(profile)) == plan                    # to_dict и обратно без потерь


def test_the_author_sees_the_logline_and_the_framework_in_the_plan():
    profile = make()
    plan = planned(profile)
    user = build_user_prompt(profile, plan, seeds_for(profile))
    block = json.loads(user.split("<plan>")[1].split("</plan>")[0])
    assert block["logline"] == plan.logline and block["framework"] == plan.framework


def test_plan_text_limits_are_short_and_told_to_the_model_up_front():
    profile = make()
    assert "premise" in rejected(profile, lambda p: p.update(premise="я" * 241))
    assert "image_brief[2]" in rejected(profile, lambda p: p["image_brief"].__setitem__(1, "The hero runs through a sunny meadow. " * 9))
    system, _ = build_planner_prompts(profile, seeds_for(profile))
    assert "каждая строка image_brief до 300 знаков" in system and "premise до 240 знаков" in system
    assert "Многоточия в плане не нужны" in system


# ============================================================================ техника и механика
@pytest.mark.parametrize("text, label", [
    ("Герой нашёл механизм и повернул рычаг.", "механизм"), ("Он вставил пластину в паз.", "пластина"),
    ("Нужна ключ-звезда, чтобы открыть дверь.", "ключ-звезда"), ("Он привязал ленту к тележке.", "лента"),
    ("Это была хитрая схема из шестерёнок.", "схема"), ("Он взял пульт и антенну.", "пульт"),
    ("Герой дёрнул трос.", "трос"), ("Датчик мигнул.", "датчик"), ("Новое устройство загудело.", "устройство"),
])
def test_technical_words_are_found(text, label):
    assert any(label.split()[0] in hit for hit in tech_hits(text)), (text, tech_hits(text))


@pytest.mark.parametrize("text", [
    "Лентяй спал на траве, а ленивый кот зевал.", "Он взял ключик и открыл калитку.", "Лес был полон ярких огоньков.",
    "Пуф толкнул камень, и тот покатился с горки.", "Замок на холме сверкал флажками.", "Они построили домик из веток.",
    "Бам! Хлоп! Топ-топ! Плюх!", "Мышка принесла пластилин.",
])
def test_ordinary_simple_words_are_not_technical(text):
    assert not tech_hits(text), (text, tech_hits(text))


@pytest.mark.parametrize("field, value, word", [
    ("premise", "Ребёнок собирает механизм из шестерёнок, чтобы открыть ворота", "механизм"),
    ("solution", "герой вставляет пластину в паз и поворачивает рычаг", "пластина"),
    ("want", "найти ключ-звезду от замочной скважины", "ключ"),
])
def test_a_plan_with_technical_words_is_sent_back_with_a_clear_message(field, value, word):
    message = rejected(make(), lambda p: p.update({field: value}))
    assert "технические слова" in message and word in message and "без механизмов" in message and "добрым или смелым" in message


def test_technical_words_in_the_book_text_are_a_soft_violation_with_the_word_named():
    profile = make()
    plan = planned(profile)
    data = author_dict(profile, seeds_for(profile))
    data["pages"][1]["text"] = "На пути была пластина и хитрый механизм, а мостик унесло водой, Ура!"
    story = assemble_story(profile, plan, data)
    found = [v for v in check_story(story, profile, plan) if v.code == "tech"]
    assert found and all(v.soft and v.page == 2 for v in found)
    assert any("пластина" in v.message for v in found) and any("механизм" in v.message for v in found)


# ============================================================================ новое место на каждой странице
@pytest.mark.parametrize("brief, expected", [
    ("Wide shot: the hero walks along a sunny path in a green meadow, carrying a basket.", {"path", "meadow"}),
    ("Medium shot: the hero stops at the edge of the stream in soft morning light.", {"stream"}),
    ("The helper peeks out from behind a big rock and waves to the hero on the stream bank in warm light.", {"rock", "bank"}),
    ("Close-up: the hero smiles inside a dim tunnel with glowing mushrooms.", {"tunnel"}),
    ("The hero and the helper team stand close together, golden light all around.", set()),
])
def test_the_place_of_a_brief_is_the_main_word_after_in_on_near_behind(brief, expected):
    assert brief_places(brief) == expected


def test_two_neighbouring_briefs_in_the_same_place_are_rejected_naming_the_place():
    def same(plan):
        plan["image_brief"][3] = "The hero and the helper run through the dim tunnel with glowing mushrooms, light flickers."
        plan["image_brief"][4] = "Wide shot: the hero walks deeper into the long tunnel and looks up at the glowing ceiling in cool light."
    message = rejected(make(), same)
    assert "image_brief[4] и image_brief[5]" in message and "«tunnel»" in message and "НОВОЕ место" in message


def test_different_places_light_and_scale_pass_and_distant_pages_may_return_to_a_place():
    def varied(plan):
        plan["image_brief"][2] = "The hero and the helper wait on a sunny hill above the village in bright morning light."
        plan["image_brief"][3] = "Close-up: the hero crosses a rope bridge over a glittering river, sparks in the air."
        plan["image_brief"][4] = "Wide shot: the friends rest under a giant blossoming tree at golden sunset."
        plan["image_brief"][5] = "Medium shot: the hero and the helper walk across a sunny hill again, long shadows."
    assert planned(make(), varied)


def test_every_mock_scene_set_passes_the_place_check_for_every_place():
    from app import options
    for place in options.PLACES:
        profile = make(place=place, place_custom="во дворе" if place == "custom" else "")
        assert planned(profile)


# ============================================================================ команда друзей
def team_profile(**extra) -> Profile:
    return make(world="ninja_animals", **extra)


def test_team_worlds_and_sizes_are_declared():
    assert D.WORLD_TEAM == {"ninja_animals": 4, "rescue_team": 4, "workshop_helpers": 3, "space_crew": 3, "mountain_friends": 3,
                            "kingdom": 3, "builders": 3}
    assert world_team_size(team_profile()) == 4 and world_team_size(make()) == 0 and world_team_size(make(world="custom")) == 0
    assert all(world in D.WORLD_HELPERS for world in D.WORLD_TEAM) and (D.TEAM_MIN, D.TEAM_MAX) == (2, 4)


def test_seeds_give_three_spare_names_for_the_team_that_are_not_the_leader_or_the_child():
    for i in range(40):
        seeds = pick_seeds(make(name="Топ"), random.Random(i))
        assert len(seeds.team_names) == D.TEAM_EXTRA_NAMES == len(set(seeds.team_names))
        assert seeds.helper_name.name not in seeds.team_names and "Топ" not in seeds.team_names
        assert all(n in {h.name for h in D.HELPER_NAMES} for n in seeds.team_names)
    assert seeds.to_dict()["team_names"] == ", ".join(seeds.team_names)


def test_a_valid_team_plan_keeps_every_member_with_name_kind_trait_and_look():
    profile = team_profile()
    plan = planned(profile)
    assert [m.name for m in plan.team][0] == plan.helper_name and len(plan.team) == 4
    assert plan.team[0].look == "" and all(m.look.isascii() and len(m.look.split()) >= 5 for m in plan.team[1:])
    assert plan.member_names == tuple(m.name for m in plan.team) and len(plan.teammates) == 3
    assert validate_plan(plan.to_dict(), profile, seeds_for(profile)) == plan
    assert '"look"' not in json.dumps(plan.for_author(), ensure_ascii=False)                       # автору внешность не нужна
    assert plan.for_author()["helper"]["team"][1]["name"] == plan.team[1].name


def test_a_team_world_without_a_team_or_with_too_few_friends_is_rejected():
    profile = team_profile()
    assert "нужна команда" in rejected(profile, lambda p: p["helper"].pop("team"), team=4)
    assert "команда из 4" in rejected(profile, lambda p: p["helper"].pop("team"), team=4)
    message = rejected(profile, lambda p: p["helper"].update(team=p["helper"]["team"][:3]), team=4)
    assert "3 друга" in message and "команда из 4" in message
    assert planned(make(world="forest_house"))                                                   # у обычного мира команды нет


@pytest.mark.parametrize("request_text, size", [
    ("Хочу, чтобы в книге были четыре черепашки-ниндзя", 4), ("Команда из трёх зверей-спасателей", 3),
    ("Пусть будет команда друзей", 3), ("Два друга: лисёнок и зайчик", 2), ("хочу 4 зверя ниндзя", 4),
    ("Три медведя и маленькая девочка", 3), ("Команда из пяти героев", 4), ("Четверо богатырей", 4),
])
def test_a_request_for_a_team_is_recognised_and_clamped_to_four(request_text, size):
    assert requested_team_size(make(request=request_text)) == size
    assert requested_team_size(make(favorites=request_text)) == size


@pytest.mark.parametrize("request_text", [
    "", "Хочу, чтобы в книге был большой добрый диплодок и поезд.", "Пусть будет друг-зайчик и мишка Тоша", "Три конфеты и два яблока",
    "В 2 года он любит машинки", "Про то, как мы чистим зубы", "Один добрый лисёнок",
])
def test_ordinary_requests_do_not_force_a_team(request_text):
    assert requested_team_size(make(request=request_text)) == 0


def test_cartoons_never_ask_for_a_team_they_are_only_inspiration():
    assert requested_team_size(make(cartoons="Четыре черепашки-ниндзя")) == 0


def test_the_bigger_of_the_world_and_the_request_decides_the_team_size():
    assert team_size_needed(make(world="ninja_animals")) == 4 and team_size_needed(make(world="kingdom")) == 3
    assert team_size_needed(make(world="kingdom", request="Команда из четырёх зверей")) == 4
    assert team_size_needed(make(request="Три друга")) == 3 and team_size_needed(make()) == 0


def test_a_team_may_be_asked_for_by_the_parent_without_a_team_world():
    profile = make(request="Хочу четырёх зверей-ниндзя")
    assert world_team_size(profile) == 0 and requested_team_size(profile) == 4
    plan = planned(profile)                                                      # по умолчанию команда нужного размера
    assert len(plan.team) == 4
    assert planned(make(request="только лисёнок"), team=0).team == ()


def test_a_plan_without_the_team_the_parent_asked_for_is_sent_back_naming_the_request():
    profile = make(request="Хочу четыре черепашки-ниндзя")
    message = rejected(profile, lambda p: p["helper"].pop("team"))
    assert "нужна команда из 4" in message and "родители просят команду" in message and "Хочу четыре черепашки-ниндзя" in message
    assert "важнее правила «один помощник»" in message
    assert "команда из 4" in rejected(profile, lambda p: p["helper"].update(team=p["helper"]["team"][:2]))


@pytest.mark.parametrize("mutate, fragment", [
    (lambda p: p["helper"]["team"].__setitem__(0, {**p["helper"]["team"][0], "name": "Рик"}), "лидер"),
    (lambda p: p["helper"]["team"][1].update(name="Рекс"), "не из списка"),
    (lambda p: p["helper"]["team"][2].update(name=p["helper"]["team"][1]["name"]), "повторяются"),
    (lambda p: p["helper"]["team"][1].pop("look"), "look"),
    (lambda p: p["helper"]["team"][1].update(look="маленький рыжий лис в зелёном шарфе"), "по-английски"),
    (lambda p: p["helper"]["team"][1].update(look="a small red fox"), "слишком короткое"),
    (lambda p: p["helper"]["team"][1].update(look="a small fox in a green scarf, " * 8), "слишком длинное"),
    (lambda p: p["helper"]["team"][1].update(look="a fox that looks like a Ninja Turtles hero in a mask"), "известные персонажи"),
    (lambda p: p["helper"].update(team="пять друзей"), "списком"),
    (lambda p: p["helper"].update(team=p["helper"]["team"] + p["helper"]["team"][1:]), "из 2–4"),
])
def test_bad_teams_are_rejected_with_a_readable_reason(mutate, fragment):
    assert fragment in rejected(team_profile(), mutate, team=4)


def test_with_a_team_every_brief_must_show_the_whole_team():
    message = rejected(team_profile(), lambda p: p["image_brief"].__setitem__(
        2, "Medium shot: the hero waits on a sunny hill above the village in bright morning light."), team=4)
    assert "image_brief[3]" in message and "вся команда" in message and "the helper team" in message
    assert planned(team_profile())


def test_the_cast_has_every_friend_with_a_name_and_a_look_and_roundtrips():
    profile = team_profile()
    plan = planned(profile)
    story = assemble_story(profile, plan, author_dict(profile, seeds_for(profile)))
    assert [c.role for c in story.cast] == ["hero", "helper", "teammate", "teammate", "teammate", "obstacle", "world"]
    assert [c.name for c in story.characters("teammate")] == [m.name for m in plan.teammates]
    assert all(c.look.isascii() for c in story.cast if c.role == "teammate")
    assert Story.from_dict(json.loads(json.dumps(story.to_dict(), ensure_ascii=False))) == story
    data = story.to_dict()
    data["cast"].append({"name": "Ещё", "role": "teammate", "look": "a small owl in a red scarf"})
    with pytest.raises(StoryValidationError) as err:
        validate_story(data, "ru")
    assert "не больше трёх друзей" in str(err.value)


def test_every_friend_must_be_named_in_the_story_or_the_book_fails_hard():
    profile = team_profile()
    plan = planned(profile)
    data = author_dict(profile, seeds_for(profile))
    missing = plan.teammates[1].name
    for page in data["pages"]:
        page["text"] = page["text"].replace(f" Рядом {missing}.", "")
    story = assemble_story(profile, plan, data)
    found = [v for v in check_story(story, profile, plan) if v.code == "team"]
    assert len(found) == 1 and not found[0].soft and f"«{missing}»" in found[0].message and "участвует в сюжете" in found[0].message
    full = assemble_story(profile, plan, author_dict(profile, seeds_for(profile)))
    assert not [v for v in check_story(full, profile, plan) if v.code in ("team", "cast")]


def test_team_names_are_not_new_characters_and_only_strangers_are():
    profile = team_profile()
    plan = planned(profile)
    data = author_dict(profile, seeds_for(profile))
    data["pages"][2]["text"] += " Рядом Рекс и Мурка."
    story = assemble_story(profile, plan, data)
    cast = [v for v in check_story(story, profile, plan) if v.code == "cast"]
    assert cast and "Рекс" in cast[0].message and plan.teammates[0].name not in cast[0].message


def test_the_author_prompt_names_every_friend_with_forms_and_the_one_short_line_rule():
    profile = team_profile()
    plan = planned(profile)
    seeds = seeds_for(profile)
    user = build_user_prompt(profile, plan, seeds)
    assert "КОМАНДА из 4 друзей" in user and "каждого по имени хотя бы раз" in user and "не больше одной короткой реплики" in user
    for member in plan.team:
        assert f"- {member.name} ({member.kind})" in user
    assert team_text(make(), planned(make()), seeds_for(make())) == ""
    assert "Помощник — КОМАНДА" not in build_user_prompt(make(), planned(make()), seeds_for(make()))


def test_the_planner_prompt_asks_for_a_team_when_the_world_or_the_parent_wants_one():
    profile = team_profile(request="Хочу четырёх зверей-ниндзя", cartoons="Черепашки-ниндзя")
    seeds = seeds_for(profile)
    system, user = build_planner_prompts(profile, seeds)
    assert "КОМАНДА из 2–4 разных друзей" in system and "важнее правила «один помощник»" in system
    assert "участвует КАЖДЫЙ" in system and "не больше одной короткой реплики за книгу" in system
    assert "это КОМАНДА: помощник в этой книге — команда из 4 разных друзей" in system and "helper.team[].look" in system
    assert ", ".join(seeds.team_names) in user and "придумывать другие нельзя" in user
    assert '"team": [{"name": "лидер = helper.name"' in system and "в КАЖДОМ кадре напиши \"the helper team\"" in system
    plain_system, _ = build_planner_prompts(make(), seeds_for(make()))
    assert "это КОМАНДА: помощник в этой книге" not in plain_system


def test_image_prompts_draw_the_whole_team_next_to_the_hero_on_every_page_and_on_the_cover():
    profile = team_profile()
    plan = planned(profile)
    story = assemble_story(profile, plan, author_dict(profile, seeds_for(profile)))
    looks = [story.character("helper").look] + [c.look for c in story.characters("teammate")]
    for index in range(1, PAGES + 1):
        for has_refs in (False, True):
            page = prompts.build_page_prompt(story, profile, index, has_refs=has_refs)
            assert "The helper team always stays together near the hero, all 4 friends clearly visible" in page
            assert all(look[:40] in page for look in looks) and len(page) <= prompts.MAX_PROMPT
            assert "friends of the story's world" not in page                                  # друзья мира дублировали бы команду
    for photo in (False, True):
        for title in (False, True):
            cover = prompts.build_cover_prompt(story, profile, photo_ref=photo, title_in_image=title)
            assert "stand all 4 friends of the helper team" in cover and len(cover) <= prompts.MAX_PROMPT
            assert looks[0][:40] in cover and looks[1][:30] in cover
            assert prompts.LEGAL_CLAUSE in cover and cover.endswith(story.style_note.strip())


def test_a_long_team_description_never_pushes_out_the_layout_the_legal_rule_or_the_style():
    profile = team_profile()
    plan = planned(profile)
    story = assemble_story(profile, plan, author_dict(profile, seeds_for(profile)))
    data = story.to_dict()
    for entry in data["cast"]:
        if entry["role"] in ("helper", "teammate"):
            entry["look"] = ("a fluffy little animal in a very bright coat with a golden bell, " * 8)[:300].strip()
    for page in data["pages"]:
        page["scene"] = ("the hero runs across a sunny meadow with friends " * 30)[:700].strip()
    long = validate_story(data, "ru")
    for index in (1, 2):
        page = prompts.build_page_prompt(long, profile, index, has_refs=False)
        assert len(page) <= prompts.MAX_PROMPT and prompts.page_layout_clause(index, has_refs=False) in page
        assert prompts.LEGAL_CLAUSE in page and prompts.STYLE in page and "all 4 friends" in page


async def test_pipeline_with_a_team_puts_the_team_into_the_planner_the_author_and_every_image(tmp_path):
    import asyncio
    from app.bookgen import build_book
    from .conftest import ScriptedImage
    profile = team_profile(request="Хочу четырёх зверей-ниндзя")
    text, image = ScriptedPipeline(profile, polish=True), ScriptedImage()
    result = await build_book(profile, text, image, tmp_path / "order", image_sem=asyncio.Semaphore(3), mock=True)
    assert [c.role for c in result.story.cast].count("teammate") == 3
    assert "КОМАНДА из 4 друзей" in text.calls_of("author")[0]["messages"][0][1]
    pages = [c for c in image.calls if c["label"].startswith("Страница")]
    assert len(pages) == PAGES and all("all 4 friends clearly visible" in c["prompt"] for c in pages)
    cover = next(c for c in image.calls if c["label"] == "Обложка")
    assert "stand all 4 friends of the helper team" in cover["prompt"]


# ============================================================================ проверка понятности
def report(*problems, retell=True, summary="потеряли звёзды, нашли, рады") -> str:
    return dump({"retell": [f"Страница {i}: идут дальше." for i in range(1, 9)] if retell else [],
                 "problems": [{"page": p, "kind": k, "what": w} for p, k, w in problems], "summary": summary})


def test_comprehension_reply_is_parsed_into_problems_retell_and_summary():
    parsed = parse_comprehension(report((3, "object", "что за пластина?"), (5, "logic", "откуда взялась звезда")))
    assert not parsed.clear and len(parsed.retell) == 8 and parsed.summary.startswith("потеряли")
    assert [(p.page, p.kind, p.what) for p in parsed.problems] == [(3, "object", "что за пластина?"), (5, "logic", "откуда взялась звезда")]
    assert parse_comprehension(dump(CLEAR)).clear


def test_comprehension_parser_is_lenient_about_shape_but_not_about_garbage():
    parsed = parse_comprehension(dump({"problems": ["непонятно, где всё это происходит", {"page": 99, "what": "слово"},
                                                    {"page": "2", "kind": "странный", "what": "предмет"}, {"what": ""}, 5]}))
    assert [(p.page, p.kind) for p in parsed.problems] == [(None, "logic"), (None, "logic"), (2, "logic")]
    assert parse_comprehension("```json\n" + dump(CLEAR) + "\n```").clear
    assert parse_comprehension(dump({"title": "x"})).clear                                     # нет problems — проблем нет
    for bad in ("совсем не json", dump([1]), dump({"problems": "нет"})):
        with pytest.raises(StoryValidationError):
            parse_comprehension(bad)


def test_comprehension_prompt_is_a_five_year_old_listener_that_retells_and_lists_the_unclear():
    profile = make()
    story = assemble_story(profile, planned(profile), author_dict(profile, seeds_for(profile)))
    system, user = build_comprehension_prompts(profile, story)
    assert stage_of(system) == "comprehension"
    for phrase in ("глазами пятилетнего ребёнка", "Перескажи КАЖДУЮ страницу одной короткой фразой", "слова, которых он не знает",
                   "технические подробности", "скачки логики", "где происходит действие", "что было потеряно или нужно",
                   '"problems"', "ровно 8 фраз", "<draft>"):
        assert phrase in system, phrase
    assert "Страница 8:" in user and f"Название: {story.title}" in user and "hero_visual" not in user and "scene" not in user
    assert "{" not in system.replace("{\"retell\"", "").split("Верни только JSON")[0]


def test_rewrite_prompt_names_the_problems_and_leaves_the_rest_of_the_book_alone():
    profile = make()
    plan = planned(profile)
    story = assemble_story(profile, plan, author_dict(profile, seeds_for(profile)))
    parsed = parse_comprehension(report((3, "object", "что за шнурок?"), (None, "logic", "не ясно, зачем идут")))
    user = build_clarity_rewrite_prompt(profile, plan, seeds_for(profile), story, parsed.problems)
    assert "- стр. 3 (предмет): что за шнурок?" in user and "- вся книга (логика): не ясно, зачем идут" in user
    assert "Перепиши ТОЛЬКО страницы с проблемами" in user and "БЕЗ изменений" in user and story.pages[7].text in user
    assert "<plan>" in user and "<child>" in user


async def test_a_clear_book_costs_one_extra_call_and_is_not_rewritten():
    profile = make()
    provider = ScriptedPipeline(profile, polish=True)
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "editor"]
    assert [p.text for p in story.pages] == [p["text"] for p in author_dict(profile, provider.seeds)["pages"]]


def rewritten_author(profile, provider, suffix=" Ура!", page=3):
    data = author_dict(profile, provider.seeds)
    data["pages"][page - 1]["text"] += suffix
    return data


async def test_unclear_pages_are_rewritten_by_the_author_and_the_book_is_checked_again():
    profile = make()
    provider = ScriptedPipeline(profile, polish=True)
    fixed = rewritten_author(profile, provider)
    provider.replies["comprehension"] = [report((3, "object", "что за шнурок?")), dump(CLEAR)]
    provider.replies["author"] = [None, dump(fixed)]
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "author", "comprehension", "editor"]
    assert story.pages[2].text == fixed["pages"][2]["text"] and story.pages[2].text.endswith("Ура!")
    rewrite = provider.calls_of("author")[1]["messages"][0][1]
    assert "что за шнурок?" in rewrite and "Перепиши ТОЛЬКО страницы с проблемами" in rewrite
    editor_input = provider.calls_of("editor")[0]["messages"][0][1]
    assert fixed["pages"][2]["text"] in editor_input                                  # редактор получает уже переписанный текст


async def test_the_author_gets_at_most_two_rewrites_then_the_book_is_taken_as_it_is(caplog):
    import logging
    profile = make()
    provider = ScriptedPipeline(profile, polish=True)
    first = rewritten_author(profile, provider, " Ура!")
    second = json.loads(dump(first))
    second["pages"][3]["text"] += " Ого!"
    provider.replies["comprehension"] = [report((3, "logic", "непонятно, откуда это"))]            # проблемы остаются всегда
    provider.replies["author"] = [None, dump(first), dump(second)]
    with caplog.at_level(logging.WARNING):
        story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "author", "comprehension", "author", "comprehension", "editor"]
    assert provider.stages.count("author") == 3 and provider.clarity_rewrites == 2
    assert story.pages[3].text.endswith("Ого!") and story.pages[2].text.endswith("Ура!")             # приняты обе правки
    assert any("оставлена с замечаниями понятности" in r.getMessage() for r in caplog.records)


async def test_a_rewrite_with_a_hard_violation_is_retried_with_the_exact_error_and_never_accepted_broken():
    profile = make()
    provider = ScriptedPipeline(profile, polish=True)
    broken = author_dict(profile, provider.seeds)
    broken["pages"][2]["text"] = "Навстречу вышел Человек-паук и показал мостик у ручья, а потом ушёл."
    good = rewritten_author(profile, provider)
    provider.replies["comprehension"] = [report((3, "object", "что это?")), dump(CLEAR)]
    provider.replies["author"] = [None, dump(broken), dump(good)]
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "author", "author", "comprehension", "editor"]
    retry = provider.calls_of("author")[2]["messages"][-1][1]
    assert "Твой ответ не прошёл проверку" in retry and "бренд" in retry
    assert story.pages[2].text == good["pages"][2]["text"] and "паук" not in " ".join(p.text for p in story.pages).lower()


async def test_when_the_rewrite_keeps_failing_the_old_text_stays_and_the_order_does_not_fail():
    profile = make()
    provider = ScriptedPipeline(profile, polish=True)
    provider.replies["comprehension"] = [report((3, "object", "что это?"))]
    provider.replies["author"] = [None, "не json"]
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "author", "author", "author", "editor"]    # три попытки и дальше
    assert [p.text for p in story.pages] == [p["text"] for p in author_dict(profile, provider.seeds)["pages"]]


@pytest.mark.parametrize("bad", ["совсем не json", dump({"problems": "нет"}), "[]"])
async def test_a_broken_comprehension_reply_is_skipped_and_the_pipeline_goes_on(bad):
    profile = make()
    provider = ScriptedPipeline(profile, {"comprehension": [bad]}, polish=True)
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "editor"] and len(story.pages) == PAGES


async def test_a_provider_error_in_the_comprehension_step_does_not_fail_the_book():
    profile = make()

    class Flaky(ScriptedPipeline):
        async def _complete(self, system, messages, model=None):
            if stage_of(system) == "comprehension":
                self.calls.append({"stage": "comprehension", "system": system, "messages": list(messages), "model": model})
                raise ProviderError("сбой сети")
            return await super()._complete(system, messages, model)

    provider = Flaky(profile, polish=True)
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "editor"] and len(story.pages) == PAGES


async def test_the_comprehension_step_also_runs_for_a_kyrgyz_book_before_the_editor_and_the_proofreader():
    profile = make(language="ky", name="Тимур")
    provider = ScriptedPipeline(profile, polish=True)
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "editor", "proof"] and len(story.pages) == PAGES
    assert "кыргызском языке" in provider.calls_of("comprehension")[0]["system"]


async def test_the_mock_provider_does_no_extra_calls():
    from app.providers.text_mock import MockTextProvider
    provider = MockTextProvider()
    assert provider.polish is False
    story = await provider.generate_story(make())
    assert len(story.pages) == PAGES and not check_story(story, make())


# ============================================================================ смысл книги: meaning, retell, moral из поступка
def test_plan_needs_a_meaning_and_a_retell_in_one_short_phrase_each():
    profile = make()
    assert "meaning" in rejected(profile, lambda p: p.pop("meaning"))
    assert "retell" in rejected(profile, lambda p: p.pop("retell"))
    message = rejected(profile, lambda p: p.update(meaning="Помогать тому, кто в беде, всегда нужно, потому что вместе легче всё на свете и везде."))
    assert "meaning из 16 слов" in message and "не больше 14" in message and "вытекает из того, что сделал герой" in message
    long_retell = " ".join(["слово"] * 31)
    assert "retell из 31 слово" in rejected(profile, lambda p: p.update(retell=long_retell)) and "одна фраза" in rejected(
        profile, lambda p: p.update(retell=long_retell))
    plan = planned(profile)
    assert plan.meaning.startswith("Вместе с другом") and plan.retell.startswith("Ребёнок несёт")
    assert validate_plan(plan.to_dict(), profile, seeds_for(profile)) == plan


def test_the_author_sees_meaning_and_retell_and_is_told_the_moral_follows_from_the_deed():
    from app.writer_prompts import build_system_prompt
    profile = make()
    plan = planned(profile)
    block = json.loads(build_user_prompt(profile, plan, seeds_for(profile)).split("<plan>")[1].split("</plan>")[0])
    assert block["meaning"] == plan.meaning and block["retell"] == plan.retell
    system = build_system_prompt(profile)
    assert "ОДНА короткая фраза, которая вытекает из того, что герой сделал" in system and "а не отдельная «мудрость»" in system
    assert "вытекает из поступка героя" in system.split("Схема JSON")[1]


def test_the_planner_is_asked_for_meaning_retell_calm_adults_and_a_visible_family_member():
    profile = make()
    system, _ = build_planner_prompts(profile, seeds_for(profile))
    for phrase in ("запиши в meaning ОДНУ простую мысль", "ВЫТЕКАЕТ из того, что герой СДЕЛАЛ", "В retell перескажи весь сюжет одной фразой",
                   "Никакой бессмыслицы", "Взрослые и родные (мама, бабушка) спокойные и добрые", "не боятся, не застревают, не сидят в грязи",
                   "пропавший находится и ВИДЕН", "опиши его в поле family", "meaning до 14 слов; retell до 30 слов",
                   '"meaning":', '"retell":', '"family":', "в двух последних кадрах напиши его слово"):
        assert phrase in system, phrase


# ============================================================================ эталон тона и ясности
def test_the_reference_story_is_in_the_author_prompt_for_russian_books_only():
    from app.writer_prompts import build_system_prompt, reference_text
    ref = D.REFERENCE
    assert ref.title == "Артём и малыш Шлёп" and len(ref.pages) == PAGES and ref.refrain == ""
    assert ref.pages[0].startswith("Артём гулял по долине динозавров. Вдруг он услышал: «Ой-ой-ой!»")
    assert "Эхо ответило: «Ма-ма-ма!»" in ref.pages[2] and "Шлёп прыгнул, ХЛЮП!" in ref.pages[3] and "Вместе мы сможем!" in ref.pages[4]
    assert ref.pages[5].endswith("— Мама! — закричал Шлёп.") and ref.pages[7].endswith("Шлёп смеялся громче всех.")
    assert ref.moral == "Помогать тому, кто в беде, — лучшее приключение."
    system = build_system_prompt(make(age=7))
    assert "Эталон ТОНА и ЯСНОСТИ (книга «Артём и малыш Шлёп», 7 лет)" in system and ref.pages[1] in system
    assert "moral (вытекает из поступка героя): Помогать тому, кто в беде" in system and "НЕ копируй слова, сюжет и имена" in system
    assert system.index("Эталон ТОНА") > system.index("Как писать") and system.index("Эталон ТОНА") < system.index("Образцы ФОРМЫ")
    ky = make(language="ky", name="Тимур")
    assert reference_text(ky) == "" and "Эталон ТОНА" not in build_system_prompt(ky) and D.REFERENCE_KY is None
    assert reference_text(make()).count("\n") == PAGES + 1


def test_the_reference_pages_have_no_technical_words_and_no_repeats_so_it_is_a_good_model():
    for page in D.REFERENCE.pages:
        assert not tech_hits(page)
    profile = make(name="Артём")
    story = story_from_pages(profile, list(D.REFERENCE.pages))
    found = [v for v in check_story(story, profile) if v.code in ("repeat", "tech", "ban_phrase", "brand")]
    assert not found, [str(v) for v in found]


def story_from_pages(profile: Profile, texts: list[str]):
    data = build_mock_story(profile)
    for page, text in zip(data["pages"], texts):
        page["text"] = text
    return validate_story(data, profile.language)


def test_copying_the_reference_or_taking_its_names_is_caught():
    profile = make()
    plan = planned(profile)
    data = author_dict(profile, seeds_for(profile))
    data["pages"][3]["text"] = "На реке не было моста, только скользкие камни. Тут появился Шлёп, ХЛЮП! Оба засмеялись."
    story = assemble_story(profile, plan, data)
    echoes = [v.message for v in check_story(story, profile, plan) if v.code == "echo"]
    assert any("«шлеп» взято из примера" in m or "шлёп" in m.lower() for m in echoes) or any("списана" in m for m in echoes)
    data["pages"][5]["text"] = "На самой вершине стояла огромная тень. Это была мама! Оба замерли у тропы."
    echoes = [v.message for v in check_story(assemble_story(profile, plan, data), profile, plan) if v.code == "echo"]
    assert any("списана с примера" in m for m in echoes)
    artem = make(name="Артём")                                                            # имя ребёнка из эталона не штрафуется
    own = assemble_story(artem, planned(artem), author_dict(artem, seeds_for(artem)))
    assert not [v for v in check_story(own, artem, planned(artem)) if v.code == "echo"]


# ============================================================================ запрет повторов и странных фраз
def repeated(profile: Profile, word_forms: list[str], pages=(1, 2, 3, 4, 5, 6)):
    plan = planned(profile)
    data = author_dict(profile, seeds_for(profile))
    for page, form in zip(pages, word_forms):
        data["pages"][page - 1]["text"] += f" Там {form}."
    return [v for v in check_story(assemble_story(profile, plan, data), profile, plan) if v.code == "repeat" and "встречается" in v.message]


def test_the_same_rare_word_more_than_three_times_in_a_book_is_reported_with_its_pages():
    assert D.RARE_WORD_MAX == 3
    found = repeated(make(age=8), ["глина", "глину", "глиной", "глины", "глина", "глину"])
    assert len(found) == 1 and found[0].soft and found[0].page is None
    assert "«глина»" in found[0].message and "6 раз" in found[0].message and "страницах 1, 2, 3, 4, 5, 6" in found[0].message
    assert "не больше 2 раз за книгу" in found[0].message and "он/она/это" in found[0].message


def test_three_times_is_still_fine_and_endings_of_the_word_count_as_one_word():
    assert not repeated(make(age=8), ["глина", "глину", "глиной"])
    assert repeated(make(age=8), ["глина", "глину", "глиной", "глине"])


def test_names_refrain_sounds_and_common_story_words_may_repeat():
    profile = make(age=8)
    plan = planned(profile)
    data = author_dict(profile, seeds_for(profile))
    for i in range(6):
        data["pages"][i]["text"] += f" Вместе {plan.helper_name} сказал: топ-топ, хлюп-хлюп, потом снова вместе."
    found = [v for v in check_story(assemble_story(profile, plan, data), profile, plan) if "встречается" in v.message]
    assert not found, [str(v) for v in found]


def test_the_mock_book_and_the_examples_obey_the_repeat_rule_at_every_age_and_place():
    from app import options
    for place in options.PLACES:
        for age in (4, 6, 8):
            profile = make(place=place, age=age, place_custom="во дворе" if place == "custom" else "")
            found = [v for v in check_story(validate_story(build_mock_story(profile), "ru"), profile) if "встречается" in v.message]
            assert not found, (place, age, [str(v) for v in found])


@pytest.mark.parametrize("text", [
    "Мама боится шагнуть на глину и сидит на месте.", "Он согрел ладонь боком и улыбнулся.", "Динозавр поднял ногу для первого шага и замер.",
    "Бабушка боялась шагнуть в воду.", "Шлёп не решался шагнуть дальше.",
])
def test_strange_body_phrases_and_an_adult_who_is_afraid_to_step_are_banned(text):
    profile = make(age=8)
    plan = planned(profile)
    data = author_dict(profile, seeds_for(profile))
    data["pages"][3]["text"] = text + " Ура!"
    codes = [(v.code, v.message) for v in check_story(assemble_story(profile, plan, data), profile, plan)]
    assert any(code == "ban_phrase" for code, _ in codes), codes


def test_the_author_prompt_says_the_same_word_twice_at_most_and_no_strange_body_phrases():
    from app.writer_prompts import build_system_prompt
    system = build_system_prompt(make())
    for phrase in ("Сюжет без бессмыслицы", "«согрел ладонь боком»", "«поднял ногу для первого шага»", "«боится шагнуть»",
                   "не больше 2 раз за книгу, кроме имён и рефрена", "Взрослые и родные (мама, папа, бабушка) спокойные и добрые",
                   "не боятся, не застревают, не сидят в грязи"):
        assert phrase in system, phrase


# ============================================================================ взрослый или родной в сюжете (family)
MAMA = {"role": "mother", "kind": "мама-динозавр", "look": "a calm kind green dinosaur mother with gentle eyes and a yellow scarf"}


def add_family(plan):
    plan["family"] = dict(MAMA)
    for index in (6, 7):
        plan["image_brief"][index] += " The mother stands beside the hero."


def test_a_plan_with_a_family_member_keeps_role_kind_and_look():
    profile = make()
    plan = planned(profile, add_family)
    assert plan.family.role == "mother" and plan.family.kind == "мама-динозавр" and plan.family.look.startswith("a calm kind")
    assert validate_plan(plan.to_dict(), profile, seeds_for(profile)) == plan
    assert plan.for_author()["family"] == {"role": "mother", "kind": "мама-динозавр"}                # автору внешность не нужна
    assert planned(profile).family is None and "family" not in planned(profile).to_dict()


@pytest.mark.parametrize("mutate, fragment", [
    (lambda p: p["family"].update(role="aunt"), "family.role"),
    (lambda p: p["family"].update(look="добрая мама-динозавр в жёлтом шарфе"), "по-английски"),
    (lambda p: p["family"].pop("kind"), "family.kind"),
    (lambda p: p.update(family="мама"), "объектом"),
    (lambda p: p["family"].update(look="a mother that looks like a Peppa Pig character in red"), "известные персонажи"),
])
def test_bad_family_entries_are_rejected(mutate, fragment):
    def both(plan):
        add_family(plan)
        mutate(plan)
    assert fragment in rejected(make(), both)


def test_the_family_member_must_be_visible_on_the_last_two_frames():
    def hidden(plan):
        plan["family"] = dict(MAMA)
        plan["image_brief"][7] += " The mother stands beside the hero."
    message = rejected(make(), hidden)
    assert "image_brief[7]" in message and "ВИДЕТЬ" in message and "the mother" in message
    assert planned(make(), add_family)


def test_family_words_are_not_a_place_so_two_final_frames_with_mama_pass_the_place_check():
    assert brief_places("The hero hugs the mother in a sunny valley beside the mother.") == {"valley"}
    assert planned(make(), add_family)


def test_the_cast_gets_the_family_member_and_page_prompts_draw_her_when_the_scene_names_her():
    profile = make()
    plan = planned(profile, add_family)
    story = assemble_story(profile, plan, author_dict(profile, seeds_for(profile)))
    assert [c.role for c in story.cast] == ["hero", "helper", "family", "obstacle"]
    assert story.character("family").name == "мама-динозавр" and story.character("family").look == MAMA["look"]
    assert Story.from_dict(json.loads(json.dumps(story.to_dict(), ensure_ascii=False))) == story
    last = prompts.build_page_prompt(story, profile, PAGES, has_refs=True)
    assert "The family member, a calm and kind adult, clearly visible" in last and MAMA["look"][:40] in last
    assert len(last) <= prompts.MAX_PROMPT and prompts.LEGAL_CLAUSE in last
    assert "family member" not in prompts.build_page_prompt(story, profile, 2, has_refs=True)        # в начале книги её нет
    data = story.to_dict()
    data["cast"].append(dict(data["cast"][2]))
    with pytest.raises(StoryValidationError) as err:
        validate_story(data, "ru")
    assert "одного взрослого (family)" in str(err.value)


# ============================================================================ понятность: смысл и бессмыслица
def test_comprehension_reply_carries_the_meaning_and_nonsense_becomes_problems():
    parsed = parse_comprehension(dump({"retell": [], "meaning": "помогать тому, кто в беде", "problems": [
        {"page": 2, "kind": "sense", "what": "мама боится шагнуть"}], "nonsense": [{"page": 4, "what": "мокрая глина без причины"},
                                                                                "согрел ладонь боком", {"page": 99, "what": "странно"}]}))
    assert parsed.meaning == "помогать тому, кто в беде" and not parsed.clear
    assert [(p.page, p.kind) for p in parsed.problems] == [(2, "sense"), (4, "sense"), (None, "sense"), (None, "sense")]
    assert parse_comprehension(dump(CLEAR)).meaning == ""


def test_comprehension_prompt_asks_for_the_meaning_and_for_events_without_sense_and_shows_the_plan_intent():
    profile = make()
    plan = planned(profile)
    story = assemble_story(profile, plan, author_dict(profile, seeds_for(profile)))
    system, user = build_comprehension_prompts(profile, story, plan)
    for phrase in ("В чём смысл книги одной фразой", "Вытекает ли этот смысл и строка moral из того, что герой сделал",
                   "события, не имеющие смысла", "«боится шагнуть»", "предмет (глина, лента) без объяснения", "«согрел ладонь боком»", 'kind="sense"',
                   '"meaning": "смысл книги одной фразой"', "word|object|logic|place|sense"):
        assert phrase in system, phrase
    assert f"сюжет «{plan.logline}», смысл «{plan.meaning}»" in user and f"moral: {story.moral}" in user
    assert "Замысел режиссёра" not in build_comprehension_prompts(profile, story)[1]


async def test_a_book_without_sense_is_rewritten_including_a_moral_that_does_not_follow():
    profile = make()
    provider = ScriptedPipeline(profile, polish=True)
    fixed = rewritten_author(profile, provider)
    fixed["moral"] = "Помогать другу — лучшее приключение."
    provider.replies["comprehension"] = [dump({"retell": [], "meaning": "неясно", "problems": [
        {"page": None, "kind": "sense", "what": "moral не вытекает из сюжета"},
        {"page": 4, "kind": "sense", "what": "кто-то боится шагнуть: бессмыслица"}]}), dump(CLEAR)]
    provider.replies["author"] = [None, dump(fixed)]
    story = await provider.generate_story(profile)
    assert provider.stages == ["planner", "author", "comprehension", "author", "comprehension", "editor"]
    rewrite = provider.calls_of("author")[1]["messages"][0][1]
    assert "- вся книга (смысл): moral не вытекает из сюжета" in rewrite and "- стр. 4 (смысл): кто-то боится шагнуть" in rewrite
    assert "перепиши moral одной короткой фразой" in rewrite and "иначе moral не трогай" in rewrite
    assert story.moral == "Помогать другу — лучшее приключение."
    first_check = provider.calls_of("comprehension")[0]["messages"][0][1]
    assert f"смысл «{provider.calls_of('planner') and json.loads(dump(plan_dict(profile, provider.seeds)))['meaning']}»" in first_check
