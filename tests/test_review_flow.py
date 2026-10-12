"""Двухшаговая ручная проверка: заявку клиента принимает человек, готовую книгу смотрит человек, и только потом она уходит клиенту.

Шаг 1: заказ создаётся (книга со счёта списывается), но генерация не стартует: статус awaiting_approval, администратору приходит
карточка с кнопками «Принять и начать» / «Отклонить». Шаг 2: после генерации книга НЕ уходит клиенту, статус in_review, администратору
приходят оба PDF и карточка с кнопками «Отправить клиенту», «Сделать заново», «Исправить страницу», «Исправить текст».
Всё на поддельных провайдерах и поддельном боте, без сети."""
import asyncio
import io
import json
import re
import time
from datetime import datetime
from pathlib import Path

import pytest
from aiogram.types import ForceReply, Update
from PIL import Image

from app import service as service_module
from app.bot import TelegramNotifier, pages_keyboard, request_keyboard, review_keyboard
from app.config import Settings
from app.errors import ConflictError, NotFoundError, ProviderError, ValidationError
from app.notify import NullNotifier
from app.story import PAGES

from .conftest import ADMIN_ID, SAMPLE, FakeNotifier, PlainNotifier, ScriptedImage, build_env, provider_error, tma
from .test_access import give_access
from .test_api import post_with_photo
from .test_bot import FakeSession, command_update, make_bot, make_dp, sent_messages
from .test_sheet import SheetImage

USER = 42
GOOD_TEXT = ("Айдар вышел во двор и увидел маленького светлячка. Огонёк у него погас, и светлячок загрустил. "
             "Айдар сел рядом и пообещал помочь.")


def jpeg(color=(200, 120, 80)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (300, 200), color).save(out, "JPEG")
    return out.getvalue()


async def make_env(tmp_path, *, approve=True, review=True, closed=True, credits=2, image=None, **kw):
    env = await build_env(tmp_path, closed=closed, approve=approve, review=review, image=image, **kw)
    if closed and credits:
        await give_access(env, user_id=USER, credits=credits)
    return env


async def close(env):
    await env.service.shutdown()
    await env.client.close()
    env.db.close()


async def settle(env):
    """Ждём, пока закончатся все фоновые задачи сервиса (генерация, перерисовка страницы)."""
    while env.service._tasks:
        await asyncio.gather(*list(env.service._tasks), return_exceptions=True)
        await asyncio.sleep(0)                      # даём задачам выйти из набора (иначе цикл крутится вхолостую)


