"""Миры книги («как в любимом мультфильме», но без чужих героев) и поле cartoons: список миров, анкета, API, зёрна, промты
режиссёра, «библия героев» для картинок, список чужих брендов.

Сеть не нужна: модель текста и картинок поддельные."""
import asyncio
import json
import random
import time

import pytest

from app import options, prompts
from app import writer_data as D
from app.errors import ValidationError
from app.profile import CARTOONS_MAX, Profile
from app.providers.text_mock import MockTextProvider
from app.story import PAGES, Story, validate_story
from app.writer import assemble_story, brand_hits, check_story, pick_seeds, validate_plan
from app.writer_prompts import build_planner_prompts, build_system_prompt, build_user_prompt, world_text

from .conftest import SAMPLE, legacy_profile, ScriptedImage, tma
from .writer_helpers import ScriptedPipeline, author_dict, plan_dict, seeds_for

WORLD_IDS = ["football", "dino_friend", "princess", "space_crew", "hero_agile", "rescue_team", "unicorns", "race_cars",
             "dragon_friend", "mermaid", "hero_team", "blocks", "ice_kingdom", "wizard_school", "animal_city", "long_braid",
             "star_singers", "fast_pals", "jump_land", "blue_tractor", "forest_house", "workshop_helpers", "ninja_animals",
             "mountain_friends"]


def make(**extra) -> Profile:
    return legacy_profile(extra)


def book(profile: Profile):
    seeds = seeds_for(profile)
    plan = validate_plan(plan_dict(profile, seeds), profile, seeds)
    return plan, assemble_story(profile, plan, author_dict(profile, seeds))


# ----------------------------------------------------------------------------- список миров
def test_worlds_are_the_agreed_catalog_of_24_in_the_agreed_order():
    assert list(options.WORLDS) == WORLD_IDS and len(WORLD_IDS) == 24 and "custom" not in options.WORLDS
    assert options.WORLDS["forest_house"]["label"] == "Лесной дом"
    assert "медведь" in options.WORLDS["forest_house"]["hint"] and "проказница" in options.WORLDS["forest_house"]["hint"]
    assert options.WORLDS["football"]["label"] == "Футбол" and options.WORLDS["princess"]["label"] == "В стиле принцессы"
    assert all(v["label"] and v["hint"] and v["emoji"] for v in options.WORLDS.values())
    assert len({v["label"] for v in options.WORLDS.values()}) == 24


def test_every_theme_rests_on_an_original_archetype_and_none_shares_one():
    ids = {a.id for a in D.ARCHETYPES}
    for world_id, world in options.WORLDS.items():
        assert world["archetype_key"] in ids, world_id
        assert D.archetype_for_world(world_id).id == world["archetype_key"] or D.archetype_for_world(world_id) is None
    used = [w["archetype_key"] for w in options.WORLDS.values()]
    assert len(used) == len(set(used)) == 24                                 # у каждой темы свой архетип


def test_catalog_has_no_foreign_brand_names():
    banned = ("minecraft", "frozen", "холодное сердце", "человек-паук", "spider", "гарри", "поттер", "хогвартс", "mario", "марио",
              "мстител", "маквин", "дисней", "disney", "k-pop", "эльза", "ёжик соник", "sonic", "pixar")
    for world_id, world in options.WORLDS.items():
        text = f"{world['label']} {world['hint']}".lower()
        assert not any(b in text for b in banned), world_id
        assert not brand_hits(text), world_id


def test_new_archetypes_for_the_kingdom_and_the_builders_are_original_looks():
    kingdom, builders = D.archetype_by_id("kingdom"), D.archetype_by_id("builders")
    assert kingdom.magic is True and not builders.magic
    for archetype in (kingdom, builders):
        assert archetype.function and archetype.avoid and len(archetype.look.split()) >= 12
        assert not brand_hits(archetype.look) and not brand_hits(archetype.function) and archetype.look.isascii()


def test_archetype_looks_never_name_a_brand():
    for archetype in D.ARCHETYPES:
        assert not brand_hits(archetype.look), archetype.id
        assert not brand_hits(archetype.function), archetype.id


