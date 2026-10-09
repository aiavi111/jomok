"""Мелкие, но важные проверки: склонение имён, логи без секретов, ссылки, анкета."""
import logging
import time

import pytest

from app.declension import genitive_ru
from app.errors import ValidationError
from app.links import check_token, make_token
from app.logging_setup import RedactingFormatter, Redactor, redact, setup_logging
from app.profile import Profile
from app.textutil import clean_text, human_wait, ru_plural

from .conftest import SAMPLE


@pytest.mark.parametrize("name, gender, expected", [
    ("Айдар", "boy", "Айдара"), ("Нурбек", "boy", "Нурбека"), ("Андрей", "boy", "Андрея"),
    ("Игорь", "boy", "Игоря"), ("Артём", "boy", "Артёма"), ("Алтынбай", "boy", "Алтынбая"),
    ("Алина", "girl", "Алины"), ("Айша", "girl", "Айши"), ("Мария", "girl", "Марии"),
    ("Таня", "girl", "Тани"), ("Айгүл", "girl", "Айгүл"), ("Айдай", "girl", "Айдай"),
    ("Жибек", "girl", "Жибек"), ("Айсулуу", "girl", "Айсулуу"), ("Emma", "girl", "Emma"),
    ("Анна-Мария", "girl", "Анна-Марии"), ("Любовь", "girl", "Любови"),
])
def test_genitive_names(name, gender, expected):
    assert genitive_ru(name, gender) == expected


def test_plural_and_wait_helpers():
    assert [ru_plural(n, "сказку", "сказки", "сказок") for n in (1, 2, 5, 11, 21, 24)] == \
        ["сказку", "сказки", "сказок", "сказок", "сказку", "сказки"]
    assert human_wait(5400) == "1 ч 30 мин" and human_wait(30) == "1 мин" and human_wait(7200) == "2 ч"


def test_clean_text_removes_controls_tags_and_invisible_characters():
    assert clean_text("  a\u0000b‮<i>c</i>​   d\n e ") == "ab" "ic/i d e"
    assert clean_text(None) == "" and clean_text("a\r\n\r\nb", keep_newlines=True) == "a\nb"


def test_secrets_never_appear_in_logs_or_tracebacks(capsys):
    token = "123456789:TESTtokenFAKEfakeTESTtokenFAKE_12345"
    openai = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    gemini = "AIzaSyA-1234567890abcdefghijklmnopqrstuv"
    cf = "cfTOKENabcdef1234567890ABCDEF1234567890xy"
    setup_logging([token, openai, gemini, cf])
    log = logging.getLogger("leak-test")
    log.error("ошибка запроса https://api.telegram.org/bot%s/getMe", token)
    log.warning("ключ %s и %s, заголовок Authorization: Bearer %s, x-goog-api-key: %s", openai, cf, cf, gemini)
    try:
        raise RuntimeError(f"HTTP 401 for url 'https://api.telegram.org/bot{token}/getMe' key={openai}")
    except RuntimeError:
        log.exception("сбой")
    log.info("initData: tma query_id=AAH&user=%7B%22id%22%3A1%7D&auth_date=1700000000&hash=abcdef0123456789abcdef")
    err = capsys.readouterr().err
    for secret in (token, openai, gemini, cf, token.split(":")[1], "abcdef0123456789abcdef"):
        assert secret not in err, secret
    assert "***" in err


def test_redactor_catches_unknown_keys_by_pattern():
    r = Redactor()
    out = r("a 111222333:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi_-12 b sk-live-ABCDEFGHIJKLMNOP1234 c AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345678")
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi" not in out and "sk-live" not in out and "AIzaSy" not in out


def test_httpx_loggers_are_quiet_because_telegram_urls_contain_the_token():
    setup_logging([])
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_signed_links_are_bound_to_order_owner_and_expire():
    secret = b"s" * 32
    token = make_token(secret, "order1234567", 42)
    assert check_token(secret, "order1234567", 42, token)
    assert not check_token(secret, "order1234567", 43, token)          # чужой пользователь
    assert not check_token(secret, "another123456", 42, token)         # другой заказ
    assert not check_token(b"x" * 32, "order1234567", 42, token)       # другой секрет
    assert not check_token(secret, "order1234567", 42, token, now=time.time() + 7 * 3600 * 2)   # просрочено
    assert make_token(secret, "order1234567", 42, now=1000) == make_token(secret, "order1234567", 42, now=1500)  # стабильна в течение часа


