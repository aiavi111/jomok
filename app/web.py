"""Веб-сервер (aiohttp): отдаёт Mini App и API. Во всех /api/* (кроме /api/health) нужен
заголовок Authorization: tma <initData>; файлы заказа можно открыть и по подписанной ссылке ?t=…"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from . import __version__, options
from .auth import TgUser, authenticate
from .config import ROOT, Settings
from .errors import AppError, AuthError, ForbiddenError, NotFoundError, ValidationError
from .imaging import MAX_PHOTO_BYTES
from .links import check_token
from .service import OrderService
from .db import Database

log = logging.getLogger(__name__)

WEBAPP_DIR = ROOT / "webapp"
FILE_ROUTE = re.compile(r"^/api/(orders/[^/]+/(img/[^/]+|book\.pdf)|payment/qr|admin/receipts/[^/]+)$")
MAX_PROFILE_BYTES = 20_000

SETTINGS_KEY = web.AppKey("settings", Settings)
SERVICE_KEY = web.AppKey("service", OrderService)
DB_KEY = web.AppKey("db", Database)
BOT_KEY = web.AppKey("bot_info", dict)
try:
    USER_KEY = web.RequestKey("user", object)      # aiohttp 3.12+
except AttributeError:                               # более старые версии aiohttp
    USER_KEY = "user"


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def json_response(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=_dumps, headers={"Cache-Control": "no-store"})


def error_response(message: str, status: int, code: str = "error", **extra) -> web.Response:
    return json_response({"error": message, "code": code, **{k: v for k, v in extra.items() if v is not None}}, status)


# ------------------------------------------------------------------ middleware
@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except AppError as e:
        return error_response(e.message, e.status, e.code, field=e.field, **e.extra)
    except web.HTTPRequestEntityTooLarge:
        return error_response("Файл слишком большой. Выберите фото поменьше (до 8 МБ).", 413, "too_large")
    except web.HTTPException as e:
        if request.path.startswith("/api/"):
            return error_response({404: "Такой страницы нет.", 405: "Так делать нельзя."}.get(e.status, "Запрос не получился."),
                                  e.status, "http")
        raise
    except Exception:  # noqa: BLE001
        log.exception("Необработанная ошибка в %s %s", request.method, request.path)
        return error_response("На сервере что-то пошло не так. Попробуйте ещё раз через минуту.", 500, "server")


@web.middleware
async def auth_middleware(request: web.Request, handler):
    path = request.path
    if not path.startswith("/api/") or path == "/api/health":
        return await handler(request)
    settings: Settings = request.app[SETTINGS_KEY]
    header = request.headers.get("Authorization", "")
    if header or not FILE_ROUTE.match(path):
        user = authenticate(header, settings.telegram_bot_token, dev_mode=settings.dev_mode)
        request[USER_KEY] = user
        request.app[DB_KEY].upsert_user(user.id, user.username, user.first_name, user.language_code)
    else:
        request[USER_KEY] = None      # файл по подписанной ссылке: проверим подпись в обработчике
    return await handler(request)


@web.middleware
async def headers_middleware(request: web.Request, handler):
    response = await handler(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if not request.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


# ------------------------------------------------------------------ обработчики
async def health(request: web.Request) -> web.Response:
    return json_response({"status": "ok", "version": __version__})


def _is_admin(settings: Settings, user: TgUser) -> bool:
    return settings.admin_chat_id is not None and user.id == settings.admin_chat_id


async def get_config(request: web.Request) -> web.Response:
    settings: Settings = request.app[SETTINGS_KEY]
    service: OrderService = request.app[SERVICE_KEY]
    user: TgUser = request[USER_KEY]
    bot_info = request.app[BOT_KEY]
    return json_response({
        "text_provider": settings.text_provider,
        "image_provider": settings.image_provider,
        "mock": settings.uses_mock,
        "dev_mode": settings.dev_mode,
        "photo_supported": service.photo_supported(),
        "privacy_warning": settings.privacy_warning,
        "price_text": service.price_text(),
        "free_in_test": not service.desk.required(),
        "payment_required": service.desk.required(),
        "is_admin": _is_admin(settings, user),
        "limits": {
            "books_per_day": settings.max_books_per_user_per_day,
            "remaining_today": service.remaining_today(user.id),
            "name_max": 30, "text_max": 120, "likes_max": 3, "traits_max": 3,
        },
        "options": options.public_options(),
        "active_order_id": service.active_order_id(user.id),
        "bot_username": bot_info.get("username"),
        "user": {"first_name": user.first_name},
    })


async def _read_order_request(request: web.Request) -> tuple[dict, bytes | None]:
    if request.content_type.startswith("multipart/"):
        reader = await request.multipart()
        payload: dict | None = None
        photo: bytes | None = None
        async for part in reader:
            if part.name == "profile":
                raw = await part.read(decode=False)
                if len(raw) > MAX_PROFILE_BYTES:
                    raise ValidationError("Анкета слишком большая.")
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    raise ValidationError("Анкета пришла в неверном виде. Обновите приложение и попробуйте ещё раз.")
            elif part.name == "photo":
                chunks, size = [], 0
                while True:
                    chunk = await part.read_chunk(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_PHOTO_BYTES:
                        raise ValidationError("Фото слишком большое. Выберите снимок поменьше (до 8 МБ).", field="photo")
                    chunks.append(chunk)
                photo = b"".join(chunks) or None
        if payload is None:
            raise ValidationError("В запросе нет анкеты.")
        return payload, photo
    try:
        body = await request.read()
        if len(body) > MAX_PROFILE_BYTES:
            raise ValidationError("Анкета слишком большая.")
        return json.loads(body.decode("utf-8")), None
    except (ValueError, UnicodeDecodeError):
        raise ValidationError("Анкета пришла в неверном виде. Обновите приложение и попробуйте ещё раз.")


async def create_order(request: web.Request) -> web.Response:
    service: OrderService = request.app[SERVICE_KEY]
    payload, photo = await _read_order_request(request)
    order_id = await service.create_order(request[USER_KEY], payload, photo)
    status = service.db.get_order(order_id)["status"]
    return json_response({"order_id": order_id, "status": status}, 201)


async def get_order(request: web.Request) -> web.Response:
    settings: Settings = request.app[SETTINGS_KEY]
    service: OrderService = request.app[SERVICE_KEY]
    user: TgUser = request[USER_KEY]
    return json_response(service.view(request.match_info["order_id"], user, is_admin=_is_admin(settings, user)))


async def resend_order(request: web.Request) -> web.Response:
    service: OrderService = request.app[SERVICE_KEY]
    ok = await service.resend(request.match_info["order_id"], request[USER_KEY])
    if not ok:
        return json_response({"delivered": False, "message": "Не получилось отправить PDF в чат. "
                              "Откройте бота, нажмите /start и повторите, либо скачайте файл по кнопке «Скачать PDF»."})
    return json_response({"delivered": True, "message": "PDF отправлен вам в чат."})


def _authorize_file(request: web.Request, order_id: str) -> None:
    service: OrderService = request.app[SERVICE_KEY]
    user: TgUser | None = request[USER_KEY]
    owner = service.owner_of(order_id)
    if owner is None:
        raise NotFoundError("Такой книги нет.")
    if user is not None:
        if owner != user.id:
            raise NotFoundError("Такой книги нет.")
        return
    if not check_token(service.link_secret, order_id, owner, request.query.get("t")):
        raise AuthError("Ссылка устарела или недействительна. Откройте приложение заново и скачайте файл ещё раз.")


async def get_image(request: web.Request) -> web.StreamResponse:
    service: OrderService = request.app[SERVICE_KEY]
    order_id, name = request.match_info["order_id"], request.match_info["name"]
    _authorize_file(request, order_id)
    path = service.file_path(order_id, name)
    return web.FileResponse(path, headers={"Cache-Control": "private, max-age=3600", "Content-Type": "image/jpeg"})


async def get_pdf(request: web.Request) -> web.StreamResponse:
    service: OrderService = request.app[SERVICE_KEY]
    order_id = request.match_info["order_id"]
    _authorize_file(request, order_id)
    path = service.file_path(order_id, "book.pdf")
    download = request.query.get("download") == "1"
    ascii_name = "skazka.pdf"
    headers = {
        "Content-Type": "application/pdf",
        "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{ascii_name}"; '
                               f"filename*=UTF-8''{quote(ascii_name)}",
        "Cache-Control": "private, no-store",
        # Требование Telegram для Telegram.WebApp.downloadFile (Bot API 8.0+)
        "Access-Control-Allow-Origin": "https://web.telegram.org",
    }
    return web.FileResponse(path, headers=headers)


# ------------------------------------------------------------------ оплата по QR
async def _read_single_image(request: web.Request, field: str, limit: int = MAX_PHOTO_BYTES) -> bytes:
    if not request.content_type.startswith("multipart/"):
        raise ValidationError("Прикрепите картинку.")
    reader = await request.multipart()
    async for part in reader:
        if part.name != field:
            continue
        chunks, size = [], 0
        while True:
            chunk = await part.read_chunk(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValidationError("Файл слишком большой. Выберите картинку поменьше (до 8 МБ).")
            chunks.append(chunk)
        data = b"".join(chunks)
        if data:
            return data
    raise ValidationError("Картинка не пришла. Попробуйте ещё раз.")


def _require_admin(request: web.Request) -> TgUser:
    user: TgUser | None = request[USER_KEY]
    if user is None or not _is_admin(request.app[SETTINGS_KEY], user):
        raise ForbiddenError("Эта страница только для владельца.")
    return user


def _check_signed(request: web.Request, token_id: str) -> None:
    """Файл открывается либо с подписью Telegram (в заголовке), либо по подписанной ссылке ?t=."""
    if request[USER_KEY] is not None:
        return
    if not check_token(request.app[SERVICE_KEY].link_secret, token_id, 0, request.query.get("t")):
        raise AuthError("Ссылка устарела. Откройте приложение заново.")


async def get_payment_qr(request: web.Request) -> web.StreamResponse:
    service: OrderService = request.app[SERVICE_KEY]
    _check_signed(request, "payment-qr")
    if not service.desk.has_qr():
        raise NotFoundError("QR-код ещё не загружен.")
    headers = {"Cache-Control": "private, max-age=300", "Content-Type": "image/png",
               "Access-Control-Allow-Origin": "https://web.telegram.org"}      # нужно для Telegram.WebApp.downloadFile
    if request.query.get("download") == "1":
        headers["Content-Disposition"] = 'attachment; filename="qr-oplata.png"'
    return web.FileResponse(service.desk.qr_path, headers=headers)


async def post_receipt(request: web.Request) -> web.Response:
    service: OrderService = request.app[SERVICE_KEY]
    raw = await _read_single_image(request, "receipt")
    await service.submit_receipt(request.match_info["order_id"], request[USER_KEY], raw)
    return json_response({"ok": True, "status": "payment_review"})


async def cancel_order(request: web.Request) -> web.Response:
    service: OrderService = request.app[SERVICE_KEY]
    service.cancel_unpaid(request.match_info["order_id"], request[USER_KEY].id)
    return json_response({"ok": True})


async def admin_payments(request: web.Request) -> web.Response:
    _require_admin(request)
    return json_response(request.app[SERVICE_KEY].admin_overview())


async def admin_receipt(request: web.Request) -> web.StreamResponse:
    service: OrderService = request.app[SERVICE_KEY]
    order_id = request.match_info["order_id"]
    if request[USER_KEY] is not None:
        _require_admin(request)
    else:
        _check_signed(request, f"receipt-{order_id}")
    return web.FileResponse(service.receipt_path(order_id), headers={"Cache-Control": "private, no-store", "Content-Type": "image/jpeg"})


async def admin_approve(request: web.Request) -> web.Response:
    _require_admin(request)
    await request.app[SERVICE_KEY].approve(request.match_info["order_id"])
    return json_response({"ok": True})


async def admin_reject(request: web.Request) -> web.Response:
    _require_admin(request)
    reason = None
    if request.can_read_body:
        try:
            data = await request.json()
            reason = data.get("reason") if isinstance(data, dict) else None
        except ValueError:
            raise ValidationError("Причина пришла в неверном виде.")
    await request.app[SERVICE_KEY].reject(request.match_info["order_id"], reason)
    return json_response({"ok": True})


async def admin_settings(request: web.Request) -> web.Response:
    _require_admin(request)
    service: OrderService = request.app[SERVICE_KEY]
    try:
        data = await request.json()
    except ValueError:
        raise ValidationError("Настройки пришли в неверном виде.")
    service.desk.update(data)
    return json_response({**service.desk.settings(), "qr_url": service.qr_url()})


async def admin_qr(request: web.Request) -> web.Response:
    _require_admin(request)
    service: OrderService = request.app[SERVICE_KEY]
    service.desk.save_qr(await _read_single_image(request, "qr"))
    return json_response({**service.desk.settings(), "qr_url": service.qr_url()})


async def post_feedback(request: web.Request) -> web.Response:
    service: OrderService = request.app[SERVICE_KEY]
    try:
        data = await request.json()
    except ValueError:
        raise ValidationError("Отзыв пришёл в неверном виде.")
    await service.save_feedback(request[USER_KEY], data)
    return json_response({"ok": True})


# ------------------------------------------------------------------ Mini App (статические файлы)
def _asset_version() -> str:
    h = hashlib.sha1()
    for path in sorted(WEBAPP_DIR.glob("*")):
        if path.is_file():
            h.update(path.name.encode())
            h.update(str(path.stat().st_mtime_ns).encode())
    return h.hexdigest()[:10]


async def index(request: web.Request) -> web.Response:
    html = (WEBAPP_DIR / "index.html").read_text(encoding="utf-8").replace("__V__", _asset_version())
    return web.Response(text=html, content_type="text/html", charset="utf-8")


def create_app(settings: Settings, db: Database, service: OrderService, bot_info: dict | None = None) -> web.Application:
    app = web.Application(middlewares=[error_middleware, headers_middleware, auth_middleware],
                          client_max_size=MAX_PHOTO_BYTES + 512 * 1024)
    app[SETTINGS_KEY] = settings
    app[SERVICE_KEY] = service
    app[DB_KEY] = db
    app[BOT_KEY] = bot_info if bot_info is not None else {}
    app.router.add_get("/", index)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/orders", create_order)
    app.router.add_get("/api/orders/{order_id}", get_order)
    app.router.add_post("/api/orders/{order_id}/send", resend_order)
    app.router.add_get("/api/orders/{order_id}/img/{name}.jpg", get_image)
    app.router.add_get("/api/orders/{order_id}/book.pdf", get_pdf)
    app.router.add_post("/api/feedback", post_feedback)
    app.router.add_get("/api/payment/qr", get_payment_qr)
    app.router.add_post("/api/orders/{order_id}/receipt", post_receipt)
    app.router.add_post("/api/orders/{order_id}/cancel", cancel_order)
    app.router.add_get("/api/admin/payments", admin_payments)
    app.router.add_get("/api/admin/receipts/{order_id}.jpg", admin_receipt)
    app.router.add_post("/api/admin/orders/{order_id}/approve", admin_approve)
    app.router.add_post("/api/admin/orders/{order_id}/reject", admin_reject)
    app.router.add_post("/api/admin/settings", admin_settings)
    app.router.add_post("/api/admin/qr", admin_qr)
    if WEBAPP_DIR.exists():
        app.router.add_static("/static/", WEBAPP_DIR, follow_symlinks=False)
    return app