def test_islamic_mode_drops_the_magic_archetype_of_a_world_but_not_the_rest():
    for magic in ("princess", "unicorns", "wizard_school", "mermaid", "ice_kingdom", "dragon_friend", "long_braid"):
        assert D.archetype_for_world(magic, islamic=True) is None and D.archetype_for_world(magic).magic, magic
    assert D.archetype_for_world("princess", islamic=False).id == "kingdom"
    assert D.archetype_for_world("football", islamic=True).id == "football"
    assert D.archetype_for_world("forest_house", islamic=True).id == "honey"
    assert D.archetype_for_world(None) is None and D.archetype_for_world("nonsense") is None


def test_public_options_expose_worlds_without_the_internal_archetype_key():
    data = options.public_options()
    assert [w["id"] for w in data["worlds"]] == WORLD_IDS
    assert all(set(w) == {"id", "label", "hint", "emoji"} for w in data["worlds"])
    json.dumps(data, ensure_ascii=False)


# ----------------------------------------------------------------------------- анкета: world и cartoons
def test_world_is_required_for_new_orders_and_old_stored_orders_without_it_still_read():
    assert make().world is None and make().cartoons == ""                   # make() — профиль «как раньше», без мира
    for empty in (None, ""):
        with pytest.raises(ValidationError) as err:
            Profile.from_payload({**SAMPLE, "world": empty})
        assert err.value.field == "world"
    old = Profile.from_dict({k: v for k, v in Profile.from_payload(SAMPLE).to_dict().items() if k != "world"})
    assert old.world is None and old.for_model().get("world_label") is None


def test_legacy_world_ids_of_old_orders_are_read_as_the_new_ones():
    for old, new in (("kingdom", "princess"), ("builders", "blue_tractor"), ("caped_hero", "hero_agile")):
        data = {**Profile.from_payload(SAMPLE).to_dict(), "world": old}
        assert Profile.from_dict(data).world == new and Profile.from_dict(data).world_label
        with pytest.raises(ValidationError):
            Profile.from_payload({**SAMPLE, "world": old})                  # новая анкета старые id не берёт


@pytest.mark.parametrize("world", WORLD_IDS)
def test_every_listed_world_is_accepted(world):
    profile = legacy_profile({"world": world})
    assert profile.world == world and profile.world_label == options.WORLDS[world]["label"]


@pytest.mark.parametrize("bad", ["tardis", "FOREST_HOUSE", " forest_house", 5, False, ["forest_house"], {"id": "kingdom"}, "custom"])
def test_unknown_world_is_rejected_with_the_world_field(bad):
    with pytest.raises(ValidationError) as err:
        Profile.from_payload({**SAMPLE, "world": bad})
    assert err.value.field == "world" and "тему" in err.value.message.lower()


def test_cartoons_are_cleaned_like_the_other_free_texts_and_limited_to_120_characters():
    assert CARTOONS_MAX == 120
    cleaned = make(cartoons="  Маша\u0000 и <b>Медведь</b>‮   и \n\n Фиксики  ").cartoons
    assert "<" not in cleaned and ">" not in cleaned and "\x00" not in cleaned and "‮" not in cleaned and "\n" not in cleaned
    assert cleaned == "Маша и bМедведь/b и Фиксики"
    assert len(make(cartoons="я" * 120).cartoons) == 120
    with pytest.raises(ValidationError) as err:
        make(cartoons="я" * 121)
    assert err.value.field == "cartoons" and "120" in err.value.message
    assert make(cartoons=None).cartoons == "" and make(cartoons=123).cartoons == "123"


def test_writer_sees_the_world_the_archetype_and_the_cartoons_as_inspiration_only():
    child = make(world="forest_house", cartoons="Маша и Медведь, Лунтик").for_model()
    assert child["world_label"] == "Лесной дом" and child["world_hint"] == options.WORLDS["forest_house"]["hint"]
    assert child["archetype"] == D.archetype_by_id("honey").title
    assert child["cartoons"] == "Маша и Медведь, Лунтик"
    assert "ТОЛЬКО ВДОХНОВЕНИЕ" in child["cartoons_note"] and "НЕ имена" in child["cartoons_note"]
    user = build_user_prompt(make(world="forest_house", cartoons="Фиксики"))
    block = json.loads(user.split("<child>")[1].split("</child>")[0])
    assert block["world_label"] == "Лесной дом" and block["cartoons"] == "Фиксики" and block["archetype"] == "Дядя Мёд"


