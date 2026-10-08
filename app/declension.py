"""Родительный падеж имени для подписей «Сказка для …» (по правилам, зная пол ребёнка).

Это простое правило для типичных русских и кыргызских имён. Редкие имена оно может
склонить неточно — тогда имя остаётся без изменений, что всегда читается нормально.
"""
from __future__ import annotations

_CYR = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюяүөңӨҮҢ")
_HUSH = "гкхжчшщ"
_INDECLINABLE_ENDINGS = "еёиоуыэю"

_EXCEPTIONS = {
    "павел": "Павла", "лев": "Льва", "пётр": "Петра", "петр": "Петра",
    "любовь": "Любови",
}


def _is_cyrillic(word: str) -> bool:
    letters = [ch.lower() for ch in word if ch.isalpha()]
    return bool(letters) and all(ch in _CYR for ch in letters)


def _decline_word(word: str, boy: bool) -> str:
    low = word.lower()
    if low in _EXCEPTIONS:
        return _EXCEPTIONS[low]
    if not _is_cyrillic(word) or len(word) < 2:
        return word
    last = low[-1]
    stem = word[:-1]
    if last in _INDECLINABLE_ENDINGS:
        return word
    if last == "а":
        return stem + ("и" if low[-2] in _HUSH else "ы")
    if last == "я":
        if low[-2] in "иеая":      # Мария → Марии, Алия → Алии
            return stem + "и"
        return stem + "и"          # Таня → Тани
    if last == "й":
        return stem + "я" if boy else word
    if last == "ь":
        if boy:
            return stem + "я"
        return stem + "и" if low == "любовь" else word
    # оканчивается на согласную
    return word + "а" if boy else word


def genitive_ru(name: str, gender: str) -> str:
    """«Айдар» → «Айдара», «Алина» → «Алины», девочке «Айгүл» → «Айгүл»."""
    name = name.strip()
    if not name:
        return name
    boy = gender != "girl"
    # склоняем только последнюю часть: «Анна-Мария» → «Анна-Марии»
    for sep in (" ", "-"):
        if sep in name:
            head, _, tail = name.rpartition(sep)
            return head + sep + genitive_ru(tail, gender)
    return _decline_word(name, boy)
