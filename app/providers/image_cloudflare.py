"""Cloudflare Workers AI (FLUX.1 schnell), картинки. Бесплатно 10 000 «нейронов» в сутки (сброс в 00:00 UTC).

По документации Cloudflare Workers AI (раздел моделей для картинок) модель принимает только
prompt (до 2048 символов) и steps (до 8) и референсов не принимает, поэтому сходство героя держится
одинаковым подробным описанием в каждом промте.
"""
from __future__ import annotations

import base64
import logging
from typing import Sequence

import httpx

from ..errors import ProviderError
from .base import ImageProvider
from .http import IMAGE_TIMEOUT, error_text, json_body, request_with_retries, safe

log = logging.getLogger(__name__)

API = "https://api.cloudflare.com/client/v4"
MAX_PROMPT = 2048
DEFAULT_STEPS = 4


def _error_code(resp: httpx.Response) -> int | None:
    errors = json_body(resp).get("errors") or []
    if errors and isinstance(errors[0], dict):
        code = errors[0].get("code")
        return code if isinstance(code, int) else None
    return None


def explain_error(resp: httpx.Response, model: str) -> ProviderError:
    status, code, text = resp.status_code, _error_code(resp), error_text(resp)
    if status in (401, 403) or code in (10000, 9109):
        return ProviderError("Cloudflare не принял токен. Проверьте CLOUDFLARE_API_TOKEN и CLOUDFLARE_ACCOUNT_ID в .env: "
                             "токен создаётся на dash.cloudflare.com → Workers AI → Use REST API → Create a Workers AI "
                             "API Token, а Account ID — на той же странице.", fatal=True, status=status)
    if code == 3036:
        return ProviderError("Закончился бесплатный дневной лимит Cloudflare (10 000 «нейронов», это около 170 картинок). "
                             "Он сбросится в 00:00 по UTC (в Бишкеке — в 06:00). Подождите или подключите платный тариф.",
                             fatal=True, status=status)
    if status == 429:
        return ProviderError("Cloudflare временно ограничил частоту запросов. Попробуйте ещё раз через минуту.", status=status)
    if status == 404 or code in (3042, 5007):
        return ProviderError(f"Модель «{model}» не найдена в Cloudflare. Проверьте CLOUDFLARE_IMAGE_MODEL в .env.",
                             fatal=True, status=status)
    if status >= 500:
        return ProviderError(f"Сервис Cloudflare сейчас недоступен ({status}). Попробуйте через несколько минут.", status=status)
    return ProviderError(f"Cloudflare отклонил запрос ({status}): {text}", status=status)


def decode_image(resp: httpx.Response) -> bytes:
    """Ответ — JSON с base64 в result.image или сразу байты картинки."""
    content_type = resp.headers.get("content-type", "")
    if content_type.startswith("image/"):
        return resp.content
    data = json_body(resp)
    result = data.get("result", data)
    image = result.get("image") if isinstance(result, dict) else result if isinstance(result, str) else None
    if not isinstance(image, str) or not image:
        raise ProviderError("Cloudflare вернул ответ без картинки. Попробуйте ещё раз.")
    if image.startswith("data:"):
        image = image.split(",", 1)[-1]
    try:
        return base64.b64decode(image, validate=False)
    except ValueError:
        raise ProviderError("Cloudflare вернул повреждённую картинку. Попробуйте ещё раз.")


class CloudflareImageProvider(ImageProvider):
    name = "cloudflare"
    supports_reference = False       # референсы и фото этой модели не отправляем никогда

    def __init__(self, account_id: str, api_token: str, model: str, steps: int = DEFAULT_STEPS, *,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.account_id = account_id
        self.api_token = api_token
        self.model = model
        self.steps = max(1, min(8, steps))
        self._transport = transport

    @property
    def url(self) -> str:
        return f"{API}/accounts/{self.account_id}/ai/run/{self.model}"

    async def generate(self, prompt: str, refs: Sequence[bytes] | None = None, size: str = "1024x1024",
                       *, label: str | None = None) -> bytes:
        body = {"prompt": prompt[:MAX_PROMPT], "steps": self.steps}      # refs намеренно игнорируются
        async with httpx.AsyncClient(timeout=IMAGE_TIMEOUT, transport=self._transport) as client:
            resp = await request_with_retries(
                client, "POST", self.url, provider="Cloudflare", json=body,
                headers={"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"},
                retryable=lambda r: r.status_code >= 500 or _error_code(r) != 3036,
            )
        if resp.status_code != 200:
            raise explain_error(resp, self.model)
        data = json_body(resp)
        if data and data.get("success") is False:
            raise explain_error(resp, self.model)
        return decode_image(resp)
