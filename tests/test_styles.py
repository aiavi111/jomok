"""Стиль иллюстраций выбирает родитель: options.STYLES (3D-мультик, 2D-мультик, реалистичный), поле profile.style,
блоки стиля в промтах обложки и страниц, запись в /api/config и в просмотре заказа. Сеть не нужна."""
import asyncio
import json

import pytest

from app import options, prompts
from app.profile import Profile
from app.story import PAGES
from app.writer import assemble_story, validate_plan
from app.writer_prompts import build_planner_prompts, style_text

from .conftest import SAMPLE, ScriptedImage, tma
from .writer_helpers import author_dict, plan_dict, seeds_for

STYLE_IDS = ["cartoon3d", "flat2d", "realistic"]
OTHER = {sid: [x for x in STYLE_IDS if x != sid] for sid in STYLE_IDS}


def make(**extra) -> Profile:
    return Profile.from_payload({**SAMPLE, **extra})


def story_for(profile: Profile):
    seeds = seeds_for(profile)
    plan = validate_plan(plan_dict(profile, seeds), profile, seeds)
    return assemble_story(profile, plan, author_dict(profile, seeds))


# ----------------------------------------------------------------------------- список стилей
def test_styles_are_the_agreed_three_with_label_hint_and_emoji():
    assert options.STYLES == [
        {"id": "cartoon3d", "label": "3D-мультик", "hint": "яркий, как в кино про зверят", "emoji": "🧸"},
        {"id": "flat2d", "label": "2D-мультик", "hint": "плоская цветная иллюстрация как в детских книжках", "emoji": "✏️"},
        {"id": "realistic", "label": "Реалистичный", "hint": "кинематографичные кадры, ребёнок как на вашем фото", "emoji": "📷"},
    ]
    assert options.DEFAULT_STYLE == "cartoon3d" and options.STYLE_IDS == tuple(STYLE_IDS)
    assert options.style_label("flat2d") == "2D-мультик" and options.style_label("zzz") == "3D-мультик"


def test_public_options_expose_styles_like_worlds():
    data = options.public_options()
    assert data["styles"] == options.STYLES and data["default_style"] == "cartoon3d"
    assert all(set(item) == {"id", "label", "hint", "emoji"} for item in data["styles"])
    assert set(data["worlds"][0]) == set(data["styles"][0]) == {"id", "label", "hint", "emoji"}
    json.dumps(data, ensure_ascii=False)
    data["styles"][0]["label"] = "испорчено"                                       # копия: общий список не меняется
    assert options.STYLES[0]["label"] == "3D-мультик"


async def test_config_sends_the_styles_to_the_mini_app(env):
    data = await (await env.client.get("/api/config", headers=tma())).json()
    assert data["options"]["styles"] == options.STYLES and data["options"]["default_style"] == "cartoon3d"


# ----------------------------------------------------------------------------- анкета
def test_style_defaults_to_cartoon3d_and_known_ids_are_kept():
    assert make().style == "cartoon3d"
    for style in STYLE_IDS:
        assert make(style=style).style == style


@pytest.mark.parametrize("bad", [None, "", "pixel", "REALISTIC", "flat2d ", 3, ["realistic"], {"id": "flat2d"}, True])
def test_unknown_or_odd_style_falls_back_to_the_default_without_an_error(bad):
    assert make(style=bad).style == "cartoon3d"


def test_old_stored_profiles_without_a_style_still_load_as_cartoon3d():
    stored = make().to_dict()
    stored.pop("style")
    restored = Profile.from_dict(stored)
    assert restored.style == "cartoon3d" and restored.style_label == "3D-мультик"
    assert Profile.from_dict(json.loads(json.dumps(make(style="realistic").to_dict()))).style == "realistic"
    assert make(style="flat2d").scrubbed()["style"] == "flat2d"                        # стиль не личные данные, остаётся для статистики


def test_the_writer_sees_the_style_label_inside_the_child_block():
    assert make().for_model()["style_label"] == "3D-мультик"
    assert make(style="realistic").for_model()["style_label"] == "Реалистичный"
    assert make(style="flat2d").style_label == "2D-мультик"


async def test_order_api_stores_the_style_and_the_view_returns_it(env):
    order_id = await env.create({**SAMPLE, "style": "flat2d"})
    assert json.loads(env.db.get_order(order_id)["profile_json"])["style"] == "flat2d"
    view = await env.wait_done(order_id)
    assert view["status"] == "done" and view["style"] == "flat2d" and view["style_label"] == "2D-мультик"


async def test_order_api_accepts_an_unknown_style_and_old_clients_without_it(env):
    unknown = await env.create({**SAMPLE, "style": "watercolor"})
    assert json.loads(env.db.get_order(unknown)["profile_json"])["style"] == "cartoon3d"
    await env.wait_done(unknown)
    old = await env.create(SAMPLE)
    view = await env.wait_done(old)
    assert view["style"] == "cartoon3d" and view["style_label"] == "3D-мультик"


# ----------------------------------------------------------------------------- блоки стиля в промтах
def test_each_style_has_its_own_block_the_default_one_is_the_old_style():
    assert prompts.style_block(make()) == prompts.STYLE and prompts.style_block(make(), cover=True) == prompts.STYLE_COVER
    flat, real = make(style="flat2d"), make(style="realistic")
    assert "flat vector-like children's book illustration" in prompts.style_block(flat) and "clean confident outlines" in prompts.style_block(flat)
    assert "saturated rainbow colours" in prompts.style_block(flat) and "no photorealism" in prompts.style_block(flat)
    assert "cinematic photoreal" in prompts.style_block(real) and "natural skin" in prompts.style_block(real)
    assert "exactly like the reference photo" in prompts.style_block(real) and "high-end CGI" in prompts.style_block(real)
    for style in STYLE_IDS:
        profile = make(style=style)
        assert prompts.style_block(profile).endswith(", no text, no letters, no watermark")
        assert prompts.style_block(profile, cover=True).endswith(", no watermark, no logos")
    assert prompts.style_block(make(style="zzz")) == prompts.STYLE


