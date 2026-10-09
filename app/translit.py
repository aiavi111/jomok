"""Имя ребёнка латиницей: как модель может записать «Айдар» (Aidar / Aydar / Ajdar).

Нужно, чтобы имя не попало в промты для картинок (prompts.scrub_name) и чтобы счётчик имени в тексте книги
(writer.py) не принимал латинские варианты за чужие слова."""
from __future__ import annotations

_TRANSLIT_BASE = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ү": "u", "ө": "o", "ң": "ng",
}
# разные схемы, которыми модель может записать имя латиницей: Айдар → Aidar / Aydar / Ajdar
_TRANSLIT_PROFILES = [
    {"й": "y", "х": "kh", "ё": "yo", "ң": "ng"},
    {"й": "i", "х": "kh", "ң": "n"},
    {"й": "j", "х": "h", "ң": "n"},
    {"й": "y", "х": "h", "ң": "n", "ү": "uu", "ө": "oo"},
    {"й": "i", "х": "h", "ң": "ng", "ү": "ü", "ө": "ö"},
    {"й": "y", "х": "kh", "ү": "y", "ө": "o", "ң": "n"},
]


def latin_variants(name: str) -> set[str]:
    """Как имя могут записать латиницей (в нижнем регистре)."""
    out: set[str] = set()
    low = name.lower()
    if all(ch.isascii() or not ch.isalpha() for ch in low):
        return {low}
    for profile in _TRANSLIT_PROFILES:
        table = {**_TRANSLIT_BASE, **profile}
        out.add("".join(table.get(ch, ch) for ch in low))
        if low[:1] == "е":                                   # Егор → Yegor
            out.add("y" + "".join(table.get(ch, ch) for ch in low))
    return {v for v in out if len(v) >= 2}
