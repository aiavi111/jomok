"""Новые поля анкеты: тема книги (topic), «что хотите увидеть» (request), «любимые герои» (favorites)."""
import json
import time

import pytest

from app import options, prompts
from app.errors import ValidationError
from app.profile import FAVORITES_MAX, REQUEST_MAX, Profile

from .conftest import SAMPLE, tma


def make(**extra) -> Profile:
    return Profile.from_payload({**SAMPLE, **extra})


# ----------------------------------------------------------------------------- список тем
def test_topics_are_the_agreed_list_with_label_and_hint():
    assert list(options.TOPICS) == ["adventure", "dinosaurs", "space", "animals", "superheroes", "pirates", "sea",
                                    "friends", "kindness", "life_lesson", "custom"]
    labels = {k: v["label"] for k, v in options.TOPICS.items()}
    assert labels == {"adventure": "Приключение", "dinosaurs": "Динозавры", "space": "Космос", "animals": "Звери и лес",
                      "superheroes": "Супергерои", "pirates": "Пираты и клад", "sea": "Море", "friends": "Друзья",
                      "kindness": "Добрые дела", "life_lesson": "Учимся жизни", "custom": "Своя тема"}
    assert all(v["hint"] and v["emoji"] for v in options.TOPICS.values())
    assert "зубки" in options.TOPICS["life_lesson"]["hint"].lower() and options.DEFAULT_TOPIC == "adventure"


def test_public_options_expose_topics_for_the_mini_app():
    data = options.public_options()
    assert [t["id"] for t in data["topics"]] == list(options.TOPICS)
    assert set(data["topics"][0]) == {"id", "label", "emoji", "hint"} and data["default_topic"] == "adventure"
    json.dumps(data, ensure_ascii=False)


# ----------------------------------------------------------------------------- тема
def test_topic_defaults_to_adventure_when_the_client_does_not_send_it():
    assert make().topic == "adventure"
    assert make(topic=None).topic == "adventure" and make(topic="").topic == "adventure"


@pytest.mark.parametrize("topic", [t for t in options.TOPICS if t != "custom"])
def test_every_listed_topic_is_accepted(topic):
    profile = make(topic=topic)
    assert profile.topic == topic and profile.topic_label == options.TOPICS[topic]["label"] and profile.topic_custom == ""


@pytest.mark.parametrize("bad", ["fairy", "ADVENTURE", 5, ["space"], {"id": "space"}])
def test_unknown_topic_is_rejected_with_the_field_name(bad):
    with pytest.raises(ValidationError) as err:
        make(topic=bad)
    assert err.value.field == "topic"


def test_custom_topic_needs_a_description_or_a_request():
    with pytest.raises(ValidationError) as err:
        make(topic="custom")
    assert err.value.field == "topic_custom"
    with pytest.raises(ValidationError):
        make(topic="custom", topic_custom="   ")
    own = make(topic="custom", topic_custom="Как мы строим снежную крепость")
    assert own.topic_label == "Как мы строим снежную крепость"
    by_request = make(topic="custom", request="Хочу книгу про то, как мы с папой чиним велосипед")
    assert by_request.topic_label == "Своя тема" and by_request.topic_custom == ""


def test_custom_topic_text_is_limited_and_ignored_for_other_topics():
    with pytest.raises(ValidationError) as err:
        make(topic="custom", topic_custom="я" * 121)
    assert err.value.field == "topic_custom"
    assert make(topic="space", topic_custom="лишнее").topic_custom == ""


# ----------------------------------------------------------------------------- request и favorites
def test_request_and_favorites_are_optional_and_stored():
    plain = make()
    assert plain.request == "" and plain.favorites == ""
    full = make(request="Хочу, чтобы в книге был большой экскаватор и друг-зайчик.", favorites="Зайчик Бобо, мишка, поезд")
    assert full.request.startswith("Хочу, чтобы") and full.favorites == "Зайчик Бобо, мишка, поезд"


