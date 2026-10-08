"""Подписанные ссылки на файлы заказа.

Картинки в <img> и скачивание PDF не умеют отправлять заголовок Authorization, поэтому
владелец заказа (проверенный по initData) получает в ответе API короткоживущие ссылки с подписью.
Ссылка привязана к заказу и его владельцу; чужой человек её не получит.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path

BUCKET = 3600           # ссылка не меняется в течение часа — браузер кэширует картинки
TTL = 6 * 3600          # и живёт ещё несколько часов


def load_or_create_secret(data_dir: Path) -> bytes:
    path = Path(data_dir) / "link_secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        value = path.read_text().strip()
        if len(value) >= 32:
            return value.encode()
    value = secrets.token_hex(32)
    path.write_text(value)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value.encode()


def _sign(secret: bytes, order_id: str, user_id: int, exp: int) -> str:
    msg = f"{order_id}|{user_id}|{exp}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:32]


def make_token(secret: bytes, order_id: str, user_id: int, *, now: float | None = None) -> str:
    current = int(time.time() if now is None else now)
    exp = (current // BUCKET + 1) * BUCKET + TTL
    return f"{exp}.{_sign(secret, order_id, user_id, exp)}"


def check_token(secret: bytes, order_id: str, user_id: int, token: str | None, *, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    exp_text, _, sig = token.partition(".")
    try:
        exp = int(exp_text)
    except ValueError:
        return False
    current = time.time() if now is None else now
    if exp < current:
        return False
    return hmac.compare_digest(_sign(secret, order_id, user_id, exp), sig)