async def wait_status(env, order_id, *statuses, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        row = env.db.get_order(order_id)
        if row["status"] in statuses:
            await settle(env)
            return row
        await asyncio.sleep(0.02)
    raise AssertionError(f"статус {statuses} не наступил, сейчас {env.db.get_order(order_id)['status']}")


async def make_request(env, user=USER, payload=None) -> str:
    resp = await env.client.post("/api/orders", json=payload or SAMPLE, headers=tma(user))
    data = await resp.json()
    assert resp.status == 201, data
    return data["order_id"]


async def to_review(env, user=USER, payload=None) -> str:
    """Заявка → принята → книга сгенерирована → ждёт проверки."""
    order_id = await make_request(env, user, payload)
    if env.db.get_order(order_id)["status"] == "awaiting_approval":
        await env.service.accept_request(order_id)
    await wait_status(env, order_id, "in_review", "error")
    return order_id


async def get_view(env, order_id, user=USER):
    resp = await env.client.get(f"/api/orders/{order_id}", headers=tma(user))
    return resp.status, await resp.json()


def odir(env, order_id) -> Path:
    return env.service.order_dir(order_id)


# ============================================================================ шаг 1: заявка
async def test_request_is_created_without_starting_the_generation(tmp_path):
    image = ScriptedImage()
    env = await make_env(tmp_path, image=image)
    try:
        order_id = await make_request(env)
        row = env.db.get_order(order_id)
        assert row["status"] == "awaiting_approval" and row["credit_used"] == 1
        assert env.db.get_credits(USER) == 1                               # книга списана, как обычно
        await asyncio.sleep(0.2)
        assert env.service._tasks == set() and image.calls == []         # генерация не стартовала, ничего не нарисовано
        assert env.db.get_order(order_id)["status"] == "awaiting_approval" and env.db.get_order(order_id)["title"] is None
    finally:
        await close(env)


async def test_create_response_and_order_view_say_awaiting_approval(tmp_path):
    env = await make_env(tmp_path)
    try:
        resp = await env.client.post("/api/orders", json=SAMPLE, headers=tma(USER))
        data = await resp.json()
        assert resp.status == 201 and data["status"] == "awaiting_approval"
        status, view = await get_view(env, data["order_id"])
        assert status == 200 and view["status"] == "awaiting_approval" and view["pdf_url"] is None
        assert view["pages"] == [] and view["cover_url"] is None and view["title"] is None
        assert "%" not in view["progress"]["label"] and view["progress"]["label"] == "Заявка на проверке"
    finally:
        await close(env)


async def test_request_card_has_everything_and_two_buttons_in_the_orders_chat(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier)
    try:
        payload = {**SAMPLE, "request": "Хочу, чтобы Айдар водил экскаватор", "photo_consent": True, "person_role": "grandmother"}
        resp = await post_with_photo(env.client, payload, jpeg(), user_id=USER)
        assert resp.status == 201
        order_id = (await resp.json())["order_id"]
        (card_order, text), = notifier.requests
        assert card_order == order_id and text.startswith(f"🧾 Новая заявка {order_id}")
        for part in ("От: ", "id 42", "Айдар, 6 лет, мальчик", "Тема: ", "Стиль: 3D-мультик", "язык: русский", "фото: есть",
                     "фото близкого человека: нет", "Пожелание: Хочу, чтобы Айдар водил экскаватор", "Осталось книг у клиента: 1"):
            assert part in text, part
        assert not [t for t in notifier.admin_texts if t.startswith("🧾")]            # «Новый заказ» без кнопок не дублируется
        assert notifier.reviews == [] and notifier.books == []
        # клиенту бот пишет, что заявка принята
        assert notifier.user_texts == [(USER, "✅ Заявка принята. Пришлём книгу в течение 1–2 часов")]
    finally:
        await close(env)


async def test_request_card_says_no_photo_and_no_wish(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier)
    try:
        await make_request(env)
        text = notifier.requests[0][1]
        assert "фото: нет" in text and "фото близкого человека: нет" in text and "Пожелание: нет" in text
    finally:
        await close(env)


async def test_accepting_the_request_queues_it_and_the_generation_runs_to_review(tmp_path):
    image = ScriptedImage()
    env = await make_env(tmp_path, image=image)
    try:
        order_id = await make_request(env)
        await env.service.accept_request(order_id)
        assert env.db.get_order(order_id)["status"] in ("queued", "writing", "drawing", "assembling", "in_review")
        row = await wait_status(env, order_id, "in_review", "error")
        assert row["status"] == "in_review" and row["title"] and row["finished_at"]
        assert len(image.calls) >= PAGES + 1                                # обложка и страницы нарисованы
    finally:
        await close(env)


async def test_declining_returns_the_book_deletes_files_and_tells_the_client(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier)
    try:
        payload = {**SAMPLE, "photo_consent": True}
        resp = await post_with_photo(env.client, payload, jpeg(), user_id=USER)
        order_id = (await resp.json())["order_id"]
        assert env.db.get_credits(USER) == 1 and (odir(env, order_id) / "photo.jpg").exists()
        await env.service.decline_request(order_id)
        row = env.db.get_order(order_id)
        assert row["status"] == "cancelled" and row["files_deleted"] == 1 and row["credit_used"] == 0
        assert env.db.get_credits(USER) == 2                                # книга вернулась на счёт
        assert not odir(env, order_id).exists()                             # фото и файлы заказа удалены
        assert json.loads(row["profile_json"])["name"] == "" and json.loads(row["profile_json"])["scrubbed"] is True
        assert notifier.user_texts[-1] == (USER, "К сожалению, заявку не получилось принять. Книга возвращена на ваш счёт, напишите нам.")
        assert env.db.active_order(USER) is None                            # человек может создать новую заявку
        _, view = await get_view(env, order_id)
        assert view["status"] == "cancelled"
    finally:
        await close(env)


async def test_declined_request_of_an_open_bot_does_not_promise_a_refund(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier, closed=False)
    try:
        order_id = await make_request(env)
        await env.service.decline_request(order_id)
        assert notifier.user_texts[-1] == (USER, "К сожалению, заявку не получилось принять. Напишите нам.")
    finally:
        await close(env)


async def test_double_click_is_harmless_in_every_order(tmp_path):
    image = ScriptedImage()
    env = await make_env(tmp_path, image=image, credits=3)
    try:
        a = await make_request(env)
        await env.service.accept_request(a)
        with pytest.raises(ConflictError):
            await env.service.accept_request(a)                            # второй «Принять»
        with pytest.raises(ConflictError):
            await env.service.decline_request(a)                           # «Отклонить» после «Принять»
        await wait_status(env, a, "in_review")
        credits = env.db.get_credits(USER)
        b_user = 43
        await give_access(env, user_id=b_user, credits=1)
        b = await make_request(env, user=b_user)
        await env.service.decline_request(b)
        with pytest.raises(ConflictError):
            await env.service.decline_request(b)                           # второй «Отклонить»
        with pytest.raises(ConflictError):
            await env.service.accept_request(b)                            # «Принять» после «Отклонить»
        assert env.db.get_credits(b_user) == 1                              # книга вернулась ровно один раз
        assert env.db.get_credits(USER) == credits
        with pytest.raises(NotFoundError):
            await env.service.accept_request("несуществующий")
    finally:
        await close(env)


async def test_two_parallel_clicks_start_the_generation_only_once(tmp_path):
    image = ScriptedImage()
    env = await make_env(tmp_path, image=image)
    try:
        order_id = await make_request(env)
        results = await asyncio.gather(env.service.accept_request(order_id), env.service.accept_request(order_id),
                                       env.service.decline_request(order_id), return_exceptions=True)
        assert sum(r is None for r in results) == 1                         # выигрывает ровно одно нажатие
        await settle(env)
        assert env.db.get_order(order_id)["status"] in ("in_review", "cancelled")
    finally:
        await close(env)


async def test_owner_requests_skip_the_approval_step_but_the_book_is_still_reviewed(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier, credits=0)
    try:
        order_id = await make_request(env, user=ADMIN_ID)
        assert env.db.get_order(order_id)["status"] in ("queued", "writing", "drawing", "assembling")
        assert notifier.requests == [] and notifier.user_texts == []        # самому себе заявку принимать не нужно
        row = await wait_status(env, order_id, "in_review", "error")
        assert row["status"] == "in_review"                                  # а книгу владелец тоже проверяет
        assert notifier.books == [] and notifier.reviews
    finally:
        await close(env)


async def test_one_active_order_per_person_includes_the_new_statuses(tmp_path):
    env = await make_env(tmp_path, credits=3)
    try:
        order_id = await make_request(env)
        resp = await env.client.post("/api/orders", json=SAMPLE, headers=tma(USER))
        data = await resp.json()
        assert resp.status == 409 and data["order_id"] == order_id           # заявка ещё ждёт решения
        cfg = await (await env.client.get("/api/config", headers=tma(USER))).json()
        assert cfg["active_order_id"] == order_id
        await env.service.accept_request(order_id)
        await wait_status(env, order_id, "in_review")
        resp = await env.client.post("/api/orders", json=SAMPLE, headers=tma(USER))
        assert resp.status == 409 and (await resp.json())["order_id"] == order_id    # книга ещё на проверке
        await env.service.approve_book(order_id)
        resp = await env.client.post("/api/orders", json=SAMPLE, headers=tma(USER))
        assert resp.status == 201
    finally:
        await close(env)


# ============================================================================ шаг 2: проверка книги
async def test_generation_ends_in_review_and_nothing_goes_to_the_client(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier)
    try:
        order_id = await to_review(env)
        row = env.db.get_order(order_id)
        assert row["status"] == "in_review" and row["delivered"] is None
        assert notifier.books == [] and notifier.print_offers == []          # клиенту ни книги, ни предложения печати
        assert [t for _, t in notifier.user_texts] == ["✅ Заявка принята. Пришлём книгу в течение 1–2 часов"]
        d = odir(env, order_id)
        assert (d / "book.pdf").exists() and (d / "mobile.pdf").exists()
        # администратору пришли оба файла и карточка с кнопками
        names = [name for _, name, _ in notifier.admin_books]
        assert len(names) == 2 and names[0].endswith("(развороты).pdf") and names[1].endswith("(для телефона).pdf")
        assert [p.name for p, _, _ in notifier.admin_books] == ["book.pdf", "mobile.pdf"]
        (card_order, text), = notifier.reviews
        assert card_order == order_id and "Книга готова, проверьте её" in text and "Клиенту ничего не уйдёт" in text
        assert "Не нарисовались" not in text
    finally:
        await close(env)


async def test_client_sees_a_waiting_status_without_pages_images_or_pdf(tmp_path):
    env = await make_env(tmp_path)
    try:
        order_id = await to_review(env)
        status, view = await get_view(env, order_id)
        assert status == 200 and view["status"] == "in_review"
        assert view["pdf_url"] is None and view["pages"] == [] and view["cover_url"] is None
        assert view["title"] is None and view["book"] is None and view["review"] is True
        assert view["progress"]["label"] == "Проверяем книгу"
        for name in ("img/cover.jpg", "img/p1.jpg", "book.pdf"):             # и по прямым ссылкам файлов не отдаём
            resp = await env.client.get(f"/api/orders/{order_id}/{name}", headers=tma(USER))
            assert resp.status == 404, name
        resp = await env.client.post(f"/api/orders/{order_id}/send", headers=tma(USER))
        assert resp.status == 404                                            # повторная отправка в чат тоже только для готовых
    finally:
        await close(env)


async def test_pages_are_hidden_from_the_client_while_the_book_is_being_made(tmp_path):
    image = ScriptedImage(delay=0.05)
    env = await make_env(tmp_path, image=image, approve=False)
    try:
        order_id = await make_request(env)
        seen = set()
        end = time.time() + 20
        while time.time() < end and env.db.get_order(order_id)["status"] != "in_review":
            _, view = await get_view(env, order_id)
            seen.add((view["status"], bool(view["pages"]), bool(view["cover_url"])))
            await asyncio.sleep(0.02)
        assert all(not pages and not cover for _, pages, cover in seen), seen
        assert any(s in ("writing", "drawing") for s, _, _ in seen)
    finally:
        await close(env)


async def test_sending_to_the_client_delivers_both_files_marks_done_and_deletes_photos(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier)
    try:
        resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, jpeg(), user_id=USER)
        order_id = (await resp.json())["order_id"]
        await env.service.accept_request(order_id)
        await wait_status(env, order_id, "in_review")
        assert (odir(env, order_id) / "photo.jpg").exists()                  # для правок фото ещё нужно
        admin_files = len(notifier.admin_books)
        await env.service.approve_book(order_id)
        row = env.db.get_order(order_id)
        assert row["status"] == "done" and row["delivered"] == 1
        assert [(u, n) for u, _, n, _ in notifier.books][0][0] == USER and len(notifier.books) == 2       # книга и версия для телефона
        assert notifier.books[1][2].endswith("(для телефона).pdf")
        assert notifier.print_offers == [] or notifier.print_offers[0][0] == USER                       # предложение печати только клиенту
        assert len(notifier.admin_books) == admin_files                      # копию админу второй раз не шлём: он уже видел оба файла
        assert not (odir(env, order_id) / "photo.jpg").exists() and not (odir(env, order_id) / "person.jpg").exists()
        status, view = await get_view(env, order_id)
        assert view["status"] == "done" and view["pdf_url"] and len(view["pages"]) == PAGES and view["delivered"] is True
        assert any(t.startswith(f"✅ Заказ {order_id} готов") for t in notifier.admin_texts)           # карточка «готов» в чат заказов
    finally:
        await close(env)


