"""Собирает PDF-книгу из samples/profile_example.json без сервера и без ключей.

    python demo.py                          # пример на русском
    python demo.py samples/profile_ky.json  # пример на кыргызском
    python demo.py --from-env               # текст и картинки делают провайдеры из .env (Gemini, Cloudflare, OpenAI)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.bookgen import build_book
from app.config import ConfigError, Settings
from app.errors import ProviderError, StoryError, ValidationError
from app.logging_setup import redact
from app.profile import Profile
from app.providers import make_image_provider, make_text_provider
from app.providers.image_mock import MockImageProvider
from app.providers.text_mock import MockTextProvider

ROOT = Path(__file__).resolve().parent


async def main(sample: Path, from_env: bool = False) -> Path:
    try:
        profile = Profile.from_payload(json.loads(sample.read_text(encoding="utf-8")))
    except ValidationError as e:
        sys.exit(f"В файле {sample.name} ошибка: {e.message}")
    out_dir = ROOT / "demo_output" / sample.stem
    stages = {"writing": "Пишу сказку", "drawing": "Рисую иллюстрации", "assembling": "Собираю PDF"}

    async def on_status(status: str) -> None:
        print(f"  • {stages.get(status, status)}…")

    text_provider, image_provider, mock = MockTextProvider(), MockImageProvider(), True
    suffix = ""
    if from_env:
        try:
            settings = Settings.from_env()
            redact.add(settings.secrets)
            text_provider = make_text_provider(settings)
            image_provider = make_image_provider(settings)
        except ConfigError as e:
            sys.exit(f"Ошибка настройки: {e}")
        mock = settings.uses_mock
        suffix = f"_{settings.text_provider}_{settings.image_provider}"
        print(f"Собираю книгу из {sample.name}: текст — {settings.text_provider}, картинки — {settings.image_provider}")
    else:
        print(f"Собираю демо-книгу из {sample.name} (заглушки, без сети)")
    try:
        result = await build_book(profile, text_provider, image_provider, out_dir, mock=mock, on_status=on_status)
    except ProviderError as e:
        sys.exit(f"Не получилось: {e.message}")
    except StoryError as e:
        sys.exit(f"Модель не смогла написать сказку: {redact(str(e))}")
    if result.failed_pages:
        print(f"Внимание: не нарисовались {', '.join(result.failed_pages)} — на их месте заглушки. {result.failure_notes[0]}")
    pdf = ROOT / "demo_output" / f"{sample.stem}{suffix}.pdf"
    pdf.write_bytes(result.pdf_path.read_bytes())
    print(f"\nГотово! Название: «{result.story.title}»")
    print(f"PDF: {pdf}")
    return pdf


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = Path(args[0]) if args else ROOT / "samples" / "profile_example.json"
    asyncio.run(main(path, from_env=bool({"--from-env", "--text-from-env"} & set(sys.argv[1:]))))
