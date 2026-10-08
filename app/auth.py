"""Проверка подписи initData из Telegram Mini App.

Алгоритм — из официальной инструкции Telegram (раздел «Validating data received via the Mini App»):
  secret_key        = HMAC_SHA256(ключ = "WebAppData", сообщение = токен бота)
  data_check_string = все полученные поля, кроме hash, по алфавиту, «key=value» через перевод строки
  hash              = hex(HMAC_SHA256(ключ = secret_key, сообщение = data_check_string))
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from .errors import AuthError

log = logging.getLogger(__name__)

MAX_AGE_SECONDS = 24 * 60 * 60     # initData старше 24 часов отклоняем
FUTURE_SKEW_SECONDS = 5 * 60       # допуск на разницу часов

NOT_FROM_TELEGRAM = ("Не удалось проверить, что запрос пришёл из Telegram. "
                     "Закройте приложение и откройте его снова через бота кнопкой «Создать сказку».")
EXPIRED = ("Сессия устарела. Закройте приложение и откройте его снова через бота, "
           "чтобы продолжить.")


@dataclass(frozen=True)
class TgUser:
    id: int
    first_name: str = ""
    username: str | None = None
    language_code: str | None = None


def compute_hash(fields: dict[str, str], bot_token: str) -> str:
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def _parse(init_data: str) -> dict[str, str]:
    pairs = parse_qsl(init_data, keep_blank_values=True)
    fields: dict[str, str] = {}
    for key, value in pairs:
        if key in fields:
            raise AuthError(NOT_FROM_TELEGRAM)       # повторяющиеся поля — подделка
        fields[key] = value
    return fields


def _user_from(fields: dict[str, str]) -> TgUser:
    try:
        raw = json.loads(fields["user"])
        return TgUser(
            id=int(raw["id"]),
            first_name=str(raw.get("first_name") or ""),
            username=raw.get("username"),
            language_code=raw.get("language_code"),
        )
    except (KeyError, ValueError, TypeError):
        raise AuthError(NOT_FROM_TELEGRAM)


def verify_init_data(init_data: str, bot_token: str, *, max_age: int = MAX_AGE_SECONDS,
                     now: float | None = None) -> TgUser:
    """Проверяет подпись и возраст initData; возвращает пользователя из проверенных данных."""
    if not init_data or not bot_token:
        raise AuthError(NOT_FROM_TELEGRAM)
    fields = _parse(init_data)
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise AuthError(NOT_FROM_TELEGRAM)
    if not hmac.compare_digest(compute_hash(fields, bot_token), received_hash):
        raise AuthError(NOT_FROM_TELEGRAM)
    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError):
        raise AuthError(NOT_FROM_TELEGRAM)
    current = time.time() if now is None else now
    if current - auth_date > max_age:
        raise AuthError(EXPIRED)
    if auth_date - current > FUTURE_SKEW_SECONDS:
        raise AuthError(NOT_FROM_TELEGRAM)
    return _user_from(fields)


def authenticate(header: str, bot_token: str, *, dev_mode: bool, dev_user_id: int = 1) -> TgUser:
    """header — значение заголовка Authorization: «tma <initData>»."""
    scheme, _, init_data = (header or "").partition(" ")
    if scheme.lower() != "tma" or not init_data.strip():
        if dev_mode:
            return TgUser(id=dev_user_id, first_name="Разработчик")
        raise AuthError(NOT_FROM_TELEGRAM)
    init_data = init_data.strip()
    if dev_mode:
        # В режиме разработки подпись не обязательна: «tma dev» или «tma dev:42» (номер тестового пользователя).
        if init_data == "dev" or init_data.startswith("dev:"):
            try:
                uid = int(init_data.split(":", 1)[1]) if ":" in init_data else dev_user_id
            except ValueError:
                uid = dev_user_id
            return TgUser(id=uid, first_name="Разработчик")
        try:
            return verify_init_data(init_data, bot_token)
        except AuthError:
            try:
                return _user_from(_parse(init_data))      # без проверки подписи, только для разработки
            except AuthError:
                return TgUser(id=dev_user_id, first_name="Разработчик")
    return verify_init_data(init_data, bot_token)
