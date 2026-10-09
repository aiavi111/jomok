"""Показывает книгу, которую пишет выбранный в .env текстовый провайдер (картинки и сервер не нужны).

    python story_preview.py                         # анкета из samples/profile_example.json
    python story_preview.py samples/profile_ky.json # кыргызский пример
    python story_preview.py --full                  # ещё показать рефрен, героев и английские описания для художника

Конвейер: режиссёр (план) → автор (текст) → «понятно ли пятилетнему» → редактор. Это 4–5 запросов к модели, у кыргызского ещё вычитка.
Удобно, чтобы сразу оценить качество текста после того, как вписали GEMINI_API_KEY или OPENAI_API_KEY
и поставили TEXT_PROVIDER=gemini (или openai). С TEXT_PROVIDER=mock покажет шаблонный текст.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from app.config import ConfigError, Settings
from app.errors import ProviderError, StoryError, ValidationError
from app.logging_setup import redact
from app.profile import Profile
from app.providers import make_text_provider

ROOT = Path(__file__).resolve().parent


async def preview(settings: Settings, data: dict, *, full: bool = False, out=print) -> int:
    redact.add(settings.secrets)
    try:
        profile = Profile.from_payload(data)
        provider = make_text_provider(settings)
    except (ConfigError, ValidationError) as e:
        out(f"Ошибка настройки: {getattr(e, 'message', e)}")
        return 2
    out(f"Пишу книгу для вымышленного ребёнка: текст = {settings.text_provider}. Это может занять до минуты…")
    if settings.text_provider == "gemini":
        out("Напоминание: бесплатный тариф Gemini использует присланное для улучшения продуктов Google — "
            "вводите только вымышленные данные.")
    started = time.monotonic()
    try:
        story = await provider.generate_story(profile)
    except ProviderError as e:
        out(f"\nНе получилось: {e.message}")
        return 1
    except StoryError as e:
        out(f"\nМодель три раза подряд вернула ответ, не прошедший проверку. Последняя причина: {redact(str(e))}")
        return 1
    seconds = time.monotonic() - started
    out(f"\n=== {story.title} ===\n")
    for number, page in enumerate(story.pages, start=1):
        out(f"Страница {number}\n{page.text}\n")
        if full:
            out(f"  [сцена для художника] {page.scene}\n")
    out(f"Мораль: {story.moral}")
    out(f"Пожелание: {story.wish}")
    if full:
        out(f"\n[герой для художника] {story.hero_visual}\n[стиль] {story.style_note}")
        out(f"[рефрен] {story.refrain}")
        for character in story.cast:
            out(f"[актёр: {character.role}] {character.name}: {character.look}")
    out(f"\nГотово за {seconds:.0f} с.")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    full = "--full" in sys.argv[1:]
    sample = Path(args[0]) if args else ROOT / "samples" / "profile_example.json"
    try:
        settings = Settings.from_env()
        data = json.loads(sample.read_text(encoding="utf-8"))
    except (ConfigError, OSError, ValueError) as e:
        print(f"Ошибка: {e}")
        return 2
    return asyncio.run(preview(settings, data, full=full))


if __name__ == "__main__":
    sys.exit(main())