async def test_send_twice_is_harmless_and_unready_books_cannot_be_sent(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier)
    try:
        order_id = await make_request(env)
        with pytest.raises(ConflictError):
            await env.service.approve_book(order_id)                         # заявку ещё не приняли, книги нет
        await env.service.accept_request(order_id)
        await wait_status(env, order_id, "in_review")
        results = await asyncio.gather(env.service.approve_book(order_id), env.service.approve_book(order_id),
                                       return_exceptions=True)
        assert sum(r is None for r in results) == 1 and sum(isinstance(r, ConflictError) for r in results) == 1
        assert len(notifier.books) == 2                                      # книга ушла один раз
        with pytest.raises(ConflictError):
            await env.service.approve_book(order_id)
        with pytest.raises(ConflictError):
            await env.service.redo_book(order_id)
    finally:
        await close(env)


async def test_failed_generation_still_means_error_refund_and_admin_message(tmp_path):
    notifier = FakeNotifier()
    image = ScriptedImage(fail=lambda n, prompt, label: provider_error("нет денег", fatal=True))
    env = await make_env(tmp_path, notifier=notifier, image=image)
    try:
        order_id = await make_request(env)
        await env.service.accept_request(order_id)
        row = await wait_status(env, order_id, "error")
        assert row["error"] and env.db.get_credits(USER) == 2                 # книга вернулась
        assert any("не создан" in t for t in notifier.admin_texts) and notifier.reviews == [] and notifier.books == []
        assert notifier.user_texts[-1][0] == USER and "не получилась" in notifier.user_texts[-1][1]   # клиент мог закрыть приложение
    finally:
        await close(env)


async def test_failed_pages_are_marked_in_the_review_card(tmp_path):
    notifier = FakeNotifier()
    image = ScriptedImage(fail=lambda n, prompt, label: provider_error("фильтр", no_retry=True) if label == "Страница 3" else None)
    env = await make_env(tmp_path, notifier=notifier, image=image)
    try:
        order_id = await to_review(env)
        assert "Не нарисовались: страница 3" in notifier.reviews[0][1] and "Исправить страницу" in notifier.reviews[0][1]
    finally:
        await close(env)


async def test_redo_regenerates_from_the_same_form_and_keeps_the_photo(tmp_path):
    notifier = FakeNotifier()
    image = ScriptedImage()
    env = await make_env(tmp_path, notifier=notifier, image=image)
    try:
        resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, jpeg((10, 200, 10)), user_id=USER)
        order_id = (await resp.json())["order_id"]
        await env.service.accept_request(order_id)
        await wait_status(env, order_id, "in_review")
        photo = (odir(env, order_id) / "photo.jpg").read_bytes()
        calls_before = len(image.calls)
        (odir(env, order_id) / "p2.jpg").write_bytes(b"old-page")            # старая картинка не должна остаться
        await env.service.redo_book(order_id)
        assert env.db.get_order(order_id)["status"] in ("queued", "writing", "drawing", "assembling")
        await wait_status(env, order_id, "in_review", "error")
        assert env.db.get_order(order_id)["status"] == "in_review"
        assert len(image.calls) >= calls_before + PAGES + 1                  # заново нарисованы обложка и страницы
        assert all(c["refs"] and photo in c["refs"] for c in image.calls[calls_before:] if c["label"] in ("Обложка", "Страница 2"))
        assert (odir(env, order_id) / "p2.jpg").read_bytes() != b"old-page" and (odir(env, order_id) / "photo.jpg").read_bytes() == photo
        assert len(notifier.reviews) == 2 and len(notifier.admin_books) == 4  # администратор получил новую книгу
        assert notifier.books == [] and env.db.get_credits(USER) == 1          # вторая книга со счёта не списывается
    finally:
        await close(env)


async def test_redo_explains_when_the_photo_is_already_gone(tmp_path):
    env = await make_env(tmp_path)
    try:
        resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, jpeg(), user_id=USER)
        order_id = (await resp.json())["order_id"]
        await env.service.accept_request(order_id)
        await wait_status(env, order_id, "in_review")
        (odir(env, order_id) / "photo.jpg").unlink()                          # прошло 23 часа: фото удалила уборка
        with pytest.raises(ConflictError) as err:
            await env.service.redo_book(order_id)
        assert "Фото уже удалено" in err.value.message and "23 часов" in err.value.message
        assert env.db.get_order(order_id)["status"] == "in_review"            # книга осталась на проверке, ничего не сломалось
        with pytest.raises(ConflictError):
            await env.service.start_page_redraw(order_id, 3, "")
        await env.service.approve_book(order_id)                              # отправить как есть можно
        assert env.db.get_order(order_id)["status"] == "done"
    finally:
        await close(env)


async def test_redo_without_a_photo_order_needs_no_photo(tmp_path):
    env = await make_env(tmp_path)
    try:
        order_id = await to_review(env)
        await env.service.redo_book(order_id)
        await wait_status(env, order_id, "in_review", "error")
        assert env.db.get_order(order_id)["status"] == "in_review"
    finally:
        await close(env)


