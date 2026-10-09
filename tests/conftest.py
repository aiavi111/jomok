"""Общие настройки тестов: поддельные провайдеры, подписанный initData, тестовый сервер."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import quote, urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app import bookgen
from app.config import Settings
from app.db import Database
from app.errors import ProviderError
from app.links import load_or_create_secret
from app.logging_setup import redact
from app.payments import FreePayment
from app.profile import Profile
from app.providers.image_mock import MockImageProvider
from app.providers.text_mock import MockTextProvider
from app.service import OrderService
from app.web import create_app

BOT_TOKEN = "123456789:TESTtokenTESTtokenTESTtokenTEST12345"
ADMIN_ID = 777

SAMPLE = {
    "name": "Айдар", "age": 6, "gender": "boy",
    "appearance": {"hair": "", "eyes": "", "clothes": ""},
    "likes": ["Лошади"], "traits": ["kind", "brave"], "place": "yurt", "value": "kindness",
    "islamic": False, "headscarf": False, "language": "ru", "dedication": "Для сына",
}


@pytest.fixture(autouse=True)
def fast_pauses(monkeypatch):
    """Паузы между повторами картинок в тестах не нужны."""
    monkeypatch.setattr(bookgen, "RETRY_PAUSES", (0.0, 0.0))


@pytest.fixture(autouse=True)
def _no_leftover_secrets():
    yield
    redact._secrets.clear()


def make_settings(tmp_path: Path, **over) -> Settings:
    base = dict(
        telegram_bot_token=BOT_TOKEN, webapp_url="https://example.test", admin_chat_id=ADMIN_ID,
        text_provider="mock", image_provider="mock", dev_mode=False,
        max_books_per_user_per_day=3, keep_files_days=7, data_dir=tmp_path / "data",
        mock_delay_seconds=0.0, image_concurrency=3, max_parallel_generations=3,
    )
    base.update(over)
    return Settings(**base)


def sign_init_data(user_id: int = 42, *, token: str = BOT_TOKEN, auth_date: float | None = None,
                   first_name: str = "Тест", extra: dict | None = None) -> str:
    """Собирает initData так же, как это делает Telegram, и подписывает его."""
    fields = {
        "auth_date": str(int(time.time() if auth_date is None else auth_date)),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps({"id": user_id, "first_name": first_name, "language_code": "ru"}, ensure_ascii=False),
        "signature": "abcdefSIGNATURE",
    }
    fields.update(extra or {})
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields, quote_via=quote)


def tma(user_id: int = 42, **kw) -> dict:
    return {"Authorization": "tma " + sign_init_data(user_id, **kw)}


class FakeNotifier:
    def __init__(self, deliver: bool = True):
        self.deliver = deliver
        self.books: list[tuple] = []
        self.admin_books: list[tuple] = []
        self.admin_texts: list[str] = []
        self.payments: list[tuple] = []
        self.user_texts: list[tuple] = []
        self.print_offers: list[tuple] = []

    async def send_book(self, user_id, pdf_path, filename, caption) -> bool:
        self.books.append((user_id, Path(pdf_path), filename, caption))
        return self.deliver

    async def send_admin_book(self, pdf_path, filename, caption) -> None:
        self.admin_books.append((Path(pdf_path), filename, caption))

    async def notify_admin(self, text: str) -> None:
        self.admin_texts.append(text)

    async def notify_payment(self, order_id, receipt_path, text) -> None:
        self.payments.append((order_id, Path(receipt_path), text))

    async def notify_user(self, user_id, text) -> None:
        self.user_texts.append((user_id, text))

    async def send_print_offer(self, user_id, text, whatsapp_url) -> None:
        self.print_offers.append((user_id, text, whatsapp_url))


class PlainNotifier:
    """Старый вид уведомителя: только три обязательных метода (без чеков, сообщений человеку и печатной версии)."""

    def __init__(self):
        self.books: list[tuple] = []

    async def send_book(self, user_id, pdf_path, filename, caption) -> bool:
        self.books.append((user_id, Path(pdf_path), filename, caption))
        return True

    async def send_admin_book(self, pdf_path, filename, caption) -> None:
        return None

    async def notify_admin(self, text: str) -> None:
        return None


class Env:
    def __init__(self, settings, db, service, notifier, client):
        self.settings, self.db, self.service, self.notifier, self.client = settings, db, service, notifier, client

    async def wait_done(self, order_id: str, user_id: int = 42, timeout: float = 30.0) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            resp = await self.client.get(f"/api/orders/{order_id}", headers=tma(user_id))
            data = await resp.json()
            if data["status"] in ("done", "error"):
                return data
            await asyncio.sleep(0.05)
        raise AssertionError("заказ не завершился вовремя")

    async def create(self, payload: dict | None = None, user_id: int = 42) -> str:
        resp = await self.client.post("/api/orders", json=payload or SAMPLE, headers=tma(user_id))
        data = await resp.json()
        assert resp.status == 201, data
        return data["order_id"]


async def build_env(tmp_path: Path, *, text=None, image=None, notifier=None, closed: bool = False,
                    **settings_over) -> Env:
    """closed=False: бот открыт для всех (как до личных ссылок), так проще проверять остальное.
    closed=True: настоящий режим по умолчанию, создавать книги могут только владелец и те, у кого есть книги."""
    settings = make_settings(tmp_path, **settings_over)
    db = Database(settings.data_dir / "test.sqlite3")
    db.set_setting("closed_bot", "1" if closed else "0")
    notifier = notifier or FakeNotifier()
    service = OrderService(settings, db, text or MockTextProvider(), image or MockImageProvider(), notifier,
                           FreePayment(), load_or_create_secret(settings.data_dir))
    app = create_app(settings, db, service, {"username": "test_bot"})
    client = TestClient(TestServer(app))
    await client.start_server()
    return Env(settings, db, service, notifier, client)


def make_service(tmp_path: Path, *, closed: bool = True, notifier=None, **settings_over) -> OrderService:
    """Сервис без веб-сервера (для тестов бота и базы). По умолчанию бот закрыт, как в настоящей работе."""
    settings = make_settings(tmp_path, **settings_over)
    db = Database(settings.data_dir / "service.sqlite3")
    db.set_setting("closed_bot", "1" if closed else "0")
    return OrderService(settings, db, MockTextProvider(), MockImageProvider(), notifier or FakeNotifier(),
                        FreePayment(), load_or_create_secret(settings.data_dir))


@pytest.fixture
async def env(tmp_path):
    e = await build_env(tmp_path)
    yield e
    await e.service.shutdown()
    await e.client.close()
    e.db.close()


@pytest.fixture
def profile() -> Profile:
    return Profile.from_payload(SAMPLE)


class ScriptedImage(MockImageProvider):
    """Картинки-заглушки с программируемыми сбоями и учётом одновременных вызовов."""

    def __init__(self, fail=None, supports_reference=True, delay=0.01):
        super().__init__(delay=delay)
        self.supports_reference = supports_reference
        self.fail = fail or (lambda call_no, prompt, label: None)
        self.calls: list[dict] = []
        self.active = 0
        self.max_active = 0

    async def generate(self, prompt, refs=None, size="1024x1024", *, label=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        call_no = len(self.calls) + 1
        self.calls.append({"prompt": prompt, "refs": list(refs) if refs else None, "label": label, "n": call_no, "size": size})
        try:
            error = self.fail(call_no, prompt, label)
            if error:
                raise error
            return await super().generate(prompt, refs, size, label=label)
        finally:
            self.active -= 1


def provider_error(message="сбой", **kw) -> ProviderError:
    return ProviderError(message, **kw)