def test_request_and_favorites_are_cleaned_like_other_text_fields():
    profile = make(request="  Динозавр\u0000 <b>и</b>‮   ракета \n\n и ещё  ", favorites="<script>Зайка</script>\t\tМишка")
    assert "<" not in profile.request and ">" not in profile.request and "\x00" not in profile.request
    assert "‮" not in profile.request and "  " not in profile.request and "\n" not in profile.request
    assert profile.request == "Динозавр bи/b ракета и ещё"
    assert "<" not in profile.favorites and ">" not in profile.favorites and profile.favorites == "scriptЗайка/script Мишка"


def test_request_and_favorites_have_length_limits():
    assert (REQUEST_MAX, FAVORITES_MAX) == (300, 120)
    assert len(make(request="я" * 300).request) == 300 and len(make(favorites="я" * 120).favorites) == 120
    with pytest.raises(ValidationError) as err:
        make(request="я" * 301)
    assert err.value.field == "request" and "300" in err.value.message
    with pytest.raises(ValidationError) as err:
        make(favorites="я" * 121)
    assert err.value.field == "favorites" and "120" in err.value.message


def test_non_text_values_do_not_crash_the_fields():
    assert make(request=None, favorites=None).request == ""
    assert make(request=123, favorites=4.5).request == "123"


# ----------------------------------------------------------------------------- для писателя
def test_writer_sees_topic_request_and_favorites_inside_the_child_json():
    profile = make(topic="dinosaurs", request="Хочу друга-диплодока", favorites="Зайчик Бобо")
    child = profile.for_model()
    assert child["topic_label"] == "Динозавры" and child["request"] == "Хочу друга-диплодока"
    assert child["favorites"] == "Зайчик Бобо" and child["topic_hint"] == options.TOPICS["dinosaurs"]["hint"]
    user = prompts.build_user_prompt(profile)
    block = user.split("<child>")[1].split("</child>")[0]
    data = json.loads(block)
    assert data["topic_label"] == "Динозавры" and data["request"] == "Хочу друга-диплодока" and data["favorites"] == "Зайчик Бобо"


def test_empty_request_and_favorites_are_left_out_but_the_topic_is_always_there():
    child = make().for_model()
    assert child["topic_label"] == "Приключение" and "request" not in child and "favorites" not in child
    assert "место действия" in child and "ценность" in child                    # прежние поля на месте


def test_custom_topic_goes_to_the_writer_as_the_text_the_parent_wrote():
    child = make(topic="custom", topic_custom="Мой день рождения в юрте").for_model()
    assert child["topic_label"] == "Мой день рождения в юрте" and "topic_hint" not in child


def test_system_prompt_templates_are_not_touched_by_the_new_fields():
    assert "{topic" not in prompts.SYSTEM_TEMPLATE and "request" not in prompts.build_system_prompt(make())[:10]


# ----------------------------------------------------------------------------- хранение и стирание
def test_profile_roundtrip_keeps_new_fields_and_old_stored_profiles_get_defaults():
    profile = make(topic="space", request="Ракета", favorites="Лунтик не нужен")
    again = Profile.from_dict(json.loads(json.dumps(profile.to_dict(), ensure_ascii=False)))
    assert (again.topic, again.request, again.favorites) == ("space", "Ракета", "Лунтик не нужен")
    old = profile.to_dict()
    for key in ("topic", "topic_custom", "request", "favorites"):
        old.pop(key)
    restored = Profile.from_dict(old)
    assert restored.topic == "adventure" and restored.request == "" and restored.favorites == ""


def test_scrubbed_profile_drops_free_text_but_keeps_the_topic_for_statistics():
    profile = make(topic="custom", topic_custom="Секретная тема", request="личное пожелание", favorites="любимый мишка Тоша")
    scrubbed = profile.scrubbed()
    assert scrubbed["request"] == "" and scrubbed["favorites"] == "" and scrubbed["topic_custom"] == ""
    assert scrubbed["topic"] == "custom" and scrubbed["name"] == "" and scrubbed["dedication"] == "" and scrubbed["scrubbed"] is True
    assert "Тоша" not in json.dumps(scrubbed, ensure_ascii=False) and "Секретная" not in json.dumps(scrubbed, ensure_ascii=False)