# ---- исправить страницу
async def test_page_redraw_draws_only_that_page_with_the_same_references_and_the_note(tmp_path):
    notifier = FakeNotifier()
    image = SheetImage()
    env = await make_env(tmp_path, notifier=notifier, image=image)
    try:
        resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, jpeg(), user_id=USER)
        order_id = (await resp.json())["order_id"]
        await env.service.accept_request(order_id)
        await wait_status(env, order_id, "in_review")
        d = odir(env, order_id)
        photo, sheet = (d / "photo.jpg").read_bytes(), (d / "sheet.jpg").read_bytes()
        old = {n: (d / n).read_bytes() for n in ("p2.jpg", "p3.jpg", "cover.jpg")}
        pdf_before, mobile_before = (d / "book.pdf").read_bytes(), (d / "mobile.pdf").read_bytes()
        calls_before = len(image.calls)
        await env.service.start_page_redraw(order_id, 3, "убрать лишнюю собаку")
        await settle(env)
        new_calls = image.calls[calls_before:]
        assert len(new_calls) == 1 and new_calls[0]["label"].startswith("Страница 3")      # перерисована ТОЛЬКО одна страница
        assert new_calls[0]["refs"] == [photo, sheet]                         # те же образцы: фото ребёнка и лист героев
        assert "убрать лишнюю собаку" in new_calls[0]["prompt"] and "IMPORTANT correction" in new_calls[0]["prompt"]
        assert (d / "p3.jpg").read_bytes() != old["p3.jpg"] and (d / "p2.jpg").read_bytes() == old["p2.jpg"]
        assert (d / "cover.jpg").read_bytes() == old["cover.jpg"]
        assert (d / "book.pdf").read_bytes() != pdf_before and (d / "mobile.pdf").read_bytes() != mobile_before   # PDF пересобраны
        assert len(notifier.admin_books) == 4 and len(notifier.reviews) == 2   # администратору всё прислали снова
        assert "Страница 3 перерисована" in notifier.reviews[1][1]
        assert env.db.get_order(order_id)["status"] == "in_review" and notifier.books == []
        assert "p3.jpg.tmp" not in [p.name for p in d.iterdir()]
    finally:
        await close(env)


async def test_page_redraw_without_a_note_draws_the_scene_again(tmp_path):
    image = ScriptedImage()
    env = await make_env(tmp_path, image=image)
    try:
        order_id = await to_review(env)
        before = len(image.calls)
        await env.service.start_page_redraw(order_id, 5, "")
        await settle(env)
        (call,) = image.calls[before:]
        assert call["label"].startswith("Страница 5") and "IMPORTANT correction" not in call["prompt"]
    finally:
        await close(env)


async def test_page_redraw_failure_keeps_the_old_picture_and_tells_the_admin(tmp_path):
    notifier = FakeNotifier()
    state = {"fail": False}
    image = ScriptedImage(fail=lambda n, prompt, label: provider_error("фильтр безопасности", no_retry=True) if state["fail"] else None)
    env = await make_env(tmp_path, notifier=notifier, image=image)
    try:
        order_id = await to_review(env)
        d = odir(env, order_id)
        old, pdf = (d / "p4.jpg").read_bytes(), (d / "book.pdf").read_bytes()
        state["fail"] = True
        await env.service.start_page_redraw(order_id, 4, "ночь")
        await settle(env)
        assert (d / "p4.jpg").read_bytes() == old and (d / "book.pdf").read_bytes() == pdf
        assert "перерисовать не вышло" in notifier.reviews[-1][1] and "Прежняя картинка осталась" in notifier.reviews[-1][1]
        assert env.db.get_order(order_id)["status"] == "in_review" and env.service._busy == set()
        state["fail"] = False
        await env.service.start_page_redraw(order_id, 4, "")                  # можно попробовать снова
        await settle(env)
        assert (d / "p4.jpg").read_bytes() != old
    finally:
        await close(env)


async def test_page_redraw_checks_the_page_number_and_blocks_a_second_click(tmp_path):
    image = ScriptedImage(delay=0.2)
    env = await make_env(tmp_path, image=image)
    try:
        order_id = await to_review(env)
        for bad in (0, PAGES + 1):
            with pytest.raises(ValidationError):
                await env.service.start_page_redraw(order_id, bad, "")
        await env.service.start_page_redraw(order_id, 2, "")
        with pytest.raises(ConflictError):
            await env.service.start_page_redraw(order_id, 3, "")              # пока идёт перерисовка, другие кнопки ждут
        with pytest.raises(ConflictError):
            await env.service.approve_book(order_id)
        await settle(env)
        await env.service.approve_book(order_id)
        assert env.db.get_order(order_id)["status"] == "done"
    finally:
        await close(env)


# ---- исправить текст
async def test_text_fix_rebuilds_the_pdfs_and_sends_them_again(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier)
    try:
        order_id = await to_review(env)
        d = odir(env, order_id)
        pdf_before = (d / "book.pdf").read_bytes()
        await env.service.set_page_text(order_id, 2, GOOD_TEXT)
        story = json.loads((d / "story.json").read_text(encoding="utf-8"))
        assert story["pages"][1]["text"] == GOOD_TEXT and story["pages"][0]["text"] != GOOD_TEXT
        assert (d / "book.pdf").read_bytes() != pdf_before and (d / "mobile.pdf").exists()
        assert len(notifier.admin_books) == 4 and "Текст страницы 2 исправлен" in notifier.reviews[-1][1]
        status, view = await get_view(env, order_id)
        assert view["status"] == "in_review" and view["pages"] == []         # клиент по-прежнему ничего не видит
        await env.service.approve_book(order_id)                              # клиент получает исправленный PDF
        _, done = await get_view(env, order_id)
        assert done["pages"][1]["text"] == GOOD_TEXT
    finally:
        await close(env)


@pytest.mark.parametrize("bad, reason", [
    ("слово " * 80, "слов"),                                                 # страница не влезает в разворот
    ("Aidar went to the yard and saw a small firefly sitting on the old fence. " * 2, "язык"),   # чужой язык
    ("   ", "пустой"),
    ("а" * 1300, ""),
])
async def test_text_fix_refuses_texts_that_break_the_hard_rules(tmp_path, bad, reason):
    env = await make_env(tmp_path)
    try:
        order_id = await to_review(env)
        d = odir(env, order_id)
        before, pdf = (d / "story.json").read_text(encoding="utf-8"), (d / "book.pdf").read_bytes()
        with pytest.raises(ValidationError) as err:
            await env.service.set_page_text(order_id, 3, bad)
        assert reason in err.value.message
        assert (d / "story.json").read_text(encoding="utf-8") == before and (d / "book.pdf").read_bytes() == pdf
        assert env.service._busy == set()
        with pytest.raises(ValidationError):
            await env.service.set_page_text(order_id, PAGES + 1, GOOD_TEXT)
    finally:
        await close(env)


# ============================================================================ переключатели
async def test_both_switches_are_on_by_default_and_off_gives_the_old_automatic_flow(tmp_path):
    env = await build_env(tmp_path)                                           # настройки базы пусты: действуют значения по умолчанию
    try:
        env.db._conn.execute("DELETE FROM settings WHERE key IN ('approve_requests','review_books')")
        assert env.service.approve_requests() is True and env.service.review_books() is True
        assert env.service.admin_settings()["approve_requests"] is True and env.service.admin_settings()["review_books"] is True
    finally:
        await close(env)
    env = await make_env(tmp_path / "off", approve=False, review=False, credits=0, closed=False)
    try:
        order_id = await make_request(env)
        row = await env.wait_done(order_id)
        assert row["status"] == "done" and env.service.approve_requests() is False
        assert len(env.notifier.books) == 2 and env.notifier.requests == [] and env.notifier.reviews == []
    finally:
        await close(env)


async def test_each_switch_works_on_its_own(tmp_path):
    env = await make_env(tmp_path / "a", approve=True, review=False, credits=0, closed=False)
    try:
        order_id = await make_request(env)
        assert env.db.get_order(order_id)["status"] == "awaiting_approval"
        await env.service.accept_request(order_id)
        assert (await env.wait_done(order_id))["status"] == "done"            # книгу после заявки никто не проверяет
    finally:
        await close(env)
    env = await make_env(tmp_path / "b", approve=False, review=True, credits=0, closed=False)
    try:
        order_id = await make_request(env)
        assert env.db.get_order(order_id)["status"] != "awaiting_approval"
        await wait_status(env, order_id, "in_review")
        assert env.notifier.requests == [] and env.notifier.books == []
    finally:
        await close(env)


