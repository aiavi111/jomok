"""API целиком: подпись, лимиты, доступ к файлам, ошибки, отзывы, фото, перезапуск."""
import io
import json
import time

import aiohttp
import pytest
from PIL import Image

from app.errors import ProviderError
from app.links import make_token
from app.providers.base import TextProvider
from app.providers.text_mock import MockTextProvider

from .conftest import ADMIN_ID, SAMPLE, FakeNotifier, ScriptedImage, build_env, provider_error, sign_init_data, tma


def jpeg(size=(300, 200), color=(200, 120, 80)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


# ----------------------------------------------------------------------- доступ и подпись
async def test_health_needs_no_auth(env):
    resp = await env.client.get("/api/health")
    assert resp.status == 200 and (await resp.json())["status"] == "ok"


async def test_every_other_api_route_requires_valid_signature(env):
    forged = {"Authorization": "tma " + sign_init_data(1, token="1:OTHERtokenOTHERtokenOTHERtokenOTHER12")}
    for headers in ({}, {"Authorization": "tma garbage"}, forged):
        for method, url in (("get", "/api/config"), ("post", "/api/orders"), ("get", "/api/orders/abcdefghijkl"),
                            ("post", "/api/feedback")):
            resp = await getattr(env.client, method)(url, headers=headers)
            assert resp.status == 401, (method, url, headers)


async def test_expired_init_data_is_rejected(env):
    old = tma(1, auth_date=time.time() - 2 * 86400)
    assert (await env.client.get("/api/config", headers=old)).status == 401


async def test_config_describes_providers_limits_and_options(env):
    data = await (await env.client.get("/api/config", headers=tma())).json()
    assert data["text_provider"] == "mock" and data["image_provider"] == "mock" and data["mock"] is True
    assert data["limits"]["books_per_day"] == 3 and data["limits"]["remaining_today"] == 3
    assert data["photo_supported"] is True and data["privacy_warning"] is None
    assert data["price_text"] == "499 сом" and data["free_in_test"] is True and data["dev_mode"] is False
    assert [p["id"] for p in data["options"]["places"]][0] == "mountains"
    assert data["bot_username"] == "test_bot" and data["active_order_id"] is None


async def test_gemini_text_shows_privacy_warning_and_disables_photo(tmp_path):
    e = await build_env(tmp_path, text_provider="gemini")
    try:
        data = await (await e.client.get("/api/config", headers=tma())).json()
        assert data["privacy_warning"] == "Тестовый режим: не вводите настоящие имена и не загружайте фото"
        assert data["photo_supported"] is False
    finally:
        await e.client.close(); e.db.close()


async def test_dev_mode_skips_signature_but_normal_mode_does_not(tmp_path):
    e = await build_env(tmp_path, dev_mode=True)
    try:
        assert (await e.client.get("/api/config")).status == 200
        assert (await e.client.get("/api/config", headers={"Authorization": "tma dev:5"})).status == 200
    finally:
        await e.client.close(); e.db.close()


# ----------------------------------------------------------------------- заказ от начала до конца
async def test_full_order_flow_with_files_and_delivery(env):
    order_id = await env.create()
    order = await env.wait_done(order_id)
    assert order["status"] == "done" and order["progress"]["percent"] == 100
    assert order["title"] and len(order["pages"]) == 8 and all(p["image_url"] for p in order["pages"])
    assert order["cover_url"] and order["pdf_url"] and order["book"]["caption"] == "Сказка для Айдара"
    assert order["delivered"] is True and order["error"] is None and "error_detail" not in order
    # PDF отправлен в чат владельца и копия — администратору
    assert [b[0] for b in env.notifier.books] == [42]
    assert env.notifier.books[0][2].endswith(".pdf") and len(env.notifier.admin_books) == 1
    # файлы по заголовку
    pdf = await env.client.get(f"/api/orders/{order_id}/book.pdf", headers=tma())
    assert pdf.status == 200 and pdf.content_type == "application/pdf" and (await pdf.read())[:4] == b"%PDF"
    img = await env.client.get(f"/api/orders/{order_id}/img/p3.jpg", headers=tma())
    assert img.status == 200 and img.content_type == "image/jpeg"
    # и по подписанной ссылке (для <img> и скачивания), с нужными заголовками для downloadFile
    link = await env.client.get(order["pdf_url"] + "&download=1")
    assert link.status == 200
    assert link.headers["Content-Disposition"].startswith("attachment; filename=")
    assert link.headers["Access-Control-Allow-Origin"] == "https://web.telegram.org"
    assert (await env.client.get(order["pages"][0]["image_url"])).status == 200


async def test_pages_appear_before_pdf_is_ready(tmp_path):
    e = await build_env(tmp_path, image=ScriptedImage(delay=0.15))
    try:
        order_id = await e.create()
        seen_partial = False
        for _ in range(200):
            data = await (await e.client.get(f"/api/orders/{order_id}", headers=tma())).json()
            pages = data["pages"]
            if pages and any(p["image_url"] is None for p in pages) and any(p["image_url"] for p in pages):
                seen_partial = True
                assert all(p["text"] for p in pages)            # текст есть сразу после написания
                assert data["pdf_url"] is None and data["status"] == "drawing"
                break
            if data["status"] in ("done", "error"):
                break
            await __import__("asyncio").sleep(0.03)
        assert seen_partial
    finally:
        await e.wait_done(order_id)
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_stranger_cannot_see_order_or_files(env):
    order_id = await env.create(user_id=42)
    done = await env.wait_done(order_id)
    other = tma(43)
    assert (await env.client.get(f"/api/orders/{order_id}", headers=other)).status == 404
    assert (await env.client.get(f"/api/orders/{order_id}/book.pdf", headers=other)).status == 404
    assert (await env.client.get(f"/api/orders/{order_id}/img/cover.jpg", headers=other)).status == 404
    assert (await env.client.post(f"/api/orders/{order_id}/send", headers=other)).status == 404
    assert (await env.client.post("/api/feedback", json={"order_id": order_id, "rating": "up"}, headers=other)).status == 404
    # без заголовка и без подписи — нельзя; с чужой/просроченной подписью — нельзя
    assert (await env.client.get(f"/api/orders/{order_id}/book.pdf")).status == 401
    assert (await env.client.get(f"/api/orders/{order_id}/book.pdf?t=1.abc")).status == 401
    old = make_token(env.service.link_secret, order_id, 42, now=time.time() - 30 * 3600)
    assert (await env.client.get(f"/api/orders/{order_id}/book.pdf?t={old}")).status == 401
    stolen = make_token(env.service.link_secret, order_id, 43)
    assert (await env.client.get(f"/api/orders/{order_id}/book.pdf?t={stolen}")).status == 401
    assert (await env.client.get(done["pdf_url"])).status == 200


async def test_bad_order_ids_and_file_names_never_touch_the_disk(env):
    for bad in ("..", "..%2F..%2Fetc", "a" * 100, "x"):
        resp = await env.client.get(f"/api/orders/{bad}/book.pdf", headers=tma())
        assert resp.status in (404, 405)
    order_id = await env.create()
    await env.wait_done(order_id)
    assert (await env.client.get(f"/api/orders/{order_id}/img/p9.jpg", headers=tma())).status == 404
    assert (await env.client.get(f"/api/orders/{order_id}/img/story.jpg", headers=tma())).status == 404


# ----------------------------------------------------------------------- лимиты
async def test_daily_book_limit(tmp_path):
    e = await build_env(tmp_path, max_books_per_user_per_day=2)
    try:
        for _ in range(2):
            order_id = await e.create()
            assert (await e.wait_done(order_id))["status"] == "done"
        resp = await e.client.post("/api/orders", json=SAMPLE, headers=tma())
        data = await resp.json()
        assert resp.status == 429 and data["code"] == "limit"
        assert "2 сказки" in data["error"] and "лимит (2)" in data["error"] and "через" in data["error"]
        cfg = await (await e.client.get("/api/config", headers=tma())).json()
        assert cfg["limits"]["remaining_today"] == 0
        # другой пользователь не затронут
        assert (await e.client.post("/api/orders", json=SAMPLE, headers=tma(99))).status == 201
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_only_one_active_order_per_user(tmp_path):
    e = await build_env(tmp_path, image=ScriptedImage(delay=0.2))
    try:
        first = await e.create()
        resp = await e.client.post("/api/orders", json=SAMPLE, headers=tma())
        data = await resp.json()
        assert resp.status == 409 and data["order_id"] == first
        cfg = await (await e.client.get("/api/config", headers=tma())).json()
        assert cfg["active_order_id"] == first
        await e.wait_done(first)
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_at_most_three_books_generate_at_the_same_time(tmp_path):
    state = {"now": 0, "max": 0}

    class Counting(MockTextProvider):
        async def generate_story(self, profile):
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
            try:
                await __import__("asyncio").sleep(0.15)
                return await super().generate_story(profile)
            finally:
                state["now"] -= 1

    e = await build_env(tmp_path, text=Counting(), max_books_per_user_per_day=5)
    try:
        ids = [(await e.create(user_id=100 + n), 100 + n) for n in range(6)]
        for order_id, uid in ids:
            assert (await e.wait_done(order_id, uid))["status"] == "done"
        assert state["max"] == 3
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


@pytest.mark.parametrize("patch, field", [
    ({"name": ""}, "name"), ({"name": "А" * 31}, "name"), ({"name": "Ай<script>"}, "name"),
    ({"age": 2}, "age"), ({"age": 10}, "age"), ({"age": "семь"}, "age"),
    ({"gender": "other"}, "gender"), ({"likes": ["а", "б", "в", "г"]}, "likes"), ({"likes": ["я" * 61]}, "likes"),
    ({"traits": ["kind", "brave", "funny", "shy"]}, "traits"), ({"traits": ["evil"]}, "traits"),
    ({"place": "moon"}, "place"), ({"place": "custom", "place_custom": ""}, "place_custom"),
    ({"value": "greed"}, "value"), ({"language": "en"}, "language"),
    ({"dedication": "я" * 121}, "dedication"),
    ({"appearance": {"hair": "я" * 121, "eyes": "", "clothes": ""}}, "hair"),
])
async def test_invalid_questionnaire_is_rejected_with_field(env, patch, field):
    resp = await env.client.post("/api/orders", json={**SAMPLE, **patch}, headers=tma())
    data = await resp.json()
    assert resp.status == 400 and data["field"] == field and data["error"]


async def test_control_characters_are_stripped_from_text_fields(env):
    payload = {**SAMPLE, "dedication": "Привет\u0000‮​\nмир   вот", "likes": ["Кони\u0007"]}
    order_id = await env.create(payload)
    stored = json.loads(env.db.get_order(order_id)["profile_json"])
    assert stored["dedication"] == "Привет мир вот" and stored["likes"] == ["Кони"]
    await env.wait_done(order_id)


async def test_broken_json_body_gives_readable_error(env):
    resp = await env.client.post("/api/orders", data=b"{not json", headers={**tma(), "Content-Type": "application/json"})
    assert resp.status == 400 and "error" in await resp.json()


# ----------------------------------------------------------------------- ошибки генерации
class ExplodingText(TextProvider):
    name = "boom"

    async def _complete(self, system, messages):
        raise provider_error("Неверный ключ OpenAI. Проверьте OPENAI_API_KEY в .env.", fatal=True)

    async def generate_story(self, profile):
        raise provider_error("Неверный ключ OpenAI. Проверьте OPENAI_API_KEY в .env.", fatal=True)


async def test_service_failure_is_explained_not_counted_and_admin_is_told(tmp_path):
    e = await build_env(tmp_path, text=ExplodingText(), max_books_per_user_per_day=1)
    try:
        order_id = await e.create(user_id=42)
        data = await e.wait_done(order_id)
        assert data["status"] == "error"
        assert "не засчитана" in data["error"] and "OPENAI" not in data["error"]       # родителю — без технических деталей
        assert "error_detail" not in data
        assert any("Неверный ключ OpenAI" in t for t in e.notifier.admin_texts)
        # попытка не считается: лимит 1, но можно создать ещё раз
        again = await e.client.post("/api/orders", json=SAMPLE, headers=tma(42))
        assert again.status == 201
        await e.wait_done((await again.json())["order_id"])
        # администратор видит техническую причину прямо в Mini App
        admin_order = await e.create(user_id=ADMIN_ID)
        detail = await e.wait_done(admin_order, ADMIN_ID)
        assert "Неверный ключ OpenAI" in detail["error_detail"]
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_one_broken_picture_does_not_break_the_book_and_admin_is_notified(tmp_path):
    image = ScriptedImage(fail=lambda n, p, label: provider_error("503 от провайдера") if label == "Страница 6" else None)
    e = await build_env(tmp_path, image=image)
    try:
        order_id = await e.create()
        data = await e.wait_done(order_id)
        assert data["status"] == "done" and data["pdf_url"] and len(data["pages"]) == 8
        assert data["pages"][5]["image_url"]                       # на месте — заглушка
        assert any("p6" in t and "заглушки" in t for t in e.notifier.admin_texts)
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_unfinished_orders_become_errors_after_restart_and_are_not_counted(tmp_path):
    e = await build_env(tmp_path, max_books_per_user_per_day=1)
    try:
        e.db.create_order("restartOrder1", 42, json.dumps({"language": "ru"}))
        e.db.update_order("restartOrder1", status="drawing")
        e.service.recover()
        row = e.db.get_order("restartOrder1")
        assert row["status"] == "error" and "перезапущен" in row["error"]
        assert (await e.client.post("/api/orders", json=SAMPLE, headers=tma(42))).status == 201
        await e.wait_done(e.db.active_order(42)["id"])
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


# ----------------------------------------------------------------------- доставка в чат
async def test_failed_delivery_is_reported_and_can_be_retried(tmp_path):
    notifier = FakeNotifier(deliver=False)
    e = await build_env(tmp_path, notifier=notifier)
    try:
        order_id = await e.create()
        data = await e.wait_done(order_id)
        assert data["delivered"] is False and data["pdf_url"]
        resp = await e.client.post(f"/api/orders/{order_id}/send", headers=tma())
        assert (await resp.json())["delivered"] is False
        notifier.deliver = True
        resp = await e.client.post(f"/api/orders/{order_id}/send", headers=tma())
        assert (await resp.json())["delivered"] is True
        assert (await (await e.client.get(f"/api/orders/{order_id}", headers=tma())).json())["delivered"] is True
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


# ----------------------------------------------------------------------- отзывы
async def test_feedback_saved_updated_and_forwarded_to_admin(env):
    order_id = await env.create()
    await env.wait_done(order_id)
    resp = await env.client.post("/api/feedback", headers=tma(), json={
        "order_id": order_id, "rating": "up", "comment": "Очень понравилось!", "would_pay": "yes"})
    assert resp.status == 200
    row = env.db.get_feedback(order_id, 42)
    assert (row["rating"], row["would_pay"], row["comment"]) == (1, "yes", "Очень понравилось!")
    await env.client.post("/api/feedback", headers=tma(), json={"order_id": order_id, "rating": "down", "would_pay": "no"})
    assert env.db.get_feedback(order_id, 42)["rating"] == 0
    assert any("Отзыв по заказу" in t and "Очень понравилось" in t for t in env.notifier.admin_texts)


@pytest.mark.parametrize("body", [
    {"rating": "great"}, {"would_pay": "definitely"}, {"comment": "я" * 1001, "rating": "up"}, {},
])
async def test_feedback_validation(env, body):
    order_id = await env.create()
    await env.wait_done(order_id)
    resp = await env.client.post("/api/feedback", headers=tma(), json={"order_id": order_id, **body})
    assert resp.status == 400


# ----------------------------------------------------------------------- фото
async def post_with_photo(client, payload, photo, user_id=42):
    form = aiohttp.FormData()
    form.add_field("profile", json.dumps(payload, ensure_ascii=False), content_type="application/json")
    form.add_field("photo", photo, filename="kid.jpg", content_type="image/jpeg")
    return await client.post("/api/orders", data=form, headers=tma(user_id))


async def test_photo_requires_parent_consent(env):
    resp = await post_with_photo(env.client, SAMPLE, jpeg())
    data = await resp.json()
    assert resp.status == 400 and data["field"] == "photo_consent" and "согласие" in data["error"]


async def test_photo_reaches_only_reference_capable_provider_and_is_deleted_after(tmp_path):
    image = ScriptedImage(supports_reference=True)
    e = await build_env(tmp_path, image=image)
    try:
        resp = await post_with_photo(e.client, {**SAMPLE, "photo_consent": True}, jpeg())
        assert resp.status == 201
        order_id = (await resp.json())["order_id"]
        await e.wait_done(order_id)
        cover = next(c for c in image.calls if c["label"] == "Обложка")
        assert cover["refs"] and cover["refs"][0][:2] == b"\xff\xd8"           # JPEG без метаданных
        assert not (e.service.order_dir(order_id) / "photo.jpg").exists()      # удалено сразу после генерации
        assert "photo" not in e.db.get_order(order_id)["profile_json"].replace("has_photo", "")
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close()


async def test_photo_is_refused_for_provider_without_references(tmp_path):
    e = await build_env(tmp_path, image=ScriptedImage(supports_reference=False))
    try:
        cfg = await (await e.client.get("/api/config", headers=tma())).json()
        assert cfg["photo_supported"] is False
        resp = await post_with_photo(e.client, {**SAMPLE, "photo_consent": True}, jpeg())
        assert resp.status == 400 and (await resp.json())["field"] == "photo"
    finally:
        await e.client.close(); e.db.close()


async def test_not_an_image_and_huge_photo_are_rejected(env):
    resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, b"%PDF-1.4 not an image")
    assert resp.status == 400 and (await resp.json())["field"] == "photo"
    resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, b"\xff\xd8" + b"0" * (9 * 1024 * 1024))
    assert resp.status in (400, 413)


