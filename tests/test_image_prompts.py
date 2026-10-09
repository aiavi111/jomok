"""Промты для картинок: широкая страница 2:1 (герои на одной половине, другая спокойная под текст), правило про
чужих персонажей во всех промтах, ограничение длины с неурезаемыми кусками."""
import pytest

from app import prompts
from app.profile import Profile
from app.story import PAGES, validate_story

from .conftest import SAMPLE
from .test_story import good_story

LAYOUT_START = "wide panoramic double-page spread, 2:1"
CALM = ("calm, softly lit, uncluttered area (a quieter, softer-detail part of the same place as in the scene, such as "
        "blurred foliage, mist, rock, water or ground) with nothing important in it, left free for text")


@pytest.fixture
def story():
    return validate_story(good_story(), "ru")


def long_story():
    data = good_story()
    data["hero_visual"] = ("a cheerful little hero in a bright vest " * 40)[:900].strip()
    data["style_note"] = ("sunny saturated palette " * 40)[:400].strip()
    for page in data["pages"]:
        page["scene"] = ("the hero runs across a sunny meadow with friends " * 30)[:700].strip()
    return validate_story(data, "ru")


# ----------------------------------------------------------------------------- композиция страницы
@pytest.mark.parametrize("index, hero_half, calm_half", [(1, "left", "right"), (3, "left", "right"), (5, "left", "right"),
                                                          (7, "left", "right"), (2, "right", "left"), (4, "right", "left"),
                                                          (6, "right", "left"), (8, "right", "left")])
def test_page_prompt_puts_heroes_on_one_half_and_keeps_the_text_half_calm(story, profile, index, hero_half, calm_half):
    for has_refs in (False, True):
        prompt = prompts.build_page_prompt(story, profile, index, has_refs=has_refs)
        low = prompt.lower()
        assert low.startswith(LAYOUT_START)
        assert f"in the {hero_half} half" in low and f"the {calm_half} half is a {CALM}" in low
        assert "large, clearly visible, in action, standing or moving (never sitting at a desk)" in low
        assert f"in the {calm_half} half." not in low and f"the {hero_half} half is a calm" not in low


def test_odd_pages_are_calm_on_the_right_and_even_pages_calm_on_the_left_like_the_pdf_text(story, profile):
    from app.layout import text_side
    for index in range(1, PAGES + 1):
        low = prompts.build_page_prompt(story, profile, index, has_refs=True).lower()
        assert f"the {text_side(index)} half is a calm" in low


def test_page_prompt_names_the_reference_hero_only_when_there_are_references(story, profile):
    with_refs = prompts.build_page_prompt(story, profile, 1, has_refs=True)
    without = prompts.build_page_prompt(story, profile, 1, has_refs=False)
    assert "the hero from the reference image and the helper character" in with_refs
    assert "the hero and the helper character" in without and "reference image" not in without


def test_cover_prompts_do_not_ask_for_a_wide_spread(story, profile):
    for photo in (False, True):
        for title in (False, True):
            prompt = prompts.build_cover_prompt(story, profile, photo_ref=photo, title_in_image=title).lower()
            assert "double-page" not in prompt and "half is a calm" not in prompt


# ----------------------------------------------------------------------------- правило про чужих персонажей
LEGAL = ("Never draw existing trademarked or copyrighted characters; if the story mentions a famous type of character, "
         "draw an original look-alike archetype.")


def test_legal_rule_is_in_every_image_prompt(story, profile):
    assert prompts.LEGAL_CLAUSE == LEGAL
    for index in range(1, PAGES + 1):
        for has_refs in (False, True):
            assert LEGAL in prompts.build_page_prompt(story, profile, index, has_refs=has_refs)
    for photo in (False, True):
        for title in (False, True):
            assert LEGAL in prompts.build_cover_prompt(story, profile, photo_ref=photo, title_in_image=title)


def test_old_style_rules_still_hold(story, profile):
    page = prompts.build_page_prompt(story, profile, 1, has_refs=False)
    assert prompts.STYLE in page and "no text, no letters, no watermark" in page
    cover = prompts.build_cover_prompt(story, profile, photo_ref=False, title_in_image=True)
    assert prompts.STYLE_COVER in cover and f"«{story.title}»" in cover


# ----------------------------------------------------------------------------- длина
def test_long_inputs_never_cut_the_layout_the_legal_rule_or_the_style():
    story, profile = long_story(), Profile.from_payload(SAMPLE)
    for index in range(1, PAGES + 1):
        for has_refs in (False, True):
            prompt = prompts.build_page_prompt(story, profile, index, has_refs=has_refs)
            assert len(prompt) <= prompts.MAX_PROMPT
            assert prompts.page_layout_clause(index, has_refs=has_refs) in prompt
            assert LEGAL in prompt and prompts.STYLE in prompt


def test_long_cover_keeps_the_title_clause_the_legal_rule_and_the_style_whole():
    story, profile = long_story(), Profile.from_payload({**SAMPLE, "islamic": True})
    for photo in (False, True):
        prompt = prompts.build_cover_prompt(story, profile, photo_ref=photo, title_in_image=True)
        assert len(prompt) <= prompts.MAX_PROMPT
        assert prompts.COVER_TITLE_CLAUSE.format(title=story.title.strip()) in prompt
        assert LEGAL in prompt and prompts.STYLE_COVER in prompt
        plain = prompts.build_cover_prompt(story, profile, photo_ref=photo)
        assert len(plain) <= prompts.MAX_PROMPT and LEGAL in plain and prompts.STYLE in plain


def test_hero_description_is_what_gets_cut_when_the_prompt_is_too_long_not_the_fixed_clauses():
    story, profile = long_story(), Profile.from_payload(SAMPLE)
    prompt = prompts.build_page_prompt(story, profile, 1, has_refs=False)
    assert story.pages[0].scene in prompt and story.hero_visual not in prompt and story.hero_visual[:40] in prompt
    assert len(prompt) > prompts.MAX_PROMPT - 400                              # место использовано, ничего лишнего не выброшено


def test_short_style_note_is_kept_at_the_end_when_there_is_room(story, profile):
    prompt = prompts.build_page_prompt(story, profile, 2, has_refs=True)
    assert prompt.endswith(story.style_note.strip()) and len(prompt) < prompts.MAX_PROMPT


def test_child_name_is_still_scrubbed_from_the_layout_prompt(profile):
    data = good_story()
    data["pages"][0]["scene"] = "Aidar runs along the shore while Aidar's horse follows. Айдар smiles."
    data["hero_visual"] = "A six-year-old boy named Aidar with a blue vest, short black hair and a happy smile on his face."
    story = validate_story(data, "ru")
    prompt = prompts.build_page_prompt(story, profile, 1, has_refs=False).lower()
    assert "aidar" not in prompt and "айдар" not in prompt