async def test_admin_api_switches_the_two_checks_and_the_next_order_follows(tmp_path):
    env = await make_env(tmp_path, credits=3)
    try:
        resp = await env.client.get("/api/admin/payments", headers=tma(ADMIN_ID))
        data = await resp.json()
        assert data["settings"]["approve_requests"] is True and data["settings"]["review_books"] is True
        assert data["settings"]["approve_requests_active"] is True and data["waiting"] == {"requests": 0, "books": 0}
        order_id = await make_request(env)
        assert (await (await env.client.get("/api/admin/payments", headers=tma(ADMIN_ID))).json())["waiting"] == {"requests": 1, "books": 0}
        resp = await env.client.post("/api/admin/settings", json={"approve_requests": False, "review_books": False}, headers=tma(ADMIN_ID))
        data = await resp.json()
        assert resp.status == 200 and data["approve_requests"] is False and data["review_books"] is False
        assert env.db.get_setting("approve_requests") == "0" and env.db.get_setting("review_books") == "0"
        # уже созданную заявку это не трогает: её по-прежнему решает человек
        assert env.db.get_order(order_id)["status"] == "awaiting_approval"
        await env.service.decline_request(order_id)
        second = await make_request(env)
        assert (await env.wait_done(second))["status"] == "done"             # теперь всё автоматически
        resp = await env.client.post("/api/admin/settings", json={"approve_requests": True}, headers=tma(ADMIN_ID))
        assert (await resp.json())["approve_requests"] is True and (await resp.json())["review_books"] is False
        resp = await env.client.post("/api/admin/settings", json={"review_books": "maybe"}, headers=tma(ADMIN_ID))
        assert resp.status == 400 and env.db.get_setting("review_books") == "0"        # ошибка в поле ничего не меняет
    finally:
        await close(env)


async def test_only_the_owner_changes_the_switches(tmp_path):
    env = await make_env(tmp_path)
    try:
        resp = await env.client.post("/api/admin/settings", json={"review_books": False}, headers=tma(USER))
        assert resp.status == 403 and env.service.review_books() is True
    finally:
        await close(env)


def test_environment_variables_set_the_defaults(monkeypatch, tmp_path):
    for name in ("APPROVE_REQUESTS", "REVIEW_BOOKS", "REVIEW_AUTO_SEND_HOURS"):
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env(env_file=None)
    assert s.approve_requests is True and s.review_books is True and s.review_auto_send_hours == 0
    monkeypatch.setenv("APPROVE_REQUESTS", "off")
    monkeypatch.setenv("REVIEW_BOOKS", "on")
    monkeypatch.setenv("REVIEW_AUTO_SEND_HOURS", "6")
    s = Settings.from_env(env_file=None)
    assert s.approve_requests is False and s.review_books is True and s.review_auto_send_hours == 6
    for off in ("0", "false", "no", "OFF"):
        monkeypatch.setenv("REVIEW_BOOKS", off)
        assert Settings.from_env(env_file=None).review_books is False
    monkeypatch.setenv("REVIEW_BOOKS", "включить")                           # опечатка не отключает защиту клиента
    assert Settings.from_env(env_file=None).review_books is True
    monkeypatch.setenv("REVIEW_AUTO_SEND_HOURS", "-3")
    assert Settings.from_env(env_file=None).review_auto_send_hours == 0


async def test_database_switch_beats_the_environment_default(tmp_path):
    env = await build_env(tmp_path, approve=True, review=True)
    try:
        assert env.service.approve_requests_setting() is True
    finally:
        await close(env)
    env = await build_env(tmp_path / "x", approve=False, review=False)
    try:
        assert env.service.settings.approve_requests is True and env.service.approve_requests() is False
    finally:
        await close(env)


@pytest.mark.parametrize("notifier", [PlainNotifier(), NullNotifier()])
async def test_without_a_bot_that_can_show_buttons_the_checks_stay_off(tmp_path, notifier):
    """Нет бота с кнопками (режим заглушек без Telegram): заказ не должен зависнуть, поэтому ручная проверка не включается."""
    env = await build_env(tmp_path, notifier=notifier, approve=True, review=True)
    try:
        assert env.service.approve_requests_setting() and not env.service.approve_requests() and not env.service.review_books()
        assert env.service.admin_settings()["approve_requests_active"] is False
        order_id = await make_request(env)
        assert (await env.wait_done(order_id))["status"] == "done"
    finally:
        await close(env)


# ============================================================================ перезапуск, напоминания, уборка
async def test_restart_leaves_requests_and_books_on_review_untouched(tmp_path):
    env = await make_env(tmp_path, credits=3)
    try:
        a = await make_request(env)
        user_b = 44
        await give_access(env, user_id=user_b, credits=1)
        b = await make_request(env, user=user_b)
        await env.service.accept_request(b)
        await wait_status(env, b, "in_review")
        credits = (env.db.get_credits(USER), env.db.get_credits(user_b))
        env.service.recover()
        assert env.service.resume_paid() == 0
        assert env.db.get_order(a)["status"] == "awaiting_approval" and env.db.get_order(b)["status"] == "in_review"
        assert (env.db.get_credits(USER), env.db.get_credits(user_b)) == credits       # ничего не вернулось и не списалось
        assert (odir(env, b) / "book.pdf").exists()
    finally:
        await close(env)


async def test_restart_still_marks_unpaid_running_orders_as_errors(tmp_path):
    env = await make_env(tmp_path, approve=False, review=False)
    try:
        env.db.create_order("running00001", USER, json.dumps({"name": "А"}), status="drawing", use_credit=False)
        env.service.recover()
        assert env.db.get_order("running00001")["status"] == "error"
    finally:
        await close(env)


def age(env, order_id, hours):
    """Состарить заказ: заявка ждёт решения уже hours часов."""
    past = time.time() - hours * 3600
    env.db._exec("UPDATE orders SET review_at=?, created_at=? WHERE id=?", (past, past, order_id))


async def test_admin_gets_a_reminder_every_hour_up_to_six_times(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier)
    try:
        order_id = await make_request(env)
        assert await env.service.send_reminders() == 0                         # ещё не прошёл час
        for n in range(1, 8):
            age(env, order_id, 1.1)
            sent = await env.service.send_reminders()
            assert sent == (1 if n <= 6 else 0), n
        assert len(notifier.requests) == 1 + 6                                  # сама заявка и ровно шесть напоминаний
        assert notifier.requests[1][1].startswith("⏰ Заявка ждёт решения") and "напоминание 1 из 6" in notifier.requests[1][1]
        assert "Герой: Айдар" in notifier.requests[1][1] and env.db.get_order(order_id)["reminders"] == 6
        # решённая заявка больше не напоминает
        await env.service.decline_request(order_id)
        age(env, order_id, 5)
        assert await env.service.send_reminders() == 0
    finally:
        await close(env)


