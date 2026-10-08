"""Настройки проекта: всё берётся из файла .env (или из переменных окружения).

Названия моделей и ключи живут только в .env — в коде их нет.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

TEXT_PROVIDERS = ("mock", "openai", "gemini")
IMAGE_PROVIDERS = ("mock", "openai", "cloudflare")


class ConfigError(Exception):
    """Понятная русская ошибка настройки."""


def _s(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return (value if value is not None else default).strip()


def _webapp_url() -> str:
    """WEBAPP_URL из настроек; на Railway, если не задан, берём выданный им домен."""
    url = _s("WEBAPP_URL")
    if not url:
        domain = _s("RAILWAY_PUBLIC_DOMAIN")
        if domain:
            url = f"https://{domain}"
    return url.rstrip("/")


def _int(name: str, default: int) -> int:
    raw = _s(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"В .env строка {name} должна быть целым числом, а там: «{raw}».")


def _float(name: str, default: float) -> float:
    raw = _s(name)
    if not raw:
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        raise ConfigError(f"В .env строка {name} должна быть числом, а там: «{raw}».")


def _bool(name: str, default: bool = False) -> bool:
    raw = _s(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "да")


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str = ""
    webapp_url: str = ""
    admin_chat_id: int | None = None

    text_provider: str = "mock"
    image_provider: str = "mock"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_text_model: str = ""
    openai_image_model: str = ""
    openai_image_quality: str = "medium"

    gemini_api_key: str = ""
    gemini_model: str = ""

    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    cloudflare_image_model: str = ""

    dev_mode: bool = False
    max_books_per_user_per_day: int = 3
    keep_files_days: int = 7

    host: str = "127.0.0.1"
    port: int = 8080
    data_dir: Path = ROOT / "data"
    max_parallel_generations: int = 3
    image_concurrency: int = 3
    mock_delay_seconds: float = 1.2

    price_text: str = "499 сом"

    @classmethod
    def from_env(cls, env_file: Path | None = ROOT / ".env") -> "Settings":
        if env_file is not None and Path(env_file).exists():
            # override=False: переменные, уже заданные в системе, важнее файла
            load_dotenv(env_file, override=False)

        admin_raw = _s("ADMIN_CHAT_ID")
        admin_id: int | None = None
        if admin_raw:
            try:
                admin_id = int(admin_raw)
            except ValueError:
                raise ConfigError(
                    "В .env строка ADMIN_CHAT_ID должна быть числом. "
                    "Отправьте боту команду /id — он ответит нужным числом."
                )

        data_dir = Path(_s("DATA_DIR", "data"))
        if not data_dir.is_absolute():
            data_dir = ROOT / data_dir

        settings = cls(
            telegram_bot_token=_s("TELEGRAM_BOT_TOKEN"),
            webapp_url=_webapp_url(),
            admin_chat_id=admin_id,
            text_provider=_s("TEXT_PROVIDER", "mock").lower() or "mock",
            image_provider=_s("IMAGE_PROVIDER", "mock").lower() or "mock",
            openai_api_key=_s("OPENAI_API_KEY"),
            openai_base_url=_s("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            openai_text_model=_s("OPENAI_TEXT_MODEL"),
            openai_image_model=_s("OPENAI_IMAGE_MODEL"),
            openai_image_quality=_s("OPENAI_IMAGE_QUALITY", "medium").lower() or "medium",
            gemini_api_key=_s("GEMINI_API_KEY"),
            gemini_model=_s("GEMINI_MODEL"),
            cloudflare_account_id=_s("CLOUDFLARE_ACCOUNT_ID"),
            cloudflare_api_token=_s("CLOUDFLARE_API_TOKEN"),
            cloudflare_image_model=_s("CLOUDFLARE_IMAGE_MODEL"),
            dev_mode=_bool("DEV_MODE", False),
            max_books_per_user_per_day=_int("MAX_BOOKS_PER_USER_PER_DAY", 3),
            keep_files_days=_int("KEEP_FILES_DAYS", 7),
            host=_s("HOST", "127.0.0.1") or "127.0.0.1",
            port=_int("PORT", 8080),
            data_dir=data_dir,
            max_parallel_generations=max(1, _int("MAX_PARALLEL_GENERATIONS", 3)),
            image_concurrency=max(1, _int("IMAGE_CONCURRENCY", 3)),
            mock_delay_seconds=max(0.0, _float("MOCK_DELAY_SECONDS", 1.2)),
        )
        settings.check_provider_names()
        return settings

    # ------------------------------------------------------------------ проверки
    def check_provider_names(self) -> None:
        if self.text_provider not in TEXT_PROVIDERS:
            raise ConfigError(
                f"В .env строка TEXT_PROVIDER = «{self.text_provider}», "
                f"а должна быть одна из: {', '.join(TEXT_PROVIDERS)}."
            )
        if self.image_provider not in IMAGE_PROVIDERS:
            raise ConfigError(
                f"В .env строка IMAGE_PROVIDER = «{self.image_provider}», "
                f"а должна быть одна из: {', '.join(IMAGE_PROVIDERS)}."
            )

    @property
    def secrets(self) -> list[str]:
        """Значения, которые нельзя выводить в логи и ответы."""
        values = [
            self.telegram_bot_token,
            self.openai_api_key,
            self.gemini_api_key,
            self.cloudflare_api_token,
            self.cloudflare_account_id,
        ]
        return [v for v in values if v and len(v) >= 6]

    @property
    def uses_mock(self) -> bool:
        return self.text_provider == "mock" or self.image_provider == "mock"

    @property
    def privacy_warning(self) -> str | None:
        if self.text_provider == "gemini":
            return "Тестовый режим: не вводите настоящие имена и не загружайте фото"
        return None
