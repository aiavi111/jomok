"""Обложка с названием, нарисованным внутри картинки: проверка надписи, повторы, запасной вариант с плашкой."""
import asyncio
import json

import pytest

from app import prompts
from app.bookgen import COVER_ATTEMPTS, build_book, read_cover_meta, title_key
from app.profile import Profile
from app.providers.text_mock import MockTextProvider

from .conftest import SAMPLE, ScriptedImage


class ReadingText(MockTextProvider):
    """Заглушка текста, которая «читает» с обложки заранее заданные надписи по очереди."""

    def __init__(self, reads):
        super().__init__()
        self.reads = list(reads)
        self.read_calls = 0

    async def read_cover_text(self, image: bytes):
        self.read_calls += 1
        item = self.reads.pop(0) if self.reads else None
        if isinstance(item, Exception):
            raise item
        return item


class TextImage(ScriptedImage):
    renders_text = True


async def run(tmp_path, image, text):
    profile = Profile.from_payload(SAMPLE)
    return await build_book(profile, text, image, tmp_path / "order", image_sem=asyncio.Semaphore(3), mock=True)


def cover_calls(image):
    return [c for c in image.calls if c["label"] == "Обложка"]


async def test_title_is_written_into_the_cover_prompt_with_the_twenty_checks(tmp_path):
    image = TextImage()
    text = ReadingText([None])
    result = await run(tmp_path, image, text)
    prompt = cover_calls(image)[0]["prompt"]
    assert f"«{result.story.title}»" in prompt and "twenty times" in prompt and "no other text" in prompt.lower()
    assert "not overloaded" in prompt and "no text, no letters" not in prompt
    assert result.cover_has_title is True
    assert read_cover_meta(tmp_path / "order") == {"title_in_image": True}


async def test_cover_with_correct_title_is_accepted_at_once(tmp_path):
    image = TextImage()
    title = MockTextProvider.__new__(MockTextProvider)
    text = ReadingText([])
    # правильное название читается как есть (регистр и знаки не важны)
    story_title = (await MockTextProvider().generate_story(Profile.from_payload(SAMPLE))).title
    text.reads = [story_title.upper() + "!"]
    result = await run(tmp_path, image, text)
    assert len(cover_calls(image)) == 1 and text.read_calls == 1 and result.cover_has_title


async def test_cover_with_a_typo_is_redrawn_until_the_title_is_right(tmp_path):
    image = TextImage()
    title = (await MockTextProvider().generate_story(Profile.from_payload(SAMPLE))).title
    text = ReadingText([title[:-1] + "Ж", title[1:], title])
    result = await run(tmp_path, image, text)
    assert len(cover_calls(image)) == 3 and text.read_calls == 3 and result.cover_has_title is True


async def test_cover_falls_back_to_a_plate_when_every_attempt_has_errors(tmp_path):
    image = TextImage()
    text = ReadingText(["совсем не то"] * COVER_ATTEMPTS)
    result = await run(tmp_path, image, text)
    calls = cover_calls(image)
    assert len(calls) == COVER_ATTEMPTS + 1                       # три попытки с названием и одна без букв
    assert "twenty times" in calls[0]["prompt"] and "twenty times" not in calls[-1]["prompt"]
    assert "no text, no letters" in calls[-1]["prompt"]
    assert result.cover_has_title is False and any("без букв" in n for n in result.failure_notes)
    assert read_cover_meta(tmp_path / "order") == {"title_in_image": False}


async def test_unreadable_check_does_not_block_the_order(tmp_path):
    image = TextImage()
    text = ReadingText([RuntimeError("нет связи")])
    result = await run(tmp_path, image, text)
    assert result.cover_has_title is True and len(cover_calls(image)) == 1


async def test_provider_without_text_rendering_keeps_the_title_plate(tmp_path):
    image = ScriptedImage()                                       # renders_text = False
    text = ReadingText([])
    result = await run(tmp_path, image, text)
    assert text.read_calls == 0 and len(cover_calls(image)) == 1
    assert result.cover_has_title is False
    assert "twenty times" not in cover_calls(image)[0]["prompt"]


def test_title_key_ignores_case_punctuation_latin_lookalikes_and_ky_letters():
    assert title_key("Айгүл и «Комуз»!") == title_key("АЙГУЛ И КОМУЗ")
    assert title_key("Aмир и конь") == title_key("Амир и конь")      # первая A латинская
    assert title_key("Амир") != title_key("Амр")


async def test_order_view_tells_whether_the_title_is_already_on_the_cover(env):
    order_id = await env.create()
    done = await env.wait_done(order_id)
    assert done["cover_has_title"] is False                      # заглушки не рисуют буквы: название кладётся плашкой