async def test_books_on_review_are_reminded_with_buttons_text_and_stop_when_sent(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier)
    try:
        order_id = await to_review(env)
        age(env, order_id, 2)
        assert await env.service.send_reminders() == 1
        assert notifier.reviews[-1][0] == order_id and notifier.reviews[-1][1].startswith("⏰ Книга ждёт проверки")
        await env.service.approve_book(order_id)
        age(env, order_id, 3)
        assert await env.service.send_reminders() == 0
    finally:
        await close(env)


async def test_auto_send_is_off_by_default_and_sends_old_books_when_enabled(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier, review_auto_send_hours=3)
    try:
        order_id = await to_review(env)
        assert await env.service.auto_send_due() == 0                          # прошло мало времени
        env.db._exec("UPDATE orders SET finished_at=? WHERE id=?", (time.time() - 4 * 3600, order_id))
        assert await env.service.auto_send_due() == 1
        assert env.db.get_order(order_id)["status"] == "done" and len(notifier.books) == 2
        assert any("отправлена клиенту автоматически" in t for t in notifier.admin_texts)
    finally:
        await close(env)
    env = await make_env(tmp_path / "off", review_auto_send_hours=0)
    try:
        order_id = await to_review(env)
        env.db._exec("UPDATE orders SET finished_at=? WHERE id=?", (time.time() - 100 * 3600, order_id))
        assert await env.service.auto_send_due() == 0 and env.db.get_order(order_id)["status"] == "in_review"
    finally:
        await close(env)


async def test_cleanup_keeps_pending_orders_and_the_photo_is_purged_after_23_hours(tmp_path):
    env = await make_env(tmp_path, credits=3, keep_files_days=1)
    try:
        resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, jpeg(), user_id=USER)
        order_id = (await resp.json())["order_id"]
        await env.service.accept_request(order_id)
        await wait_status(env, order_id, "in_review")
        user_b = 45
        await give_access(env, user_id=user_b, credits=1)
        waiting = await make_request(env, user=user_b)
        old = time.time() - 5 * 86400
        env.db._exec("UPDATE orders SET created_at=? WHERE id IN (?,?)", (old, order_id, waiting))
        import os
        for path in odir(env, order_id).iterdir():
            os.utime(path, (old, old))
        env.service.cleanup()
        assert env.db.get_order(order_id)["files_deleted"] == 0 and env.db.get_order(waiting)["files_deleted"] == 0
        assert (odir(env, order_id) / "book.pdf").exists() and odir(env, waiting).exists()
        assert env.db.get_order(order_id)["status"] == "in_review" and env.db.get_order(waiting)["status"] == "awaiting_approval"
        assert not (odir(env, order_id) / "photo.jpg").exists()                  # фото старше 23 часов удалено, книга осталась
        with pytest.raises(ConflictError):
            await env.service.redo_book(order_id)                                 # и «Сделать заново» это честно объясняет
        await env.service.approve_book(order_id)
    finally:
        await close(env)


async def test_photo_stays_after_generation_only_while_the_book_waits_for_review(tmp_path):
    env = await make_env(tmp_path, approve=False, review=False, credits=0, closed=False)
    try:
        resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, jpeg(), user_id=USER)
        order_id = (await resp.json())["order_id"]
        await env.wait_done(order_id)
        assert not (odir(env, order_id) / "photo.jpg").exists()                  # без проверки всё как раньше: фото сразу удалено
    finally:
        await close(env)
    env = await make_env(tmp_path / "r", approve=False, review=True, credits=0, closed=False)
    try:
        resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, jpeg(), user_id=USER)
        order_id = (await resp.json())["order_id"]
        await wait_status(env, order_id, "in_review")
        assert (odir(env, order_id) / "photo.jpg").exists()
        await env.service.approve_book(order_id)
        assert not (odir(env, order_id) / "photo.jpg").exists()
    finally:
        await close(env)


# ============================================================================ бот: кнопки и сообщения
def callback_update(bot, data, *, user_id=ADMIN_ID, chat_id=ADMIN_ID, message_id=7):
    return Update.model_validate({"update_id": 5, "callback_query": {
        "id": "cb1", "from": {"id": user_id, "is_bot": False, "first_name": "Кто-то"}, "chat_instance": "ci", "data": data,
        "message": {"message_id": message_id, "date": int(datetime.now().timestamp()), "chat": {"id": chat_id, "type": "private"},
                    "text": "карточка"}}}, context={"bot": bot})


async def press(service, data, *, user_id=ADMIN_ID, chat_id=ADMIN_ID):
    session = FakeSession()
    bot = make_bot(session)
    await make_dp("https://tale.example.test", service).feed_update(bot, callback_update(bot, data, user_id=user_id, chat_id=chat_id))
    return session


def kinds(session):
    return [type(c).__name__ for c in session.calls]


def alerts(session):
    return [c for c in session.calls if type(c).__name__ == "AnswerCallbackQuery"]


async def say(service, text, *, chat_id=ADMIN_ID):
    session = FakeSession()
    bot = make_bot(session)
    await make_dp("https://tale.example.test", service).feed_update(bot, command_update(bot, text, chat_id=chat_id))
    return session


async def test_buttons_have_the_agreed_callback_data_and_fit_telegram(tmp_path):
    order_id = "abc_DEF-1234"
    (ok, no), = request_keyboard(order_id).inline_keyboard
    assert (ok.text, ok.callback_data) == ("✅ Принять и начать", f"req:ok:{order_id}")
    assert (no.text, no.callback_data) == ("❌ Отклонить", f"req:no:{order_id}")
    rows = review_keyboard(order_id).inline_keyboard
    flat = [b for row in rows for b in row]
    assert [(b.text, b.callback_data) for b in flat] == [
        ("✅ Отправить клиенту", f"rev:ok:{order_id}"), ("🔁 Сделать заново", f"rev:redo:{order_id}"),
        ("🖼 Исправить страницу", f"rev:page:{order_id}"), ("✏️ Исправить текст", f"rev:text:{order_id}")]
    (row,) = pages_keyboard(order_id, "text").inline_keyboard
    assert [b.text for b in row] == [str(n) for n in range(1, PAGES + 1)] and row[2].callback_data == f"rev:text:{order_id}:3"
    for button in flat + row:
        assert len(button.callback_data.encode()) <= 64


async def test_notifier_sends_the_cards_with_buttons_to_the_right_chats():
    session = FakeSession()
    notifier = TelegramNotifier(make_bot(session), admin_chat_id=777, orders_chat_id=-100555)
    assert notifier.can_approve_requests and notifier.can_review_books
    await notifier.notify_request("order0000001", "Заявка <b>с & знаками</b>")
    await notifier.notify_review("order0000001", "Книга готова")
    request, review = sent_messages(session)
    assert request.chat_id == -100555 and review.chat_id == 777
    assert request.text == "Заявка <b>с & знаками</b>" and request.parse_mode is None          # текст родителей показываем как есть
    assert [b.callback_data for b in request.reply_markup.inline_keyboard[0]] == ["req:ok:order0000001", "req:no:order0000001"]
    assert review.reply_markup.inline_keyboard[0][0].callback_data == "rev:ok:order0000001"
    # чата заказов нет: заявки идут владельцу; чата владельца нет: проверка невозможна
    fallback = TelegramNotifier(make_bot(FakeSession()), admin_chat_id=777)
    assert fallback.orders_chat_id == 777 and fallback.can_approve_requests
    nobody = TelegramNotifier(make_bot(FakeSession()), admin_chat_id=None)
    assert not nobody.can_approve_requests and not nobody.can_review_books
    await nobody.notify_request("order0000001", "x")
    await nobody.notify_review("order0000001", "x")


