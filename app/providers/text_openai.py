"""OpenAI, текст: POST {OPENAI_BASE_URL}/chat/completions.

Параметры temperature и max_tokens не передаются: модели GPT-6 — «думающие», для них temperature недоступна,
а лимит задаётся другим параметром (max_completion_tokens), который нам не нужен.
Ответ просим в режиме JSON (response_format = json_object); слово JSON есть в инструкции.
"""
from __future__ import annotations

import base64
import json
import logging

import httpx

from ..errors import ProviderError
from .base import TextProvider
from .http import TEXT_TIMEOUT, json_body, request_with_retries, error_text
from .openai_common import explain_error, headers, retryable

log = logging.getLogger(__name__)


class OpenAITextProvider(TextProvider):
    polish = True
    name = "openai"

    def __init__(self, api_key: str, base_url: str, model: str, *, proof_model: str = "",
                 transport: httpx.AsyncBaseTransport | None = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.proof_model = proof_model
        self._transport = transport
        self._json_mode = True
        self.effort = ""            # reasoning_effort (OPENAI_TEXT_EFFORT); пусто — не передаём, модель решает сама

    def _body(self, system: str, messages: list[tuple[str, str]], model: str | None = None) -> dict:
        body: dict = {
            "model": model or self.model,
            "messages": [{"role": "system", "content": system}]
            + [{"role": role, "content": text} for role, text in messages],
        }
        if self._json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.effort and not model:
            body["reasoning_effort"] = self.effort      # только основная модель: у вычитки (TEXT_PROOF_MODEL) может быть другой набор режимов
        return body

    async def _post(self, client: httpx.AsyncClient, system: str, messages: list[tuple[str, str]],
                    model: str | None = None) -> httpx.Response:
        return await request_with_retries(
            client, "POST", f"{self.base_url}/chat/completions", provider="OpenAI",
            headers=headers(self.api_key), json=self._body(system, messages, model), retryable=retryable,
        )

    async def _complete(self, system: str, messages: list[tuple[str, str]], model: str | None = None) -> str:
        """model — другая модель только на этот запрос (вычитка кыргызского, TEXT_PROOF_MODEL)."""
        async with httpx.AsyncClient(timeout=TEXT_TIMEOUT, transport=self._transport) as client:
            resp = await self._post(client, system, messages, model)
            if resp.status_code == 400 and self._json_mode and "response_format" in error_text(resp).lower():
                log.warning("Модель не принимает response_format — продолжаю без него, JSON проверяется всё равно")
                self._json_mode = False
                resp = await self._post(client, system, messages, model)
        if resp.status_code != 200:
            raise explain_error(resp, model or self.model,
                                model_var="TEXT_PROOF_MODEL" if model else "OPENAI_TEXT_MODEL")
        choices = json_body(resp).get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        if message.get("refusal"):
            raise ProviderError("OpenAI отказался писать эту книгу. Попробуйте изменить анкету.", no_retry=True)
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("OpenAI вернул пустой ответ. Попробуйте ещё раз.")
        return content

    async def read_cover_text(self, image: bytes) -> str | None:
        """Просит модель прочитать название, нарисованное на обложке, буква в букву (без исправления ошибок)."""
        url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": (
                    "This is the front cover of a children's book. Read the large title lettering exactly as it is "
                    "printed, letter by letter. Do NOT correct spelling and do not guess: if a letter looks wrong, "
                    "write the wrong letter. Ignore any small text. Return JSON: {\"title\": \"<text as printed>\"}.")},
                {"type": "image_url", "image_url": {"url": url}},
            ]}],
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=TEXT_TIMEOUT, transport=self._transport) as client:
                resp = await request_with_retries(client, "POST", f"{self.base_url}/chat/completions", provider="OpenAI",
                                                  headers=headers(self.api_key), json=body, retryable=retryable)
            if resp.status_code != 200:
                log.warning("Проверка надписи на обложке недоступна (%s)", resp.status_code)
                return None
            content = ((json_body(resp).get("choices") or [{}])[0].get("message") or {}).get("content")
            data = json.loads(content) if isinstance(content, str) else None
            title = data.get("title") if isinstance(data, dict) else None
            return title if isinstance(title, str) else None
        except (ProviderError, ValueError, httpx.HTTPError):
            log.warning("Не удалось проверить надпись на обложке")
            return None
