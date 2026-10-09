"""Выбор провайдеров по настройкам из .env."""
from __future__ import annotations

from ..config import ConfigError, Settings
from .base import ImageProvider, TextProvider


def _need(value: str, var: str, provider_var: str, provider: str) -> None:
    if not value:
        raise ConfigError(
            f"В .env указано {provider_var}={provider}, но строка {var} пустая. "
            f"Заполните её (где взять — в README.md) или верните {provider_var}=mock."
        )


def make_text_provider(s: Settings) -> TextProvider:
    if s.text_provider == "mock":
        from .text_mock import MockTextProvider
        return MockTextProvider(delay=s.mock_delay_seconds)
    if s.text_provider == "openai":
        _need(s.openai_api_key, "OPENAI_API_KEY", "TEXT_PROVIDER", "openai")
        _need(s.openai_text_model, "OPENAI_TEXT_MODEL", "TEXT_PROVIDER", "openai")
        from .text_openai import OpenAITextProvider
        provider = OpenAITextProvider(s.openai_api_key, s.openai_base_url, s.openai_text_model,
                                      proof_model=s.text_proof_model)
        provider.simple_writer = s.writer_mode == "simple"
        provider.effort = s.openai_text_effort
        return provider
    if s.text_provider == "gemini":
        _need(s.gemini_api_key, "GEMINI_API_KEY", "TEXT_PROVIDER", "gemini")
        _need(s.gemini_model, "GEMINI_MODEL", "TEXT_PROVIDER", "gemini")
        from .text_gemini import GeminiTextProvider
        provider = GeminiTextProvider(s.gemini_api_key, s.gemini_model, proof_model=s.text_proof_model)
        provider.simple_writer = s.writer_mode == "simple"
        return provider
    raise ConfigError(f"Неизвестный TEXT_PROVIDER: {s.text_provider}")


def make_image_provider(s: Settings) -> ImageProvider:
    if s.image_provider == "mock":
        from .image_mock import MockImageProvider
        return MockImageProvider(delay=s.mock_delay_seconds)
    if s.image_provider == "openai":
        _need(s.openai_api_key, "OPENAI_API_KEY", "IMAGE_PROVIDER", "openai")
        _need(s.openai_image_model, "OPENAI_IMAGE_MODEL", "IMAGE_PROVIDER", "openai")
        from .image_openai import OpenAIImageProvider
        return OpenAIImageProvider(s.openai_api_key, s.openai_base_url, s.openai_image_model,
                                   s.openai_image_quality)
    if s.image_provider == "cloudflare":
        _need(s.cloudflare_account_id, "CLOUDFLARE_ACCOUNT_ID", "IMAGE_PROVIDER", "cloudflare")
        _need(s.cloudflare_api_token, "CLOUDFLARE_API_TOKEN", "IMAGE_PROVIDER", "cloudflare")
        _need(s.cloudflare_image_model, "CLOUDFLARE_IMAGE_MODEL", "IMAGE_PROVIDER", "cloudflare")
        from .image_cloudflare import CloudflareImageProvider
        return CloudflareImageProvider(s.cloudflare_account_id, s.cloudflare_api_token, s.cloudflare_image_model)
    raise ConfigError(f"Неизвестный IMAGE_PROVIDER: {s.image_provider}")
