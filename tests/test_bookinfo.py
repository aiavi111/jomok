"""Слово «книга» вместо «сказка»: подписи книги, PDF, сообщения сервера (бот не затронут)."""
import pytest

from app import service
from app.bookinfo import book_format, book_labels
from app.errors import ValidationError
from app.profile import Profile
from app.providers.text_mock import build_mock_story
from app.story import validate_story

from .conftest import SAMPLE


def labels(language="ru", name="Айдар", gender="boy"):
    profile = Profile.from_payload({**SAMPLE, "language": language, "name": name, "gender": gender})
    return book_labels(validate_story(build_mock_story(profile), language), profile)


def test_russian_labels_say_book():
    ru = labels()
    assert ru["caption"] == "Книга для Айдара" and ru["dedication_title"] == "Для Айдара" and ru["the_end"] == "Конец"
    assert ru["signature"] == "Эта книга создана специально для Айдара"
    assert not any("сказ" in str(v).lower() for k, v in ru.items() if k in ("caption", "signature", "dedication_title"))


def test_kyrgyz_labels_say_kitep_not_jomok():
    ky = labels("ky", "Үмүт")
    assert ky["caption"] == "Үмүт үчүн китеп" and ky["signature"] == "Бул китеп атайын Үмүт үчүн жазылган"
    assert ky["dedication_title"] == "Үмүт үчүн" and ky["the_end"] == "Аягы"
    assert "жомок" not in ky["caption"] + ky["signature"]


def test_girl_name_is_declined_in_the_book_caption():
    assert labels(name="Айгүл", gender="girl")["caption"] == "Книга для Айгүл"


def test_server_messages_to_people_say_book():
    for text in (service.GENERIC_ERROR, service.STORY_ERROR, service.INTERRUPTED, service.PRINT_MESSAGE,
                 service.ACCESS_MESSAGE):
        assert "сказк" not in text.lower() and "книг" in text.lower(), text
    assert service.safe_filename("") == "Книга.pdf" and service.safe_filename("Айдар и конь") == "Айдар и конь.pdf"


def test_validation_messages_say_book():
    with pytest.raises(ValidationError) as err:
        Profile.from_payload({**SAMPLE, "age": 12})
    assert "Книги подходят" in err.value.message and "сказ" not in err.value.message.lower()
    for key, bad in (("place", "mars"), ("value", "greed")):
        with pytest.raises(ValidationError) as err:
            Profile.from_payload({**SAMPLE, key: bad})
        assert "сказк" not in err.value.message.lower()


async def test_delivered_caption_calls_it_a_personal_book(env):
    order_id = await env.create()
    await env.wait_done(order_id)
    caption = env.notifier.books[0][3]
    assert "персональная книга" in caption and "сказка" not in caption.lower()


def test_book_format_describes_images_spreads_and_text_side():
    assert book_format() == {
        "pages": 8, "spreads": 10,
        "cover_image": {"width": 1024, "height": 1024, "ratio": "1:1"},
        "page_image": {"width": 2048, "height": 1024, "ratio": "2:1"},
        "text_side": {"odd": "right", "even": "left"},
    }
