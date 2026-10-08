"""Очистка пользовательского текста и мелкие помощники для строк."""
from __future__ import annotations

import re
import unicodedata

# управляющие, невидимые и «разворачивающие» символы
_STRIP = re.compile("[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f"
                    "​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_SPACES = re.compile(r"\s+")


def clean_text(value, *, keep_newlines: bool = False) -> str:
    """Убирает управляющие символы, угловые скобки и лишние пробелы. Длину не режет."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFC", str(value))
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _STRIP.sub("", s)
    s = s.replace("<", "").replace(">", "")
    if keep_newlines:
        lines = [_SPACES.sub(" ", line).strip() for line in s.split("\n")]
        s = "\n".join(line for line in lines if line)
    else:
        s = _SPACES.sub(" ", s)
    return s.strip()


def cyrillic_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    cyr = sum(1 for ch in letters if "Ѐ" <= ch <= "ӿ")
    return cyr / len(letters)


def word_count(text: str) -> int:
    return len(text.split())


def cap_first(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def cut_words(text: str, limit: int) -> str:
    """Обрезает по границе слова, не превышая limit символов."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    return cut or text[:limit]


def ru_plural(n: int, one: str, few: str, many: str) -> str:
    """ru_plural(3, 'сказку', 'сказки', 'сказок') -> 'сказки'."""
    n = abs(int(n))
    if n % 100 in (11, 12, 13, 14):
        return many
    if n % 10 == 1:
        return one
    if n % 10 in (2, 3, 4):
        return few
    return many


def human_wait(seconds: float) -> str:
    """5400 -> '1 ч 30 мин'."""
    minutes = max(1, int(round(seconds / 60)))
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"