@pytest.mark.parametrize("style", STYLE_IDS)
def test_page_and_cover_prompts_carry_the_chosen_style_and_only_it(style):
    profile = make(style=style)
    story = story_for(profile)
    block, cover_block = prompts.style_block(profile), prompts.style_block(profile, cover=True)
    for index in range(1, PAGES + 1):
        for has_refs in (False, True):
            page = prompts.build_page_prompt(story, profile, index, has_refs=has_refs)
            assert block in page and len(page) <= prompts.MAX_PROMPT and prompts.LEGAL_CLAUSE in page
            assert page.endswith(story.style_note.strip())                                           # палитра по-прежнему в конце
            for other in OTHER[style]:
                assert prompts.style_block(make(style=other)) not in page
    for photo in (False, True):
        for title in (False, True):
            cover = prompts.build_cover_prompt(story, profile, photo_ref=photo, title_in_image=title)
            assert (cover_block if title else block) in cover and len(cover) <= prompts.MAX_PROMPT
            assert "Right next to the hero stands the hero's helper" in cover and prompts.LEGAL_CLAUSE in cover
            for other in OTHER[style]:
                assert prompts.style_block(make(style=other), cover=title) not in cover


def test_realistic_style_keeps_the_childs_face_and_never_asks_for_a_cartoon_look():
    profile = make(style="realistic")
    story = story_for(profile)
    cover = prompts.build_cover_prompt(story, profile, photo_ref=True, title_in_image=True)
    assert prompts.REALISTIC_PHOTO_INSTRUCTION in cover and "recognisably the same real person" in cover
    assert "face shape, eyes, hair, skin tone and age" in cover and "Do not copy the photo's pose" in cover
    assert prompts.PHOTO_INSTRUCTION not in cover and "no photorealism" not in cover
    page = prompts.build_page_prompt(story, profile, 3, has_refs=True)
    assert prompts.REALISTIC_SAME_CHARACTER in page and "recognisably the same person" in page
    assert prompts.SAME_CHARACTER not in page and "no photorealism" not in page and "3D-animated" not in page


def test_cartoon_styles_keep_the_old_photo_rules():
    for style in ("cartoon3d", "flat2d"):
        profile = make(style=style)
        story = story_for(profile)
        cover = prompts.build_cover_prompt(story, profile, photo_ref=True, title_in_image=True)
        assert prompts.PHOTO_INSTRUCTION in cover and "no photorealism" in cover
        assert prompts.SAME_CHARACTER in prompts.build_page_prompt(story, profile, 2, has_refs=True)


def test_long_texts_never_cut_the_style_block_whatever_the_style():
    from app.story import validate_story
    for style in STYLE_IDS:
        profile = make(style=style, islamic=True)
        data = story_for(profile).to_dict()
        data["hero_visual"] = ("a cheerful little hero in a bright vest " * 40)[:900].strip()
        for page in data["pages"]:
            page["scene"] = ("the hero runs across a sunny meadow with friends " * 30)[:700].strip()
        story = validate_story(data, "ru")
        for index in (1, 2):
            page = prompts.build_page_prompt(story, profile, index, has_refs=False)
            assert prompts.style_block(profile) in page and prompts.MODEST in page and len(page) <= prompts.MAX_PROMPT
        cover = prompts.build_cover_prompt(story, profile, photo_ref=True, title_in_image=True)
        assert prompts.style_block(profile, cover=True) in cover and prompts.photo_instruction(profile) in cover
        assert len(cover) <= prompts.MAX_PROMPT


def test_the_planner_is_told_the_chosen_style_and_still_gets_the_palettes():
    for style, phrase in (("cartoon3d", "3D-мультик"), ("flat2d", "плоский 2D-мультик"), ("realistic", "реалистичный")):
        profile = make(style=style)
        system, user = build_planner_prompts(profile, seeds_for(profile))
        assert phrase in system and phrase in style_text(profile) and "Палитры книги" in system
        assert json.loads(user.split("<child>")[1].split("</child>")[0])["style_label"] == options.style_label(style)
    assert "лицо и волосы как у ребёнка на фото" in style_text(make(style="realistic"))


# ----------------------------------------------------------------------------- вся книга со всеми тремя стилями
@pytest.mark.parametrize("style", STYLE_IDS)
async def test_mock_pipeline_builds_a_book_in_every_style(tmp_path, style):
    from app.bookgen import build_book
    from app.providers.text_mock import MockTextProvider
    profile = make(style=style)
    image = ScriptedImage()
    result = await build_book(profile, MockTextProvider(), image, tmp_path / "order", image_sem=asyncio.Semaphore(3), mock=True)
    assert result.pdf_path.exists() and result.pdf_path.stat().st_size > 10_000 and len(result.story.pages) == PAGES
    assert not result.failed_pages
    block, cover_block = prompts.style_block(profile), prompts.style_block(profile, cover=True)
    pages = [c for c in image.calls if c["label"].startswith("Страница")]
    cover = next(c for c in image.calls if c["label"] == "Обложка")
    assert len(pages) == PAGES and all(block in c["prompt"] for c in pages)
    assert block in cover["prompt"] or cover_block in cover["prompt"]
    assert all(prompts.LEGAL_CLAUSE in c["prompt"] and len(c["prompt"]) <= prompts.MAX_PROMPT for c in image.calls)
    assert all("айдар" not in c["prompt"].lower() and "aidar" not in c["prompt"].lower() for c in pages)