async def test_exif_gps_is_stripped_from_photo():
    from app.imaging import prepare_photo
    image = Image.new("RGB", (400, 300), (10, 120, 200))
    exif = Image.Exif()
    exif[0x8825] = {1: "N"}                       # блок GPS
    exif[0x010F] = "SecretCamera"
    buf = io.BytesIO()
    image.save(buf, "JPEG", exif=exif)
    assert b"SecretCamera" in buf.getvalue()
    cleaned = prepare_photo(buf.getvalue())
    assert b"SecretCamera" not in cleaned and not Image.open(io.BytesIO(cleaned)).getexif()


# ----------------------------------------------------------------------- очистка
async def test_files_and_personal_data_are_removed_after_keep_days(env):
    order_id = await env.create()
    await env.wait_done(order_id)
    odir = env.service.order_dir(order_id)
    assert odir.exists()
    assert env.service.cleanup() == 0                                  # свежий заказ не трогаем
    env.db._exec("UPDATE orders SET created_at=? WHERE id=?", (time.time() - 8 * 86400, order_id))
    assert env.service.cleanup() == 1
    assert not odir.exists()
    row = env.db.get_order(order_id)
    assert row["files_deleted"] == 1 and json.loads(row["profile_json"])["name"] == ""
    assert (await env.client.get(f"/api/orders/{order_id}/book.pdf", headers=tma())).status == 404
    data = await (await env.client.get(f"/api/orders/{order_id}", headers=tma())).json()
    assert data["files_deleted"] is True and data["pdf_url"] is None


# ----------------------------------------------------------------------- Mini App
async def test_mini_app_is_served_with_cache_busting_version(env):
    resp = await env.client.get("/")
    html = await resp.text()
    assert resp.status == 200 and "telegram-web-app.js" in html
    assert "__V__" not in html and "/static/app.js?v=" in html
    assert (await env.client.get("/static/app.js")).status == 200
    assert (await env.client.get("/static/style.css")).status == 200
    assert (await env.client.get("/static/../app/config.py")).status in (403, 404)