def test_profile_hides_headscarf_without_islamic_mode_or_for_boys():
    assert Profile.from_payload({**SAMPLE, "gender": "girl", "headscarf": True}).headscarf is False
    assert Profile.from_payload({**SAMPLE, "gender": "boy", "islamic": True, "headscarf": True}).headscarf is False
    assert Profile.from_payload({**SAMPLE, "gender": "girl", "islamic": True, "headscarf": True}).headscarf is True


def test_scrubbed_profile_has_no_personal_data():
    scrubbed = Profile.from_payload({**SAMPLE, "dedication": "секрет"}).scrubbed()
    assert scrubbed["name"] == "" and scrubbed["dedication"] == "" and scrubbed["likes"] == [] and scrubbed["age"] == 6


def test_dev_secrets_property_lists_all_keys():
    from tests.conftest import make_settings
    from pathlib import Path
    s = make_settings(Path("."), openai_api_key="sk-abcdefgh", gemini_api_key="AIzaabcdefgh", cloudflare_api_token="cf-token-1234")
    assert {"sk-abcdefgh", "AIzaabcdefgh", "cf-token-1234"} <= set(s.secrets)


def test_empty_env_file_means_everything_runs_on_stubs(tmp_path, monkeypatch):
    from app.config import Settings, ConfigError
    for var in ("TELEGRAM_BOT_TOKEN", "WEBAPP_URL", "ADMIN_CHAT_ID", "TEXT_PROVIDER", "IMAGE_PROVIDER", "OPENAI_API_KEY",
                "GEMINI_API_KEY", "CLOUDFLARE_API_TOKEN", "DEV_MODE", "MAX_BOOKS_PER_USER_PER_DAY", "KEEP_FILES_DAYS",
                "OPENAI_TEXT_MODEL", "TEXT_PROOF_MODEL", "DATA_DIR", "PORT"):
        monkeypatch.delenv(var, raising=False)
    empty = tmp_path / ".env"
    empty.write_text("")
    s = Settings.from_env(empty)
    assert (s.text_provider, s.image_provider, s.dev_mode) == ("mock", "mock", False)
    assert s.max_books_per_user_per_day == 3 and s.keep_files_days == 7 and s.port == 8080 and s.admin_chat_id is None
    assert s.text_proof_model == ""                                  # отдельной модели корректора по умолчанию нет
    assert s.secrets == []
    monkeypatch.setenv("TEXT_PROVIDER", "chatgpt")
    with pytest.raises(ConfigError):
        Settings.from_env(empty)
    monkeypatch.setenv("TEXT_PROVIDER", "mock")
    monkeypatch.setenv("ADMIN_CHAT_ID", "не число")
    with pytest.raises(ConfigError):
        Settings.from_env(empty)


def test_env_file_values_are_read_but_system_variables_win(tmp_path, monkeypatch):
    from app.config import Settings
    monkeypatch.delenv("TEXT_PROVIDER", raising=False)
    monkeypatch.delenv("MAX_BOOKS_PER_USER_PER_DAY", raising=False)
    monkeypatch.delenv("TEXT_PROOF_MODEL", raising=False)
    env = tmp_path / ".env"
    env.write_text("TEXT_PROVIDER=gemini   # комментарий\nMAX_BOOKS_PER_USER_PER_DAY=5\nDEV_MODE=1\nTEXT_PROOF_MODEL=proof-model\n")
    monkeypatch.setenv("MAX_BOOKS_PER_USER_PER_DAY", "9")
    s = Settings.from_env(env)
    assert s.text_provider == "gemini" and s.max_books_per_user_per_day == 9 and s.dev_mode is True
    assert s.text_proof_model == "proof-model"
