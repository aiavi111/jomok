"""Общее для текстового и картиночного провайдеров OpenAI: заголовки и разбор ошибок."""
from __future__ import annotations

import httpx

from ..errors import ProviderError
from .http import error_text, json_body

# По документации OpenAI нехватка денег и лимиты расходов приходят как 429 с такими кодами
# (error.type при этом может оставаться insufficient_quota).
BILLING_CODES = {
    "insufficient_quota", "credit_balance_exhausted", "organization_spend_limit_exceeded",
    "project_spend_limit_exceeded", "organization_usage_limit_exceeded",
}


def headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def error_fields(resp: httpx.Response) -> tuple[str, str]:
    err = json_body(resp).get("error")
    if isinstance(err, dict):
        return str(err.get("code") or ""), str(err.get("type") or "")
    return "", ""


def is_billing_problem(resp: httpx.Response) -> bool:
    code, kind = error_fields(resp)
    return resp.status_code == 429 and (code in BILLING_CODES or kind == "insufficient_quota")


def retryable(resp: httpx.Response) -> bool:
    """429 из-за денег повторять бессмысленно; обычное ограничение частоты и 5xx — повторяем."""
    return not is_billing_problem(resp)


def explain_error(resp: httpx.Response, model: str, *, model_var: str, images: bool = False) -> ProviderError:
    status = resp.status_code
    code, kind = error_fields(resp)
    text = error_text(resp)
    low = text.lower()
    if status == 401:
        return ProviderError("Неверный ключ OpenAI. Проверьте строку OPENAI_API_KEY в .env: ключ создают на "
                             "platform.openai.com → API keys → Create new secret key и копируют целиком (начинается с sk-).",
                             fatal=True, status=status)
    if status == 403 and ("verif" in low or "organization must be" in low):
        return ProviderError("OpenAI просит подтвердить организацию, чтобы пользоваться этой моделью. Откройте "
                             "platform.openai.com → Settings → Organization → General → Verify Organization, пройдите "
                             "проверку (после неё может понадобиться до 15 минут) и повторите.", fatal=True, status=status)
    if status == 403:
        return ProviderError(f"У ключа нет доступа к модели «{model}» (403: {text}). Проверьте {model_var} в .env "
                             "и права проекта в OpenAI.", fatal=True, status=status)
    if status == 404 or code == "model_not_found":
        return ProviderError(f"Модель «{model}» не найдена в OpenAI. Проверьте строку {model_var} в .env. "
                             "Список доступных моделей покажет python check_keys.py.", fatal=True, status=status)
    if is_billing_problem(resp):
        return ProviderError("На счёте OpenAI закончились деньги или достигнут лимит расходов. Пополните баланс: "
                             "platform.openai.com → Settings → Billing (нужно не меньше $5) и проверьте лимиты.",
                             fatal=True, status=status)
    if status == 429:
        return ProviderError("OpenAI ограничил частоту запросов (слишком много сразу). Книга продолжит через минуту; "
                             "если так повторяется, уменьшите IMAGE_CONCURRENCY в .env.", status=status)
    if status >= 500:
        return ProviderError(f"Сервис OpenAI сейчас недоступен ({status}). Попробуйте через несколько минут.", status=status)
    if images and (code == "moderation_blocked" or "safety" in low or "moderation" in low):
        return ProviderError("OpenAI не нарисовал эту картинку: сработал фильтр безопасности. "
                             "На её месте будет заглушка.", no_retry=True, status=status)
    if images:
        return ProviderError(f"OpenAI отклонил запрос на картинку ({status}): {text}", no_retry=True, status=status)
    return ProviderError(f"OpenAI отклонил запрос ({status}): {text}", fatal=True, status=status)