def test_a_book_without_a_world_or_cartoons_keeps_the_old_child_block():
    child = make().for_model()
    assert not {"world_label", "world_hint", "archetype", "cartoons", "cartoons_note"} & set(child)


def test_a_magic_world_loses_its_archetype_in_islamic_mode():
    assert "archetype" not in make(world="princess", islamic=True).for_model()
    assert make(world="princess").for_model()["archetype"] == D.archetype_by_id("kingdom").title


def test_profile_roundtrip_and_scrubbing_keep_the_world_but_erase_the_cartoons():
    profile = make(world="blue_tractor", cartoons="Фиксики и Лунтик")
    again = Profile.from_dict(json.loads(json.dumps(profile.to_dict(), ensure_ascii=False)))
    assert (again.world, again.cartoons) == ("blue_tractor", "Фиксики и Лунтик")
    scrubbed = profile.scrubbed()
    assert scrubbed["cartoons"] == "" and scrubbed["world"] == "blue_tractor" and "Лунтик" not in json.dumps(scrubbed, ensure_ascii=False)
    old = profile.to_dict()
    old.pop("world"), old.pop("cartoons")
    restored = Profile.from_dict(old)
    assert restored.world is None and restored.cartoons == ""


# ----------------------------------------------------------------------------- API
async def test_config_lists_the_worlds_and_the_cartoons_limit(env):
    data = await (await env.client.get("/api/config", headers=tma())).json()
    worlds = data["options"]["worlds"]
    assert [w["id"] for w in worlds] == WORLD_IDS and set(worlds[0]) == {"id", "label", "hint", "emoji"}
    assert worlds[0] == {"id": "football", "label": "Футбол", "hint": options.WORLDS["football"]["hint"], "emoji": "⚽"}
    assert data["limits"]["cartoons_max"] == 120 and data["limits"]["favorites_max"] == 120


async def test_order_api_accepts_world_and_cartoons_and_cleanup_erases_only_the_cartoons(env):
    payload = {**SAMPLE, "world": "rescue_team", "cartoons": "Щенячий патруль"}
    order_id = await env.create(payload)
    stored = json.loads(env.db.get_order(order_id)["profile_json"])
    assert stored["world"] == "rescue_team" and stored["cartoons"] == "Щенячий патруль"
    await env.wait_done(order_id)
    env.db._exec("UPDATE orders SET created_at=? WHERE id=?", (time.time() - 8 * 86400, order_id))
    assert env.service.cleanup() == 1
    after = json.loads(env.db.get_order(order_id)["profile_json"])
    assert after["cartoons"] == "" and after["world"] == "rescue_team" and after["name"] == ""


@pytest.mark.parametrize("extra, field", [({"world": "tardis"}, "world"), ({"world": 7}, "world"),
                                          ({"world": ["kingdom"]}, "world"), ({"world": None}, "world"), ({"world": "custom"}, "world"), ({"cartoons": "я" * 121}, "cartoons")])
async def test_order_api_rejects_a_bad_world_and_too_long_cartoons(env, extra, field):
    resp = await env.client.post("/api/orders", json={**SAMPLE, **extra}, headers=tma())
    data = await resp.json()
    assert resp.status == 400 and data["field"] == field, data
    assert (await env.client.post("/api/orders", json={**SAMPLE, "world": "football", "cartoons": ""}, headers=tma())).status == 201


async def test_a_client_without_a_theme_gets_a_clear_error_on_the_world_field(env):
    resp = await env.client.post("/api/orders", json={k: v for k, v in SAMPLE.items() if k != "world"}, headers=tma())
    data = await resp.json()
    assert resp.status == 400 and data["field"] == "world" and "тему" in data["error"].lower() if "error" in data else data["field"] == "world"
    order_id = await env.create(SAMPLE)
    stored = json.loads(env.db.get_order(order_id)["profile_json"])
    assert stored["world"] == "football" and stored["cartoons"] == ""


