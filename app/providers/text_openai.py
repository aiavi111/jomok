"""OpenAI, текст: POST {OPENAI_BASE_URL}/chat/completions.

Параметры temperature и max_tokens не передаются: модели GPT-6 — «думающие», для них temperature недоступна,
а лимит задаётся другим параметром (max_completion_tokens), который нам не нужен.
Ответ просим в режиме JSON (response_format = json_object); слово JSON есть в инструкции.
"""
from __future__ import annotations

import logging

import httpx

from ..errors import ProviderError
from .base import TextProvider
from .http import TEXT_TIMEOUT, json_body, request_with_retries, error_text
from .openai_common import explain_error, headers, retryable

log = logging.getLogger(__name__)


class OpenAITextProvider(TextProvider):
    name = "openai"

    def __init__(self, api_key: str, base_url: str, model: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._transport = transport
        self._json_mode = True

    def _body(self, system: str, messages: list[tuple[str, str]]) -> dict:
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}]
            + [{"role": role, "content": text} for role, text in messages],
        }
        if self._json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    async def _post(self, client: httpx.AsyncClient, system: str, messages: list[tuple[str, str]]) -> httpx.Response:
        return await request_with_retries(
            client, "POST", f"{self.base_url}/chat/completions", provider="OpenAI",
            headers=headers(self.api_key), json=self._body(system, messages), retryable=retryable,
        )

    async def _complete(self, system: str, messages: list[tuple[str, str]]) -> str:
        async with httpx.AsyncClient(timeout=TEXT_TIMEOUT, transport=self._transport) as client:
            resp = await self._post(client, system, messages)
            if resp.status_code == 400 and self._json_mode and "response_format" in error_text(resp).lower():
                log.warning("Модель не принимает response_format — продолжаю без него, JSON проверяется всё равно")
                self._json_mode = False
                resp = await self._post(client, system, messages)
        if resp.status_code != 200:
            raise explain_error(resp, self.model, model_var="OPENAI_TEXT_MODEL")
        choices = json_body(resp).get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        if message.get("refusal"):
            raise ProviderError("OpenAI отказался писать эту сказку. Попробуйте изменить анкету.", no_retry=True)
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("OpenAI вернул пустой ответ. Попробуйте ещё раз.")
        return content
