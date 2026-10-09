"""Оплата переводом по QR: настройки владельца, чек, подтверждение, отказ, отмена, перезапуск."""
import io
import json
import sqlite3
import time

import aiohttp
import pytest
from PIL import Image

from app.db import Database
from app.service import OrderService
from app.links import load_or_create_secret
from app.payments import FreePayment
from app.providers.image_mock import MockImageProvider
from app.providers.text_mock import MockTextProvider

from .conftest import ADMIN_ID, SAMPLE, FakeNotifier, build_env, tma

USER = 42


def png(size=(300, 300), color=(10, 10, 10)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def jpeg(size=(800, 1200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (240, 240, 240)).save(out, "JPEG")
    return out.getvalue()


def form(field: str, data: bytes, name="file.png", ctype="image/png") -> aiohttp.FormData:
    f = aiohttp.FormData()
    f.add_field(field, data, filename=name, content_type=ctype)
    return f


async def setup_payments(env, *, price="499 сом", enable=True):
    resp = await env.client.post("/api/admin/qr", data=form("qr", png()), headers=tma(ADMIN_ID))
    assert resp.status == 200, await resp.text()
    resp = await env.client.post("/api/admin/settings", json={"enabled": enable, "price_text": price}, headers=tma(ADMIN_ID))
    assert resp.status == 200, await resp.text()


async def create_unpaid(env, user=USER) -> str:
    resp = await env.client.post("/api/orders", json=SAMPLE, headers=tma(user))
    data = await resp.json()
    assert resp.status == 201 and data["status"] == "awaiting_payment", data
    return data["order_id"]


async def send_receipt(env, order_id, user=USER, data=None):
    return await env.client.post(f"/api/orders/{order_id}/receipt", data=form("receipt", data or jpeg(), "check.jpg", "image/jpeg"),
                                 headers=tma(user))


async def view(env, order_id, user=USER) -> dict:
    return await (await env.client.get(f"/api/orders/{order_id}", headers=tma(user))).json()


# ----------------------------------------------------------------------- настройки владельца
async def test_by_default_books_are_created_without_payment(env):
    cfg = await (await env.client.get("/api/config", headers=tma(USER))).json()
    assert cfg["payment_required"] is False and cfg["is_admin"] is False
    order_id = await env.create()
    assert (await env.wait_done(order_id))["status"] == "done"


async def test_admin_routes_are_closed_for_everyone_but_the_owner(env):
    for method, url in (("get", "/api/admin/payments"), ("post", "/api/admin/settings"), ("post", "/api/admin/qr"),
                        ("post", "/api/admin/orders/abcdefghijkl/approve"), ("post", "/api/admin/orders/abcdefghijkl/reject")):
        resp = await getattr(env.client, method)(url, headers=tma(USER))
        assert resp.status == 403, (method, url)
        assert (await getattr(env.client, method)(url)).status == 401


async def test_cannot_enable_payments_without_qr(env):
    resp = await env.client.post("/api/admin/settings", json={"enabled": True}, headers=tma(ADMIN_ID))
    assert resp.status == 400 and "QR" in (await resp.json())["error"]


async def test_owner_uploads_qr_sets_price_and_users_see_it(env):
    await setup_payments(env, price="650 сом")
    cfg = await (await env.client.get("/api/config", headers=tma(USER))).json()
    assert cfg["payment_required"] is True and cfg["price_text"] == "650 сом" and cfg["free_in_test"] is False
    admin_cfg = await (await env.client.get("/api/config", headers=tma(ADMIN_ID))).json()
    assert admin_cfg["is_admin"] is True


async def test_bad_qr_and_bad_settings_are_rejected(env):
    for bad in (b"not an image", png((40, 40))):
        resp = await env.client.post("/api/admin/qr", data=form("qr", bad), headers=tma(ADMIN_ID))
        assert resp.status == 400
    resp = await env.client.post("/api/admin/settings", json={"price_text": ""}, headers=tma(ADMIN_ID))
    assert resp.status == 400
    resp = await env.client.post("/api/admin/settings", json={"instructions": "x" * 500}, headers=tma(ADMIN_ID))
    assert resp.status == 400


# ----------------------------------------------------------------------- покупка
async def test_unpaid_order_waits_and_nothing_is_generated(env):
    await setup_payments(env)
    order_id = await create_unpaid(env)
    await env.service.shutdown()
    v = await view(env, order_id)
    assert v["status"] == "awaiting_payment" and v["progress"]["label"] == "Ждём оплату"
    assert v["payment"]["price_text"] == "499 сом" and v["payment"]["receipt_sent"] is False
    assert v["payment"]["qr_url"].startswith("/api/payment/qr?t=")
    assert env.service.db.get_order(order_id)["paid"] == 0
    assert not (env.service.order_dir(order_id) / "story.json").exists()


async def test_qr_is_served_by_signed_link_and_by_header_only(env):
    await setup_payments(env)
    order_id = await create_unpaid(env)
    url = (await view(env, order_id))["payment"]["qr_url"]
    resp = await env.client.get(url)
    assert resp.status == 200 and resp.headers["Content-Type"] == "image/png"
    assert (await env.client.get("/api/payment/qr")).status == 401
    assert (await env.client.get("/api/payment/qr?t=1.deadbeef")).status == 401
    assert (await env.client.get("/api/payment/qr", headers=tma(USER))).status == 200


async def test_user_cannot_start_second_order_while_first_waits_for_payment(env):
    await setup_payments(env)
    first = await create_unpaid(env)
    resp = await env.client.post("/api/orders", json=SAMPLE, headers=tma(USER))
    assert resp.status == 409 and (await resp.json())["order_id"] == first
    cfg = await (await env.client.get("/api/config", headers=tma(USER))).json()
    assert cfg["active_order_id"] == first


async def test_receipt_goes_to_owner_and_order_waits_for_confirmation(env):
    await setup_payments(env)
    order_id = await create_unpaid(env)
    resp = await send_receipt(env, order_id)
    assert resp.status == 200
    v = await view(env, order_id)
    assert v["status"] == "payment_review" and v["payment"]["receipt_sent"] is True
    assert len(env.notifier.payments) == 1
    oid, path, text = env.notifier.payments[0]
    assert oid == order_id and path.exists() and "499 сом" in text and "Айдар" in text
    assert not (env.service.order_dir(order_id) / "story.json").exists()      # без подтверждения — ничего не пишется


async def test_receipt_must_be_an_image_and_belong_to_the_user(env):
    await setup_payments(env)
    order_id = await create_unpaid(env)
    assert (await send_receipt(env, order_id, data=b"%PDF-1.4 hello")).status == 400
    assert (await send_receipt(env, order_id, user=99)).status == 404
    resp = await env.client.post(f"/api/orders/{order_id}/receipt", json={}, headers=tma(USER))
    assert resp.status == 400


async def test_owner_sees_pending_receipts_and_opens_the_photo(env):
    await setup_payments(env)
    order_id = await create_unpaid(env)
    await send_receipt(env, order_id)
    data = await (await env.client.get("/api/admin/payments", headers=tma(ADMIN_ID))).json()
    assert [p["id"] for p in data["pending"]] == [order_id]
    item = data["pending"][0]
    assert item["child"] == "Айдар, 6 лет" and item["user"] == "Тест"
    resp = await env.client.get(item["receipt_url"])
    assert resp.status == 200 and resp.headers["Content-Type"] == "image/jpeg"
    assert (await env.client.get(f"/api/admin/receipts/{order_id}.jpg")).status == 401
    assert (await env.client.get(f"/api/admin/receipts/{order_id}.jpg", headers=tma(USER))).status == 403
    assert (await env.client.get(f"/api/admin/receipts/{order_id}.jpg", headers=tma(ADMIN_ID))).status == 200
    other = await env.client.get(f"/api/admin/receipts/zzzzzzzzzz.jpg?t={item['receipt_url'].split('t=')[1]}")
    assert other.status in (401, 404)


async def test_confirmation_starts_generation_and_tells_the_user(env):
    await setup_payments(env)
    order_id = await create_unpaid(env)
    await send_receipt(env, order_id)
    resp = await env.client.post(f"/api/admin/orders/{order_id}/approve", headers=tma(ADMIN_ID))
    assert resp.status == 200
    done = await env.wait_done(order_id)
    assert done["status"] == "done" and done["pdf_url"]
    row = env.service.db.get_order(order_id)
    assert row["paid"] == 1 and row["paid_at"] is not None
    assert any(uid == USER and "Оплата получена" in text for uid, text in env.notifier.user_texts)
    assert len(env.notifier.books) == 1
    overview = await (await env.client.get("/api/admin/payments", headers=tma(ADMIN_ID))).json()
    assert overview["pending"] == [] and overview["paid_today"] == 1 and overview["recent"][0]["id"] == order_id


async def test_double_confirmation_is_refused(env):
    await setup_payments(env)
    order_id = await create_unpaid(env)
    await send_receipt(env, order_id)
    assert (await env.client.post(f"/api/admin/orders/{order_id}/approve", headers=tma(ADMIN_ID))).status == 200
    assert (await env.client.post(f"/api/admin/orders/{order_id}/approve", headers=tma(ADMIN_ID))).status == 409
    await env.wait_done(order_id)


async def test_owner_can_confirm_without_receipt(env):
    """Заплатили в другом месте (например, договорились в WhatsApp): владелец подтверждает сам."""
    await setup_payments(env)
    order_id = await create_unpaid(env)
    assert (await env.client.post(f"/api/admin/orders/{order_id}/approve", headers=tma(ADMIN_ID))).status == 200
    assert (await env.wait_done(order_id))["status"] == "done"


async def test_rejection_returns_order_to_payment_with_reason_and_allows_new_receipt(env):
    await setup_payments(env)
    order_id = await create_unpaid(env)
    await send_receipt(env, order_id)
    resp = await env.client.post(f"/api/admin/orders/{order_id}/reject", json={"reason": "Сумма меньше 499"}, headers=tma(ADMIN_ID))
    assert resp.status == 200
    v = await view(env, order_id)
    assert v["status"] == "awaiting_payment" and v["payment"]["note"] == "Сумма меньше 499"
    assert any("Сумма меньше 499" in text for _, text in env.notifier.user_texts)
    assert not (env.service.order_dir(order_id) / "receipt.jpg").exists()
    assert (await send_receipt(env, order_id)).status == 200
    assert (await view(env, order_id))["status"] == "payment_review"
    assert (await env.client.post(f"/api/admin/orders/{order_id}/reject", headers=tma(ADMIN_ID))).status == 200
    assert (await view(env, order_id))["payment"]["note"].startswith("Платёж не найден")


async def test_user_can_cancel_unpaid_order_and_start_over(env):
    await setup_payments(env)
    order_id = await create_unpaid(env)
    assert (await env.client.post(f"/api/orders/{order_id}/cancel", headers=tma(99))).status == 404
    assert (await env.client.post(f"/api/orders/{order_id}/cancel", headers=tma(USER))).status == 200
    assert (await view(env, order_id))["status"] == "cancelled"
    assert env.service.remaining_today(USER) == 3                          # отменённый заказ в лимит не входит
    assert await create_unpaid(env)


async def test_paid_order_cannot_be_cancelled(env):
    order_id = await env.create()
    await env.wait_done(order_id)
    assert (await env.client.post(f"/api/orders/{order_id}/cancel", headers=tma(USER))).status == 409


async def test_turning_payments_off_lets_waiting_user_through_owner_only(env):
    await setup_payments(env)
    order_id = await create_unpaid(env)
    await env.client.post("/api/admin/settings", json={"enabled": False}, headers=tma(ADMIN_ID))
    assert (await send_receipt(env, order_id)).status == 409


# ----------------------------------------------------------------------- перезапуск и уборка
async def test_paid_order_survives_restart_but_unpaid_generation_is_interrupted(tmp_path):
    e = await build_env(tmp_path)
    try:
        db = e.service.db
        for oid, paid in (("paidpaid01", 1), ("freefree01", 0)):
            db.create_order(oid, USER if paid else 43, json.dumps(SAMPLE_PROFILE()), paid=bool(paid))
            db.update_order(oid, status="drawing")
        e.service.recover()
        assert db.get_order("freefree01")["status"] == "error"
        assert db.get_order("paidpaid01")["status"] == "drawing"
        assert e.service.resume_paid() == 1
        await e.wait_done("paidpaid01")
        assert db.get_order("paidpaid01")["status"] == "done"
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


def SAMPLE_PROFILE() -> dict:
    from app.profile import Profile
    return Profile.from_payload(SAMPLE).to_dict()


async def test_old_unpaid_orders_are_cancelled_by_cleanup(env):
    await setup_payments(env)
    order_id = await create_unpaid(env)
    env.db._exec("UPDATE orders SET created_at=? WHERE id=?", (time.time() - 5 * 86400, order_id))
    env.service.cleanup()
    row = env.db.get_order(order_id)
    assert row["status"] == "cancelled" and row["files_deleted"] == 1
    assert "Айдар" not in row["profile_json"]


def test_old_database_gets_new_columns(tmp_path):
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript("""CREATE TABLE orders(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, status TEXT NOT NULL,
        profile_json TEXT NOT NULL, title TEXT, paid INTEGER NOT NULL DEFAULT 0, payment_charge_id TEXT, error TEXT,
        error_detail TEXT, delivered INTEGER, files_deleted INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
        updated_at REAL NOT NULL, finished_at REAL);
        INSERT INTO orders(id,user_id,status,profile_json,created_at,updated_at) VALUES('x',1,'done','{}',1,1);""")
    conn.close()
    db = Database(path)
    db.update_order("x", pay_note="ok", paid_at=5.0, receipt_at=1.0)
    row = db.get_order("x")
    assert row["pay_note"] == "ok" and row["paid_at"] == 5.0
    db.close()
