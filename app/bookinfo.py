"""Подписи книги (обложка, посвящение, финал) — одни и те же в PDF и в просмотре Mini App."""
from __future__ import annotations

from .declension import genitive_ru
from .layout import COVER_SIZE, PAGE_SIZE, text_side
from .profile import Profile
from .story import PAGES, Story

MOCK_NOTE = "Тестовая сборка: заглушки"

_LABELS = {
    "ru": {
        "caption": "Книга для {gen}",
        "dedication_title": "Для {gen}",
        "the_end": "Конец",
        "signature": "Эта книга создана специально для {gen}",
    },
    "ky": {
        "caption": "{name} үчүн китеп",
        "dedication_title": "{name} үчүн",
        "the_end": "Аягы",
        "signature": "Бул китеп атайын {name} үчүн жазылган",
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


def book_format() -> dict:
    """Формат книги для Mini App (/api/config): число страниц и разворотов, размеры картинок, где лежит текст."""
    return {
        "pages": PAGES,
        "spreads": PAGES + 2,                                    # обложка, страницы истории, финал
        "cover_image": {"width": COVER_SIZE[0], "height": COVER_SIZE[1], "ratio": "1:1"},
        "page_image": {"width": PAGE_SIZE[0], "height": PAGE_SIZE[1], "ratio": "2:1"},
        "text_side": {"odd": text_side(1), "even": text_side(2)},   # половина широкой картинки, на которой лежит текст
    }