async def test_a_broken_chat_never_breaks_the_order(tmp_path):
    class Broken(FakeNotifier):
        async def notify_request(self, order_id, text):
            raise RuntimeError("чат недоступен")

        async def notify_review(self, order_id, text):
            raise RuntimeError("чат недоступен")

        async def send_admin_book(self, *a):
            raise RuntimeError("чат недоступен")

    env = await make_env(tmp_path, notifier=Broken())
    try:
        order_id = await make_request(env)
        assert env.db.get_order(order_id)["status"] == "awaiting_approval"
        await env.service.accept_request(order_id)
        row = await wait_status(env, order_id, "in_review", "error")
        assert row["status"] == "in_review"                                       # книга на проверке, напоминание пришлёт карточку снова
    finally:
        await close(env)


async def test_request_buttons_work_for_admins_only_and_remove_themselves(tmp_path):
    env = await make_env(tmp_path)
    try:
        order_id = await make_request(env)
        stranger = await press(env.service, f"req:ok:{order_id}", user_id=999)
        assert env.db.get_order(order_id)["status"] == "awaiting_approval"
        (alert,) = alerts(stranger)
        assert alert.show_alert and "только для владельца" in alert.text and "EditMessageReplyMarkup" not in kinds(stranger)
        client = await press(env.service, f"req:no:{order_id}", user_id=USER)       # сам клиент тоже не может
        assert env.db.get_order(order_id)["status"] == "awaiting_approval" and alerts(client)[0].show_alert
        accepted = await press(env.service, f"req:ok:{order_id}")
        assert "EditMessageReplyMarkup" in kinds(accepted) and alerts(accepted)[0].text.startswith("✅ Заявка принята")
        assert env.db.get_order(order_id)["status"] != "awaiting_approval"
        again = await press(env.service, f"req:ok:{order_id}")                       # двойной клик: ничего не ломается
        assert alerts(again)[0].show_alert and "уже обработана" in alerts(again)[0].text
        assert "EditMessageReplyMarkup" in kinds(again)                              # кнопки убраны
        await settle(env)
    finally:
        await close(env)


async def test_extra_admins_can_press_the_buttons_too(tmp_path):
    env = await make_env(tmp_path, extra_admin_ids=(888,))
    try:
        order_id = await make_request(env)
        session = await press(env.service, f"req:no:{order_id}", user_id=888)
        assert env.db.get_order(order_id)["status"] == "cancelled" and "❌" in alerts(session)[0].text
    finally:
        await close(env)


async def test_review_buttons_admin_only_ok_and_double_click(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier)
    try:
        order_id = await to_review(env)
        stranger = await press(env.service, f"rev:ok:{order_id}", user_id=USER, chat_id=USER)
        assert env.db.get_order(order_id)["status"] == "in_review" and notifier.books == []
        assert alerts(stranger)[0].show_alert and "только для владельца" in alerts(stranger)[0].text
        for data in (f"rev:redo:{order_id}", f"rev:page:{order_id}", f"rev:text:{order_id}", f"rev:pn:{order_id}:2", f"rev:text:{order_id}:2"):
            await press(env.service, data, user_id=USER, chat_id=USER)
        assert env.db.get_order(order_id)["status"] == "in_review" and env.service._pending == {} and env.service._tasks == set()
        ok = await press(env.service, f"rev:ok:{order_id}")
        assert env.db.get_order(order_id)["status"] == "done" and len(notifier.books) == 2
        assert "EditMessageReplyMarkup" in kinds(ok)
        again = await press(env.service, f"rev:ok:{order_id}")
        assert len(notifier.books) == 2 and "EditMessageReplyMarkup" in kinds(again) and alerts(again)[-1].show_alert
    finally:
        await close(env)


async def test_redo_button_starts_the_book_again(tmp_path):
    env = await make_env(tmp_path)
    try:
        order_id = await to_review(env)
        session = await press(env.service, f"rev:redo:{order_id}")
        assert "Делаю книгу заново" in sent_messages(session)[0].text and "EditMessageReplyMarkup" in kinds(session)
        assert env.db.get_order(order_id)["status"] != "in_review" or env.service._tasks
        await wait_status(env, order_id, "in_review", "error")
        assert env.db.get_order(order_id)["status"] == "in_review"
    finally:
        await close(env)


async def test_long_refusal_goes_to_the_chat_not_to_the_alert(tmp_path):
    env = await make_env(tmp_path)
    try:
        resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, jpeg(), user_id=USER)
        order_id = (await resp.json())["order_id"]
        await env.service.accept_request(order_id)
        await wait_status(env, order_id, "in_review")
        (odir(env, order_id) / "photo.jpg").unlink()
        session = await press(env.service, f"rev:redo:{order_id}")
        assert len(service_module.PHOTO_GONE.format(what="новая книга")) > 190
        (message,) = sent_messages(session)
        assert "Фото уже удалено" in message.text and not alerts(session)[0].show_alert
        assert "EditMessageReplyMarkup" not in kinds(session)                          # книга всё ещё на проверке: кнопки остаются
    finally:
        await close(env)


async def test_page_button_refuses_at_once_when_the_photo_is_gone_not_after_the_note(tmp_path):
    env = await make_env(tmp_path)
    try:
        resp = await post_with_photo(env.client, {**SAMPLE, "photo_consent": True}, jpeg(), user_id=USER)
        order_id = (await resp.json())["order_id"]
        await env.service.accept_request(order_id)
        await wait_status(env, order_id, "in_review")
        (odir(env, order_id) / "photo.jpg").unlink()
        for data in (f"rev:page:{order_id}", f"rev:pn:{order_id}:3"):
            session = await press(env.service, data)
            (message,) = sent_messages(session)
            assert "Фото уже удалено" in message.text and "страница не получится" in message.text
        assert env.service.pending_edit(ADMIN_ID, ADMIN_ID) is None and env.db.get_order(order_id)["status"] == "in_review"
        text_picker = await press(env.service, f"rev:text:{order_id}:3")          # текст править можно и без фото
        assert env.service.pending_edit(ADMIN_ID, ADMIN_ID).kind == "text" and "Страница 3" in sent_messages(text_picker)[0].text
    finally:
        await close(env)


async def test_a_failure_while_sending_the_review_keeps_the_book_on_review(tmp_path, monkeypatch):
    env = await make_env(tmp_path)
    try:
        def broken(*a, **k):
            raise RuntimeError("сбой")
        monkeypatch.setattr(env.service, "_review_text", broken)
        order_id = await make_request(env)
        await env.service.accept_request(order_id)
        row = await wait_status(env, order_id, "in_review", "error")
        assert row["status"] == "in_review" and env.db.get_credits(USER) == 1      # книга не превращается в ошибку и не возвращается
    finally:
        await close(env)


