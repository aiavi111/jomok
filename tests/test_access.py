"""Закрытый бот и личные ссылки, книги на счёте, цены и печатная версия, срок хранения фото."""
import asyncio
import json
import os
import sqlite3
import threading
import time
from urllib.parse import quote

import pytest

from app.config import Settings
from app.db import Database
from app.errors import StoryError, ValidationError
from app.paydesk import DEFAULT_PRINT_PRICE, PaymentDesk
from app.service import (CLEANUP_PERIOD, CLOSED_TEXT, INVITE_LIST_LIMIT, PHOTO_PURGE_AFTER, PHOTO_TTL, PRINT_MESSAGE,
                         OrderService)
from app.providers.base import TextProvider
from app.web import BOT_KEY

from .conftest import ADMIN_ID, SAMPLE, FakeNotifier, PlainNotifier, ScriptedImage, build_env, make_service, tma
from .test_api import jpeg, post_with_photo
from .test_payment import form, png

USER = 42
HOUR = 3600
PRINT_ASK = quote(PRINT_MESSAGE, safe="")


class BoomText(TextProvider):
    """Писатель, который всегда ломается (сбой внешнего сервиса)."""
    name = "boom"

    async def _complete(self, system, messages):
        from app.errors import ProviderError
        raise ProviderError("сервис недоступен", fatal=True)

    async def generate_story(self, profile):
        await self._complete("", [])


class BrokenStoryText(BoomText):
    async def generate_story(self, profile):
        raise StoryError("ответ не прошёл проверку")


class CrashingText(BoomText):
    async def generate_story(self, profile):
        raise RuntimeError("неожиданный сбой")


async def api(env, method, url, user=ADMIN_ID, **kw):
    resp = await getattr(env.client, method)(url, headers=tma(user), **kw)
    return resp.status, await resp.json()


async def make_invite(env, credits=1, note="") -> dict:
    status, data = await api(env, "post", "/api/admin/invites", json={"credits": credits, "note": note})
    assert status == 201, data
    return data


async def give_access(env, user_id=USER, credits=1) -> None:
    token = (await make_invite(env, credits))["token"]
    assert await env.service.redeem_invite(token, user_id, first_name="Мама") == credits


async def post_order(env, user=USER):
    resp = await env.client.post("/api/orders", json=SAMPLE, headers=tma(user))
    return resp.status, await resp.json()


async def config(env, user=USER) -> dict:
    return (await api(env, "get", "/api/config", user))[1]


@pytest.fixture
async def closed_env(tmp_path):
    e = await build_env(tmp_path, closed=True)
    yield e
    await e.service.shutdown()
    await e.client.close()
    e.db.close()


# ======================================================================= база данных
def test_new_tables_exist_and_migrations_can_run_twice(tmp_path):
    path = tmp_path / "x.sqlite3"
    Database(path).close()
    db = Database(path)                       # второй запуск на той же базе: ничего не ломается
    tables = {r["name"] for r in db._all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"invites", "access"} <= tables
    assert [r["name"] for r in db._all("PRAGMA table_info(invites)")] == \
        ["token", "credits", "note", "created_at", "used_by", "used_at"]
    assert [r["name"] for r in db._all("PRAGMA table_info(access)")] == \
        ["user_id", "credits", "granted_at", "last_invite"]
    assert [r["name"] for r in db._all("PRAGMA table_info(orders)")].count("credit_used") == 1
    db.close()


def test_old_database_without_new_tables_and_column_is_upgraded(tmp_path):
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript("""CREATE TABLE orders(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, status TEXT NOT NULL,
        profile_json TEXT NOT NULL, title TEXT, paid INTEGER NOT NULL DEFAULT 0, payment_charge_id TEXT, error TEXT,
        error_detail TEXT, delivered INTEGER, files_deleted INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
        updated_at REAL NOT NULL, finished_at REAL);
        INSERT INTO orders(id,user_id,status,profile_json,created_at,updated_at) VALUES('x',1,'done','{}',1,1);""")
    conn.close()
    db = Database(path)
    assert db.get_order("x")["credit_used"] == 0 and db.get_credits(1) == 0
    db.create_invite("tokentoken1", 2, "")
    assert db.redeem_invite("tokentoken1", 1) == 2 and db.get_credits(1) == 2
    db.close()


