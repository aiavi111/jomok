"""Gemini (Google), текст. Только для теста с вымышленными данными: на бесплатном тарифе
Google использует присланное для улучшения своих продуктов.

Запрос — по документации https://ai.google.dev/api/generate-content:
POST /v1beta/models/{model}:generateContent, заголовок x-goog-api-key.
"""
from __future__ import annotations

import logging

import httpx

from ..errors import ProviderError
from .base import TextProvider
from .http import TEXT_TIMEOUT, error_text, json_body, request_with_retries, safe

log = logging.getLogger(__name__)

BASE = "https://generativelanguage.googleapis.com/v1beta"
# Gemini 3.x по умолчанию «думает», а мысли входят в лимит ответа — поэтому лимит большой
MAX_OUTPUT_TOKENS = 16384


def _retry_delay_from_error(resp: httpx.Response) -> float | None:
    """Gemini может прислать error.details[].retryDelay вида "34s"."""
    details = (json_body(resp).get("error") or {}).get("details") or []
    for item in details:
        delay = item.get("retryDelay") if isinstance(item, dict) else None
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                return None
    return None


def _retryable(resp: httpx.Response) -> bool:
    """5xx и короткие паузы 429 повторяем; дневной лимит (PerDay) и долгие паузы — нет."""
    if resp.status_code >= 500:
        return True
    if "perday" in error_text(resp).lower().replace(" ", ""):
        return False
    return (_retry_delay_from_error(resp) or 0) <= 120


def explain_error(resp: httpx.Response, model: str, model_var: str = "GEMINI_MODEL") -> ProviderError:
    status = resp.status_code
    text = error_text(resp)
    low = text.lower()
    if status in (400, 401, 403) and ("api key" in low or "api_key" in low or "credential" in low or status == 401):
        return ProviderError("Неверный ключ Gemini. Проверьте строку GEMINI_API_KEY в .env: ключ берут на "
                             "aistudio.google.com (кнопка Get API key) и копируют целиком.", fatal=True, status=status)
    if status == 403:
        return ProviderError(f"Gemini не пускает с этим ключом (403): {text}. Проверьте, что в проекте Google "
                             "включён Gemini API и ключ не ограничен по адресам.", fatal=True, status=status)
    if status == 404:
        return ProviderError(f"Модель «{model}» не найдена в Gemini. Проверьте строку {model_var} в .env. "
                             "Список доступных моделей покажет python check_keys.py.", fatal=True, status=status)
    if status == 429:
        wait = _retry_delay_from_error(resp)
        if wait is not None and wait <= 120 and "perday" not in low.replace(" ", ""):
            return ProviderError("Gemini временно ограничил частоту запросов. Попробуйте через минуту.", status=status)
        return ProviderError("Закончился дневной лимит бесплатного тарифа Gemini (или он равен нулю для этой модели). "
                             f"Подождите до завтра, выберите другую модель в {model_var} или подключите оплату "
                             "в aistudio.google.com.", fatal=True, status=status)
    if status >= 500:
        return ProviderError(f"Сервис Gemini сейчас недоступен ({status}). Попробуйте через несколько минут.", status=status)
    return ProviderError(f"Gemini отклонил запрос ({status}): {text}", fatal=True, status=status)


class GeminiTextProvider(TextProvider):
    polish = True
    name = "gemini"

    def __init__(self, api_key: str, model: str, *, proof_model: str = "",
                 transport: httpx.AsyncBaseTransport | None = None):
        self.api_key = api_key
        self.model = model.removeprefix("models/")
        self.proof_model = proof_model.removeprefix("models/")
        self._transport = transport

    def _body(self, system: str, messages: list[tuple[str, str]]) -> dict:
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]}
                for role, text in messages
            ],
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": MAX_OUTPUT_TOKENS},
        }

    async def _complete(self, system: str, messages: list[tuple[str, str]], model: str | None = None) -> str:
        """model — другая модель только на этот запрос (вычитка кыргызского, TEXT_PROOF_MODEL)."""
        used = (model or self.model).removeprefix("models/")
        url = f"{BASE}/models/{used}:generateContent"
        async with httpx.AsyncClient(timeout=TEXT_TIMEOUT, transport=self._transport) as client:
            resp = await request_with_retries(
                client, "POST", url, provider="Gemini",
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                json=self._body(system, messages), delay_hint=_retry_delay_from_error,
                retryable=_retryable,
            )
        if resp.status_code != 200:
            raise explain_error(resp, used, "TEXT_PROOF_MODEL" if model else "GEMINI_MODEL")
        data = json_body(resp)
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "нет ответа")
            raise ProviderError(f"Gemini не вернул текст ({safe(reason)}). Попробуйте ещё раз.", no_retry=True)
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
        if not text.strip():
            finish = candidates[0].get("finishReason", "")
            raise ProviderError(f"Gemini вернул пустой ответ ({safe(finish)}). Попробуйте ещё раз.")
        return text
