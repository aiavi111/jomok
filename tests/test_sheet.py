"""Лист героев (нейтральный фон) как образец для страниц, и простой писатель: имена в сценах заменяются ролями."""
import asyncio
import json

from app import prompts
from app.bookgen import build_book
from app.profile import Profile
from app.providers.text_mock import MockTextProvider
from app.simple_writer import _no_names, assemble, hero_look
from app.story import PAGES

from .conftest import SAMPLE, ScriptedImage, provider_error


class SheetImage(ScriptedImage):
    needs_character_sheet = True


async def run(tmp_path, image, profile, photo=None):
    return await build_book(profile, MockTextProvider(), image, tmp_path / "order", photo=photo,
                            image_sem=asyncio.Semaphore(3), mock=True)


async def test_pages_and_cover_take_the_sheet_and_photo_not_the_cover(tmp_path):
    photo = b"\xff\xd8photo-bytes"
    image = SheetImage(supports_reference=True)
    await run(tmp_path, image, Profile.from_payload(SAMPLE, has_photo=True), photo)
    sheet_call = next(c for c in image.calls if c["label"] == "Лист героев")
    assert sheet_call["refs"] is None                         # лист рисуется без фото: с фото в кадр лезет пейзаж
    assert "pure-white" in sheet_call["prompt"] and "no landscape" in sheet_call["prompt"]
    sheet = (tmp_path / "order" / "sheet.jpg").read_bytes()
    cover = (tmp_path / "order" / "cover.jpg").read_bytes()
    cover_call = next(c for c in image.calls if c["label"] == "Обложка")
    assert cover_call["refs"] == [photo, sheet]
    pages = [c for c in image.calls if c["label"].startswith("Страница")]
    assert len(pages) == PAGES
    for call in pages:
        assert call["refs"] == [photo, sheet] and cover not in call["refs"]


async def test_failed_sheet_falls_back_to_the_cover_as_reference(tmp_path):
    photo = b"\xff\xd8photo-bytes"
    image = SheetImage(supports_reference=True,
                       fail=lambda n, prompt, label: provider_error("сбой", no_retry=True) if label == "Лист героев" else None)
    result = await run(tmp_path, image, Profile.from_payload(SAMPLE, has_photo=True), photo)
    assert result.failed_pages == []                           # лист в список «не нарисовано» не попадает
    cover = (tmp_path / "order" / "cover.jpg").read_bytes()
    pages = [c for c in image.calls if c["label"].startswith("Страница")]
    assert all(c["refs"] == [cover, photo] for c in pages)


async def test_providers_without_the_flag_keep_the_old_flow(tmp_path):
    image = ScriptedImage(supports_reference=True)
    await run(tmp_path, image, Profile.from_payload(SAMPLE))
    assert all(c["label"] != "Лист героев" for c in image.calls)


def test_names_in_scenes_become_roles_in_any_case_and_spelling():
    out = _no_names("Artyom notices Topa; Topa's mother hugs him. Then topa smiles.", {"Топа": "the helper"})
    assert "Topa" not in out and "topa" not in out and out.count("the helper") == 3


def _answer(**over):
    page = {"text": "Артём шёл по лесу.", "scene": "A boy walks through a green forest at noon, the helper walks beside him."}
    data = {"title": "Артём и Топа", "meaning": "Помогай тому, кто потерялся.", "wish": "Расти добрым.",
            "hero_outfit": "a blue hoodie and brown trousers",
            "helper": {"name": "Топа", "kind": "динозаврик", "look": "a small round green dinosaur with round glasses"},
            "friends": [], "family": None, "pages": [dict(page) for _ in range(PAGES)]}
    data.update(over)
    return data