async def test_order_api_accepts_the_new_fields_and_cleanup_erases_the_free_text(env):
    payload = {**SAMPLE, "topic": "pirates", "request": "Хочу карту сокровищ", "favorites": "Попугай Кеша"}
    order_id = await env.create(payload)
    row = env.db.get_order(order_id)
    stored = json.loads(row["profile_json"])
    assert stored["topic"] == "pirates" and stored["request"] == "Хочу карту сокровищ" and stored["favorites"] == "Попугай Кеша"
    await env.wait_done(order_id)
    env.db._exec("UPDATE orders SET created_at=? WHERE id=?", (time.time() - 8 * 86400, order_id))
    assert env.service.cleanup() == 1
    after = json.loads(env.db.get_order(order_id)["profile_json"])
    assert after["request"] == "" and after["favorites"] == "" and after["topic"] == "pirates" and after["name"] == ""


async def test_order_api_rejects_a_bad_topic_and_too_long_text(env):
    for extra, field in (({"topic": "unicorns"}, "topic"), ({"request": "я" * 301}, "request"),
                         ({"favorites": "я" * 121}, "favorites"), ({"topic": "custom"}, "topic_custom")):
        resp = await env.client.post("/api/orders", json={**SAMPLE, **extra}, headers=tma())
        data = await resp.json()
        assert resp.status == 400 and data["field"] == field, (extra, data)


async def test_config_exposes_topics_and_the_new_limits(env):
    data = await (await env.client.get("/api/config", headers=tma())).json()
    topics = data["options"]["topics"]
    assert [t["id"] for t in topics] == list(options.TOPICS) and topics[0]["id"] == "adventure"
    assert data["options"]["default_topic"] == "adventure"
    assert data["limits"]["request_max"] == 300 and data["limits"]["favorites_max"] == 120
    assert data["book_format"] == {
        "pages": PAGES_COUNT, "spreads": PAGES_COUNT + 2,
        "cover_image": {"width": 1024, "height": 1024, "ratio": "1:1"},
        "page_image": {"width": 2048, "height": 1024, "ratio": "2:1"},
        "text_side": {"odd": "right", "even": "left"}}


PAGES_COUNT = 8


@pytest.mark.parametrize("key, field", [("place", "place"), ("value", "value"), ("language", "language"), ("topic", "topic")])
@pytest.mark.parametrize("bad", [["mountains"], {"id": "yurt"}, 7])
def test_ids_that_arrive_as_lists_or_objects_are_a_validation_error_not_a_crash(key, field, bad):
    with pytest.raises(ValidationError) as err:
        make(**{key: bad})
    assert err.value.field == field


def test_trait_ids_of_the_wrong_type_are_a_validation_error_too():
    with pytest.raises(ValidationError) as err:
        make(traits=[["kind"]])
    assert err.value.field == "traits"


# ----------------------------------------------------------------------------- убранные из анкеты поля
def test_place_favorites_cartoons_are_optional_for_new_clients():
    data = {k: v for k, v in SAMPLE.items() if k not in ("place", "place_custom", "favorites", "cartoons")}
    profile = Profile.from_payload(data)
    assert profile.place == "mountains" and profile.place_label and profile.favorites == "" and profile.cartoons == ""
    assert Profile.from_payload({**data, "place": ""}).place == "mountains"
    with pytest.raises(ValidationError):
        Profile.from_payload({**data, "place": "nowhere"})                   # чужое значение по-прежнему ошибка


def test_old_clients_still_send_place_favorites_cartoons():
    profile = make(place="space", favorites="Зайчик", cartoons="Фиксики")
    assert profile.place == "space" and profile.favorites == "Зайчик" and profile.cartoons == "Фиксики"
