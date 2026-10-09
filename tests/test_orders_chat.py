"""Карточки заказов владельцу: «Новый заказ» при создании и «Заказ готов» после доставки (чат ORDERS_CHAT_ID или чат владельца)."""
from types import SimpleNamespace

import pytest

from app.bot import TelegramNotifier
from app.config import ConfigError, Settings

from .conftest import ADMIN_ID, SAMPLE, FakeNotifier, PlainNotifier, build_env, tma
from .test_access import give_access


class CardNotifier(FakeNotifier):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cards: list[str] = []

    async def notify_order(self, text: str) -> None:
        self.cards.append(text)


async def order(env, user=ADMIN_ID):
    resp = await env.client.post("/api/orders", json=SAMPLE, headers=tma(user))
    assert resp.status == 201
    return (await resp.json())["order_id"]


async def test_new_order_and_ready_cards_reach_the_orders_chat(tmp_path):
    notifier = CardNotifier()
    env = await build_env(tmp_path, notifier=notifier, closed=True)
    try:
        await give_access(env, user_id=42, credits=2)
        order_id = await order(env, user=42)
        await env.wait_done(order_id)
        new, ready = notifier.cards[0], notifier.cards[-1]
        assert new.startswith(f"🧾 Новый заказ {order_id}") and "Айдар" in new and "Осталось книг у клиента: 1" in new
        assert "id 42" in new and "фото: нет" in new and "Стиль: 3D-мультик" in new
        assert ready.startswith(f"✅ Заказ {order_id} готов")
        assert not [t for t in notifier.admin_texts if t.startswith(("🧾", "✅"))]    # в чат владельца карточки не дублируются
    finally:
        await env.service.shutdown(); await env.client.close(); env.db.close()


async def test_without_notify_order_the_cards_go_to_the_admin_chat(tmp_path):
    notifier = FakeNotifier()                                      # старый уведомитель без notify_order
    env = await build_env(tmp_path, notifier=notifier)
    try:
        order_id = await order(env, user=42)
        await env.wait_done(order_id)
        assert any(t.startswith("🧾 Новый заказ") for t in notifier.admin_texts)
        assert any(t.startswith("✅ Заказ") for t in notifier.admin_texts)
    finally:
        await env.service.shutdown(); await env.client.close(); env.db.close()


async def test_a_failing_card_never_breaks_the_order(tmp_path):
    class Broken(CardNotifier):
        async def notify_order(self, text):
            raise RuntimeError("чат недоступен")

    env = await build_env(tmp_path, notifier=Broken())
    try:
        order_id = await order(env, user=42)
        assert (await env.wait_done(order_id))["status"] == "done"
    finally:
        await env.service.shutdown(); await env.client.close(); env.db.close()


async def test_plain_notifier_without_any_extras_still_works(tmp_path):
    env = await build_env(tmp_path, notifier=PlainNotifier())
    try:
        assert (await env.wait_done(await order(env, user=42)))["status"] == "done"
    finally:
        await env.service.shutdown(); await env.client.close(); env.db.close()


class FakeBot:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send_message(self, chat_id, text, **kw):
        if self.fail:
            raise RuntimeError("нет доступа")
        self.sent.append((chat_id, text))


async def test_telegram_notifier_sends_cards_to_the_orders_chat_or_falls_back_to_the_owner():
    bot = FakeBot()
    await TelegramNotifier(bot, 111, "", -100500).notify_order("карточка")
    assert bot.sent == [(-100500, "карточка")]
    bot = FakeBot()
    await TelegramNotifier(bot, 111).notify_order("<b>карточка</b>")
    assert bot.sent == [(111, "&lt;b&gt;карточка&lt;/b&gt;")]       # без ORDERS_CHAT_ID: чат владельца, текст экранирован
    bot = FakeBot()
    await TelegramNotifier(bot, None).notify_order("никуда")
    assert bot.sent == []
    await TelegramNotifier(FakeBot(fail=True), 111).notify_order("сбой не пробрасывается")


def test_orders_chat_id_setting(monkeypatch, tmp_path):
    monkeypatch.setenv("ORDERS_CHAT_ID", "-100123456")
    assert Settings.from_env(env_file=None).orders_chat_id == -100123456
    monkeypatch.setenv("ORDERS_CHAT_ID", "")
    assert Settings.from_env(env_file=None).orders_chat_id is None
    monkeypatch.setenv("ORDERS_CHAT_ID", "abc")
    with pytest.raises(ConfigError, match="ORDERS_CHAT_ID"):
        Settings.from_env(env_file=None)