def test_assemble_builds_cast_and_never_names_the_helper_in_scenes():
    profile = Profile.from_payload({**SAMPLE, "name": "Артём"}, has_photo=True)
    data = _answer()
    data["pages"][2]["scene"] = "Low view in the forest: Topa passes under a branch that the hero holds."
    story = assemble(profile, data)
    assert [c.role for c in story.cast][:2] == ["hero", "helper"]
    assert "Topa" not in story.pages[2].scene and "the helper" in story.pages[2].scene
    assert "exactly like the child in the reference photo" in story.cast[0].look
    assert story.style_note and story.moral == "Помогай тому, кто потерялся."


def test_hero_look_without_photo_has_no_photo_words_and_with_photo_points_to_the_photo():
    plain = hero_look(Profile.from_payload(SAMPLE, has_photo=False), "a red jacket, curly red hair, green eyes")
    assert "reference photo" not in plain and plain.endswith("wearing a red jacket, curly red hair, green eyes.")
    assert "exactly like the child in the reference photo" in hero_look(Profile.from_payload(SAMPLE, has_photo=True), "a red jacket")


def test_sheet_prompt_lists_every_creature_without_a_place_or_the_child():
    profile = Profile.from_payload({**SAMPLE, "name": "Артём"}, has_photo=True)
    story = assemble(profile, _answer(friends=[{"name": "Лис", "kind": "лис", "look": "a small orange fox with a green scarf"}],
                                      family={"kind": "мама", "look": "a large calm green dinosaur with a gentle smile"}))
    prompt = prompts.build_sheet_prompt(story, profile)
    assert len(prompt) <= prompts.MAX_PROMPT
    low = prompt.lower()
    assert "helper:" in low and "friend:" in low and "family member" in low and "pure-white" in low
    assert "reference photo" not in low and "artём" not in low and "hero" not in low
    assert prompts.has_sheet_characters(story)


async def test_no_sheet_when_the_hero_is_alone(tmp_path):
    class Alone(MockTextProvider):
        async def generate_story(self, p):
            story = (await super().generate_story(p)).to_dict()
            story["cast"] = [c for c in story.get("cast", []) if c["role"] == "hero"]
            from app.story import validate_story
            return validate_story(story, p.language)

    image = SheetImage(supports_reference=True)
    await build_book(Profile.from_payload(SAMPLE), Alone(), image, tmp_path / "order", image_sem=asyncio.Semaphore(3), mock=True)
    assert all(c["label"] != "Лист героев" for c in image.calls)


# ----------------------------------------------------------------------------- пожелание родителей обязательно
import pytest as _pytest
from app.errors import StoryValidationError


def _football(profile_extra=None, **over):
    profile = Profile.from_payload({**SAMPLE, "request": "Артём играет на большом стадионе в футболке с номером 7", **(profile_extra or {})})
    data = _answer(requirements=[{"what": "большой стадион", "en": "stadium"}], **over)
    for page in data["pages"]:
        page["scene"] = "A boy in a red jersey number 7 on a huge stadium with the helper beside him."
    return profile, data


def test_request_details_that_reach_the_scenes_are_accepted():
    profile, data = _football()
    assert assemble(profile, data).pages[0].scene.count("stadium") == 1


def test_request_without_requirements_is_rejected():
    profile, data = _football()
    data["requirements"] = []
    with _pytest.raises(StoryValidationError, match="requirements"):
        assemble(profile, data)


def test_request_detail_lost_in_the_scenes_is_rejected():
    profile, data = _football()
    for page in data["pages"][2:]:
        page["scene"] = "A boy walks in a green forest with the helper beside him."
    with _pytest.raises(StoryValidationError, match="stadium"):
        assemble(profile, data)


def test_celebrity_in_requirements_is_rejected():
    profile, data = _football()
    data["requirements"] = [{"what": "играть с Роналду", "en": "stadium"}]
    with _pytest.raises(StoryValidationError, match="знаменитость"):
        assemble(profile, data)


def test_helper_must_be_on_nearly_every_picture():
    profile, data = _football()
    for page in data["pages"][:4]:
        page["scene"] = "A boy in a red jersey number 7 alone on a huge stadium."
    with _pytest.raises(StoryValidationError, match="helper"):
        assemble(profile, data)


