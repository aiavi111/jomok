"""Подписи книги (обложка, посвящение, финал) — одни и те же в PDF и в просмотре Mini App."""
from __future__ import annotations

from .declension import genitive_ru
from .profile import Profile
from .story import Story

MOCK_NOTE = "Тестовая сборка: заглушки"

_LABELS = {
    "ru": {
        "caption": "Сказка для {gen}",
        "dedication_title": "Для {gen}",
        "the_end": "Конец",
        "signature": "Эта сказка создана специально для {gen}",
    },
    "ky": {
        "caption": "{name} үчүн жомок",
        "dedication_title": "{name} үчүн",
        "the_end": "Аягы",
        "signature": "Бул жомок атайын {name} үчүн жазылган",
    },
}


def book_labels(story: Story, profile: Profile) -> dict:
    gen = genitive_ru(profile.name, profile.gender) if profile.language == "ru" else profile.name
    labels = {k: v.format(gen=gen, name=profile.name) for k, v in _LABELS[profile.language].items()}
    labels.update({
        "title": story.title,
        "dedication_text": profile.dedication,
        "moral": story.moral,
        "wish": story.wish,
        "mock_note": MOCK_NOTE,
    })
    return labels
