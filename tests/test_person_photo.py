"""Фото близкого человека (мама, папа, бабушка, брат...): с ним он рисуется по фото, без него в книге нет людей, кроме героя-ребёнка."""
import asyncio
import io
import json
import os
import re
import time
from pathlib import Path

import aiohttp
import pytest
from PIL import Image

from app import prompts
from app.bookgen import build_book
from app.errors import StoryValidationError
from app.profile import Profile
from app.providers.text_mock import MockTextProvider
from app.simple_writer import PERSON_LOOK, assemble, people_in_scene, system_prompt, user_prompt
from app.story import PAGES

from .conftest import SAMPLE, ScriptedImage, build_env, tma
from .test_sheet import SheetImage, _answer

WEBAPP = Path(__file__).resolve().parent.parent / "webapp"
JS = (WEBAPP / "app.js").read_text(encoding="utf-8")
CSS = (WEBAPP / "style.css").read_text(encoding="utf-8")


def jpeg(size=(300, 200), color=(200, 120, 80)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def profile_with(parent=False, role="mother", **extra):
    return Profile.from_payload({**SAMPLE, "name": "Артём", "person_role": role, **extra}, has_person_photo=parent)


# ----------------------------------------------------------------------- профиль
def test_profile_roles_label_and_russian_names():
    for role, ru in (("mother", "мама"), ("father", "папа"), ("grandmother", "бабушка"), ("grandfather", "дедушка"), ("brother", "брат"),
                     ("sister", "сестра"), ("aunt", "тётя"), ("uncle", "дядя")):
        assert profile_with(True, role).person_ru == ru and profile_with(True, role).person_label == ""
    other = profile_with(True, "other", person_label="друг семьи")
    assert other.person_ru == "друг семьи" and profile_with(True, "other").person_ru == "близкий человек"
    assert profile_with(True, "mother", person_label="друг семьи").person_label == ""            # метка только для «другого»
    with pytest.raises(Exception):
        profile_with(True, "other", person_label="я" * 31)
    assert "person_label" in profile_with(True, "other", person_label="друг семьи").scrubbed() and \
        profile_with(True, "other", person_label="друг семьи").scrubbed()["person_label"] == ""


def test_profile_stores_person_photo_flag_and_role_and_old_orders_still_load():
    p = profile_with(True, "father")
    assert p.has_person_photo and p.person_role == "father"
    again = Profile.from_dict(p.to_dict())
    assert again.has_person_photo and again.person_role == "father"
    old = {k: v for k, v in p.to_dict().items() if k not in ("has_person_photo", "person_role")}
    assert not Profile.from_dict(old).has_person_photo and Profile.from_dict(old).person_role == "mother"
    assert profile_with(False, "дедушка").person_role == "mother"                  # чужое значение не ломает анкету


# ----------------------------------------------------------------------- писатель
def test_people_detector_has_no_false_alarms_on_hero_helper_and_creatures():
    p = profile_with()
    for ok in ("the hero and the helper walk in a green forest at noon", "A boy walks beside the helper", "the child waves to a dinosaur mother",
               "a baby goat kid near a queen bee", "the helper is a robot teacher with a big smile", "the hero meets a dragon dad by the lake"):
        assert people_in_scene(ok, p) == [], ok
    for bad, word in (("the hero meets a woman at the market", "woman"), ("the hero and another boy run", "boy"), ("a girl waves", "girl"),
                      ("children play near the hero", "children"), ("the hero and his father", "father"), ("a doctor smiles", "doctor")):
        assert people_in_scene(bad, p) == [word], bad


def test_without_a_person_photo_a_person_in_any_scene_is_a_hard_error_with_a_clear_text():
    profile = profile_with()
    data = _answer()
    data["pages"][4]["scene"] = "The hero and the helper sit by the fire with a kind grandmother in a warm kitchen."
    with pytest.raises(StoryValidationError) as err:
        assemble(profile, data)
    text = str(err.value)
    assert "В книге без фото близкого человека нет людей, кроме героя" in text and "страница 5" in text and "grandmother" in text
    assert "замени" in text and "зверя" in text


def test_without_a_person_photo_animals_dinosaurs_and_creatures_are_fine():
    data = _answer(family={"kind": "мама-динозавр", "look": "a large calm green dinosaur with a gentle smile"})
    for page in data["pages"]:
        page["scene"] = "The hero and the helper walk with a dinosaur mother and a baby fox through a green forest."
    story = assemble(profile_with(), data)
    assert [c.role for c in story.cast] == ["hero", "helper", "family"]


def test_without_a_person_photo_a_human_family_member_is_rejected():
    data = _answer(family={"kind": "мама", "look": "a kind mother with dark hair in a blue dress"})
    with pytest.raises(StoryValidationError, match="Поле family"):
        assemble(profile_with(), data)
    data = _answer(family={"kind": "бабушка", "look": "a gentle grandmother with a green scarf"})
    with pytest.raises(StoryValidationError, match="нет людей"):
        assemble(profile_with(), data)


def test_with_a_person_photo_the_parent_is_allowed_and_cast_as_family():
    profile = profile_with(True, "mother")
    data = _answer(family={"kind": "мама", "look": "a kind mother with dark hair in a blue dress"})
    data["pages"][6]["scene"] = "The hero hugs the parent while the helper jumps beside them at golden sunset."
    story = assemble(profile, data)
    family = story.character("family")
    assert family and family.name == "мама" and family.look == PERSON_LOOK                # внешность лица не выдумывается
    assert "blue dress" not in story.to_dict().__str__()


def test_with_a_person_photo_the_person_is_named_exactly_by_the_role():
    profile = profile_with(True, "grandmother")
    data = _answer()
    data["pages"][7]["scene"] = "The hero and the grandmother walk home with the helper at sunset."
    story = assemble(profile, data)
    assert story.character("family").name == "бабушка" and story.character("family").look == PERSON_LOOK
    data["pages"][7]["scene"] = "The hero and the mother walk home with the helper at sunset."      # мама, а на фото бабушка
    with pytest.raises(StoryValidationError, match="лишний человек"):
        assemble(profile, data)
    other = profile_with(True, "other", person_label="друг семьи")
    data["pages"][7]["scene"] = "The hero and the person walk home with the helper at sunset."
    assert assemble(other, data).character("family").name == "друг семьи"
    sister = profile_with(True, "sister")                                                             # ребёнок тоже допустим по фото
    data["pages"][7]["scene"] = "The hero and the sister walk home with the helper at sunset."
    assert assemble(sister, data).character("family").name == "сестра"
    data["pages"][7]["scene"] = "The hero and another girl walk home with the helper at sunset."
    with pytest.raises(StoryValidationError):
        assemble(profile_with(True, "brother"), data)


def test_with_a_person_photo_father_role_and_automatic_family_when_the_scene_names_the_parent():
    profile = profile_with(True, "father")
    data = _answer()                                                                       # family не заполнен
    data["pages"][7]["scene"] = "The hero and the father walk home with the helper at sunset."
    story = assemble(profile, data)
    assert story.character("family").name == "папа"
    data["pages"][7]["scene"] = "The hero and the mother walk home with the helper at sunset."      # мама, а на фото папа
    with pytest.raises(StoryValidationError, match="лишний человек"):
        assemble(profile, data)


def test_with_a_person_photo_other_people_are_still_rejected():
    profile = profile_with(True, "mother")
    for scene in ("The hero plays with a girl and the helper in a park.", "A teacher shows the hero a map near the helper.",
                  "The hero and grandma bake bread with the helper."):
        data = _answer()
        data["pages"][2]["scene"] = scene
        with pytest.raises(StoryValidationError, match="лишний человек"):
            assemble(profile, data)


def test_prompts_tell_the_writer_the_rule_in_both_cases():
    plain = system_prompt(profile_with())
    assert "НЕТ ЛЮДЕЙ, кроме героя" in plain and "ни маму, ни папу" in plain and "лицом не показывай" not in plain
    assert "Фото близкого человека: нет (людей в книге нет, кроме героя)." in user_prompt(profile_with(), None)
    with_photo = system_prompt(profile_with(True, "father"))
    assert "ОДИН человек" in with_photo and "the person from the reference photo" in with_photo and '"kind": "папа"' in with_photo
    assert "ровно так: «бабушка»" in system_prompt(profile_with(True, "grandmother")) and "the grandmother" in system_prompt(profile_with(True, "grandmother"))
    assert "Фото близкого человека: есть (папа нарисуется по фото" in user_prompt(profile_with(True, "father"), None)


# ----------------------------------------------------------------------- картинки
PARENT = b"\xff\xd8parent-bytes"
CHILD = b"\xff\xd8photo-bytes"


class ParentText(MockTextProvider):
    """Писатель: родитель в кадрах 6–8, на остальных страницах только герой и помощник."""

    first = None

    async def generate_story(self, profile):
        data = _answer(family={"kind": "мама", "look": "ignored"})
        if self.first:
            data["pages"][0]["scene"] = self.first
        for i in (5, 6, 7):
            data["pages"][i]["scene"] = "The hero and the parent smile together while the helper plays nearby in the sun."
        return assemble(profile, data)


async def run(tmp_path, image, profile, text, photo=CHILD, parent=PARENT):
    return await build_book(profile, text, image, tmp_path / "order", photo=photo, person_photo=parent,
                            image_sem=asyncio.Semaphore(3), mock=True)


async def test_person_photo_is_the_last_reference_only_on_frames_with_the_parent(tmp_path):
    image = SheetImage(supports_reference=True)
    await run(tmp_path, image, profile_with(True), ParentText())
    sheet = (tmp_path / "order" / "sheet.jpg").read_bytes()
    pages = {int(c["label"].split()[-1]): c for c in image.calls if c["label"].startswith("Страница")}
    assert len(pages) == PAGES
    for i, call in pages.items():
        if i in (6, 7, 8):
            assert call["refs"] == [CHILD, sheet, PARENT]
            assert "looks exactly like the person in the last reference photo (same face, hair, skin tone)" in call["prompt"]
        else:
            assert call["refs"] == [CHILD, sheet] and "last reference photo" not in call["prompt"]
        assert len(call["prompt"]) <= prompts.MAX_PROMPT
    cover = next(c for c in image.calls if c["label"] == "Обложка")
    assert cover["refs"] == [CHILD, sheet] and "last reference photo" not in cover["prompt"]       # на первой сцене родителя нет
    sheet_call = next(c for c in image.calls if c["label"] == "Лист героев")
    assert sheet_call["refs"] is None and "parent" not in sheet_call["prompt"].lower()             # на листе героев людей нет


async def test_cover_gets_the_person_photo_when_the_first_scene_shows_the_parent(tmp_path):
    class FirstScene(ParentText):
        first = "The hero and the parent wave goodbye with the helper at the door in the morning light."

    image = SheetImage(supports_reference=True)
    await run(tmp_path, image, profile_with(True), FirstScene())
    sheet = (tmp_path / "order" / "sheet.jpg").read_bytes()
    cover = next(c for c in image.calls if c["label"] == "Обложка")
    assert cover["refs"] == [CHILD, sheet, PARENT] and "last reference photo" in cover["prompt"]
    assert len(cover["prompt"]) <= prompts.MAX_PROMPT


async def test_no_person_photo_changes_nothing_in_the_references(tmp_path):
    image = SheetImage(supports_reference=True)
    await run(tmp_path, image, profile_with(False), MockTextProvider(), parent=None)
    sheet = (tmp_path / "order" / "sheet.jpg").read_bytes()
    for call in image.calls:
        assert "last reference photo" not in call["prompt"]
        if call["label"].startswith("Страница"):
            assert call["refs"] == [CHILD, sheet]


async def test_person_photo_is_ignored_when_the_book_has_no_parent_or_provider_has_no_references(tmp_path):
    image = SheetImage(supports_reference=True)
    await run(tmp_path, image, profile_with(True), MockTextProvider())          # писатель не вывел родителя в кадр
    assert all(PARENT not in (c["refs"] or []) for c in image.calls)
    plain = ScriptedImage(supports_reference=False)
    await build_book(profile_with(True), ParentText(), plain, tmp_path / "o2", photo=CHILD, person_photo=PARENT,
                     image_sem=asyncio.Semaphore(3), mock=True)
    assert all(not c["refs"] for c in plain.calls)


def test_prompt_lengths_stay_within_the_limit_with_the_parent_clause():
    profile = profile_with(True)
    data = _answer(family={"kind": "мама", "look": "x"})
    for page in data["pages"]:
        page["scene"] = ("The hero and the parent and the helper stand on a very wide sunny meadow " * 8)[:690]
    story = assemble(profile, data)
    for i in range(1, PAGES + 1):
        page = prompts.build_page_prompt(story, profile, i, has_refs=True, person_ref=True)
        assert len(page) <= prompts.MAX_PROMPT and "last reference photo" in page
    for title in (False, True):
        assert len(prompts.build_cover_prompt(story, profile, photo_ref=True, title_in_image=title, person_ref=True)) <= prompts.MAX_PROMPT


# ----------------------------------------------------------------------- API и удаление
async def post(client, payload, *, photo=None, parent=None, parent_type="image/jpeg", user_id=42):
    form = aiohttp.FormData()
    form.add_field("profile", json.dumps(payload, ensure_ascii=False), content_type="application/json")
    if photo is not None:
        form.add_field("photo", photo, filename="kid.jpg", content_type="image/jpeg")
    if parent is not None:
        form.add_field("person_photo", parent, filename="mom.jpg", content_type=parent_type)
    return await client.post("/api/orders", data=form, headers=tma(user_id))


async def test_person_photo_is_accepted_stored_as_parent_jpg_and_removed_after_generation(tmp_path):
    image = SheetImage(supports_reference=True)
    e = await build_env(tmp_path, image=image)
    try:
        cfg = await (await e.client.get("/api/config", headers=tma())).json()
        assert cfg["person_photo_supported"] is True
        resp = await post(e.client, {**SAMPLE, "photo_consent": True, "person_role": "father"}, parent=jpeg())
        assert resp.status == 201
        order_id = (await resp.json())["order_id"]
        profile = json.loads(e.db.get_order(order_id)["profile_json"])
        assert profile["has_person_photo"] is True and profile["person_role"] == "father" and profile["has_photo"] is False
        await e.wait_done(order_id)
        odir = e.service.order_dir(order_id)
        assert not (odir / "person.jpg").exists() and not (odir / "photo.jpg").exists()
        assert any("фото близкого человека: есть, папа" in t for t in e.notifier.admin_texts)
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_person_photo_needs_consent_and_a_real_image_and_a_small_file(env):
    resp = await post(env.client, SAMPLE, parent=jpeg())
    data = await resp.json()
    assert resp.status == 400 and data["field"] == "photo_consent"
    resp = await post(env.client, {**SAMPLE, "photo_consent": True}, parent=b"%PDF-1.4 not an image")
    data = await resp.json()
    assert resp.status == 400 and data["field"] == "person_photo" and data["error"].startswith("Фото близкого человека")
    resp = await post(env.client, {**SAMPLE, "photo_consent": True}, parent=b"\xff\xd8" + b"0" * (9 * 1024 * 1024))
    assert resp.status in (400, 413)
    if resp.status == 400:
        assert (await resp.json())["field"] == "person_photo"


async def test_person_photo_is_refused_for_provider_without_references(tmp_path):
    e = await build_env(tmp_path, image=ScriptedImage(supports_reference=False))
    try:
        cfg = await (await e.client.get("/api/config", headers=tma())).json()
        assert cfg["person_photo_supported"] is False
        resp = await post(e.client, {**SAMPLE, "photo_consent": True}, parent=jpeg())
        assert resp.status == 400
    finally:
        await e.client.close(); e.db.close()


def age(path, hours):
    old = time.time() - hours * 3600
    os.utime(path, (old, old))


async def test_old_person_photos_are_purged_with_child_photos(env):
    order_id = await env.create()
    await env.wait_done(order_id)
    odir = env.service.order_dir(order_id)
    for name in ("photo.jpg", "person.jpg"):
        (odir / name).write_bytes(b"\xff\xd8x")
    age(odir / "person.jpg", 22)
    assert env.service.purge_old_photos() == 0 and (odir / "person.jpg").exists()
    age(odir / "person.jpg", 23.5)
    age(odir / "photo.jpg", 23.5)
    assert env.service.purge_old_photos() == 2
    assert not (odir / "person.jpg").exists() and not (odir / "photo.jpg").exists() and (odir / "book.pdf").exists()


# ----------------------------------------------------------------------- Mini App
def test_miniapp_has_the_person_photo_block_and_sends_it():
    assert "Фото близкого человека (необязательно)" in JS and "Кто это?" in JS
    assert "Если хотите, чтобы этот человек был в книге, добавьте фото. Без фото в книге будут только малыш и придуманные герои." in JS
    for label, icon_name in (("Мама", "mom"), ("Папа", "dad"), ("Бабушка", "granny"), ("Дедушка", "grandpa"), ("Брат", "boy"), ("Сестра", "girl"), ("Другой", "friends")):
        assert f"label: '{label}', i: '{icon_name}'" in JS and re.search(rf"^    {icon_name}: '<", JS, re.M), label
    assert 'data-field="person_label" maxlength="30"' in JS
    assert "form.append('person_photo', S.person, 'person.jpg')" in JS and "body.person_role" in JS
    assert "Я согласен(на) на обработку фото этого человека" in JS and "data-act=\"person-remove\"" in JS
    assert "(!S.photo || S.a.photo_consent) && (!S.person || S.a.person_consent)" in JS          # согласие обязательно, если фото добавлено
    assert "'Фото близкого человека'" in JS and "person_photo_supported" in JS                             # старый сервер без поддержки блок не покажет
    assert re.search(r"HEIC", JS) and "downscale(file, 1024)" in JS                                # устойчивая загрузка осталась общей
    assert ".role-tile" in CSS and ".person-block" in CSS