def test_default_place_never_reaches_the_writer():
    from app.simple_writer import user_prompt
    profile = Profile.from_payload({**SAMPLE, "request": "Артём играет на стадионе"})
    prompt = user_prompt(profile, None)
    assert "место действия" not in prompt and "стадионе" in prompt and "Место действия выбери сам" in prompt


def test_soft_problems_carry_a_finished_book_so_the_order_is_not_lost():
    from app.simple_writer import SoftProblem
    profile, data = _football()
    for page in data["pages"][2:]:
        page["scene"] = "A boy walks in a green forest with the helper beside him."
    with _pytest.raises(SoftProblem) as e:
        assemble(profile, data)
    assert len(e.value.story.pages) == PAGES


async def test_book_is_still_made_when_requirements_stay_unmet_after_all_attempts():
    import json as _json
    from app.providers.base import TextProvider

    profile, data = _football()
    for page in data["pages"][2:]:
        page["scene"] = "A boy walks in a green forest with the helper beside him."
    data["pages"] = [{"text": "Артём шёл по лесу вместе с другом. Они искали мяч и смеялись. — Вот он! — крикнул Артём. Друг радостно кивнул.", "scene": p["scene"]} for p in data["pages"]]

    class Stubborn(TextProvider):
        simple_writer = True
        calls = 0

        async def _complete(self, system, messages, model=None):
            Stubborn.calls += 1
            return _json.dumps(data, ensure_ascii=False)

    story = await Stubborn().generate_story(profile)
    assert Stubborn.calls == 3 and len(story.pages) == PAGES        # три попытки, потом берём лучшее вместо ошибки заказа


def test_multi_word_requirement_is_satisfied_by_any_part_of_it():
    profile, data = _football()
    data["requirements"] = [{"what": "спасает город", "en": "child superhero, city rescue"}]
    for page in data["pages"]:
        page["scene"] = "A boy on a rooftop during a city rescue with the helper beside him."
    assert len(assemble(profile, data).pages) == PAGES


def test_the_moon_is_not_a_banned_name_when_parents_ask_for_the_moon():
    from app.writer import check_story
    text = "Тимур с другом летел к Луне. Вдруг Луна засияла ярко. — Смотри, Луна! — сказал он."
    for request, banned in (("Тимур строит корабль и летит на Луну", False), ("Тимур идёт гулять во двор", True)):
        profile, data = _football({"request": request})
        data["requirements"] = [{"what": "Луна", "en": "moon"}]
        for page in data["pages"]:
            page["scene"] = "A boy near the Moon with the helper beside him."
            page["text"] = text
        try:
            story = assemble(profile, data)
        except StoryValidationError as e:               # мелкие замечания приносят собранную книгу с собой
            story = e.story
        codes = {v.code for v in check_story(story, profile, None)}
        assert ("ban_name" in codes) is banned, request


def test_human_adults_are_never_drawn_with_a_face_but_animal_parents_are():
    from app.simple_writer import is_human_adult
    assert is_human_adult("a kind mother in a blue dress") and is_human_adult("The parent hugs the hero")
    assert not is_human_adult("a large calm green dinosaur, the mother of the helper")
    profile, data = _football()
    data["family"] = {"kind": "мама", "look": "a kind mother with dark hair in a blue dress"}
    for page in data["pages"]:
        page["scene"] = "A boy in a red jersey number 7 on a huge stadium with the helper beside him and his mother."
    story = assemble(profile, data)
    assert not story.characters("family")                                        # лицо мамы не рисуем и не описываем
    assert all("face is never visible" in p.scene for p in story.pages)
    data["family"] = {"kind": "мама-динозавр", "look": "a large calm green dinosaur with a gentle smile"}
    for page in data["pages"]:
        page["scene"] = "A boy in a red jersey number 7 on a huge stadium with the helper and a dinosaur mother."
    story = assemble(profile, data)
    assert story.characters("family") and not any("face is never visible" in p.scene for p in story.pages)
