"""Общие правила исходящих запросов: таймауты, повторы при 429/5xx/таймауте с растущей паузой
и учётом Retry-After, русские сообщения об ошибках. Ключи в тексты ошибок не попадают."""
from __future__ import annotations

import asyncio
import email.utils
import json
import logging
import random
import time
from typing import Callable

import httpx

from ..errors import ProviderError
from ..logging_setup import redact

log = logging.getLogger(__name__)

TEXT_TIMEOUT = httpx.Timeout(120.0, connect=15.0)
IMAGE_TIMEOUT = httpx.Timeout(300.0, connect=15.0)
MAX_ATTEMPTS = 4
BASE_DELAY = 2.0
MAX_DELAY = 60.0           # дольше одной паузы не ждём
GIVE_UP_AFTER = 120.0      # если сервис просит подождать дольше — не повторяем, а объясняем причину

_sleep = asyncio.sleep     # в тестах подменяется, чтобы не ждать по-настоящему


def safe(text: str, limit: int = 300) -> str:
    """Текст для сообщения об ошибке: без ключей и без лишней длины."""
    text = redact(" ".join(str(text).split()))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def retry_after_seconds(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
        return max(0.0, when.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


def backoff(attempt: int) -> float:
    return min(MAX_DELAY, BASE_DELAY * (2 ** attempt)) + random.uniform(0, 0.5)


def json_body(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except (ValueError, json.JSONDecodeError):
        return {}


async def request_with_retries(
    client: httpx.AsyncClient, method: str, url: str, *, provider: str, attempts: int = MAX_ATTEMPTS,
    retryable: Callable[[httpx.Response], bool] | None = None,
    delay_hint: Callable[[httpx.Response], float | None] | None = None,
    **kwargs,
) -> httpx.Response:
    """Возвращает ответ (в том числе с кодом ошибки — его разбирает провайдер).
    Повторяет при 429, 5xx, таймауте и обрыве связи; паузы растут, Retry-After учитывается.
    Бросает ProviderError, только если связи так и не было."""
    last: ProviderError | None = None
    for attempt in range(attempts):
        try:
            resp = await client.request(method, url, **kwargs)
        except httpx.TimeoutException:
            last = ProviderError(f"{provider}: сервис не ответил вовремя (таймаут). Попробуйте ещё раз позже.")
            delay = backoff(attempt)
        except httpx.HTTPError as e:
            last = ProviderError(f"{provider}: нет связи с сервисом ({type(e).__name__}). Проверьте интернет.")
            delay = backoff(attempt)
        else:
            if resp.status_code != 429 and resp.status_code < 500:
                return resp
            if retryable is not None and not retryable(resp):
                return resp
            if attempt == attempts - 1:
                return resp
            delay = retry_after_seconds(resp)
            if delay is None and delay_hint is not None:
                delay = delay_hint(resp)
            if delay is None:
                delay = backoff(attempt)
            if delay > GIVE_UP_AFTER:
                return resp
            delay = min(delay, MAX_DELAY)
        if attempt == attempts - 1:
            break
        log.warning("%s: повтор через %.1f с (попытка %s из %s)", provider, delay, attempt + 1, attempts)
        await _sleep(delay)
    assert last is not None
    raise last


def error_text(resp: httpx.Response) -> str:
    """Короткий текст ошибки из ответа сервиса (без ключей)."""
    data = json_body(resp)
    err = data.get("error")
    if isinstance(err, dict):
        return safe(err.get("message") or json.dumps(err, ensure_ascii=False))
    if isinstance(err, str):
        return safe(err)
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        return safe(first.get("message") if isinstance(first, dict) else first)
    return safe(resp.text[:200]) if resp.text else f"код {resp.status_code}"