# ----------------------------------------------------------------------------- зёрна: помощник и место из мира
@pytest.mark.parametrize("world", list(D.WORLD_HELPERS))
def test_the_helper_and_the_setting_come_from_the_chosen_world(world):
    profile = make(world=world)
    allowed = set(D.WORLD_HELPERS[world])
    assert allowed <= {t.id for t in D.HELPER_TYPES}
    for i in range(40):
        seeds = pick_seeds(profile, random.Random(i))
        assert seeds.helper_type.id in allowed, (world, seeds.helper_type.id)
        assert seeds.setting in D.SETTINGS_BY_WORLD[world]
        assert seeds.helper_name.gender in (seeds.helper_type.gender, "n") and seeds.palette in D.PALETTES


def test_a_topic_with_its_own_settings_beats_the_world_setting_and_a_world_without_helpers_uses_the_usual_pool():
    space = make(world="forest_house", topic="space")
    assert all(pick_seeds(space, random.Random(i)).setting in D.SETTINGS_BY_TOPIC["space"] for i in range(20))
    plain = make(world="football")
    types = {pick_seeds(plain, random.Random(i)).helper_type.id for i in range(120)}
    assert len(types) >= 8 and not types & {"excavator", "little_train", "tinker", "rescue_hare"}


def test_world_only_helpers_never_appear_in_books_without_that_world():
    only = {t.id for t in D.HELPER_TYPES if t.world_only}
    assert only == {"rescue_hare", "tinker", "excavator", "little_train"}
    for profile in (make(), make(topic="space"), make(world="forest_house"), make(world="princess")):
        assert not only & {pick_seeds(profile, random.Random(i)).helper_type.id for i in range(150)}


def test_a_magic_world_gets_a_plain_helper_in_islamic_mode():
    islamic = make(world="princess", islamic=True)
    assert {pick_seeds(islamic, random.Random(i)).helper_type.id for i in range(80)} == {"kitten"}
    assert "dragon" in {pick_seeds(make(world="princess"), random.Random(i)).helper_type.id for i in range(80)}


def test_palette_follows_the_topic_often_and_all_five_palettes_are_used():
    assert [p.id for p in D.PALETTES] == ["sunset_gold", "rainbow_sky", "neon_night", "aqua_sea", "forest_emerald"]
    sea = [pick_seeds(make(topic="sea", place="underwater"), random.Random(i)).palette.id for i in range(100)]
    assert sea.count("aqua_sea") >= 50
    assert {pick_seeds(make(), random.Random(i)).palette.id for i in range(100)} == {p.id for p in D.PALETTES}
    assert all(p.en.isascii() and len(p.en) <= prompts.NOTE_MAX for p in D.PALETTES)


# ----------------------------------------------------------------------------- режиссёр
def test_planner_gets_the_archetype_block_of_the_world_and_the_cartoons_rule():
    profile = make(world="forest_house", cartoons="Маша и Медведь")
    system, user = build_planner_prompts(profile, seeds_for(profile))
    honey = D.archetype_by_id("honey")
    assert "Мир книги выбран родителями: «Лесной дом»" in system
    assert honey.title in system and honey.look in system and honey.function in system
    assert "Родители назвали любимые мультфильмы" in system and "ТОЛЬКО вдохновение" in system
    assert "роль, настроение и функцию" in system and "НИКОГДА имена, одежду, цвета и внешность" in system
    child = json.loads(user.split("<child>")[1].split("</child>")[0])
    assert child["world_label"] == "Лесной дом" and child["cartoons"] == "Маша и Медведь" and child["archetype"] == "Дядя Мёд"
    assert "ЗАПРЕЩЕНЫ" in system and "НИКОГДА не пиши его имя" in system and "называет такой мультфильм" in system


def test_planner_without_a_world_or_cartoons_has_neither_block():
    profile = make()
    system, _ = build_planner_prompts(profile, seeds_for(profile))
    assert "Мир книги выбран родителями" not in system and "Родители назвали любимые мультфильмы" not in system
    assert world_text(profile) == ""


def test_planner_text_for_a_magic_world_in_islamic_mode():
    islamic = make(world="princess", islamic=True)
    text = world_text(islamic)
    assert "без магии, драконов и фей" in text and D.archetype_by_id("kingdom").title not in text
    system, _ = build_planner_prompts(islamic, seeds_for(islamic))
    assert "Королевство сказочных башен" not in system.split("Оригинальные архетипы")[1].split("Мир книги выбран")[0]


