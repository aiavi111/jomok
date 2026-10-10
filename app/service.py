"""Сервис заказов: доступ по личным ссылкам, лимиты, очередь, генерация книги, статус для Mini App, доставка,
предложение печатной версии, отзывы, уборка файлов (в том числе фото не старше суток)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from .auth import TgUser
from .bookgen import PAGE_IMAGE_NAMES, BookResult, build_book, read_cover_meta, read_layout_meta
from .readpdf import build_mobile_pdf
from .bookinfo import book_labels
from .config import Settings
from .declension import genitive_ru
from .db import ACTIVE_STATUSES, PAYMENT_STATUSES, Database
from .errors import (AppError, BusyError, ClosedError, ConflictError, LimitError, NotFoundError, ProviderError,
                     StoryError, ValidationError)
from .paydesk import PaymentDesk
from .imaging import hex_color, band_color, prepare_photo
from .layout import text_side
from .overlay import emphasis_runs
from .links import make_token
from .notify import Notifier
from .payments import PaymentProvider
from .profile import Profile
from .providers.base import ImageProvider, TextProvider
from .story import PAGES, Story
from .textutil import clean_text, human_wait, ru_plural

log = logging.getLogger(__name__)

ORDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,32}$")
IMAGE_NAME_RE = re.compile(r"^(cover|" + "|".join(PAGE_IMAGE_NAMES) + r")$")   # cover, p1..pN
DAY = 24 * 60 * 60
PERSON_FILE = "person.jpg"      # фото близкого человека в папке заказа: живёт и удаляется вместе с photo.jpg
UNPAID_KEEP_DAYS = 3             # неоплаченный заказ без чека через столько дней отменяется сам
QR_TOKEN_ID = "payment-qr"
DEFAULT_REJECT = "Платёж не найден. Проверьте сумму и отправьте чек ещё раз."
QUEUE_MAX = 30
WOULD_PAY = ("yes", "maybe", "no")

# --- закрытый бот и личные ссылки
CLOSED_KEY = "closed_bot"        # в таблице settings: "1" закрыт (по умолчанию), "0" открыт для всех
CLOSED_TEXT = ("Бот работает по личным ссылкам. Ссылку на доступ вы получите после оплаты: "
               "напишите нам в WhatsApp.")
INVITE_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
INVITE_MAX_CREDITS = 20
INVITE_NOTE_MAX = 80
INVITE_LIST_LIMIT = 30

# --- предложение печатной версии
PRINT_TITLE = "Хотите заказать печатную версию?"
PRINT_NOTE = "Мягкая фотокнига 21×21 см"
PRINT_MESSAGE = "Здравствуйте! Хочу заказать печатную версию книги"
PRINT_BUTTON = "Заказать в WhatsApp"
ACCESS_MESSAGE = "Здравствуйте! Хочу получить ссылку на создание книги"      # текст в WhatsApp для получения доступа

# --- обещание про фото: удаляем сразу после создания книги и в любом случае не позже чем через сутки
PHOTO_TTL = DAY
CLEANUP_PERIOD = 60 * 60          # как часто main.py запускает cleanup()
ORDER_TIMEOUT = 30 * 60        # на весь заказ (текст и картинки) не больше 30 минут: подвисший сервис не держит клиента часами
RESEND_PAUSE = 45              # секунд между повторными отправками одной книги
MAX_FAILED_PAGES = 2           # больше двух ненарисованных страниц (или обложка) = заказ не удался, книга возвращается
PHOTO_PURGE_AFTER = PHOTO_TTL - CLEANUP_PERIOD   # режем с запасом на период уборки: фото живёт не дольше суток

GENERIC_ERROR = ("Не получилось создать книгу: на нашей стороне произошёл сбой. "
                 "Эта попытка не засчитана — попробуйте ещё раз через несколько минут.")
STORY_ERROR = ("Книга пока не получилась: ответ писателя не прошёл проверку. "
               "Эта попытка не засчитана — попробуйте ещё раз.")
INTERRUPTED = ("Сервер был перезапущен, и создание книги прервалось. "
               "Эта попытка не засчитана — создайте книгу ещё раз.")


def safe_filename(title: str) -> str:
    name = re.sub(r"[^\w\- ]+", "", title, flags=re.UNICODE).strip()
    return (name or "Книга") + ".pdf"


def whatsapp_url(digits: str, message: str = PRINT_MESSAGE) -> str:
    """Ссылка на чат владельца в WhatsApp с готовым русским сообщением."""
    return f"https://wa.me/{digits}?text={quote(message, safe='')}"


def invite_url(bot_username: str, token: str) -> str:
    """Личная ссылка: бот получает «/start inv_<токен>»."""
    return f"https://t.me/{bot_username}?start=inv_{token}"


def _parse_flag(value, field: str, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("1", "true", "0", "false"):
        return value.strip().lower() in ("1", "true")
    raise ValidationError(f"{label}: включено или выключено.", field=field)


class OrderService:
    def __init__(self, settings: Settings, db: Database, text: TextProvider, image: ImageProvider,
                 notifier: Notifier, payment: PaymentProvider, link_secret: bytes, desk: PaymentDesk | None = None):
        self.settings = settings
        self.db = db
        self.text = text
        self.image = image
        self.notifier = notifier
        self.payment = payment
        self.link_secret = link_secret
        self.desk = desk or PaymentDesk(db, settings.data_dir, settings.price_text)
        self.orders_dir = Path(settings.data_dir) / "orders"
        self.orders_dir.mkdir(parents=True, exist_ok=True)
        self._resent: dict[str, float] = {}                                  # когда книгу последний раз отправляли повторно
        self.gen_sem = asyncio.Semaphore(settings.max_parallel_generations)   # книг одновременно на весь сервис
        self.image_sem = asyncio.Semaphore(settings.image_concurrency)         # картинок одновременно
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ запуск и остановка
    def recover(self) -> None:
        n = self.db.interrupt_unfinished(INTERRUPTED, "Сервер перезапущен во время генерации")
        if n:
            log.warning("Недописанных заказов помечено ошибкой после перезапуска: %s", n)

    def resume_paid(self) -> int:
        """Оплаченные заказы, которые прервал перезапуск, запускаем заново: платить второй раз не нужно."""
        rows = self.db.unfinished_paid()
        for row in rows:
            self.db.update_order(row["id"], status="queued")
            self._start(row["id"])
        if rows:
            log.warning("Оплаченных заказов запущено заново после перезапуска: %s", len(rows))
        return len(rows)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------------------------ пути
    def order_dir(self, order_id: str) -> Path:
        if not ORDER_ID_RE.match(order_id):
            raise NotFoundError("Такой книги нет.")
        return self.orders_dir / order_id

    # ------------------------------------------------------------------ доступ по личным ссылкам
    def is_admin(self, user_id: int) -> bool:
        return self.settings.is_admin_id(user_id)

    def closed(self) -> bool:
        """Закрытый режим включён, пока владелец явно не выключил его в админке."""
        return self.db.get_setting(CLOSED_KEY, "1") != "0"

    def set_closed(self, value: bool) -> None:
        self.db.set_setting(CLOSED_KEY, "1" if value else "0")

    def access_state(self, user_id: int) -> dict:
        """granted: можно ли прямо сейчас создать книгу (владелец, открытый режим или остались книги)."""
        admin, closed, credits = self.is_admin(user_id), self.closed(), self.db.get_credits(user_id)
        return {"granted": admin or not closed or credits > 0, "credits": credits, "closed": closed, "is_admin": admin}

    def whatsapp(self) -> str:
        return self.desk.whatsapp()

    def access_whatsapp_url(self) -> str | None:
        """Ссылка «напишите нам в WhatsApp» для тех, у кого нет доступа (с готовым сообщением); None — номер не задан."""
        wa = self.whatsapp()
        return whatsapp_url(wa, ACCESS_MESSAGE) if wa else None

    def closed_error(self) -> ClosedError:
        return ClosedError(CLOSED_TEXT, whatsapp_url=self.access_whatsapp_url())

    async def redeem_invite(self, token: str, user_id: int, *, first_name: str | None = None,
                            username: str | None = None, language_code: str | None = None) -> int | None:
        """Погашает личную ссылку (один раз, атомарно) и сообщает владельцу. None — ссылка использована или недействительна."""
        if not INVITE_RE.match(token or ""):
            return None
        self.db.upsert_user(user_id, username, first_name, language_code)
        credits = self.db.redeem_invite(token, user_id)
        if credits is None:
            return None
        log.info("Личная ссылка использована (книг: %s)", credits)
        row = self.db.get_invite(token)
        who = (first_name or "Без имени") + (f" (@{username})" if username else "")
        text = (f"🔑 Ссылка доступа использована: {who}, "
                f"{credits} {ru_plural(credits, 'книга', 'книги', 'книг')}."
                + (f"\nЗаметка: {row['note']}" if row and row["note"] else ""))
        try:
            await self.notifier.notify_admin(text)
        except Exception:  # noqa: BLE001 — доступ уже выдан, сообщение владельцу не критично
            log.exception("Не удалось сообщить владельцу об использованной ссылке")
        return credits

    def invite_available(self, token: str) -> bool:
        row = self.db.get_invite(token) if INVITE_RE.match(token or "") else None
        return row is not None and row["used_by"] is None

    def create_invite(self, data: dict | None) -> dict:
        data = data or {}
        if not isinstance(data, dict):
            raise ValidationError("Запрос пришёл в неверном виде.")
        raw = data.get("credits")
        if raw is None or raw == "":
            credits = 1
        elif isinstance(raw, bool) or not (isinstance(raw, int) or (isinstance(raw, str) and raw.strip().isdigit())):
            raise ValidationError(f"Число книг: целое от 1 до {INVITE_MAX_CREDITS}.", field="credits")
        else:
            credits = int(raw)
        if not 1 <= credits <= INVITE_MAX_CREDITS:
            raise ValidationError(f"Число книг: целое от 1 до {INVITE_MAX_CREDITS}.", field="credits")
        note = clean_text(data.get("note"))
        if len(note) > INVITE_NOTE_MAX:
            raise ValidationError(f"Заметка: не длиннее {INVITE_NOTE_MAX} символов.", field="note")
        token = secrets.token_urlsafe(9)
        self.db.create_invite(token, credits, note)
        return {"token": token, "credits": credits, "note": note}

    def list_invites(self, bot_username: str | None) -> list[dict]:
        def item(row) -> dict:
            who = None
            if row["used_by"] is not None:
                who = (row["user_first_name"] or "Без имени") + (f" (@{row['user_username']})" if row["user_username"] else "")
            return {"token": row["token"], "url": invite_url(bot_username, row["token"]) if bot_username else None,
                    "credits": row["credits"], "note": row["note"] or "", "created_at": row["created_at"],
                    "used_by": row["used_by"], "used_at": row["used_at"], "user_name": who}
        return [item(r) for r in self.db.list_invites(INVITE_LIST_LIMIT)]

    def revoke_invite(self, token: str) -> None:
        row = self.db.get_invite(token) if INVITE_RE.match(token or "") else None
        if row is None:
            raise NotFoundError("Такой ссылки нет.")
        if row["used_by"] is not None or not self.db.revoke_invite(token):
            raise ConflictError("Эта ссылка уже использована, отозвать её нельзя.")

    # ------------------------------------------------------------------ предложение печатной версии
    def print_offer(self) -> dict:
        wa = self.whatsapp()
        return {"enabled": bool(wa), "whatsapp_url": whatsapp_url(wa) if wa else None,
                "pdf_price": self.price_text(), "print_price": self.desk.print_price(),
                "title": PRINT_TITLE, "note": PRINT_NOTE}

    async def _offer_print(self, order_id: str, user_id: int) -> None:
        """Второе сообщение под книгой: цены и кнопка «Заказать в WhatsApp» (только если номер задан)."""
        offer = self.print_offer()
        send = getattr(self.notifier, "send_print_offer", None)
        if not offer["enabled"] or not send:
            return
        text = f"{PRINT_TITLE} {offer['pdf_price']}: PDF, {offer['print_price']}: мягкая фотокнига"
        try:
            await send(user_id, text, offer["whatsapp_url"])
        except Exception:  # noqa: BLE001 — книга уже доставлена
            log.exception("Заказ %s: не удалось отправить предложение печатной версии", order_id)

    # ------------------------------------------------------------------ лимиты
    def photo_supported(self) -> bool:
        # фото уходит только провайдерам с референсами, и не при тестовом бесплатном тексте Gemini
        return self.image.supports_reference and self.settings.text_provider != "gemini"

    def remaining_today(self, user_id: int) -> int:
        used = self.db.count_orders_since(user_id, time.time() - DAY, include_errors=False)
        return max(0, self.settings.max_books_per_user_per_day - used)

    def _check_limits(self, user_id: int) -> None:
        limit = self.settings.max_books_per_user_per_day
        now = time.time()
        active = self.db.active_order(user_id)
        if active:
            raise ConflictError("Ваша книга уже создаётся. Дождитесь, когда она будет готова, — это займёт несколько минут.",
                                order_id=active["id"])
        since = now - DAY
        used = self.db.count_orders_since(user_id, since, include_errors=False)
        if used >= limit:
            oldest = self.db.oldest_counted_since(user_id, since) or now
            wait = max(60.0, oldest + DAY - now)
            raise LimitError(
                f"Вы уже создали {used} {ru_plural(used, 'книгу', 'книги', 'книг')} за последние 24 часа — "
                f"это дневной лимит ({limit}). Новую книгу можно будет создать через {human_wait(wait)}.")
        attempts = self.db.count_orders_since(user_id, since, include_errors=True)
        if attempts >= limit * 3 + 3:
            raise LimitError("Слишком много попыток за сутки. Подождите и попробуйте завтра.")
        if self.db.count_status("queued") >= QUEUE_MAX:
            raise BusyError("Сейчас очень много заказов. Попробуйте через несколько минут.")

    # ------------------------------------------------------------------ создание заказа
    async def create_order(self, user: TgUser, payload: dict, photo_raw: bytes | None, parent_raw: bytes | None = None) -> str:
        # закрытый бот: книгу создаёт только тот, у кого есть книги на счёте (владелец всегда может, книги не тратит)
        use_credit = self.closed() and not self.is_admin(user.id)
        if use_credit and self.db.get_credits(user.id) <= 0:
            raise self.closed_error()
        if not isinstance(payload, dict):
            raise ValidationError("Анкета пришла в неверном виде. Обновите приложение и попробуйте ещё раз.")
        has_photo = photo_raw is not None
        has_parent = parent_raw is not None
        if has_photo or has_parent:
            if not payload.get("photo_consent") in (True, "true", 1, "1"):
                raise ValidationError("Чтобы использовать фото, нужно отметить согласие родителя на обработку фото.",
                                      field="photo_consent")
            if not self.photo_supported():
                raise ValidationError("Сейчас фото не принимается. Создайте книгу без фото.", field="photo")
        profile = Profile.from_payload(payload, has_photo=has_photo, has_person_photo=has_parent)
        photo = prepare_photo(photo_raw) if has_photo else None
        parent = self._prepare_person_photo(parent_raw) if has_parent else None

        check = await self.payment.authorize(user.id)
        if not check.ok:
            raise AppError(check.message or "Для этого заказа нужна оплата.")
        self._check_limits(user.id)

        order_id = secrets.token_urlsafe(9)
        odir = self.order_dir(order_id)
        odir.mkdir(parents=True, exist_ok=True)
        if photo:
            (odir / "photo.jpg").write_bytes(photo)
        if parent:
            (odir / PERSON_FILE).write_bytes(parent)
        needs_payment = self.desk.required() and not check.paid and not use_credit and not self.is_admin(user.id)   # по ссылке и владелец уже не платят чеком
        created = self.db.create_order(order_id, user.id, json.dumps(profile.to_dict(), ensure_ascii=False),
                                       paid=check.paid, status="awaiting_payment" if needs_payment else "queued",
                                       use_credit=use_credit)       # проверка и списание книги — одной транзакцией
        if not created:
            shutil.rmtree(odir, ignore_errors=True)
            raise self.closed_error()
        if not needs_payment:
            self._start(order_id)
        await self._order_card(self._new_order_text(order_id, user, profile, has_photo, use_credit, needs_payment))
        log.info("Заказ %s создан (возраст %s, язык %s, место %s, ценность %s, фото %s, оплата нужна: %s)",
                 order_id, profile.age, profile.language, profile.place, profile.value, has_photo, needs_payment)
        return order_id

    @staticmethod
    def _prepare_person_photo(raw: bytes) -> bytes:
        """Фото близкого человека проходит ту же проверку и очистку, что и фото ребёнка; ошибка относится к своему полю."""
        try:
            return prepare_photo(raw)
        except ValidationError as e:
            raise ValidationError("Фото близкого человека: " + e.message[0].lower() + e.message[1:], field="person_photo")

    def _new_order_text(self, order_id: str, user: TgUser, profile: Profile, has_photo: bool, use_credit: bool,
                        needs_payment: bool) -> str:
        """Карточка нового заказа для владельца: кто заказал и что (без лишних данных ребёнка)."""
        who = self.db.get_user(user.id)
        name = (who["first_name"] if who and who["first_name"] else user.first_name or "Без имени")
        username = (who["username"] if who and who["username"] else getattr(user, "username", None))
        gender = "девочка" if profile.gender == "girl" else "мальчик"
        lines = [f"🧾 Новый заказ {order_id}",
                 f"От: {name}" + (f" (@{username})" if username else "") + f", id {user.id}",
                 f"Герой: {profile.name}, {profile.age} {ru_plural(profile.age, 'год', 'года', 'лет')}, {gender}",
                 f"Тема: {profile.topic_label}" + (f" · мир: {profile.world_label}" if profile.world_label else ""),
                 f"Стиль: {profile.style_label} · язык: {'кыргызский' if profile.language == 'ky' else 'русский'}"
                 f" · фото: {'есть' if has_photo else 'нет'}" + f" · фото близкого человека: {('есть, ' + profile.person_ru) if profile.has_person_photo else 'нет'}" + (" · исламский режим" if profile.islamic else "")]
        if needs_payment:
            lines.append("Ждёт оплаты и подтверждения чека")
        elif use_credit:
            lines.append(f"Осталось книг у клиента: {self.db.get_credits(user.id)}")
        return "\n".join(lines)

    async def _order_card(self, text: str) -> None:
        """Карточка заказа в чат заказов; сбой отправки заказ не ломает."""
        notify = getattr(self.notifier, "notify_order", None) or self.notifier.notify_admin
        try:
            await notify(text)
        except Exception:  # noqa: BLE001
            log.exception("Не удалось отправить карточку заказа")

    def _start(self, order_id: str) -> None:
        task = asyncio.create_task(self._run(order_id), name=f"order-{order_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------------ оплата по QR
    def price_text(self) -> str:
        return self.desk.price_text()

    def _payment_order(self, order_id: str, user_id: int | None = None):
        """Заказ, который ждёт оплаты или проверки чека. user_id=None — вызывает администратор."""
        if not ORDER_ID_RE.match(order_id):
            raise NotFoundError("Такого заказа нет.")
        row = self.db.get_order(order_id)
        if row is None or (user_id is not None and row["user_id"] != user_id):
            raise NotFoundError("Такого заказа нет.")
        if row["status"] not in PAYMENT_STATUSES:
            raise ConflictError("Этот заказ уже обработан: оплата не требуется.")
        return row

    async def submit_receipt(self, order_id: str, user: TgUser, raw: bytes) -> None:
        row = self._payment_order(order_id, user.id)
        if not self.desk.required():
            raise ConflictError("Приём оплаты сейчас выключен. Напишите нам, мы всё поправим.")
        data = self.desk.prepare_receipt(raw)
        odir = self.order_dir(order_id)
        odir.mkdir(parents=True, exist_ok=True)
        (odir / "receipt.jpg").write_bytes(data)
        self.db.update_order(order_id, status="payment_review", receipt_at=time.time(), pay_note=None)
        profile = Profile.from_dict(json.loads(row["profile_json"]))
        who = self.db.get_user(user.id)
        label = (who["first_name"] if who and who["first_name"] else "Покупатель") + (f" (@{who['username']})" if who and who["username"] else "")
        text = (f"💳 Новый чек на {self.price_text()}\nОт: {label}\nКнига для: {profile.name}, {profile.age} "
                f"{ru_plural(profile.age, 'год', 'года', 'лет')}\nЗаказ: {order_id}")
        notify = getattr(self.notifier, "notify_payment", None)
        try:
            if notify:
                await notify(order_id, odir / "receipt.jpg", text)
            else:
                await self.notifier.notify_admin(text)
        except Exception:  # noqa: BLE001 — чек всё равно виден в админке
            log.exception("Заказ %s: не удалось сообщить администратору о чеке", order_id)
        log.info("Заказ %s: получен чек, ждёт подтверждения", order_id)

    async def _tell_user(self, user_id: int, text: str) -> None:
        send = getattr(self.notifier, "notify_user", None)
        if not send:
            return
        try:
            await send(user_id, text)
        except Exception:  # noqa: BLE001
            log.exception("Не удалось отправить сообщение пользователю")

    async def approve(self, order_id: str) -> None:
        row = self._payment_order(order_id)
        self.db.update_order(order_id, status="queued", paid=1, paid_at=time.time(), pay_note=None)
        self._start(order_id)
        log.info("Заказ %s: оплата подтверждена, генерация запущена", order_id)
        await self._tell_user(row["user_id"], "✅ Оплата получена, спасибо! Начинаем писать вашу книгу. "
                                              "Откройте приложение, чтобы следить за прогрессом, — книга придёт сюда 💛")

    async def reject(self, order_id: str, reason: str | None = None) -> None:
        row = self._payment_order(order_id)
        reason = " ".join((reason or "").split())[:300] or DEFAULT_REJECT
        (self.order_dir(order_id) / "receipt.jpg").unlink(missing_ok=True)
        self.db.update_order(order_id, status="awaiting_payment", pay_note=reason, receipt_at=None)
        log.info("Заказ %s: чек отклонён", order_id)
        await self._tell_user(row["user_id"], f"❌ Не удалось подтвердить оплату. {reason}\n"
                                              "Откройте приложение и отправьте чек ещё раз.")

    def cancel_unpaid(self, order_id: str, user_id: int | None = None) -> None:
        row = self._payment_order(order_id, user_id)
        if user_id is not None and row["status"] != "awaiting_payment":
            raise ConflictError("Чек уже отправлен, дождитесь решения владельца.")
        profile = Profile.from_dict(json.loads(row["profile_json"]))
        shutil.rmtree(self.order_dir(order_id), ignore_errors=True)
        self.db.update_order(order_id, status="cancelled", files_deleted=1, pay_note=None,
                             profile_json=json.dumps(profile.scrubbed(), ensure_ascii=False))
        log.info("Заказ %s отменён до оплаты", order_id)

    def qr_url(self) -> str | None:
        if not self.desk.has_qr():
            return None
        return f"/api/payment/qr?t={make_token(self.link_secret, QR_TOKEN_ID, 0)}"

    def admin_overview(self) -> dict:
        def item(row) -> dict:
            profile = Profile.from_dict(json.loads(row["profile_json"]))
            who = self.db.get_user(row["user_id"])
            token = make_token(self.link_secret, f"receipt-{row['id']}", 0)
            return {
                "id": row["id"], "user_id": row["user_id"],
                "user": (who["first_name"] if who and who["first_name"] else "Без имени"),
                "username": who["username"] if who else None,
                "child": f"{profile.name}, {profile.age} {ru_plural(profile.age, 'год', 'года', 'лет')}",
                "receipt_at": row["receipt_at"], "created_at": row["created_at"], "paid_at": row["paid_at"],
                "status": row["status"], "title": row["title"], "pay_note": row["pay_note"],
                "receipt_url": f"/api/admin/receipts/{row['id']}.jpg?t={token}"
                               if (self.order_dir(row["id"]) / "receipt.jpg").exists() else None,
            }
        return {
            "settings": self.admin_settings(),
            "pending": [item(r) for r in self.db.orders_with_status("payment_review")],
            "awaiting": [item(r) for r in self.db.orders_with_status("awaiting_payment", limit=30)],
            "recent": [item(r) for r in self.db.recent_paid(10)],
            "paid_today": self.db.count_paid_since(time.time() - DAY),
        }

    def admin_settings(self) -> dict:
        return {**self.desk.settings(), "qr_url": self.qr_url(), "closed": self.closed()}

    def update_admin_settings(self, data) -> dict:
        if not isinstance(data, dict):
            raise ValidationError("Настройки пришли в неверном виде.")
        closed = _parse_flag(data["closed"], "closed", "Закрытый бот") if "closed" in data else None
        self.desk.update(data)                 # при ошибке в любом поле ничего не записывается, в том числе closed
        if closed is not None:
            self.set_closed(closed)
        return self.admin_settings()

    def receipt_path(self, order_id: str) -> Path:
        if not ORDER_ID_RE.match(order_id):
            raise NotFoundError("Чека нет.")
        path = self.orders_dir / order_id / "receipt.jpg"
        if not path.exists():
            raise NotFoundError("Чека нет.")
        return path

    # ------------------------------------------------------------------ генерация
    async def _run(self, order_id: str) -> None:
        row = self.db.get_order(order_id)
        profile = Profile.from_dict(json.loads(row["profile_json"]))
        user_id = row["user_id"]
        odir = self.order_dir(order_id)
        photo_path = odir / "photo.jpg"
        photo = photo_path.read_bytes() if photo_path.exists() else None
        parent_path = odir / PERSON_FILE
        parent = parent_path.read_bytes() if parent_path.exists() else None

        async def on_status(status: str) -> None:
            self.db.update_order(order_id, status=status)

        async def on_story(story: Story) -> None:
            self.db.update_order(order_id, title=story.title)

        interrupted = False
        try:
            async with self.gen_sem:
                try:
                    result = await asyncio.wait_for(build_book(
                        profile, self.text, self.image, odir, photo=photo, person_photo=parent, image_sem=self.image_sem,
                        mock=self.settings.uses_mock, overlay_mode=self.settings.text_overlay_mode,
                        pdf_layout=self.settings.pdf_layout, on_status=on_status, on_story=on_story,
                    ), timeout=ORDER_TIMEOUT)
                except asyncio.TimeoutError:
                    raise ProviderError("Сервис слишком долго не отвечал. Попробуйте ещё раз позже.") from None
            if "cover" in result.failed_pages or len(result.failed_pages) > MAX_FAILED_PAGES:
                # книга из заглушек клиенту не нужна: заказ считается неудавшимся, книга возвращается на счёт
                raise ProviderError("Не получилось нарисовать иллюстрации. Попробуйте ещё раз позже.")
            self.db.update_order(order_id, status="done", finished_at=time.time())
            log.info("Заказ %s готов", order_id)
            await self._after_done(order_id, user_id, result)
        except asyncio.CancelledError:
            # остановка сервера (деплой): оплаченный заказ не трогаем (ни статус, ни фото), при запуске он продолжится;
            # неоплаченный получает ошибку и книга возвращается; уже готовую книгу ошибкой не портим
            current = self.db.get_order(order_id)
            if current is not None and current["status"] in ACTIVE_STATUSES:
                if current["paid"]:
                    interrupted = True
                else:
                    self.db.update_order(order_id, status="error", error=INTERRUPTED, error_detail="Остановлено")
            raise
        except ProviderError as e:
            log.error("Заказ %s: сбой внешнего сервиса: %s", order_id, e.message)
            self.db.update_order(order_id, status="error", error=GENERIC_ERROR, error_detail=e.message)
            await self.notifier.notify_admin(f"Заказ {order_id} не создан. Причина: {e.message}")
        except StoryError as e:
            log.error("Заказ %s: %s", order_id, e)
            self.db.update_order(order_id, status="error", error=STORY_ERROR, error_detail=str(e))
            await self.notifier.notify_admin(f"Заказ {order_id} не создан: {e}")
        except Exception as e:  # noqa: BLE001 — любой сбой должен попасть в статус заказа
            log.exception("Заказ %s: непредвиденная ошибка", order_id)
            self.db.update_order(order_id, status="error", error=GENERIC_ERROR,
                                 error_detail=f"{type(e).__name__}: {e}")
            await self.notifier.notify_admin(f"Заказ {order_id}: непредвиденная ошибка {type(e).__name__}")
        finally:
            if not interrupted:
                photo_path.unlink(missing_ok=True)      # фото больше не нужно — не храним ни дня
                parent_path.unlink(missing_ok=True)

    async def _after_done(self, order_id: str, user_id: int, result: BookResult) -> None:
        if result.failed_pages:
            await self.notifier.notify_admin(
                f"Заказ {order_id}: не нарисовались {len(result.failed_pages)} из {PAGES + 1} иллюстраций "
                f"({', '.join(result.failed_pages)}). Вместо них — заглушки. " + "; ".join(result.failure_notes[:3]))
        delivered = await self._deliver(order_id, user_id, result.story, result.pdf_path)
        await self._order_card(f"✅ Заказ {order_id} готов: «{result.story.title}». "
                               + ("Книга отправлена клиенту в чат." if delivered else "В чат отправить не вышло: книга ждёт клиента в приложении."))

    async def _deliver(self, order_id: str, user_id: int, story: Story, pdf_path: Path, *, offer: bool = True) -> bool:
        filename = safe_filename(story.title)
        mobile = Path(pdf_path).with_name("mobile.pdf")
        if not mobile.exists():                         # книга создана до обновления (или повторная отправка): допекаем вариант для телефона
            made = await asyncio.to_thread(self.ensure_mobile_pdf, order_id)
            mobile = made or mobile
        caption = f"🎉 Готово! «{story.title}» — персональная книга. Сохраните файл или откройте его на любом устройстве 💛"
        try:
            ok = await self.notifier.send_book(user_id, pdf_path, filename, caption)
        except Exception:  # noqa: BLE001
            log.exception("Заказ %s: ошибка отправки PDF в чат", order_id)
            ok = False
        if ok and mobile.exists():                     # второй вариант: те же страницы по одной на экран телефона (9:16)
            try:
                await self.notifier.send_book(user_id, mobile, filename.removesuffix(".pdf") + " (для телефона).pdf",
                                              "📱 Версия для телефона: страницы по одной, листайте вниз. Это та же книга.")
            except Exception:  # noqa: BLE001
                log.exception("Заказ %s: не удалось отправить вариант с разворотами", order_id)
        self.db.update_order(order_id, delivered=1 if ok else 0)
        if ok and offer:
            await self._offer_print(order_id, user_id)
        if offer:                              # копия админу только при первой отправке, не на каждую повторную
            try:
                await self.notifier.send_admin_book(pdf_path, filename, f"Копия книги. Заказ {order_id}, пользователь {user_id}.")
            except Exception:  # noqa: BLE001
                log.exception("Заказ %s: не удалось отправить копию администратору", order_id)
        return ok

    async def resend(self, order_id: str, viewer: TgUser) -> bool:
        row = self._owned_order(order_id, viewer.id)
        last = self._resent.get(order_id, 0.0)
        if time.time() - last < RESEND_PAUSE:                # двойной тап не шлёт PDF несколько раз подряд
            raise ConflictError("Файл уже отправляется. Подождите минуту и проверьте чат.")
        self._resent[order_id] = time.time()
        pdf = self.order_dir(order_id) / "book.pdf"
        if row["status"] != "done" or row["files_deleted"] or not pdf.exists():
            raise NotFoundError("Книга ещё не готова или уже удалена.")
        story = Story.from_dict(json.loads((self.order_dir(order_id) / "story.json").read_text(encoding="utf-8")))
        return await self._deliver(order_id, viewer.id, story, pdf, offer=False)

    # ------------------------------------------------------------------ вариант для телефона у уже готовых книг
    def ensure_mobile_pdf(self, order_id: str) -> Path | None:
        """Вертикальный PDF 9:16 (mobile.pdf) для готовой книги, у которой его ещё нет (книги, созданные до обновления).
        Берёт сохранённые текст и картинки; нет файлов или не получилось, возвращает None и ничего не ломает."""
        if not ORDER_ID_RE.match(order_id):
            return None
        row = self.db.get_order(order_id)
        odir = self.order_dir(order_id)
        target = odir / "mobile.pdf"
        if row is None or row["status"] != "done" or row["files_deleted"]:
            return None
        if target.exists():
            return target
        try:
            story = Story.from_dict(json.loads((odir / "story.json").read_text(encoding="utf-8")))
            profile = Profile.from_dict(json.loads(row["profile_json"]))
            images = {"cover": odir / "cover.jpg", **{f"p{i}": odir / f"p{i}.jpg" for i in range(1, len(story.pages) + 1)}}
            if not all(p.exists() for p in images.values()):
                return None
            return build_mobile_pdf(story, profile, images, target, mock=self.settings.uses_mock,
                                    cover_has_title=bool(read_cover_meta(odir).get("title_in_image")))
        except Exception:  # noqa: BLE001 — старая книга без нужных файлов не должна мешать остальным
            log.exception("Заказ %s: не удалось собрать mobile.pdf", order_id)
            return None

    def backfill_mobile_pdfs(self) -> int:
        """При запуске: собирает вариант для телефона у всех готовых книг, где он ещё не собран (по одной, быстро). Возвращает число собранных."""
        made = 0
        for row in self.db.recent_done():
            if not (self.order_dir(row["id"]) / "mobile.pdf").exists() and self.ensure_mobile_pdf(row["id"]):
                made += 1
        if made:
            log.info("Собран вариант для телефона у %s прежних книг", made)
        return made

    async def send_recent_mobile(self, limit: int = 10) -> int:
        """Владельцу: вариант для телефона последних готовых книг (чтобы посмотреть новое оформление на прежних заказах)."""
        sent = 0
        for row in self.db.recent_done(limit):
            path = await asyncio.to_thread(self.ensure_mobile_pdf, row["id"])
            if path is None:
                continue
            title = row["title"] or "Книга"
            try:
                await self.notifier.send_admin_book(path, safe_filename(title) + " (для телефона).pdf",
                                                    f"📱 Вариант для телефона. Заказ {row['id']}, «{title}».")
                sent += 1
            except Exception:  # noqa: BLE001
                log.exception("Заказ %s: не удалось отправить вариант для телефона владельцу", row["id"])
        return sent

    # ------------------------------------------------------------------ чтение
    def _owned_order(self, order_id: str, user_id: int):
        if not ORDER_ID_RE.match(order_id):
            raise NotFoundError("Такой книги нет.")
        row = self.db.get_order(order_id)
        if row is None or row["user_id"] != user_id:     # чужой заказ неотличим от несуществующего
            raise NotFoundError("Такой книги нет.")
        return row

    def owner_of(self, order_id: str) -> int | None:
        if not ORDER_ID_RE.match(order_id):
            return None
        row = self.db.get_order(order_id)
        return row["user_id"] if row else None

    def file_path(self, order_id: str, name: str) -> Path:
        row = self.db.get_order(order_id)
        if row is None:
            raise NotFoundError("Такой книги нет.")
        if row["files_deleted"]:
            raise NotFoundError(f"Файлы удалены через {self.settings.keep_files_days} дн. после создания. "
                                "Создайте книгу заново.")
        if name == "book.pdf":
            path = self.order_dir(order_id) / "book.pdf"
        elif IMAGE_NAME_RE.match(name):
            path = self.order_dir(order_id) / f"{name}.jpg"
        else:
            raise NotFoundError("Такого файла нет.")
        if not path.exists():
            raise NotFoundError("Файл ещё не готов.")
        return path

    def view(self, order_id: str, viewer: TgUser, *, is_admin: bool = False) -> dict:
        row = self._owned_order(order_id, viewer.id)
        odir = self.order_dir(order_id)
        status = row["status"]
        files_deleted = bool(row["files_deleted"])
        token = make_token(self.link_secret, order_id, row["user_id"])

        def url(name: str) -> str:
            return f"/api/orders/{order_id}/{name}?t={token}"

        story: Story | None = None
        story_path = odir / "story.json"
        if story_path.exists() and not files_deleted:
            story = Story.from_dict(json.loads(story_path.read_text(encoding="utf-8")))
        profile = Profile.from_dict(json.loads(row["profile_json"]))

        cover_ready = (odir / "cover.jpg").exists() and not files_deleted
        pages_done = sum(1 for i in range(1, PAGES + 1) if (odir / f"p{i}.jpg").exists()) if not files_deleted else 0
        pages = []
        if story:
            styles = read_layout_meta(odir).get("text_styles") or []
            for i, page in enumerate(story.pages, start=1):
                pages.append({"text": page.text,
                              "image_url": url(f"img/p{i}.jpg") if (odir / f"p{i}.jpg").exists() else None,
                              "lines": [[{"t": t, "a": a} for t, a in line] for line in emphasis_runs(page.text)],
                              "text_side": text_side(i),                       # половина широкой картинки под текст
                              "text_style": styles[i - 1] if i <= len(styles) else None})   # как оформлен в PDF

        view = {
            "id": order_id,
            "status": status,
            "mock": self.settings.uses_mock,
            "language": profile.language,
            "style": profile.style,
            "style_label": profile.style_label,
            "title": row["title"],
            "progress": self._progress(status, cover_ready, pages_done),
            "cover_url": url("img/cover.jpg") if cover_ready else None,
            "cover_color": hex_color(band_color(str(odir / "cover.jpg"))) if cover_ready else None,
            "cover_has_title": bool(read_cover_meta(odir).get("title_in_image")),
            "pages": pages,
            "book": book_labels(story, profile) if story else None,
            "pdf_url": url("book.pdf") if status == "done" and (odir / "book.pdf").exists() and not files_deleted else None,
            "delivered": None if row["delivered"] is None else bool(row["delivered"]),
            "files_deleted": files_deleted,
            "error": row["error"] if status == "error" else None,
        }
        if status == "error" and (is_admin or self.settings.dev_mode) and row["error_detail"]:
            view["error_detail"] = row["error_detail"]
        if status in PAYMENT_STATUSES:
            view["payment"] = {
                "price_text": self.price_text(), "instructions": self.desk.instructions(), "qr_url": self.qr_url(),
                "note": row["pay_note"], "receipt_sent": status == "payment_review",
                "child": genitive_ru(profile.name, profile.gender) if profile.language == "ru" else profile.name,
            }
        return view

    @staticmethod
    def _progress(status: str, cover_ready: bool, pages_done: int) -> dict:
        base = {"images_done": pages_done, "images_total": PAGES, "cover_ready": cover_ready}
        if status == "awaiting_payment":
            return {**base, "percent": 0, "stage": -1, "label": "Ждём оплату"}
        if status == "payment_review":
            return {**base, "percent": 0, "stage": -1, "label": "Проверяем оплату"}
        if status == "queued":
            return {**base, "percent": 2, "stage": -1, "label": "Жду очереди"}
        if status == "writing":
            return {**base, "percent": 8, "stage": 0, "label": "Пишу книгу"}
        if status == "drawing":
            if not cover_ready:
                return {**base, "percent": 15, "stage": 1, "label": "Рисую обложку"}
            return {**base, "percent": 20 + round(70 * pages_done / PAGES), "stage": 2,
                    "label": f"Иллюстрации {pages_done} из {PAGES}"}
        if status == "assembling":
            return {**base, "percent": 95, "stage": 3, "label": "Собираю PDF"}
        if status == "done":
            return {**base, "percent": 100, "stage": 4, "label": "Готово"}
        if status == "cancelled":
            return {**base, "percent": 0, "stage": -1, "label": "Отменено"}
        return {**base, "percent": 0, "stage": -1, "label": "Ошибка"}

    def active_order_id(self, user_id: int) -> str | None:
        row = self.db.active_order(user_id)
        return row["id"] if row else None

    # ------------------------------------------------------------------ отзывы
    async def save_feedback(self, user: TgUser, data: dict) -> None:
        if not isinstance(data, dict):
            raise ValidationError("Отзыв пришёл в неверном виде.")
        order_id = str(data.get("order_id") or "")
        row = self._owned_order(order_id, user.id)
        rating_raw = data.get("rating")
        rating = {"up": 1, "like": 1, 1: 1, True: 1, "1": 1, "down": 0, "dislike": 0, 0: 0, False: 0, "0": 0}.get(rating_raw)
        if rating_raw is not None and rating is None:
            raise ValidationError("Оценка должна быть «понравилось» или «не понравилось».", field="rating")
        would_pay = data.get("would_pay")
        if would_pay is not None and would_pay not in WOULD_PAY:
            raise ValidationError("Выберите один из ответов: да, возможно, нет.", field="would_pay")
        comment = clean_text(data.get("comment"), keep_newlines=True)
        if len(comment) > 1000:
            raise ValidationError("Комментарий слишком длинный: не больше 1000 символов.", field="comment")
        if rating is None and would_pay is None and not comment:
            raise ValidationError("Выберите оценку или ответьте на вопрос о цене.")
        self.db.upsert_feedback(order_id, user.id, rating, comment, would_pay)
        mark = {1: "👍 понравилась", 0: "👎 не понравилась", None: "оценки нет"}[rating]
        pay = {"yes": "купили бы", "maybe": "возможно купили бы", "no": "не купили бы", None: "—"}[would_pay]
        await self.notifier.notify_admin(
            f"Отзыв по заказу {order_id}: {mark}; за {self.price_text()}: {pay}."
            + (f"\nКомментарий: {comment}" if comment else ""))
        log.info("Отзыв по заказу %s сохранён", order_id)

    # ------------------------------------------------------------------ уборка
    def purge_old_photos(self) -> int:
        """Фото ребёнка не живёт дольше суток при любом статусе заказа (оплата, очередь, сбой): считаем по времени файла."""
        cutoff = time.time() - PHOTO_PURGE_AFTER
        purged = 0
        for path in self.orders_dir.iterdir():
            for name in ("photo.jpg", PERSON_FILE):
                photo = path / name
                try:
                    if path.is_dir() and photo.stat().st_mtime < cutoff:
                        photo.unlink()
                        purged += 1
                except OSError:          # нет файла (его уже убрала генерация) или папку удалили в этот момент
                    continue
        if purged:
            log.info("Удалены фото старше суток: %s", purged)
        return purged

    def cleanup(self) -> int:
        """Удаляет фото старше суток, файлы заказов старше KEEP_FILES_DAYS и стирает личные данные из анкеты.
        Возвращает число удалённых заказов (фото в него не входят)."""
        self.purge_old_photos()
        cutoff = time.time() - self.settings.keep_files_days * DAY
        removed = 0
        for row in self.db.orders_with_files_older_than(cutoff):
            shutil.rmtree(self.orders_dir / row["id"], ignore_errors=True)
            profile = Profile.from_dict(json.loads(row["profile_json"]))
            self.db.update_order(row["id"], files_deleted=1,
                                 profile_json=json.dumps(profile.scrubbed(), ensure_ascii=False))
            removed += 1
        for row in self.db.unpaid_older_than(time.time() - UNPAID_KEEP_DAYS * DAY):
            try:
                self.cancel_unpaid(row["id"])
                removed += 1
            except AppError:
                pass
        # осиротевшие папки (например, после сбоя) тоже убираем
        for path in self.orders_dir.iterdir():
            if path.is_dir() and path.stat().st_mtime < cutoff and self.db.get_order(path.name) is None:
                shutil.rmtree(path, ignore_errors=True)
        if removed:
            log.info("Удалены файлы старых заказов: %s", removed)
        return removed
