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
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .auth import TgUser
from .bookgen import PAGE_IMAGE_NAMES, BookResult, assemble_pdfs, build_book, read_cover_meta, read_layout_meta, redraw_page
from .readpdf import build_mobile_pdf
from .bookinfo import book_labels
from .config import Settings
from .declension import genitive_ru
from .db import ACTIVE_STATUSES, PAYMENT_STATUSES, REVIEW_STATUSES, Database
from .errors import (AppError, BusyError, ClosedError, ConflictError, LimitError, NotFoundError, ProviderError,
                     StoryError, StoryValidationError, ValidationError)
from .paydesk import PaymentDesk
from .imaging import hex_color, band_color, prepare_photo
from .layout import text_side
from .overlay import emphasis_runs
from .links import make_token
from .notify import Notifier
from .payments import PaymentProvider
from .profile import Profile
from .providers.base import ImageProvider, TextProvider
from .simple_writer import HARD_CODES
from .story import PAGES, Story, validate_story
from .textutil import clean_text, human_wait, ru_plural
from .writer import check_story, new_violations, violations_text

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
REVIEW_TICK = 10 * 60             # как часто main.py смотрит, не пора ли напомнить о заявке или книге без решения
ORDER_TIMEOUT = 30 * 60        # на весь заказ (текст и картинки) не больше 30 минут: подвисший сервис не держит клиента часами
RESEND_PAUSE = 45              # секунд между повторными отправками одной книги
MAX_FAILED_PAGES = 2           # больше двух ненарисованных страниц (или обложка) = заказ не удался, книга возвращается
PHOTO_PURGE_AFTER = PHOTO_TTL - CLEANUP_PERIOD   # режем с запасом на период уборки: фото живёт не дольше суток

# --- ручная проверка: заявку принимает человек, готовую книгу смотрит человек
APPROVE_KEY = "approve_requests"         # в таблице settings: "1" включено (по умолчанию из APPROVE_REQUESTS), "0" выключено
REVIEW_KEY = "review_books"              # то же для проверки готовой книги (REVIEW_BOOKS)
REMIND_EVERY = 60 * 60                   # админу напоминают о заявке или книге без решения раз в час
MAX_REMINDERS = 6                        # и не больше шести раз на один заказ
PENDING_TTL = 15 * 60                    # сколько бот ждёт от админа пометку или новый текст страницы
KEEP_ON_REDO = ("photo.jpg", PERSON_FILE, "receipt.jpg")    # при «Сделать заново» остаются фото (и чек), всё остальное рисуется заново
REQUEST_ACCEPTED_TEXT = "✅ Заявка принята. Пришлём книгу в течение 1–2 часов"
REQUEST_DECLINED_TEXT = "К сожалению, заявку не получилось принять. Книга возвращена на ваш счёт, напишите нам."
REQUEST_DECLINED_FREE_TEXT = "К сожалению, заявку не получилось принять. Напишите нам."
REVIEW_FAILED_TEXT = ("К сожалению, книга пока не получилась. Эта попытка не засчитана: книга осталась на вашем счёте. "
                      "Создайте её ещё раз чуть позже или напишите нам.")
PHOTO_GONE = ("Фото уже удалено: мы храним его не дольше 23 часов. Без фото {what} не получится похожей на ребёнка. "
              "Можно отправить книгу как есть, исправить текст или попросить клиента сделать заявку заново.")

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