def test_planner_prefers_a_cheerful_goal_a_joyful_tone_counting_and_one_palette():
    profile = make()
    seeds = seeds_for(profile)
    system, user = build_planner_prompts(profile, seeds)
    assert "Цель светлая и весёлая" in system and "пропали звёзды" in system and "вернуть миру цвет, свет или звук" in system
    assert "Тон радостный, игровой, тёплый" in system and "первая… вторая… третья…" in system
    for palette in D.PALETTES:
        assert palette.ru in system and palette.en in system
    assert f"палитра по умолчанию: {seeds.palette.ru}" in user
    assert "ОДНА палитра из списка ниже" in system and "Лица весёлые" in system


def test_planner_prompt_lists_all_archetypes():
    profile = make()
    system, _ = build_planner_prompts(profile, seeds_for(profile))
    assert all(a.title in system for a in D.ARCHETYPES) and len(D.ARCHETYPES) == 26


# ----------------------------------------------------------------------------- «библия героев» и картинки
def test_the_story_cast_gets_the_worlds_look_in_english_only_when_a_world_is_chosen():
    _, plain = book(make())
    assert [c.role for c in plain.cast] == ["hero", "helper", "obstacle"]
    plan, story = book(make(world="forest_house"))
    world = story.character("world")
    assert [c.role for c in story.cast] == ["hero", "helper", "obstacle", "world"]
    assert world.look == D.archetype_by_id("honey").look and world.name == "Лесной дом"
    assert Story.from_dict(json.loads(json.dumps(story.to_dict(), ensure_ascii=False))) == story


def test_no_world_and_islamic_magic_world_add_no_world_entry_to_the_cast():
    _, plain = book(make())
    assert plain.character("world") is None and len(plain.cast) == 3
    _, islamic = book(make(world="princess", islamic=True))               # королевство — команда: друзья в cast есть, магического мира нет
    assert islamic.character("world") is None and [c.role for c in islamic.cast] == ["hero", "helper", "teammate", "teammate", "obstacle"]


def test_only_one_world_entry_is_allowed_in_the_cast():
    _, story = book(make(world="forest_house"))
    data = story.to_dict()
    data["cast"].append(dict(data["cast"][-1]))
    with pytest.raises(Exception) as err:
        validate_story(data, "ru")
    assert "одного мира" in str(err.value)


def test_page_prompts_carry_the_worlds_friends_the_palette_and_stay_within_the_limit():
    profile = make(world="forest_house")
    _, story = book(profile)
    look = D.archetype_by_id("honey").look
    for index in range(1, PAGES + 1):
        for has_refs in (False, True):
            prompt = prompts.build_page_prompt(story, profile, index, has_refs=has_refs)
            assert prompts.world_clause(story, profile) in prompt and look[:60] in prompt
            assert len(prompt) <= prompts.MAX_PROMPT and prompts.LEGAL_CLAUSE in prompt and prompts.STYLE in prompt
            assert prompt.endswith(story.style_note.strip())                                 # палитру держит каждая страница


def test_cover_prompt_has_the_helper_next_to_the_hero_and_the_worlds_friends_behind():
    profile = make(world="forest_house")
    _, story = book(profile)
    helper = story.character("helper").look
    for photo in (False, True):
        for title in (False, True):
            prompt = prompts.build_cover_prompt(story, profile, photo_ref=photo, title_in_image=title)
            assert "Right next to the hero stands the hero's helper" in prompt and helper in prompt
            assert len(prompt) <= prompts.MAX_PROMPT and prompts.LEGAL_CLAUSE in prompt
            if not (photo and title):                  # с фото и названием места мало: помощник остаётся, друзья мира могут не влезть
                assert "friends of the story's world" in prompt and D.archetype_by_id("honey").look[:50] in prompt


def test_books_without_a_world_get_no_world_clause_at_all():
    profile = make()
    _, story = book(profile)
    assert prompts.world_clause(story, profile) == ""
    assert "friends of the story's world" not in prompts.build_page_prompt(story, profile, 3, has_refs=True)
    assert "friends of the story's world" not in prompts.build_cover_prompt(story, profile, photo_ref=False, title_in_image=True)


