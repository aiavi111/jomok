"""Проверка подписи initData: верная, подделанная, просроченная; режим DEV_MODE."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl, quote, urlencode

import pytest

from app.auth import MAX_AGE_SECONDS, authenticate, verify_init_data
from app.errors import AuthError

from .conftest import BOT_TOKEN, sign_init_data


def test_valid_init_data_returns_user():
    user = verify_init_data(sign_init_data(555, first_name="Айдар"), BOT_TOKEN)
    assert user.id == 555 and user.first_name == "Айдар" and user.language_code == "ru"


def test_matches_independent_reference_implementation():
    """Сверяем с отдельной «эталонной» сборкой подписи по тексту инструкции Telegram."""
    auth_date = str(int(time.time()))
    user = json.dumps({"id": 1, "first_name": "A"}, separators=(",", ":"))
    data_check_string = f"auth_date={auth_date}\nquery_id=Q\nuser={user}"
    secret = hmac.new(key=b"WebAppData", msg=BOT_TOKEN.encode(), digestmod=hashlib.sha256).digest()
    expected = hmac.new(key=secret, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()
    init_data = urlencode({"auth_date": auth_date, "query_id": "Q", "user": user, "hash": expected}, quote_via=quote)
    assert verify_init_data(init_data, BOT_TOKEN).id == 1


def test_signature_field_is_part_of_signed_data():
    """Поле signature входит в строку проверки (исключается только hash)."""
    good = sign_init_data(1)
    pairs = dict(parse_qsl(good))
    pairs["signature"] = "другая-подпись"          # меняем поле, hash оставляем прежним
    with pytest.raises(AuthError):
        verify_init_data(urlencode(pairs, quote_via=quote), BOT_TOKEN)


def test_tampered_user_is_rejected():
    pairs = dict(parse_qsl(sign_init_data(1)))
    pairs["user"] = json.dumps({"id": 999, "first_name": "Чужой"})
    with pytest.raises(AuthError):
        verify_init_data(urlencode(pairs, quote_via=quote), BOT_TOKEN)


def test_tampered_hash_is_rejected():
    pairs = dict(parse_qsl(sign_init_data(1)))
    pairs["hash"] = "0" * 64
    with pytest.raises(AuthError):
        verify_init_data(urlencode(pairs), BOT_TOKEN)


def test_wrong_bot_token_is_rejected():
    with pytest.raises(AuthError):
        verify_init_data(sign_init_data(1, token="999:OTHERtokenOTHERtokenOTHERtokenOTHER"), BOT_TOKEN)


def test_missing_hash_and_empty_are_rejected():
    pairs = dict(parse_qsl(sign_init_data(1)))
    del pairs["hash"]
    for bad in (urlencode(pairs), "", "garbage"):
        with pytest.raises(AuthError):
            verify_init_data(bad, BOT_TOKEN)


def test_old_auth_date_is_rejected_after_24_hours():
    now = time.time()
    old = sign_init_data(1, auth_date=now - MAX_AGE_SECONDS - 60)
    with pytest.raises(AuthError):
        verify_init_data(old, BOT_TOKEN, now=now)
    fresh = sign_init_data(1, auth_date=now - MAX_AGE_SECONDS + 600)
    assert verify_init_data(fresh, BOT_TOKEN, now=now).id == 1


def test_auth_date_from_far_future_is_rejected():
    with pytest.raises(AuthError):
        verify_init_data(sign_init_data(1, auth_date=time.time() + 3600), BOT_TOKEN)


def test_duplicate_fields_are_rejected():
    with pytest.raises(AuthError):
        verify_init_data(sign_init_data(1) + "&user=%7B%22id%22%3A2%7D", BOT_TOKEN)


def test_header_without_tma_scheme_is_rejected_when_not_dev():
    for header in ("", "Bearer abc", "tma", "tma "):
        with pytest.raises(AuthError):
            authenticate(header, BOT_TOKEN, dev_mode=False)


def test_dev_mode_accepts_unsigned_requests_but_real_mode_does_not():
    assert authenticate("tma dev", BOT_TOKEN, dev_mode=True).id == 1
    assert authenticate("tma dev:42", BOT_TOKEN, dev_mode=True).id == 42
    assert authenticate("", BOT_TOKEN, dev_mode=True).id == 1
    with pytest.raises(AuthError):
        authenticate("tma dev", BOT_TOKEN, dev_mode=False)


def test_dev_mode_still_uses_real_user_when_signature_is_valid():
    assert authenticate("tma " + sign_init_data(31337), BOT_TOKEN, dev_mode=True).id == 31337
