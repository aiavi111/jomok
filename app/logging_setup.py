"""Логи без секретов: токены и ключи заменяются на «***» в любом сообщении и трейсбеке."""
from __future__ import annotations

import logging
import re
import sys
from typing import Iterable

_PATTERNS = [
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}"),                       # токен Telegram-бота
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),                            # ключи в стиле OpenAI
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),                           # ключи Google
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"),                 # заголовки Authorization
    re.compile(r"(?i)(x-goog-api-key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(\btma\s+)[^\s'\"]{20,}"),                         # initData Mini App
]

MASK = "***"


class Redactor:
    def __init__(self, secrets: Iterable[str] = ()):
        self._secrets: list[str] = []
        self.add(secrets)

    def add(self, secrets: Iterable[str]) -> None:
        for s in secrets:
            if s and len(s) >= 6 and s not in self._secrets:
                self._secrets.append(s)
        # длинные сначала, чтобы часть ключа не осталась снаружи
        self._secrets.sort(key=len, reverse=True)

    def __call__(self, text: str) -> str:
        if not text:
            return text
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, MASK)
        for pattern in _PATTERNS:
            if pattern.groups:
                text = pattern.sub(lambda m: m.group(1) + MASK, text)
            else:
                text = pattern.sub(MASK, text)
        return text


# Общий редактор: в него попадают ключи из настроек; им же пользуются тексты ошибок.
redact = Redactor()


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # включает и трейсбек
        return redact(super().format(record))


def setup_logging(secrets: Iterable[str] = (), level: int = logging.INFO) -> None:
    redact.add(secrets)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)
    # Эти библиотеки печатают адреса запросов, а в адресе Telegram есть токен.
    for noisy in ("httpx", "httpcore", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
