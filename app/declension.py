"""Родительный падеж имени для подписей «Книга для …» (по правилам, зная пол ребёнка).

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


# ======================================================================== все падежи имени по-русски
RU_CASES = ("nom", "gen", "dat", "acc", "ins", "prep")
RU_CASE_LABELS = {"nom": "именительный", "gen": "родительный", "dat": "дательный", "acc": "винительный",
                  "ins": "творительный", "prep": "предложный"}
_VOWELS_RU = "аеёиоуыэюяүө"
_HUSH_C = "жчшщц"

# имена с беглой гласной и другие исключения: (род., дат., вин., твор., предл.)
_EXCEPTION_FORMS = {
    "павел": ("Павла", "Павлу", "Павла", "Павлом", "Павле"),
    "лев": ("Льва", "Льву", "Льва", "Львом", "Льве"),
    "пётр": ("Петра", "Петру", "Петра", "Петром", "Петре"),
    "петр": ("Петра", "Петру", "Петра", "Петром", "Петре"),
    "любовь": ("Любови", "Любови", "Любовь", "Любовью", "Любови"),
}


def _same(word: str) -> dict[str, str]:
    return {case: word for case in RU_CASES}


def _ru_word_forms(word: str, boy: bool) -> dict[str, str]:
    low = word.lower()
    forms = _same(word)
    if low in _EXCEPTION_FORMS:
        forms.update(zip(("gen", "dat", "acc", "ins", "prep"), _EXCEPTION_FORMS[low]))
        return forms
    if not _is_cyrillic(word) or len(word) < 2:
        return forms
    last, prev, stem = low[-1], low[-2], word[:-1]
    if last in _INDECLINABLE_ENDINGS or last in "үө":
        return forms
    if last == "а":                                   # Алина, Айдана, Никита
        forms.update(gen=stem + ("и" if prev in _HUSH else "ы"), dat=stem + "е", acc=stem + "у",
                     ins=stem + ("ей" if prev in _HUSH_C else "ой"), prep=stem + "е")
    elif last == "я":
        if prev == "и":                               # Мария, Алия
            forms.update(gen=stem + "и", dat=stem + "и", acc=stem + "ю", ins=stem + "ей", prep=stem + "и")
        elif prev == "ь":                             # Илья
            forms.update(gen=stem + "и", dat=stem + "е", acc=stem + "ю", ins=stem + "ёй", prep=stem + "е")
        else:                                         # Таня, Ваня
            forms.update(gen=stem + "и", dat=stem + "е", acc=stem + "ю", ins=stem + "ей", prep=stem + "е")
    elif last == "й":
        if boy:                                       # Андрей, Алтынбай, Дмитрий
            forms.update(gen=stem + "я", dat=stem + "ю", acc=stem + "я", ins=stem + "ем",
                         prep=stem + ("и" if prev == "и" else "е"))
    elif last == "ь":
        if boy:                                       # Игорь
            forms.update(gen=stem + "я", dat=stem + "ю", acc=stem + "я", ins=stem + "ем", prep=stem + "е")
    elif boy:                                         # Айдар, Нурбек
        forms.update(gen=word + "а", dat=word + "у", acc=word + "а",
                     ins=word + ("ем" if last in _HUSH_C else "ом"), prep=word + "е")
    return forms


def ru_forms(name: str, gender: str) -> dict[str, str]:
    """Все шесть падежей имени по-русски: {"nom": "Айдар", "gen": "Айдара", "dat": "Айдару", "acc": "Айдара",
    "ins": "Айдаром", "prep": "Айдаре"}. Женские имена на согласную и имена на гласную (кроме а, я) не склоняются.
    Родительный падеж совпадает с genitive_ru. Составное имя склоняется по последней части."""
    name = name.strip()
    if not name:
        return _same(name)
    boy = gender != "girl"
    for sep in (" ", "-"):
        if sep in name:
            head, _, tail = name.rpartition(sep)
            forms = ru_forms(tail, gender)
            return {case: (head + sep + form if case != "nom" else name) for case, form in forms.items()}
    forms = _ru_word_forms(name, boy)
    forms["nom"] = name
    forms["gen"] = genitive_ru(name, gender)
    return forms


# ===================================================================== падежи имени по-кыргызски
KY_CASES = ("nom", "gen", "dat", "acc", "abl", "loc")
KY_CASE_LABELS = {"nom": "атооч (именительный)", "gen": "илик (родительный)", "dat": "барыш (дательный: кому? куда?)",
                  "acc": "табыш (винительный)", "abl": "чыгыш (исходный: откуда? от кого?)",
                  "loc": "жатыш (местный: где? у кого?)"}
_KY_VOWELS = "аоуыэеиөүяюё"
_KY_VOICELESS = "кпстфхцчшщ"
_KY_FOUR = {"а": "ы", "я": "ы", "ы": "ы", "о": "у", "ё": "у", "у": "у", "ю": "у",
            "э": "и", "е": "и", "и": "и", "ө": "ү", "ү": "ү"}          # гласная окончаний -ын/-ин/-ун/-үн
_KY_TWO = {"а": "а", "я": "а", "ы": "а", "у": "а", "ю": "а", "о": "о", "ё": "о",
           "э": "е", "е": "е", "и": "е", "ө": "ө", "ү": "ө"}            # гласная окончаний -га/-ге/-го/-гө, -да/-де/-до/-дө


def _ky_last_vowel(word: str) -> str:
    for ch in reversed(word.lower()):
        if ch in _KY_VOWELS:
            return ch
    return "а"


def _ky_word_forms(word: str) -> dict[str, str]:
    low = word.lower()
    last = low[-1]
    vowel = _ky_last_vowel(low)
    four, two = _KY_FOUR[vowel], _KY_TWO[vowel]
    if last in _KY_VOWELS or last in "ъь":
        n_d, g_k, d_t = "н", "г", "д"                 # после гласной: -нын, -га, -да
        if last in "ъь":
            n_d = "д"
    elif last in _KY_VOICELESS:
        n_d, g_k, d_t = "т", "к", "т"                 # после глухой: -тын, -ка, -та
    else:
        n_d, g_k, d_t = "д", "г", "д"                 # после звонкой и сонорной: -дын, -га, -да
    return {
        "nom": word,
        "gen": f"{word}{n_d}{four}н",
        "dat": f"{word}{g_k}{two}",
        "acc": f"{word}{n_d}{four}",
        "abl": f"{word}{d_t}{two}н",
        "loc": f"{word}{d_t}{two}",
    }


def ky_forms(name: str) -> dict[str, str]:
    """Падежные формы имени по-кыргызски по гармонии гласных и уподоблению согласных.

    «Тимур» → Тимурга, Тимурдун, Тимурду, Тимурдан, Тимурда; «Берметке», «Берметтин», «Берметти»; «Айдана» →
    «Айданага», «Айдананын». Составное имя меняет последнюю часть. Имя не на кириллице остаётся без изменений.
    Автору книги эту таблицу показывают готовой, чтобы он не угадывал окончания."""
    name = name.strip()
    if not name:
        return {case: name for case in KY_CASES}
    for sep in (" ", "-"):
        if sep in name:
            head, _, tail = name.rpartition(sep)
            forms = ky_forms(tail)
            return {case: (head + sep + form if case != "nom" else name) for case, form in forms.items()}
    if not _is_cyrillic(name) or len(name) < 2:
        return {case: name for case in KY_CASES}
    return _ky_word_forms(name)