def test_long_texts_never_cut_the_worlds_fixed_clauses_the_photo_rule_or_the_palette():
    profile = make(world="forest_house", gender="girl", name="Айгүл")
    plan, story = book(profile)
    data = story.to_dict()
    data["hero_visual"] = ("a cheerful little hero in a bright vest " * 40)[:900].strip()
    data["style_note"] = D.PALETTES[3].en
    for page in data["pages"]:
        page["scene"] = ("the hero runs across a sunny meadow with friends " * 30)[:700].strip()
    data["cast"][0]["look"] = data["hero_visual"][:500]
    data["cast"][1]["look"] = ("a fluffy kitten with white paws and a blue collar, " * 10)[:500].strip()
    long = validate_story(data, "ru")
    islamic = make(world="forest_house", gender="girl", name="Айгүл", islamic=True, headscarf=True)
    for p in (profile, islamic):
        for index in (1, 4):
            page = prompts.build_page_prompt(long, p, index, has_refs=False)
            assert len(page) <= prompts.MAX_PROMPT and page.endswith(D.PALETTES[3].en)
            assert prompts.page_layout_clause(index, has_refs=False) in page and prompts.STYLE in page
        for title in (False, True):
            cover = prompts.build_cover_prompt(long, p, photo_ref=True, title_in_image=title)
            assert len(cover) <= prompts.MAX_PROMPT and prompts.PHOTO_INSTRUCTION in cover and cover.endswith(D.PALETTES[3].en)
            assert "Right next to the hero stands the hero's helper" in cover
        if p.islamic:
            assert prompts.MODEST in prompts.build_page_prompt(long, p, 2, has_refs=False)
            assert "simple headscarf" in prompts.build_cover_prompt(long, p, photo_ref=True, title_in_image=True)


# ----------------------------------------------------------------------------- конвейер от анкеты до картинок
async def test_pipeline_with_a_world_puts_the_archetype_into_the_planner_and_into_every_image_prompt(tmp_path):
    from app.bookgen import build_book
    profile = make(world="forest_house", cartoons="Маша и Медведь")
    text, image = ScriptedPipeline(profile, polish=True), ScriptedImage()
    result = await build_book(profile, text, image, tmp_path / "order", image_sem=asyncio.Semaphore(3), mock=True)
    planner = text.calls_of("planner")[0]
    assert "Мир книги выбран родителями: «Лесной дом»" in planner["system"] and "Дядя Мёд" in planner["system"]
    assert text.seeds.helper_type.id == "bear" and text.seeds.helper_type.ru in planner["messages"][0][1]
    author = text.calls_of("author")[0]
    assert "cartoons" in author["messages"][0][1] and "ТОЛЬКО ВДОХНОВЕНИЕ" in author["messages"][0][1]
    stored = json.loads((tmp_path / "order" / "story.json").read_text(encoding="utf-8"))
    assert [c["role"] for c in stored["cast"]] == ["hero", "helper", "obstacle", "world"]
    friends = D.archetype_by_id("honey").look[:50]
    pages = [c for c in image.calls if c["label"].startswith("Страница")]
    assert len(pages) == PAGES and all(friends in c["prompt"] for c in pages)
    cover = next(c for c in image.calls if c["label"] == "Обложка")
    assert "Right next to the hero" in cover["prompt"] and len(cover["prompt"]) <= prompts.MAX_PROMPT
    assert result.story.character("world").look == D.archetype_by_id("honey").look


async def test_mock_provider_ignores_the_world_but_still_returns_a_valid_book():
    profile = make(world="princess", cartoons="Холодное сердце")
    story = await MockTextProvider().generate_story(profile)
    assert len(story.pages) == PAGES and not check_story(story, profile)