def test_closed_is_the_default_for_a_fresh_database(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", admin_chat_id=ADMIN_ID)
    db = Database(tmp_path / "fresh.sqlite3")
    service = OrderService(settings, db, None, None, FakeNotifier(), None, b"s" * 32)
    assert service.closed() is True and service.access_state(5) == \
        {"granted": False, "credits": 0, "closed": True, "is_admin": False}
    assert service.access_state(ADMIN_ID)["granted"] is True
    service.set_closed(False)
    assert service.closed() is False and service.access_state(5)["granted"] is True
    db.close()


def test_invite_can_be_redeemed_only_once_even_from_many_threads(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    db.create_invite("onlyOnce001", 3, "тест")
    results, gate = [], threading.Barrier(12)

    def worker(user_id):
        gate.wait()
        results.append((user_id, db.redeem_invite("onlyOnce001", user_id)))

    threads = [threading.Thread(target=worker, args=(100 + n,)) for n in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [uid for uid, credits in results if credits is not None]
    assert len(winners) == 1 and [c for _, c in results if c is not None] == [3]
    assert db.get_credits(winners[0]) == 3 and sum(db.get_credits(100 + n) for n in range(12)) == 3
    invite = db.get_invite("onlyOnce001")
    assert invite["used_by"] == winners[0] and invite["used_at"] is not None
    db.close()


def test_redeem_adds_to_existing_balance_and_remembers_last_invite(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    db.create_invite("firstfirst1", 1, "")
    db.create_invite("secondsecon", 4, "")
    assert db.redeem_invite("firstfirst1", 7) == 1 and db.redeem_invite("secondsecon", 7) == 4
    row = db._one("SELECT * FROM access WHERE user_id=7")
    assert row["credits"] == 5 and row["last_invite"] == "secondsecon" and row["granted_at"] is not None
    assert db.redeem_invite("nope", 7) is None
    db.close()


@pytest.mark.parametrize("credits, threads, expected", [(1, 20, 1), (3, 10, 3), (5, 4, 4)])
def test_credit_is_spent_atomically_when_orders_are_created_from_many_threads(tmp_path, credits, threads, expected):
    db = Database(tmp_path / "x.sqlite3")
    db.add_credits(USER, credits)
    created, gate = [], threading.Barrier(threads)

    def worker(n):
        gate.wait()
        created.append(db.create_order(f"order{n:04d}xx", USER, "{}", use_credit=True))

    pool = [threading.Thread(target=worker, args=(n,)) for n in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    assert created.count(True) == expected and created.count(False) == threads - expected
    assert db.get_credits(USER) == credits - expected
    assert db._one("SELECT COUNT(*) FROM orders")[0] == expected          # отказанные заказы в базу не попали
    db.close()


def test_order_without_credits_is_not_created_and_nothing_goes_negative(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    assert db.create_order("order00001x", USER, "{}", use_credit=True) is False
    assert db.get_order("order00001x") is None and db.get_credits(USER) == 0
    assert db.create_order("order00002x", USER, "{}") is True            # без use_credit книга со счёта не тратится
    db.close()


def test_error_status_returns_the_credit_exactly_once(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    db.add_credits(USER, 2)
    assert db.create_order("order00001x", USER, "{}", use_credit=True) and db.get_credits(USER) == 1
    db.update_order("order00001x", status="drawing")
    assert db.get_credits(USER) == 1
    db.update_order("order00001x", status="error", error="сбой")
    assert db.get_credits(USER) == 2
    db.update_order("order00001x", status="error", error="ещё раз")        # повторная запись ошибки не даёт вторую книгу
    assert db.get_credits(USER) == 2
    db.create_order("order00002x", USER, "{}")                            # заказ без списания: возвращать нечего
    db.update_order("order00002x", status="error")
    assert db.get_credits(USER) == 2
    db.close()


def test_orders_interrupted_by_restart_get_their_credit_back(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    db.add_credits(USER, 1)
    db.create_order("order00001x", USER, "{}", use_credit=True)
    db.update_order("order00001x", status="drawing")
    assert db.interrupt_unfinished("перезапуск", "тест") == 1
    assert db.get_order("order00001x")["status"] == "error" and db.get_credits(USER) == 1
    assert db.interrupt_unfinished("перезапуск", "тест") == 0 and db.get_credits(USER) == 1
    db.close()


# ======================================================================= доступ через API
async def test_user_without_access_gets_403_closed_with_a_russian_message(closed_env):
    status, data = await post_order(closed_env)
    assert status == 403 and data["code"] == "closed" and data["error"] == CLOSED_TEXT
    assert "whatsapp_url" not in data
    assert closed_env.db._one("SELECT COUNT(*) FROM orders")[0] == 0
    # даже с неверной анкетой сначала ответ про доступ, и ничего не создаётся
    resp = await closed_env.client.post("/api/orders", json={"name": ""}, headers=tma(USER))
    assert resp.status == 403 and (await resp.json())["code"] == "closed"


async def test_closed_error_carries_whatsapp_link_when_the_number_is_set(closed_env):
    assert (await config(closed_env))["access_whatsapp_url"] is None
    await api(closed_env, "post", "/api/admin/settings", json={"whatsapp": "996555123456"})
    status, data = await post_order(closed_env)
    assert status == 403 and data["whatsapp_url"].startswith("https://wa.me/996555123456?text=")
    cfg = await config(closed_env)                       # та же ссылка заранее, для экрана «доступ закрыт»
    assert cfg["access_whatsapp_url"] == data["whatsapp_url"] != cfg["print"]["whatsapp_url"]


async def test_closed_user_can_still_open_config_and_own_orders_are_unaffected(closed_env):
    await give_access(closed_env, USER, 1)
    order_id = (await post_order(closed_env))[1]["order_id"]
    assert (await closed_env.wait_done(order_id))["status"] == "done"
    assert (await config(closed_env))["access"] == {"granted": False, "credits": 0, "closed": True, "is_admin": False}
    view = (await api(closed_env, "get", f"/api/orders/{order_id}", USER))[1]       # книги остаются доступны
    assert view["status"] == "done" and view["pdf_url"]
    assert (await closed_env.client.get(view["pdf_url"])).status == 200


async def test_config_access_for_stranger_guest_with_books_owner_and_open_mode(closed_env):
    assert (await config(closed_env, 5))["access"] == {"granted": False, "credits": 0, "closed": True, "is_admin": False}
    await give_access(closed_env, 5, 3)
    assert (await config(closed_env, 5))["access"] == {"granted": True, "credits": 3, "closed": True, "is_admin": False}
    assert (await config(closed_env, ADMIN_ID))["access"] == {"granted": True, "credits": 0, "closed": True, "is_admin": True}
    closed_env.service.set_closed(False)
    assert (await config(closed_env, 6))["access"] == {"granted": True, "credits": 0, "closed": False, "is_admin": False}


async def test_each_book_costs_one_credit_and_a_ready_book_keeps_it_spent(closed_env):
    await give_access(closed_env, USER, 2)
    status, data = await post_order(closed_env)
    assert status == 201 and closed_env.db.get_credits(USER) == 1          # книга списана сразу при создании
    assert (await closed_env.wait_done(data["order_id"]))["status"] == "done"
    assert (await config(closed_env))["access"]["credits"] == 1


async def test_after_the_last_credit_the_next_order_is_refused(closed_env):
    await give_access(closed_env, USER, 1)
    first = (await post_order(closed_env))[1]["order_id"]
    await closed_env.wait_done(first)
    status, data = await post_order(closed_env)
    assert status == 403 and data["code"] == "closed"
    await give_access(closed_env, USER, 1)                                   # новая ссылка — новая книга
    assert (await post_order(closed_env))[0] == 201


@pytest.mark.parametrize("text", [BoomText, BrokenStoryText, CrashingText])
async def test_credit_is_returned_when_the_order_ends_with_an_error(tmp_path, text):
    e = await build_env(tmp_path, closed=True, text=text())
    try:
        await give_access(e, USER, 1)
        status, data = await post_order(e)
        assert status == 201
        done = await e.wait_done(data["order_id"])
        assert done["status"] == "error" and e.db.get_credits(USER) == 1
        assert (await config(e))["access"]["granted"] is True              # можно попробовать ещё раз
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_credit_is_returned_after_server_restart_interrupts_the_order(closed_env):
    await give_access(closed_env, USER, 1)
    closed_env.db.create_order("restartOrder1", USER, json.dumps({"language": "ru"}), use_credit=True)
    closed_env.db.update_order("restartOrder1", status="writing")
    assert closed_env.db.get_credits(USER) == 0
    closed_env.service.recover()
    assert closed_env.db.get_order("restartOrder1")["status"] == "error" and closed_env.db.get_credits(USER) == 1


async def test_person_with_a_book_from_a_link_does_not_pay_by_receipt_again(closed_env):
    """Ссылка выдаётся после оплаты: касса с чеками её владельца и самого владельца не ждёт."""
    await api(closed_env, "post", "/api/admin/qr", data=form("qr", png()))
    await api(closed_env, "post", "/api/admin/settings", json={"enabled": True})
    await give_access(closed_env, USER, 1)
    status, data = await post_order(closed_env)
    assert status == 201 and data["status"] != "awaiting_payment" and closed_env.db.get_credits(USER) == 0
    assert (await closed_env.wait_done(data["order_id"], USER))["status"] == "done"
    owner = await closed_env.create(user_id=ADMIN_ID)
    assert (await closed_env.wait_done(owner, ADMIN_ID))["status"] == "done"


def test_a_cancelled_or_failed_order_gives_the_credit_back_exactly_once(tmp_path):
    from app.db import Database
    db = Database(tmp_path / "x.sqlite3")
    db.add_credits(7, 1)
    assert db.create_order("o1", 7, "{}", paid=False, status="awaiting_payment", use_credit=True) and db.get_credits(7) == 0
    db.update_order("o1", status="cancelled")
    db.update_order("o1", status="error")
    assert db.get_credits(7) == 1                                             # вернулась один раз, повтор ничего не добавляет
    db.close()


async def test_owner_creates_books_without_credits_and_spends_nothing(closed_env):
    for _ in range(2):
        order_id = await closed_env.create(user_id=ADMIN_ID)
        assert (await closed_env.wait_done(order_id, ADMIN_ID))["status"] == "done"
    assert closed_env.db.get_credits(ADMIN_ID) == 0
    closed_env.db.add_credits(ADMIN_ID, 4)                                    # даже если книги на счёте есть, владелец их не тратит
    await closed_env.wait_done(await closed_env.create(user_id=ADMIN_ID), ADMIN_ID)
    assert closed_env.db.get_credits(ADMIN_ID) == 4


async def test_open_mode_lets_anyone_create_and_never_spends_credits(closed_env):
    await give_access(closed_env, USER, 2)
    await api(closed_env, "post", "/api/admin/settings", json={"closed": False})
    for who in (USER, 99):
        assert (await closed_env.wait_done(await closed_env.create(user_id=who), who))["status"] == "done"
    assert closed_env.db.get_credits(USER) == 2 and closed_env.db.get_credits(99) == 0


async def test_daily_limit_still_applies_on_top_of_credits_and_a_refused_order_costs_nothing(tmp_path):
    e = await build_env(tmp_path, closed=True, max_books_per_user_per_day=1)
    try:
        await give_access(e, USER, 3)
        await e.wait_done(await e.create(user_id=USER))
        status, data = await post_order(e)
        assert status == 429 and data["code"] == "limit"
        assert e.db.get_credits(USER) == 2                                     # отказ из-за лимита книгу не списал
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_two_simultaneous_requests_cannot_spend_one_credit_twice(tmp_path):
    e = await build_env(tmp_path, closed=True, image=ScriptedImage(delay=0.2))
    try:
        await give_access(e, USER, 1)
        results = await asyncio.gather(*[post_order(e) for _ in range(5)])
        assert sorted(status for status, _ in results).count(201) == 1
        assert {status for status, _ in results} <= {201, 403, 409}
        assert e.db._one("SELECT COUNT(*) FROM orders")[0] == 1 and e.db.get_credits(USER) == 0
        await e.wait_done(next(d["order_id"] for status, d in results if status == 201))
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


# ======================================================================= личные ссылки в админке
async def test_owner_creates_an_invite_link_with_the_bot_username(closed_env):
    status, data = await api(closed_env, "post", "/api/admin/invites", json={"credits": 3, "note": "Мама Айдара"})
    assert status == 201 and set(data) == {"token", "url", "credits"} and data["credits"] == 3
    assert len(data["token"]) == 12 and data["url"] == f"https://t.me/test_bot?start=inv_{data['token']}"
    row = closed_env.db.get_invite(data["token"])
    assert row["credits"] == 3 and row["note"] == "Мама Айдара" and row["used_by"] is None and row["created_at"]


async def test_invite_defaults_and_validation(closed_env):
    resp = await closed_env.client.post("/api/admin/invites", headers=tma(ADMIN_ID))            # без тела: одна книга
    assert resp.status == 201 and (await resp.json())["credits"] == 1
    assert (await make_invite(closed_env, credits="4"))["credits"] == 4
    assert (await make_invite(closed_env, credits=20))["credits"] == 20
    assert closed_env.db.get_invite((await make_invite(closed_env, note="  Иван   Иванов "))["token"])["note"] == "Иван Иванов"
    assert (await make_invite(closed_env, note="я" * 80))["credits"] == 1
    for body, field in (({"credits": 0}, "credits"), ({"credits": 21}, "credits"), ({"credits": -1}, "credits"),
                        ({"credits": "много"}, "credits"), ({"credits": 1.5}, "credits"), ({"credits": True}, "credits"),
                        ({"credits": [1]}, "credits"), ({"note": "я" * 81}, "note")):
        status, data = await api(closed_env, "post", "/api/admin/invites", json=body)
        assert status == 400 and data["field"] == field and data["code"] == "invalid", body
    resp = await closed_env.client.post("/api/admin/invites", data=b"{not json", headers={**tma(ADMIN_ID), "Content-Type": "application/json"})
    assert resp.status == 400
    assert closed_env.db._one("SELECT COUNT(*) FROM invites")[0] == 5           # отклонённые ссылки не создались


async def test_invite_routes_are_owner_only(closed_env):
    for method, url in (("post", "/api/admin/invites"), ("get", "/api/admin/invites"),
                        ("post", "/api/admin/invites/abcdefghijkl/revoke")):
        assert (await getattr(closed_env.client, method)(url, headers=tma(USER))).status == 403, url
        assert (await getattr(closed_env.client, method)(url)).status == 401, url


async def test_invite_cannot_be_built_while_the_bot_is_not_running(closed_env):
    closed_env.client.app[BOT_KEY].clear()                                       # имя бота неизвестно
    status, data = await api(closed_env, "post", "/api/admin/invites", json={})
    assert status == 409 and "TELEGRAM_BOT_TOKEN" in data["error"]
    assert closed_env.db._one("SELECT COUNT(*) FROM invites")[0] == 0
    assert (await api(closed_env, "get", "/api/admin/invites"))[1] == {"invites": []}


async def test_invite_list_has_state_of_every_link_and_newest_first(closed_env):
    first = await make_invite(closed_env, 2, "первая")
    second = await make_invite(closed_env, 1, "вторая")
    await closed_env.service.redeem_invite(first["token"], 555, first_name="Мария", username="maria")
    status, data = await api(closed_env, "get", "/api/admin/invites")
    assert status == 200 and [i["token"] for i in data["invites"]] == [second["token"], first["token"]]
    new, used = data["invites"]
    assert set(new) == {"token", "url", "credits", "note", "created_at", "used_by", "used_at", "user_name"}
    assert new == {"token": second["token"], "url": second["url"], "credits": 1, "note": "вторая",
                   "created_at": new["created_at"], "used_by": None, "used_at": None, "user_name": None}
    assert used["used_by"] == 555 and used["used_at"] >= used["created_at"] and used["user_name"] == "Мария (@maria)"
    assert used["credits"] == 2 and used["url"] == f"https://t.me/test_bot?start=inv_{first['token']}"


async def test_invite_list_shows_at_most_thirty_newest_links(closed_env):
    tokens = [(await make_invite(closed_env, 1, f"n{n}"))["token"] for n in range(INVITE_LIST_LIMIT + 5)]
    data = (await api(closed_env, "get", "/api/admin/invites"))[1]["invites"]
    assert len(data) == INVITE_LIST_LIMIT == 30
    assert [i["token"] for i in data] == tokens[::-1][:30]


async def test_only_unused_links_can_be_revoked(closed_env):
    fresh, spent = await make_invite(closed_env, 1, "a"), await make_invite(closed_env, 1, "b")
    await closed_env.service.redeem_invite(spent["token"], 555)
    assert await api(closed_env, "post", f"/api/admin/invites/{fresh['token']}/revoke") == (200, {"ok": True})
    ids = [i["token"] for i in (await api(closed_env, "get", "/api/admin/invites"))[1]["invites"]]
    assert ids == [spent["token"]]
    assert await closed_env.service.redeem_invite(fresh["token"], 556) is None          # отозванная ссылка не работает
    status, data = await api(closed_env, "post", f"/api/admin/invites/{spent['token']}/revoke")
    assert status == 409 and data["code"] == "conflict"
    assert closed_env.db.get_credits(555) == 1                                          # у того, кто успел, книга осталась
    assert (await api(closed_env, "post", f"/api/admin/invites/{fresh['token']}/revoke"))[0] == 404
    assert (await api(closed_env, "post", "/api/admin/invites/zz/revoke"))[0] == 404


async def test_used_or_invalid_tokens_give_nothing(closed_env):
    token = (await make_invite(closed_env, 2))["token"]
    assert await closed_env.service.redeem_invite(token, 500) == 2
    for bad in (token, "", "inv_" + token, "нетТакой", "../etc", "x" * 100, None):
        assert await closed_env.service.redeem_invite(bad, 501) is None, bad
    assert closed_env.db.get_credits(500) == 2 and closed_env.db.get_credits(501) == 0


# ======================================================================= настройки: закрытый режим, WhatsApp, цены
async def test_owner_toggles_closed_mode_and_everyone_sees_it(closed_env):
    status, data = await api(closed_env, "post", "/api/admin/settings", json={"closed": False})
    assert status == 200 and data["closed"] is False
    assert (await config(closed_env))["access"]["closed"] is False and (await post_order(closed_env))[0] == 201
    assert (await api(closed_env, "post", "/api/admin/settings", json={"closed": "1"}))[1]["closed"] is True
    assert (await api(closed_env, "post", "/api/admin/settings", json={"closed": "false"}))[1]["closed"] is False
    assert (await api(closed_env, "post", "/api/admin/settings", json={"closed": True}))[1]["closed"] is True
    assert (await api(closed_env, "post", "/api/admin/settings", json={"price_text": "600 сом"}))[1]["closed"] is True  # не сбрасывается
    for bad in ("может быть", 2, None, [], {}):
        status, data = await api(closed_env, "post", "/api/admin/settings", json={"closed": bad})
        assert status == 400 and data["field"] == "closed", bad


async def test_settings_are_all_or_nothing(closed_env):
    status, data = await api(closed_env, "post", "/api/admin/settings",
                             json={"closed": False, "price_text": "700 сом", "whatsapp": "это не номер"})
    assert status == 400 and data["field"] == "whatsapp"
    assert closed_env.service.closed() is True and closed_env.service.price_text() == "590 сом"


async def test_admin_overview_settings_include_closed_whatsapp_and_print_price(closed_env):
    data = (await api(closed_env, "get", "/api/admin/payments"))[1]["settings"]
    assert data["closed"] is True and data["whatsapp"] == "" and data["print_price"] == DEFAULT_PRINT_PRICE == "1 290 сом"
    assert data["price_text"] == "590 сом" and data["enabled"] is False and data["qr_url"] is None
    await api(closed_env, "post", "/api/admin/settings",
              json={"closed": False, "whatsapp": "+996 555 123 456", "print_price": "1 500 сом"})
    data = (await api(closed_env, "get", "/api/admin/payments"))[1]["settings"]
    assert (data["closed"], data["whatsapp"], data["print_price"]) == (False, "996555123456", "1 500 сом")


@pytest.mark.parametrize("raw, stored", [
    ("996555123456", "996555123456"), ("+996 555 123-456", "996555123456"), ("+996 (555) 12-34-56", "996555123456"),
    ("996.555.123.456", "996555123456"), ("  996555123456 ", "996555123456"), ("", ""), (None, ""), ("   ", ""),
    ("123456789", "123456789"), ("1" * 15, "1" * 15),
])
def test_whatsapp_number_is_normalised_to_digits(raw, stored):
    assert PaymentDesk.parse_whatsapp(raw) == stored


@pytest.mark.parametrize("raw", ["12345678", "1" * 16, "abc", "996555abc456", "wa.me/996555123456", "+", "٩٩٦٥٥٥١٢٣٤٥٦",
                                 "996 555 123 456 доб. 5"])
def test_bad_whatsapp_numbers_are_rejected(raw):
    with pytest.raises(ValidationError) as e:
        PaymentDesk.parse_whatsapp(raw)
    assert e.value.field == "whatsapp" and "WhatsApp" in e.value.message


async def test_whatsapp_and_print_price_are_edited_through_the_admin_api(closed_env):
    for raw in ("12345678", "1" * 16, "abc"):
        status, data = await api(closed_env, "post", "/api/admin/settings", json={"whatsapp": raw})
        assert status == 400 and data["field"] == "whatsapp"
    assert (await api(closed_env, "post", "/api/admin/settings", json={"whatsapp": "+996 555 123 456"}))[1]["whatsapp"] == "996555123456"
    assert (await api(closed_env, "post", "/api/admin/settings", json={"whatsapp": ""}))[1]["whatsapp"] == ""     # пусто можно
    for bad in ("", "   ", "я" * 41):
        status, data = await api(closed_env, "post", "/api/admin/settings", json={"print_price": bad})
        assert status == 400 and data["field"] == "print_price"
    assert (await api(closed_env, "post", "/api/admin/settings", json={"print_price": " 1 500   сом "}))[1]["print_price"] == "1 500 сом"
    assert (await api(closed_env, "post", "/api/admin/settings", json={"print_price": "я" * 40}))[0] == 200
    assert (await api(closed_env, "post", "/api/admin/settings", json={"whatsapp": "996555123456"}, user=USER))[0] == 403


def test_default_prices_are_590_for_pdf_and_1290_for_print(tmp_path):
    assert Settings().price_text == "590 сом"
    db = Database(tmp_path / "x.sqlite3")
    desk = PaymentDesk(db, tmp_path, Settings().price_text)
    assert desk.price_text() == "590 сом" and desk.print_price() == "1 290 сом" and desk.whatsapp() == ""
    assert desk.settings()["whatsapp"] == "" and desk.settings()["print_price"] == "1 290 сом"
    db.close()


async def test_config_print_block_is_off_until_the_owner_sets_whatsapp(closed_env):
    assert (await config(closed_env))["print"] == {
        "enabled": False, "whatsapp_url": None, "pdf_price": "590 сом", "print_price": "1 290 сом",
        "title": "Хотите заказать печатную версию?", "note": "Мягкая фотокнига 21×21 см"}
    await api(closed_env, "post", "/api/admin/settings",
              json={"whatsapp": "+996 555 123 456", "print_price": "1 500 сом", "price_text": "650 сом"})
    assert (await config(closed_env))["print"] == {
        "enabled": True, "whatsapp_url": f"https://wa.me/996555123456?text={PRINT_ASK}",
        "pdf_price": "650 сом", "print_price": "1 500 сом",
        "title": "Хотите заказать печатную версию?", "note": "Мягкая фотокнига 21×21 см"}
    assert PRINT_ASK == "%D0%97%D0%B4%D1%80%D0%B0%D0%B2%D1%81%D1%82%D0%B2%D1%83%D0%B9%D1%82%D0%B5%21%20" \
        "%D0%A5%D0%BE%D1%87%D1%83%20%D0%B7%D0%B0%D0%BA%D0%B0%D0%B7%D0%B0%D1%82%D1%8C%20%D0%BF%D0%B5%D1%87%D0%B0%D1%82%D0%BD" \
        "%D1%83%D1%8E%20%D0%B2%D0%B5%D1%80%D1%81%D0%B8%D1%8E%20%D0%BA%D0%BD%D0%B8%D0%B3%D0%B8"
    await api(closed_env, "post", "/api/admin/settings", json={"whatsapp": ""})                  # пусто — предложение выключено
    assert (await config(closed_env))["print"]["enabled"] is False and (await config(closed_env))["print"]["whatsapp_url"] is None


# ======================================================================= предложение печати после книги
async def test_delivered_book_is_followed_by_a_print_offer_with_prices(closed_env):
    await api(closed_env, "post", "/api/admin/settings", json={"whatsapp": "996555123456"})
    await give_access(closed_env, USER, 1)
    done = await closed_env.wait_done((await post_order(closed_env))[1]["order_id"])
    assert done["delivered"] is True and len(closed_env.notifier.books) == 1
    assert closed_env.notifier.print_offers == [(
        USER, "Хотите заказать печатную версию? 590 сом: PDF, 1 290 сом: мягкая фотокнига",
        f"https://wa.me/996555123456?text={PRINT_ASK}")]


async def test_print_offer_uses_the_current_prices_and_is_not_repeated_on_resend(closed_env):
    await api(closed_env, "post", "/api/admin/settings",
              json={"whatsapp": "996555123456", "price_text": "650 сом", "print_price": "1 500 сом"})
    order_id = await closed_env.create(user_id=ADMIN_ID)
    await closed_env.wait_done(order_id, ADMIN_ID)
    assert [o[1] for o in closed_env.notifier.print_offers] == \
        ["Хотите заказать печатную версию? 650 сом: PDF, 1 500 сом: мягкая фотокнига"]
    resp = await closed_env.client.post(f"/api/orders/{order_id}/send", headers=tma(ADMIN_ID))
    assert (await resp.json())["delivered"] is True and len(closed_env.notifier.books) == 2
    assert len(closed_env.notifier.print_offers) == 1                             # повторная отправка PDF без повторной рекламы


async def test_no_print_offer_without_whatsapp_or_when_the_book_was_not_delivered(tmp_path):
    e = await build_env(tmp_path)
    try:
        await e.wait_done(await e.create())
        assert e.notifier.print_offers == []                                      # номер не задан: предложения нет
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()
    notifier = FakeNotifier(deliver=False)
    e = await build_env(tmp_path / "b", notifier=notifier)
    try:
        e.service.desk.update({"whatsapp": "996555123456"})
        await e.wait_done(await e.create())
        assert notifier.print_offers == []                                        # PDF не дошёл — рано предлагать печать
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_old_style_notifier_without_print_offer_method_still_works(tmp_path):
    notifier = PlainNotifier()
    e = await build_env(tmp_path, notifier=notifier)
    try:
        e.service.desk.update({"whatsapp": "996555123456"})
        assert (await e.wait_done(await e.create()))["status"] == "done" and len(notifier.books) == 1
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_failing_print_offer_does_not_break_the_order(tmp_path):
    class Failing(FakeNotifier):
        async def send_print_offer(self, user_id, text, whatsapp_url):
            raise RuntimeError("Telegram недоступен")

    e = await build_env(tmp_path, notifier=Failing())
    try:
        e.service.desk.update({"whatsapp": "996555123456"})
        done = await e.wait_done(await e.create())
        assert done["status"] == "done" and done["delivered"] is True
        assert len(e.notifier.admin_books) == 1                                    # копия владельцу всё равно ушла
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


# ======================================================================= срок хранения фото
def age(path, hours: float) -> None:
    old = time.time() - hours * HOUR
    os.utime(path, (old, old))


def test_photo_promise_constants_keep_the_hourly_cleanup_inside_24_hours():
    assert PHOTO_TTL == 24 * HOUR and CLEANUP_PERIOD == HOUR
    assert PHOTO_PURGE_AFTER + CLEANUP_PERIOD <= PHOTO_TTL                       # даже при худшем совпадении не дольше суток


async def make_photo_order(env, user=USER):
    resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, jpeg(), user)
    data = await resp.json()
    assert resp.status == 201, data
    return data["order_id"]


async def test_photo_is_removed_after_a_successful_generation(tmp_path):
    e = await build_env(tmp_path, image=ScriptedImage(supports_reference=True))
    try:
        order_id = await make_photo_order(e)
        assert (await e.wait_done(order_id))["status"] == "done"
        assert not (e.service.order_dir(order_id) / "photo.jpg").exists()
        assert (e.service.order_dir(order_id) / "book.pdf").exists()               # а книга на месте
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


@pytest.mark.parametrize("text", [BoomText, BrokenStoryText, CrashingText])
async def test_photo_is_removed_after_a_failed_generation(tmp_path, text):
    e = await build_env(tmp_path, image=ScriptedImage(supports_reference=True), text=text())
    try:
        order_id = await make_photo_order(e)
        assert (await e.wait_done(order_id))["status"] == "error"
        assert not (e.service.order_dir(order_id) / "photo.jpg").exists()
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_photo_is_removed_when_generation_is_stopped_by_shutdown(tmp_path):
    e = await build_env(tmp_path, image=ScriptedImage(supports_reference=True, delay=0.5))
    try:
        order_id = await make_photo_order(e)
        photo = e.service.order_dir(order_id) / "photo.jpg"
        await asyncio.sleep(0.1)
        assert photo.exists()                                                       # пока книга рисуется, фото лежит
        await e.service.shutdown()
        assert not photo.exists() and e.db.get_order(order_id)["status"] == "error"
    finally:
        await e.client.close(); e.db.close()


async def test_photo_of_a_waiting_order_is_purged_after_a_day_whatever_the_status(tmp_path):
    e = await build_env(tmp_path, image=ScriptedImage(supports_reference=True))
    try:
        await e.client.post("/api/admin/qr", data=form("qr", png()), headers=tma(ADMIN_ID))
        await e.client.post("/api/admin/settings", json={"enabled": True}, headers=tma(ADMIN_ID))
        old_id, young_id = await make_photo_order(e, 42), await make_photo_order(e, 43)
        assert {e.db.get_order(i)["status"] for i in (old_id, young_id)} == {"awaiting_payment"}
        old_photo, young_photo = (e.service.order_dir(i) / "photo.jpg" for i in (old_id, young_id))
        assert old_photo.exists() and young_photo.exists()
        age(old_photo, 25)
        age(young_photo, 5)
        assert e.service.cleanup() == 0                                              # заказов не удалено, фото убрано
        assert not old_photo.exists() and young_photo.exists()
        assert e.db.get_order(old_id)["status"] == "awaiting_payment" and e.service.order_dir(old_id).exists()
        age(young_photo, 24.5)
        e.service.cleanup()
        assert not young_photo.exists()
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_photo_purge_leaves_the_rest_of_the_order_and_has_a_margin_for_the_hourly_run(env):
    order_id = await env.create()
    await env.wait_done(order_id)
    odir = env.service.order_dir(order_id)
    for name in ("photo.jpg", "receipt.jpg"):
        (odir / name).write_bytes(b"\xff\xd8x")
    age(odir / "photo.jpg", 22)
    assert env.service.purge_old_photos() == 0 and (odir / "photo.jpg").exists()       # 22 часа: рано
    age(odir / "photo.jpg", 23.5)                                                      # следующий запуск был бы уже позже суток
    assert env.service.purge_old_photos() == 1 and not (odir / "photo.jpg").exists()
    assert (odir / "book.pdf").exists() and (odir / "cover.jpg").exists() and (odir / "receipt.jpg").exists()
    assert env.service.purge_old_photos() == 0                                         # повторный запуск ничего не ломает


async def test_photo_purge_covers_orphan_folders_and_survives_missing_files(env):
    orphan = env.service.orders_dir / "orphanOrder1"
    orphan.mkdir()
    (orphan / "photo.jpg").write_bytes(b"\xff\xd8x")
    (env.service.orders_dir / "emptyOrder01").mkdir()                                  # без фото
    (env.service.orders_dir / "stray.txt").write_text("x")                              # файл вместо папки
    age(orphan / "photo.jpg", 30)
    assert env.service.purge_old_photos() == 1 and not (orphan / "photo.jpg").exists()


async def test_hourly_cleanup_also_purges_photos_and_keeps_returning_order_count(env):
    order_id = await env.create()
    await env.wait_done(order_id)
    odir = env.service.order_dir(order_id)
    (odir / "photo.jpg").write_bytes(b"\xff\xd8x")
    age(odir / "photo.jpg", 48)
    assert env.service.cleanup() == 0 and not (odir / "photo.jpg").exists() and odir.exists()
    env.db._exec("UPDATE orders SET created_at=? WHERE id=?", (time.time() - 8 * 86400, order_id))
    assert env.service.cleanup() == 1 and not odir.exists()


def test_cancelled_order_has_its_own_progress_label():
    progress = OrderService._progress("cancelled", False, 0)
    assert progress["label"] == "Отменено" and progress["percent"] == 0
    assert OrderService._progress("error", False, 0)["label"] == "Ошибка"


async def test_cleanup_loop_runs_every_cleanup_period_and_survives_a_failing_run(monkeypatch):
    from app import main

    calls, pauses = [], []

    class Service:
        def cleanup(self):
            calls.append(1)
            raise RuntimeError("диск недоступен")           # ошибка уборки не должна останавливать цикл

    async def stop_after_first_pause(seconds):
        pauses.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(main.asyncio, "sleep", stop_after_first_pause)
    with pytest.raises(asyncio.CancelledError):
        await main.cleanup_loop(Service())
    assert calls == [1] and pauses == [CLEANUP_PERIOD]


async def test_failed_pictures_do_not_deliver_a_book_of_placeholders_and_refund_the_credit(tmp_path):
    from app.errors import ProviderError
    e = await build_env(tmp_path, closed=True, image=ScriptedImage(fail=lambda n, p, label: ProviderError("сбой")))
    try:
        await give_access(e, USER, 1)
        order_id = (await post_order(e))[1]["order_id"]
        end = time.time() + 30
        while time.time() < end and e.db.get_order(order_id)["status"] not in ("error", "done"):
            await asyncio.sleep(0.1)
        assert e.db.get_order(order_id)["status"] == "error" and e.db.get_credits(USER) == 1
        assert e.notifier.books == []                                      # клиенту книга из заглушек не уходит
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_resend_is_rate_limited_and_does_not_copy_the_admin_again(env):
    order_id = await env.create(user_id=42)
    await env.wait_done(order_id, 42)
    first = await env.client.post(f"/api/orders/{order_id}/send", headers=tma(42))
    second = await env.client.post(f"/api/orders/{order_id}/send", headers=tma(42))
    assert first.status == 200 and second.status == 409
    copies = len(env.notifier.admin_books)
    assert copies == 1                                                    # копия админу была только при первой доставке


def test_a_decompression_bomb_is_refused_before_it_is_decoded():
    import io
    from PIL import Image
    from app.imaging import prepare_photo
    buf = io.BytesIO()
    Image.new("L", (7000, 7000)).save(buf, "PNG")                         # 49 млн пикселей (Pillow только предупреждает), файл крошечный
    with pytest.raises(ValidationError, match="пикселях"):
        prepare_photo(buf.getvalue())