@dataclass
class PendingEdit:
    """Бот спросил у администратора пометку к странице (kind="page") или новый текст страницы (kind="text") и ждёт ответ."""
    kind: str
    order_id: str
    page: int
    until: float


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
        self._busy: set[str] = set()                                         # заказы, которые сейчас правит человек (перерисовка, текст, отправка)
        self._pending: dict[tuple[int, int], PendingEdit] = {}               # (чат, администратор) -> что бот ждёт следующим сообщением

    # ------------------------------------------------------------------ запуск и остановка
    def recover(self) -> None:
        # заявки на проверке (awaiting_approval) и готовые книги на проверке (in_review) не трогаем: это не ошибка, они ждут человека
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

    def can_review(self, user_id: int) -> bool:
        """Кнопки проверки книги: администраторы и человек из REVIEW_CHAT_ID."""
        return self.settings.can_review_id(user_id)

    def closed(self) -> bool:
        """Закрытый режим включён, пока владелец явно не выключил его в админке."""
        return self.db.get_setting(CLOSED_KEY, "1") != "0"

    def set_closed(self, value: bool) -> None:
        self.db.set_setting(CLOSED_KEY, "1" if value else "0")

    # ------------------------------------------------------------------ переключатели ручной проверки
    def _switch_raw(self, key: str, default: bool) -> bool:
        value = self.db.get_setting(key)
        return default if value is None else value != "0"

    def approve_requests_setting(self) -> bool:
        """Что выбрал владелец (переключатель в админке или APPROVE_REQUESTS), без учёта того, умеет ли бот показать кнопки."""
        return self._switch_raw(APPROVE_KEY, self.settings.approve_requests)

    def review_books_setting(self) -> bool:
        return self._switch_raw(REVIEW_KEY, self.settings.review_books)

    def approve_requests(self) -> bool:
        """Заявку клиента сначала принимает человек. Без бота с кнопками выключено: иначе заказ никто бы не принял."""
        return self.approve_requests_setting() and bool(getattr(self.notifier, "can_approve_requests", False))

    def review_books(self) -> bool:
        """Готовую книгу сначала проверяет человек. Без бота с кнопками выключено."""
        return self.review_books_setting() and bool(getattr(self.notifier, "can_review_books", False))

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
        if self.is_admin(user_id):                                 # владелец и админы тестируют без дневного лимита
            return self.settings.max_books_per_user_per_day
        used = self.db.count_orders_since(user_id, time.time() - DAY, include_errors=False)
        return max(0, self.settings.max_books_per_user_per_day - used)

    def _check_limits(self, user_id: int) -> None:
        limit = self.settings.max_books_per_user_per_day
        now = time.time()
        active = self.db.active_order(user_id)
        if active:
            raise ConflictError("Ваша книга уже создаётся. Дождитесь, когда она будет готова, — это займёт несколько минут.",
                                order_id=active["id"])
        if self.is_admin(user_id):
            return
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
        # заявка сначала ждёт человека; у владельца и у оплаченного по чеку заказа этого шага нет (чек уже подтвердил человек)
        needs_approval = not needs_payment and not self.is_admin(user.id) and self.approve_requests()
        status = "awaiting_payment" if needs_payment else "awaiting_approval" if needs_approval else "queued"
        created = self.db.create_order(order_id, user.id, json.dumps(profile.to_dict(), ensure_ascii=False),
                                       paid=check.paid, status=status,
                                       use_credit=use_credit)       # проверка и списание книги — одной транзакцией
        if not created:
            shutil.rmtree(odir, ignore_errors=True)
            raise self.closed_error()
        if needs_approval:
            await self._request_card(order_id, self._new_order_text(order_id, user, profile, has_photo, use_credit, False,
                                                                    request_card=True))
            await self._tell_user(user.id, REQUEST_ACCEPTED_TEXT)
        else:
            if not needs_payment:
                self._start(order_id)
            await self._order_card(self._new_order_text(order_id, user, profile, has_photo, use_credit, needs_payment))
        log.info("Заказ %s создан (возраст %s, язык %s, место %s, ценность %s, фото %s, статус: %s)",
                 order_id, profile.age, profile.language, profile.place, profile.value, has_photo, status)
        return order_id

    @staticmethod
    def _prepare_person_photo(raw: bytes) -> bytes:
        """Фото близкого человека проходит ту же проверку и очистку, что и фото ребёнка; ошибка относится к своему полю."""
        try:
            return prepare_photo(raw)
        except ValidationError as e:
            raise ValidationError("Фото близкого человека: " + e.message[0].lower() + e.message[1:], field="person_photo")

    def _new_order_text(self, order_id: str, user: TgUser, profile: Profile, has_photo: bool, use_credit: bool,
                        needs_payment: bool, *, request_card: bool = False) -> str:
        """Карточка нового заказа для владельца: кто заказал и что (без лишних данных ребёнка).
        request_card=True: заявка, которая ждёт решения; в карточку добавлено пожелание родителей."""
        who = self.db.get_user(user.id)
        name = (who["first_name"] if who and who["first_name"] else user.first_name or "Без имени")
        username = (who["username"] if who and who["username"] else getattr(user, "username", None))
        gender = "девочка" if profile.gender == "girl" else "мальчик"
        lines = [f"{'🧾 Новая заявка' if request_card else '🧾 Новый заказ'} {order_id}",
                 f"От: {name}" + (f" (@{username})" if username else "") + f", id {user.id}",
                 f"Герой: {profile.name}, {profile.age} {ru_plural(profile.age, 'год', 'года', 'лет')}, {gender}",
                 f"Тема: {profile.world_label or profile.topic_label}",
                 f"Стиль: {profile.style_label} · язык: {'кыргызский' if profile.language == 'ky' else 'русский'}"
                 f" · фото: {'есть' if has_photo else 'нет'}" + f" · фото близкого человека: {('есть, ' + profile.person_ru) if profile.has_person_photo else 'нет'}" + (" · исламский режим" if profile.islamic else "")]
        if request_card:
            lines.append(f"Пожелание: {profile.request or 'нет'}")
        if needs_payment:
            lines.append("Ждёт оплаты и подтверждения чека")
        elif use_credit:
            lines.append(f"Осталось книг у клиента: {self.db.get_credits(user.id)}")
        if request_card:
            lines.append("«Принять и начать» запускает книгу. «Отклонить» удалит фото и вернёт клиенту книгу.")
        return "\n".join(lines)

    def _request_text(self, row) -> str:
        """Карточка заявки по записи в базе (для напоминаний)."""
        profile = Profile.from_dict(json.loads(row["profile_json"]))
        who = self.db.get_user(row["user_id"])
        user = TgUser(id=row["user_id"], first_name=(who["first_name"] if who and who["first_name"] else ""),
                      username=who["username"] if who else None)
        return self._new_order_text(row["id"], user, profile, profile.has_photo, bool(row["credit_used"]), False, request_card=True)

    async def _order_card(self, text: str) -> None:
        """Карточка заказа в чат заказов; сбой отправки заказ не ломает."""
        notify = getattr(self.notifier, "notify_order", None) or self.notifier.notify_admin
        try:
            await notify(text)
        except Exception:  # noqa: BLE001
            log.exception("Не удалось отправить карточку заказа")

    async def _request_card(self, order_id: str, text: str) -> None:
        """Заявка с кнопками «Принять и начать» / «Отклонить» в чат заказов; сбой отправки заказ не ломает (напомнит напоминание)."""
        notify = getattr(self.notifier, "notify_request", None)
        try:
            if notify:
                await notify(order_id, text)
            else:
                await (getattr(self.notifier, "notify_order", None) or self.notifier.notify_admin)(text)
        except Exception:  # noqa: BLE001
            log.exception("Не удалось отправить заявку %s", order_id)

    async def _review_card(self, order_id: str, text: str) -> None:
        """Карточка готовой книги с кнопками проверки (в чат владельца, рядом с двумя PDF)."""
        notify = getattr(self.notifier, "notify_review", None)
        try:
            if notify:
                await notify(order_id, text)
            else:
                await self.notifier.notify_admin(text)
        except Exception:  # noqa: BLE001
            log.exception("Не удалось отправить карточку проверки %s", order_id)

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
            "waiting": {"requests": self.db.count_status("awaiting_approval"), "books": self.db.count_status("in_review")},
        }

    def admin_settings(self) -> dict:
        return {**self.desk.settings(), "qr_url": self.qr_url(), "closed": self.closed(),
                "approve_requests": self.approve_requests_setting(), "review_books": self.review_books_setting(),
                "approve_requests_active": self.approve_requests(), "review_books_active": self.review_books()}

    def update_admin_settings(self, data) -> dict:
        if not isinstance(data, dict):
            raise ValidationError("Настройки пришли в неверном виде.")
        closed = _parse_flag(data["closed"], "closed", "Закрытый бот") if "closed" in data else None
        approve = (_parse_flag(data["approve_requests"], "approve_requests", "Проверка заявок")
                   if "approve_requests" in data else None)
        review = _parse_flag(data["review_books"], "review_books", "Проверка книг") if "review_books" in data else None
        self.desk.update(data)                 # при ошибке в любом поле ничего не записывается, в том числе closed
        if closed is not None:
            self.set_closed(closed)
        if approve is not None:
            self.db.set_setting(APPROVE_KEY, "1" if approve else "0")
        if review is not None:
            self.db.set_setting(REVIEW_KEY, "1" if review else "0")
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
            if self.review_books():
                await self._hold_for_review(order_id, result)       # клиенту книга не уходит, пока её не проверит человек
            else:
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
            await self._tell_failed(user_id)
        except StoryError as e:
            log.error("Заказ %s: %s", order_id, e)
            self.db.update_order(order_id, status="error", error=STORY_ERROR, error_detail=str(e))
            await self.notifier.notify_admin(f"Заказ {order_id} не создан: {e}")
            await self._tell_failed(user_id)
        except Exception as e:  # noqa: BLE001 — любой сбой должен попасть в статус заказа
            log.exception("Заказ %s: непредвиденная ошибка", order_id)
            self.db.update_order(order_id, status="error", error=GENERIC_ERROR,
                                 error_detail=f"{type(e).__name__}: {e}")
            await self.notifier.notify_admin(f"Заказ {order_id}: непредвиденная ошибка {type(e).__name__}")
            await self._tell_failed(user_id)
        finally:
            if not interrupted and not self._waits_for_review(order_id):
                photo_path.unlink(missing_ok=True)      # фото больше не нужно — не храним ни дня
                parent_path.unlink(missing_ok=True)

    def _waits_for_review(self, order_id: str) -> bool:
        """Книга ждёт проверки человеком: фото ещё нужны («Сделать заново», «Исправить страницу»), их уберёт отправка клиенту или уборка через 23 часа."""
        row = self.db.get_order(order_id)
        return row is not None and row["status"] == "in_review"

    async def _tell_failed(self, user_id: int) -> None:
        """Когда заказ проходит ручную проверку, клиент мог закрыть приложение: о сбое ему пишет бот (сама ошибка и возврат книги уже записаны)."""
        if self.approve_requests() or self.review_books():
            await self._tell_user(user_id, REVIEW_FAILED_TEXT)

    async def _after_done(self, order_id: str, user_id: int, result: BookResult) -> None:
        if result.failed_pages:
            await self.notifier.notify_admin(
                f"Заказ {order_id}: не нарисовались {len(result.failed_pages)} из {PAGES + 1} иллюстраций "
                f"({', '.join(result.failed_pages)}). Вместо них — заглушки. " + "; ".join(result.failure_notes[:3]))
        delivered = await self._deliver(order_id, user_id, result.story, result.pdf_path)
        await self._order_card(f"✅ Заказ {order_id} готов: «{result.story.title}». "
                               + ("Книга отправлена клиенту в чат." if delivered else "В чат отправить не вышло: книга ждёт клиента в приложении."))

    async def _deliver(self, order_id: str, user_id: int, story: Story, pdf_path: Path, *, offer: bool = True,
                       admin_copy: bool | None = None) -> bool:
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
        if offer if admin_copy is None else admin_copy:      # копия админу только при первой отправке, не на каждую повторную (после проверки он уже видел оба файла)
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

    # ------------------------------------------------------------------ ручная проверка: заявка
    def _spawn(self, coro, name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _order_or_404(self, order_id: str):
        row = self.db.get_order(order_id) if ORDER_ID_RE.match(order_id or "") else None
        if row is None:
            raise NotFoundError("Такого заказа нет.")
        return row

    def order_status(self, order_id: str) -> str | None:
        row = self.db.get_order(order_id) if ORDER_ID_RE.match(order_id or "") else None
        return row["status"] if row else None

    async def accept_request(self, order_id: str) -> None:
        """Администратор принял заявку: статус queued и запуск генерации. Двойное нажатие: второй раз ConflictError."""
        self._order_or_404(order_id)
        if not self.db.transition(order_id, ("awaiting_approval",), status="queued", review_at=time.time()):
            raise ConflictError("Эта заявка уже обработана.")
        self._start(order_id)
        log.info("Заказ %s: заявка принята, генерация запущена", order_id)

    async def decline_request(self, order_id: str) -> None:
        """Администратор отклонил заявку: книга возвращается на счёт, файлы заказа (фото) удаляются, клиент получает сообщение."""
        row = self._order_or_404(order_id)
        if row["status"] != "awaiting_approval":
            raise ConflictError("Эта заявка уже обработана.")
        had_credit = bool(row["credit_used"])
        profile = Profile.from_dict(json.loads(row["profile_json"]))
        done = self.db.transition(order_id, ("awaiting_approval",), status="cancelled", files_deleted=1,
                                  profile_json=json.dumps(profile.scrubbed(), ensure_ascii=False))     # возврат книги — в той же транзакции
        if not done:
            raise ConflictError("Эта заявка уже обработана.")
        shutil.rmtree(self.order_dir(order_id), ignore_errors=True)
        log.info("Заказ %s: заявка отклонена, файлы удалены", order_id)
        await self._tell_user(row["user_id"], REQUEST_DECLINED_TEXT if had_credit else REQUEST_DECLINED_FREE_TEXT)

    # ------------------------------------------------------------------ ручная проверка: готовая книга
    def _claim(self, order_id: str) -> None:
        """Один человек правит книгу за раз: пока идёт перерисовка или отправка, другие кнопки ждут."""
        if order_id in self._busy:
            raise ConflictError("Книга сейчас обрабатывается (идёт правка или отправка). Подождите минуту и нажмите ещё раз.")
        self._busy.add(order_id)

    def _release(self, order_id: str) -> None:
        self._busy.discard(order_id)

    def review_row(self, order_id: str):
        """Заказ, который сейчас ждёт проверки. Иначе ConflictError: книга уже отправлена или ещё делается."""
        row = self._order_or_404(order_id)
        if row["status"] != "in_review":
            raise ConflictError("Эта книга уже обработана или ещё не готова к проверке.")
        return row

    def _load_story(self, order_id: str) -> Story:
        try:
            return Story.from_dict(json.loads((self.order_dir(order_id) / "story.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            raise NotFoundError("Файлы книги не найдены: возможно, их уже удалили.") from None

    def page_text(self, order_id: str, number: int) -> str:
        story = self._load_story(order_id)
        if not 1 <= number <= len(story.pages):
            raise ValidationError(f"В книге нет страницы {number}.")
        return story.pages[number - 1].text

    def _photos(self, order_id: str, profile: Profile) -> tuple[bytes | None, bytes | None]:
        """Фото ребёнка и близкого человека, если они ещё на диске (через 23 часа их удаляет уборка)."""
        odir = self.order_dir(order_id)
        photo, person = odir / "photo.jpg", odir / PERSON_FILE
        return (photo.read_bytes() if photo.exists() else None, person.read_bytes() if person.exists() else None)

    def _need_photos(self, order_id: str, profile: Profile, what: str) -> tuple[bytes | None, bytes | None]:
        photo, person = self._photos(order_id, profile)
        if (profile.has_photo and photo is None) or (profile.has_person_photo and person is None):
            raise ConflictError(PHOTO_GONE.format(what=what))
        return photo, person

    def _review_text(self, order_id: str, story: Story, profile: Profile, heading: str, failed: list[str] | tuple = ()) -> str:
        row = self.db.get_order(order_id)
        who = self.db.get_user(row["user_id"]) if row else None
        name = (who["first_name"] if who and who["first_name"] else "Без имени") + (f" (@{who['username']})" if who and who["username"] else "")
        odir = self.order_dir(order_id)
        gone = [label for label, flag, file in (("ребёнка", profile.has_photo, "photo.jpg"),
                                              ("близкого человека", profile.has_person_photo, PERSON_FILE))
                if flag and not (odir / file).exists()]
        lines = [heading, f"«{story.title}», заказ {order_id}",
                 f"От: {name}, id {row['user_id'] if row else '?'}",
                 f"Герой: {profile.name}, {profile.age} {ru_plural(profile.age, 'год', 'года', 'лет')} · {profile.style_label} · "
                 f"язык: {'кыргызский' if profile.language == 'ky' else 'русский'}"]
        if profile.request:
            lines.append(f"Пожелание: {profile.request}")
        if failed:
            lines.append("Не нарисовались: " + ", ".join(("обложка" if f == "cover" else f"страница {f[1:]}") for f in failed)
                         + ". Вместо них заглушки, нажмите «Исправить страницу».")
        if gone:
            lines.append("Фото " + " и ".join(gone) + " уже удалено: «Сделать заново» и «Исправить страницу» недоступны.")
        lines.append("Выше два файла: развороты и версия для телефона. Клиенту ничего не уйдёт, пока вы не нажмёте «Отправить клиенту».")
        return "\n".join(lines)

    async def _send_review(self, order_id: str, story: Story, profile: Profile, heading: str,
                           failed: list[str] | tuple = ()) -> None:
        """Администратору: оба PDF и карточка с кнопками. Сбой отправки заказ не ломает: напоминание пришлёт карточку снова."""
        odir = self.order_dir(order_id)
        base = safe_filename(story.title).removesuffix(".pdf")
        mobile = odir / "mobile.pdf"
        if not mobile.exists():
            mobile = await asyncio.to_thread(self.ensure_mobile_pdf, order_id) or mobile
        try:
            await self.notifier.send_admin_book(odir / "book.pdf", f"{base} (развороты).pdf",
                                                f"Проверка. Заказ {order_id}: развороты, как для печати.")
            if mobile.exists():
                await self.notifier.send_admin_book(mobile, f"{base} (для телефона).pdf",
                                                    f"Проверка. Заказ {order_id}: версия для телефона, страницы по одной.")
        except Exception:  # noqa: BLE001
            log.exception("Заказ %s: не удалось отправить файлы на проверку", order_id)
        await self._review_card(order_id, self._review_text(order_id, story, profile, heading, failed))

    async def _hold_for_review(self, order_id: str, result: BookResult) -> None:
        """Генерация закончилась: книга клиенту НЕ уходит, ждёт проверки (статус in_review, фото остаются для правок)."""
        now = time.time()
        self.db.update_order(order_id, status="in_review", finished_at=now, review_at=now, reminders=0)
        log.info("Заказ %s готов и ждёт проверки", order_id)
        row = self.db.get_order(order_id)
        profile = Profile.from_dict(json.loads(row["profile_json"]))
        if result.failure_notes:
            log.warning("Заказ %s: %s", order_id, "; ".join(result.failure_notes[:3]))
        try:
            await self._send_review(order_id, result.story, profile, "📖 Книга готова, проверьте её", result.failed_pages)
            await self._order_card(f"📖 Заказ {order_id} готов: «{result.story.title}». Владелец проверяет книгу, клиенту она пока не отправлена.")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — книга готова и ждёт проверки; сбой отправки не должен сделать из неё ошибку, напомнит напоминание
            log.exception("Заказ %s: не удалось отправить книгу на проверку", order_id)

    async def approve_book(self, order_id: str, *, auto: bool = False) -> None:
        """«Отправить клиенту»: статус done, обычная доставка (оба файла, предложение печати), фото ребёнка и человека удаляются."""
        row = self.review_row(order_id)
        self._claim(order_id)
        try:
            if not self.db.transition(order_id, ("in_review",), status="done", finished_at=time.time()):
                raise ConflictError("Эта книга уже обработана.")
            odir = self.order_dir(order_id)
            for name in ("photo.jpg", PERSON_FILE):
                (odir / name).unlink(missing_ok=True)
            story = self._load_story(order_id)
            delivered = await self._deliver(order_id, row["user_id"], story, odir / "book.pdf", admin_copy=False)
            log.info("Заказ %s проверен и отправлен клиенту%s", order_id, " автоматически" if auto else "")
            await self._order_card(f"✅ Заказ {order_id} готов: «{story.title}». "
                                   + ("Книга отправлена клиенту в чат." if delivered else "В чат отправить не вышло: книга ждёт клиента в приложении."))
        finally:
            self._release(order_id)

    async def redo_book(self, order_id: str) -> None:
        """«Сделать заново»: та же анкета и те же фото, новый текст и картинки. Нужны фото на месте, иначе объясняем почему нельзя."""
        self.review_row(order_id)
        self._claim(order_id)
        try:
            row = self.review_row(order_id)
            profile = Profile.from_dict(json.loads(row["profile_json"]))
            self._need_photos(order_id, profile, "новая книга")
            if not self.db.transition(order_id, ("in_review",), status="queued", title=None, finished_at=None,
                                      review_at=time.time(), reminders=0):
                raise ConflictError("Эта книга уже обработана.")
            for path in self.order_dir(order_id).iterdir():           # старые текст, картинки и PDF не должны перепутаться с новыми
                if path.is_file() and path.name not in KEEP_ON_REDO:
                    path.unlink(missing_ok=True)
            self._start(order_id)
            log.info("Заказ %s: администратор просит сделать книгу заново", order_id)
        finally:
            self._release(order_id)

    def check_page_redraw(self, order_id: str, number: int | None = None) -> None:
        """Можно ли сейчас перерисовать страницу: книга на проверке, номер верный, фото ещё на месте. Иначе понятная ошибка (до того, как админ напишет пометку)."""
        row = self.review_row(order_id)
        story = self._load_story(order_id)
        if number is not None and (not isinstance(number, int) or not 1 <= number <= len(story.pages)):
            raise ValidationError(f"В книге нет страницы {number}.")
        self._need_photos(order_id, Profile.from_dict(json.loads(row["profile_json"])), "страница")

    async def start_page_redraw(self, order_id: str, number: int, note: str = "") -> None:
        """«Исправить страницу»: перерисовать ТОЛЬКО эту страницу (те же образцы, сцена и пометка), пересобрать PDF и прислать администратору снова."""
        self.check_page_redraw(order_id, number)
        note = clean_text(note)[:200]
        self._claim(order_id)
        self._spawn(self._redraw_task(order_id, number, note), f"redraw-{order_id}-{number}")

    async def _redraw_task(self, order_id: str, number: int, note: str) -> None:
        try:
            row = self.review_row(order_id)
            profile = Profile.from_dict(json.loads(row["profile_json"]))
            story = self._load_story(order_id)
            photo, person = self._photos(order_id, profile)
            odir = self.order_dir(order_id)
            try:
                async with self.gen_sem:
                    await asyncio.wait_for(redraw_page(story, profile, self.image, odir, number, note=note, photo=photo,
                                                       person_photo=person, image_sem=self.image_sem), timeout=ORDER_TIMEOUT)
                await assemble_pdfs(story, profile, odir, cover_has_title=bool(read_cover_meta(odir).get("title_in_image")),
                                    mock=self.settings.uses_mock, overlay_mode=self.settings.text_overlay_mode,
                                    pdf_layout=self.settings.pdf_layout)
            except asyncio.TimeoutError:
                await self._review_card(order_id, f"⚠️ Страницу {number} перерисовать не вышло: сервис слишком долго не отвечал. "
                                                  "Прежняя картинка осталась, книга не изменилась.")
                return
            except ProviderError as e:
                log.error("Заказ %s: страница %s не перерисовалась: %s", order_id, number, e.message)
                await self._review_card(order_id, f"⚠️ Страницу {number} перерисовать не вышло: {e.message} "
                                                  "Прежняя картинка осталась, книга не изменилась.")
                return
            self.db.update_order(order_id, review_at=time.time(), reminders=0)
            log.info("Заказ %s: страница %s перерисована", order_id, number)
            await self._send_review(order_id, story, profile, f"🖼 Страница {number} перерисована, книга пересобрана")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — сбой правки не должен терять книгу: она остаётся на проверке
            log.exception("Заказ %s: ошибка при перерисовке страницы %s", order_id, number)
            await self.notifier.notify_admin(f"Заказ {order_id}: страницу {number} перерисовать не получилось (ошибка сервера). Книга не изменилась.")
        finally:
            self._release(order_id)

    async def set_page_text(self, order_id: str, number: int, text: str) -> None:
        """«Исправить текст»: новый текст страницы проходит жёсткие проверки (длина, язык, бренды), PDF пересобираются и приходят администратору."""
        row = self.review_row(order_id)
        self._claim(order_id)
        try:
            profile = Profile.from_dict(json.loads(row["profile_json"]))
            odir = self.order_dir(order_id)
            story = self._load_story(order_id)
            if not isinstance(number, int) or not 1 <= number <= len(story.pages):
                raise ValidationError(f"В книге нет страницы {number}.")
            new_text = clean_text(text, keep_newlines=True)
            if not new_text:
                raise ValidationError("Текст пустой. Пришлите новый текст страницы.")
            data = story.to_dict()
            data["pages"][number - 1]["text"] = new_text
            try:
                candidate = validate_story(data, profile.language, exact_pages=False)
            except StoryValidationError as e:
                raise ValidationError(f"Текст не подошёл: {e}") from None
            before = [v for v in check_story(story, profile, None) if v.code in HARD_CODES]
            after = [v for v in check_story(candidate, profile, None) if v.code in HARD_CODES]
            fresh = new_violations(before, after)
            if fresh:
                raise ValidationError("Текст не подошёл:\n" + violations_text(fresh))
            tmp = odir / "story.json.tmp"
            tmp.write_text(json.dumps(candidate.to_dict(), ensure_ascii=False), encoding="utf-8")
            tmp.replace(odir / "story.json")
            await assemble_pdfs(candidate, profile, odir, cover_has_title=bool(read_cover_meta(odir).get("title_in_image")),
                                mock=self.settings.uses_mock, overlay_mode=self.settings.text_overlay_mode,
                                pdf_layout=self.settings.pdf_layout)
            self.db.update_order(order_id, review_at=time.time(), reminders=0)
            log.info("Заказ %s: текст страницы %s исправлен", order_id, number)
            await self._send_review(order_id, candidate, profile, f"✏️ Текст страницы {number} исправлен, книга пересобрана")
        finally:
            self._release(order_id)

    # --- что бот ждёт от администратора следующим сообщением
    def expect_edit(self, chat_id: int, user_id: int, kind: str, order_id: str, page: int) -> None:
        self._pending[(chat_id, user_id)] = PendingEdit(kind, order_id, page, time.time() + PENDING_TTL)

    def pending_edit(self, chat_id: int, user_id: int) -> PendingEdit | None:
        item = self._pending.get((chat_id, user_id))
        if item and item.until < time.time():
            self._pending.pop((chat_id, user_id), None)
            return None
        return item

    def finish_edit(self, chat_id: int, user_id: int) -> None:
        self._pending.pop((chat_id, user_id), None)

    # --- напоминания и автоотправка
    async def send_reminders(self) -> int:
        """Раз в час напоминает администратору о заявках и книгах без решения (не больше MAX_REMINDERS раз на заказ). Возвращает число напоминаний."""
        now = time.time()
        sent = 0
        for row in self.db.orders_to_remind(now - REMIND_EVERY, MAX_REMINDERS):
            order_id = row["id"]
            if order_id in self._busy:
                continue
            number = row["reminders"] + 1
            self.db.update_order(order_id, review_at=now, reminders=number)        # отметка до отправки: сбой не засыплет админа повторами
            waited = human_wait(now - (row["finished_at"] if row["status"] == "in_review" and row["finished_at"] else row["created_at"]))
            try:
                if row["status"] == "awaiting_approval":
                    await self._request_card(order_id, f"⏰ Заявка ждёт решения уже {waited} (напоминание {number} из {MAX_REMINDERS}).\n"
                                                       + self._request_text(row))
                else:
                    story = self._load_story(order_id)
                    profile = Profile.from_dict(json.loads(row["profile_json"]))
                    await self._review_card(order_id, self._review_text(
                        order_id, story, profile, f"⏰ Книга ждёт проверки уже {waited} (напоминание {number} из {MAX_REMINDERS})"))
                sent += 1
            except AppError:
                log.warning("Заказ %s: напоминание не отправлено (нет файлов книги)", order_id)
        return sent

    async def auto_send_due(self) -> int:
        """Если задан REVIEW_AUTO_SEND_HOURS (больше 0), книга, которую никто не проверил, сама уходит клиенту. Возвращает число отправленных."""
        hours = self.settings.review_auto_send_hours
        if hours <= 0:
            return 0
        sent = 0
        for row in self.db.books_in_review_since(time.time() - hours * 3600):
            if row["id"] in self._busy:
                continue
            try:
                await self.approve_book(row["id"], auto=True)
            except AppError as e:
                log.warning("Заказ %s: автоотправка не вышла: %s", row["id"], e.message)
                continue
            sent += 1
            await self.notifier.notify_admin(f"Заказ {row['id']}: книгу никто не проверил за {human_wait(hours * 3600)}, "
                                             "она отправлена клиенту автоматически.")
        return sent

    # ------------------------------------------------------------------ вариант для телефона у уже готовых книг
    def ensure_mobile_pdf(self, order_id: str) -> Path | None:
        """Вертикальный PDF 9:16 (mobile.pdf) для готовой книги, у которой его ещё нет (книги, созданные до обновления).
        Берёт сохранённые текст и картинки; нет файлов или не получилось, возвращает None и ничего не ломает."""
        if not ORDER_ID_RE.match(order_id):
            return None
        row = self.db.get_order(order_id)
        odir = self.order_dir(order_id)
        target = odir / "mobile.pdf"
        if row is None or row["status"] not in ("done", "in_review") or row["files_deleted"]:
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
        if self._art_hidden(row["status"]):
            raise NotFoundError("Файл ещё не готов.")
        if name == "book.pdf":
            path = self.order_dir(order_id) / "book.pdf"
        elif IMAGE_NAME_RE.match(name):
            path = self.order_dir(order_id) / f"{name}.jpg"
        else:
            raise NotFoundError("Такого файла нет.")
        if not path.exists():
            raise NotFoundError("Файл ещё не готов.")
        return path

    def _art_hidden(self, status: str) -> bool:
        """Клиент не видит картинки и текст книги, пока её не проверил человек: ни при проверке, ни во время работы над ней."""
        return status in REVIEW_STATUSES or (status in ACTIVE_STATUSES and self.review_books())

    def view(self, order_id: str, viewer: TgUser, *, is_admin: bool = False) -> dict:
        row = self._owned_order(order_id, viewer.id)
        odir = self.order_dir(order_id)
        status = row["status"]
        files_deleted = bool(row["files_deleted"])
        token = make_token(self.link_secret, order_id, row["user_id"])

        def url(name: str) -> str:
            return f"/api/orders/{order_id}/{name}?t={token}"

        hidden = self._art_hidden(status)
        story: Story | None = None
        story_path = odir / "story.json"
        if story_path.exists() and not files_deleted and not hidden:
            story = Story.from_dict(json.loads(story_path.read_text(encoding="utf-8")))
        profile = Profile.from_dict(json.loads(row["profile_json"]))

        cover_ready = (odir / "cover.jpg").exists() and not files_deleted and not hidden
        pages_done = sum(1 for i in range(1, PAGES + 1) if (odir / f"p{i}.jpg").exists()) if not files_deleted and not hidden else 0
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
            "title": None if hidden else row["title"],
            "review": hidden,                      # книгу проверит человек: приложение не показывает страницы по мере готовности
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
        if status == "awaiting_approval":
            return {**base, "percent": 0, "stage": -1, "label": "Заявка на проверке"}
        if status == "in_review":
            return {**base, "percent": 0, "stage": -1, "label": "Проверяем книгу"}
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
        Заказы, которые ждут оплату или решение человека (заявка, книга на проверке), не трогаются.
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