# ----------------------------------------------------------------------------- чужие бренды
RUSSIAN_BRANDS = [
    "Маша и Медведь", "Фиксики", "Смешарики", "Щенячий патруль", "Свинка Пеппа", "Человек-паук", "Бэтмен", "Ниндзя-черепашки",
    "Хантрикс", "Лабубу", "Бибо", "Покемоны", "Майнкрафт", "Холодное сердце", "Мимимишки", "Барбоскины", "Лунтик", "Чебурашка",
    "Хелло Китти", "Спанч Боб", "Дисней", "Пиксар", "Тачки", "Вспыш", "Лего", "Халк", "Роблокс", "Гарри Поттер", "Король Лев",
    "Кунг-фу панда", "Том и Джерри", "Скуби-Ду", "Железный человек", "Мстители", "Чип и Дейл", "Звёздные войны",
]
ENGLISH_BRANDS = [
    "KPop Demon Hunters", "Huntrix", "Hello Kitty", "SpongeBob", "Disney", "Pixar", "Labubu", "Bibo", "Minecraft", "Pokemon",
    "Peppa Pig", "Spider-Man", "Batman", "Paw Patrol", "Ninja Turtles", "Masha and the Bear", "Smeshariki", "Luntik", "Roblox",
    "Fortnite", "Among Us", "Huggy Wuggy", "Poppy Playtime", "Mario", "Sonic", "Lego", "Barbie", "Minions", "Frozen",
]


@pytest.mark.parametrize("name", RUSSIAN_BRANDS)
def test_popular_russian_and_world_cartoon_names_are_caught(name):
    assert brand_hits(f"Навстречу вышли {name} и показали дорогу."), name


@pytest.mark.parametrize("name", ENGLISH_BRANDS)
def test_popular_english_names_are_caught_in_the_plan_fields_too(name):
    assert brand_hits(f"The hero meets {name} at the stream, soft light."), name


@pytest.mark.parametrize("text", [
    "С Машей и Медведем", "у Фиксиков", "про Смешариков", "дружил с Человеком-пауком", "как у Человека-паука", "мимо Холодного сердца",
    "рядом с Губкой Бобом", "к Королю Льву", "для Хелло Китти", "с Бэтменом", "на Майнкрафте", "про Пикачу и Покемонов",
    "из Щенячьего патруля", "Свинки Пеппы", "в стиле Диснея", "студии Пиксар",
])
def test_inflected_forms_of_the_names_are_caught(text):
    assert brand_hits(text), text


@pytest.mark.parametrize("text", [
    "Пуф легонько толкнул камень.", "Яркая вспышка осветила поляну, и вспыхнул розовый огонёк.", "Он катил тачку с лепёшками.",
    "Дорога вела к реке, а дорожка к дому.", "Халат висел на гвозде, а халва лежала на столе.", "Тор на крыше не жил.",
    "Бибика гудела на мосту.", "Соня уснула, а сонник лежал на полке.", "Лёгкий ветер пробежал по траве.", "Лес был полон ярких огоньков и сверкающих листьев.",
    "Маша пошла к реке, а медведь остался дома.", "Смелые зайчата смешно прыгали.",
])
def test_ordinary_bright_words_are_not_mistaken_for_brands(text):
    assert not brand_hits(text), (text, brand_hits(text))


def test_a_child_named_like_a_short_brand_is_not_blocked_but_the_brand_is():
    own = {"марио", "марию", "мариа"}
    assert not brand_hits("Марио побежал к ручью.", own)
    assert brand_hits("Марио побежал к ручью.")
    profile = make(name="Марио")
    assert "brand" not in [v.code for v in check_story(validate_story(_story_with(profile, "Марио побежал к ручью и нашёл мостик."),
                                                                       "ru"), profile)]


def _story_with(profile: Profile, first_page: str) -> dict:
    from app.providers.text_mock import build_mock_story
    data = build_mock_story(profile)
    data["pages"][0]["text"] = first_page
    return data


def test_a_brand_in_a_plan_is_rejected_with_the_names_in_the_message():
    profile = make()
    seeds = seeds_for(profile)
    data = plan_dict(profile, seeds)
    data["premise"] = "Мальчик встречает Фиксиков и Лабубу у ручья и идёт за лепёшками"
    with pytest.raises(Exception) as err:
        validate_plan(data, profile, seeds)
    assert "известные персонажи или бренды" in str(err.value) and "лабубу" in str(err.value) and "фиксик" in str(err.value)
    data = plan_dict(profile, seeds)
    data["image_brief"][2] = "The hero meets Huntrix and the Minions at the stream, bright warm light."
    with pytest.raises(Exception) as err:
        validate_plan(data, profile, seeds)
    assert "известные персонажи или бренды" in str(err.value)