async def test_page_button_asks_for_a_number_then_a_note_then_redraws_that_page_only(tmp_path):
    image = ScriptedImage()
    env = await make_env(tmp_path, image=image)
    try:
        order_id = await to_review(env)
        picker = await press(env.service, f"rev:page:{order_id}")
        (message,) = sent_messages(picker)
        (row,) = message.reply_markup.inline_keyboard
        assert [b.text for b in row] == [str(n) for n in range(1, PAGES + 1)]            # ряд кнопок 1–8
        chosen = await press(env.service, row[2].callback_data)                            # страница 3
        (ask,) = sent_messages(chosen)
        assert "Страница 3" in ask.text and "«-»" in ask.text and isinstance(ask.reply_markup, ForceReply)
        assert env.service.pending_edit(ADMIN_ID, ADMIN_ID).kind == "page"
        before = len(image.calls)
        reply = await say(env.service, "сделать день, а не ночь")
        assert "Перерисовываю страницу 3" in sent_messages(reply)[0].text
        await settle(env)
        (call,) = image.calls[before:]
        assert call["label"].startswith("Страница 3") and "сделать день, а не ночь" in call["prompt"]
        assert env.service.pending_edit(ADMIN_ID, ADMIN_ID) is None
        # «-» = без пометки
        await press(env.service, f"rev:pn:{order_id}:5")
        before = len(image.calls)
        await say(env.service, "-")
        await settle(env)
        assert image.calls[before]["label"].startswith("Страница 5") and "IMPORTANT correction" not in image.calls[before]["prompt"]
        # после этого обычные сообщения администратора бот не перехватывает
        other = await say(env.service, "привет")
        assert sent_messages(other)[0].text.startswith("Книги создаются")
    finally:
        await close(env)


async def test_text_button_shows_the_current_text_and_takes_the_next_message_as_the_new_one(tmp_path):
    notifier = FakeNotifier()
    env = await make_env(tmp_path, notifier=notifier)
    try:
        order_id = await to_review(env)
        picker = await press(env.service, f"rev:text:{order_id}")
        (row,) = sent_messages(picker)[0].reply_markup.inline_keyboard
        assert row[1].callback_data == f"rev:text:{order_id}:2"
        asked = await press(env.service, f"rev:text:{order_id}:2")
        (ask,) = sent_messages(asked)
        assert "Страница 2" in ask.text and env.service.page_text(order_id, 2).split(".")[0] in ask.text and isinstance(ask.reply_markup, ForceReply)
        # слишком длинный текст: бот объясняет, а ждёт исправленный
        bad = await say(env.service, "слово " * 80)
        texts = [m.text for m in sent_messages(bad)]
        assert texts[-1].startswith("Текст не подошёл") and "ещё раз" in texts[-1]
        assert env.service.pending_edit(ADMIN_ID, ADMIN_ID) is not None and env.service.page_text(order_id, 2) != "слово " * 80
        good = await say(env.service, GOOD_TEXT)
        assert env.service.page_text(order_id, 2) == GOOD_TEXT and env.service.pending_edit(ADMIN_ID, ADMIN_ID) is None
        assert len(notifier.admin_books) == 4 and "Текст страницы 2 исправлен" in notifier.reviews[-1][1]
        # «-» отменяет
        await press(env.service, f"rev:text:{order_id}:4")
        cancelled = await say(env.service, "-")
        assert "не меняю" in sent_messages(cancelled)[0].text and env.service.pending_edit(ADMIN_ID, ADMIN_ID) is None
        assert env.service.page_text(order_id, 4) != "-"
    finally:
        await close(env)


async def test_pending_edit_expires_and_belongs_to_one_admin_and_chat(tmp_path, monkeypatch):
    env = await make_env(tmp_path, extra_admin_ids=(888,))
    try:
        order_id = await to_review(env)
        await press(env.service, f"rev:text:{order_id}:2")
        assert env.service.pending_edit(ADMIN_ID, 888) is None and env.service.pending_edit(-100, ADMIN_ID) is None
        stray = await say(env.service, GOOD_TEXT, chat_id=888)                        # другой администратор текст не подменит
        assert env.service.page_text(order_id, 2) != GOOD_TEXT and sent_messages(stray)[0].text.startswith("Книги создаются")
        monkeypatch.setattr(service_module.time, "time", lambda real=time.time: real() + service_module.PENDING_TTL + 5)
        assert env.service.pending_edit(ADMIN_ID, ADMIN_ID) is None                    # ждали слишком долго
    finally:
        await close(env)


async def test_pending_answer_for_an_already_sent_book_is_explained(tmp_path):
    env = await make_env(tmp_path)
    try:
        order_id = await to_review(env)
        await press(env.service, f"rev:pn:{order_id}:2")
        await env.service.approve_book(order_id)                                       # пока админ думал, книгу уже отправили
        reply = await say(env.service, "что-то исправить")
        assert "уже обработана" in sent_messages(reply)[0].text and env.service.pending_edit(ADMIN_ID, ADMIN_ID) is None
    finally:
        await close(env)


# ============================================================================ Mini App
def test_mini_app_has_waiting_screens_texts_and_polls_on():
    root = Path(__file__).resolve().parent.parent / "webapp"
    js = (root / "app.js").read_text(encoding="utf-8")
    css = (root / "style.css").read_text(encoding="utf-8")
    assert "order.status === 'awaiting_approval' || order.status === 'in_review'" in js
    assert "Заявка отправлена" in js and "Обычно ответ в течение 1–2 часов, приложение можно закрыть" in js
    assert "Книга готова" in js and "Мы проверяем качество. Пришлём в течение 1–2 часов" in js
    hold = js[js.index("const HOLD = {"):js.index("function showWait(orderId, status)")]
    assert "%" not in hold and "progressbar" not in hold and "bar" not in hold              # без шкалы и процентов
    poll = js[js.index("async function poll(token)"):js.index("function updateWait(o)")]
    assert "showHold(order)" in poll and "setTimeout(() => poll(token)" in poll              # опрос продолжается
    assert poll.index("showResult(order)") < poll.index("showHold(order)") and "order.status === 'done'" in poll
    assert "showResult(order)" not in hold                                                    # экран результата только на done
    assert "else if (S.hold) { showWait(S.orderId); return; }" in poll                       # заявку приняли: снова экран ожидания
    assert ".hold .tip" in css
    wait = js[js.index("function updateWait(o)"):js.index("function fillRow")]
    assert "if (o.review)" in wait                                                            # при проверке страницы по мере готовности не показываем


def test_admin_settings_have_two_labelled_switches_with_the_server_names():
    root = Path(__file__).resolve().parent.parent / "webapp"
    js = (root / "app.js").read_text(encoding="utf-8")
    section = js[js.index("function adminSettings(st)"):js.index("async function adminAction")]
    assert "Проверять заявки" in section and "Проверять книги" in section
    assert 'data-act="approve-switch"' in section and 'data-act="review-switch"' in section
    assert section.count('role="switch"') == 4 and "aria-labelledby=\"sw-approve\"" in section and "aria-labelledby=\"sw-review\"" in section
    save = js[js.index("async function saveAdminSettings"):js.index("async function uploadQr")]
    assert "approve_requests: flagOn(st, 'approve_requests')" in save and "review_books: flagOn(st, 'review_books')" in save
    assert "'approve-switch':" in js and "'review-switch':" in js
    assert re.search(r"flagOn = \(st, key\) => st\[key\] === undefined \|\| st\[key\] === null \? true", js)    # по умолчанию включено


async def test_config_tells_the_app_when_the_wait_is_long(tmp_path):
    env = await make_env(tmp_path)
    try:
        assert (await (await env.client.get("/api/config", headers=tma(USER))).json())["manual_checks"] is True
        env.service.update_admin_settings({"approve_requests": False, "review_books": False})
        assert (await (await env.client.get("/api/config", headers=tma(USER))).json())["manual_checks"] is False
    finally:
        await close(env)
