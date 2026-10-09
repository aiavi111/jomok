"""story_preview.py: показывает сказку выбранного провайдера, понятно сообщает об ошибках и не печатает ключи."""
import json
from pathlib import Path

import httpx
import pytest

import story_preview
from app.logging_setup import redact
from app.profile import Profile
from app.providers import http as http_mod
from app.providers.text_gemini import GeminiTextProvider
from app.story import PAGES

from .conftest import SAMPLE, make_settings
from .test_providers import GEMINI_KEY, Recorder, gemini_reply, jr
from .writer_helpers import CLEAR, NO_FIXES, dump, plan_and_text, seeded


def run(coro):
    import asyncio
    return asyncio.run(coro)


def collect():
    lines: list[str] = []
    return lines, lines.append


def test_preview_with_mock_prints_title_pages_moral_and_wish(tmp_path):
    lines, out = collect()
    code = run(story_preview.preview(make_settings(tmp_path), SAMPLE, out=out))
    text = "\n".join(lines)
    assert code == 0 and f"Страница {PAGES}" in text and "Мораль:" in text and "Пожелание:" in text
    assert "[сцена для художника]" not in text
    lines2, out2 = collect()
    run(story_preview.preview(make_settings(tmp_path), SAMPLE, full=True, out=out2))
    assert "[сцена для художника]" in "\n".join(lines2) and "[герой для художника]" in "\n".join(lines2)


def test_preview_with_gemini_uses_provider_and_warns_about_free_tier(tmp_path, monkeypatch):
    plan, text = plan_and_text(Profile.from_payload(SAMPLE))
    server = Recorder(gemini_reply(plan), gemini_reply(text), gemini_reply(dump(CLEAR)), gemini_reply(NO_FIXES))
    monkeypatch.setattr(story_preview, "make_text_provider",
                        lambda s: seeded(GeminiTextProvider(s.gemini_api_key, s.gemini_model, transport=server.transport)))
    settings = make_settings(tmp_path, text_provider="gemini", gemini_api_key=GEMINI_KEY, gemini_model="m")
    lines, out = collect()
    assert run(story_preview.preview(settings, SAMPLE, out=out)) == 0
    text = "\n".join(lines)
    assert "бесплатный тариф Gemini" in text and "вымышленные" in text and GEMINI_KEY not in text
    assert len(server.requests) == 4          # план, текст, проверка понятности и проход редактора


def test_preview_explains_wrong_key_without_traceback_or_key(tmp_path, monkeypatch):
    server = Recorder(jr(400, {"error": {"message": f"API key not valid {GEMINI_KEY}"}}))
    monkeypatch.setattr(story_preview, "make_text_provider",
                        lambda s: GeminiTextProvider(s.gemini_api_key, s.gemini_model, transport=server.transport))
    lines, out = collect()
    code = run(story_preview.preview(make_settings(tmp_path, text_provider="gemini", gemini_api_key=GEMINI_KEY, gemini_model="m"), SAMPLE, out=out))
    text = "\n".join(lines)
    assert code == 1 and "Неверный ключ Gemini" in text and GEMINI_KEY not in text and "Traceback" not in text


def test_preview_reports_missing_key_and_bad_profile(tmp_path):
    lines, out = collect()
    assert run(story_preview.preview(make_settings(tmp_path, text_provider="gemini"), SAMPLE, out=out)) == 2
    assert "GEMINI_API_KEY" in "\n".join(lines)
    lines, out = collect()
    assert run(story_preview.preview(make_settings(tmp_path), {**SAMPLE, "age": 1}, out=out)) == 2
    assert "3 до 9" in "\n".join(lines)
