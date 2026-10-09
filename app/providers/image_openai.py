"""OpenAI, картинки (модели GPT Image).

Без референсов: POST /images/generations (model, prompt, size, quality, n).
С референсами:  POST /images/edits — тело JSON с массивом images из {image_url: data-URL base64}, до 16 штук;
если API не принимает JSON, тот же запрос повторяется как multipart с полями image[].
Параметр input_fidelity для этих моделей не передаётся. Ответ: data[0].b64_json.
"""
from __future__ import annotations

import base64
import logging
from typing import Sequence

import httpx

from ..errors import ProviderError
from .base import ImageProvider
from .http import IMAGE_TIMEOUT, error_text, json_body, request_with_retries
from .openai_common import explain_error, headers, retryable

log = logging.getLogger(__name__)

MAX_REFS = 16
QUALITIES = ("low", "medium", "high", "auto", "xhigh", "max")


def mime_of(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def data_url(data: bytes) -> str:
    return f"data:{mime_of(data)};base64,{base64.b64encode(data).decode()}"


class OpenAIImageProvider(ImageProvider):
    name = "openai"
    supports_reference = True
    renders_text = True           # GPT Image хорошо рисует кириллицу, название пишется на обложке картинкой

    def __init__(self, api_key: str, base_url: str, model: str, quality: str = "medium", *,
                 transport: httpx.AsyncBaseTransport | None = None):
        if quality not in QUALITIES:
            log.warning("OPENAI_IMAGE_QUALITY=%s не из списка %s, использую medium", quality, QUALITIES)
            quality = "medium"
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.quality = quality
        self._transport = transport

    def _fields(self, prompt: str, size: str) -> dict:
        return {"model": self.model, "prompt": prompt, "size": size, "quality": self.quality, "n": 1}

    async def _edit(self, client: httpx.AsyncClient, prompt: str, refs: list[bytes], size: str) -> httpx.Response:
        url = f"{self.base_url}/images/edits"
        body = {**self._fields(prompt, size), "images": [{"image_url": data_url(r)} for r in refs]}
        resp = await request_with_retries(client, "POST", url, provider="OpenAI", headers=headers(self.api_key),
                                          json=body, retryable=retryable)
        if resp.status_code in (400, 415, 422) and _format_problem(resp):
            log.warning("OpenAI не принял JSON в /images/edits — повторяю как multipart (image[])")
            fields = {k: str(v) for k, v in self._fields(prompt, size).items()}
            files = [("image[]", (f"ref{i}.{mime_of(r).split('/')[1]}", r, mime_of(r))) for i, r in enumerate(refs, 1)]
            resp = await request_with_retries(client, "POST", url, provider="OpenAI", headers=headers(self.api_key),
                                              data=fields, files=files, retryable=retryable)
        return resp

    async def generate(self, prompt: str, refs: Sequence[bytes] | None = None, size: str = "1024x1024",
                       *, label: str | None = None) -> bytes:
        refs_list = list(refs)[:MAX_REFS] if refs else []
        async with httpx.AsyncClient(timeout=IMAGE_TIMEOUT, transport=self._transport) as client:
            if refs_list:
                resp = await self._edit(client, prompt, refs_list, size)
            else:
                resp = await request_with_retries(
                    client, "POST", f"{self.base_url}/images/generations", provider="OpenAI",
                    headers=headers(self.api_key), json=self._fields(prompt, size), retryable=retryable)
        if resp.status_code != 200:
            raise explain_error(resp, self.model, model_var="OPENAI_IMAGE_MODEL", images=True)
        items = json_body(resp).get("data") or []
        b64 = items[0].get("b64_json") if items and isinstance(items[0], dict) else None
        if not b64:
            raise ProviderError("OpenAI вернул ответ без картинки. Попробуйте ещё раз.")
        try:
            return base64.b64decode(b64)
        except ValueError:
            raise ProviderError("OpenAI вернул повреждённую картинку. Попробуйте ещё раз.")


def _format_problem(resp: httpx.Response) -> bool:
    """Ошибка именно про формат тела (а не про фильтр безопасности или ключ)."""
    if resp.status_code == 415:
        return True
    low = error_text(resp).lower()
    if "moderation" in low or "safety" in low:
        return False
    return any(w in low for w in ("multipart", "content-type", "form", "json", "image[]", "invalid file", "image_url"))
