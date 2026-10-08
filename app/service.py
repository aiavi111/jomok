"""Сервис заказов: лимиты, очередь, генерация книги, статус для Mini App, доставка, отзывы, уборка файлов."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import shutil
import time
from pathlib import Path

from .auth import TgUser
from .bookgen import BookResult, build_book
from .bookinfo import book_labels
from .config import Settings
from .db import ACTIVE_STATUSES, Database
from .errors import (AppError, BusyError, ConflictError, LimitError, NotFoundError, ProviderError, StoryError,
                     ValidationError)
from .imaging import hex_color, band_color, prepare_photo
from .links import make_token
from .notify import Notifier
from .payments import PaymentProvider
from .profile import Profile
from .providers.base import ImageProvider, TextProvider
from .story import Story
from .textutil import clean_text, human_wait, ru_plural

log = logging.getLogger(__name__)

ORDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,32}$")
IMAGE_NAME_RE = re.compile(r"^(cover|p[1-8])$")
DAY = 24 * 60 * 60
QUEUE_MAX = 30
WOULD_PAY = ("yes", "maybe", "no")

GENERIC_ERROR = ("Не получилось создать сказку: на нашей стороне произошёл сбой. "
                 "Эта попытка не засчитана — попробуйте ещё раз через несколько минут.")
STORY_ERROR = ("Сказка пока не получилась: ответ писателя не прошёл проверку. "
               "Эта попытка не засчитана — попробуйте ещё раз.")
INTERRUPTED = ("Сервер был перезапущен, и создание сказки прервалось. "
               "Эта попытка не засчитана — создайте сказку ещё раз.")


def safe_filename(title: str) -> str:
    name = re.sub(r"[^\w\- ]+", "", title, flags=re.UNICODE).strip()
    return (name or "Сказка") + ".pdf"


class OrderService:
    def __init__(self, settings: Settings, db: Database, text: TextProvider, image: ImageProvider,
                 notifier: Notifier, payment: PaymentProvider, link_secret: bytes):
        self.settings = settings
        self.db = db
        self.text = text
        self.image = image
        self.notifier = notifier
        self.payment = payment
        self.link_secret = link_secret
        self.orders_dir = Path(settings.data_dir) / "orders"
        self.orders_dir.mkdir(parents=True, exist_ok=True)
        self.gen_sem = asyncio.Semaphore(settings.max_parallel_generations)   # книг одновременно на весь сервис
        self.image_sem = asyncio.Semaphore(settings.image_concurrency)         # картинок одновременно
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ запуск и остановка
    def recover(self) -> None:
        n = self.db.interrupt_unfinished(INTERRUPTED, "Сервер перезапущен во время генерации")
        if n:
            log.warning("Недописанных заказов помечено ошибкой после перезапуска: %s", n)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------------------------ пути
    def order_dir(self, order_id: str) -> Path:
        if not ORDER_ID_RE.match(order_id):
            raise NotFoundError("Такой книги нет.")
        return self.orders_dir / order_id

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
            raise ConflictError("Ваша сказка уже создаётся. Дождитесь, когда она будет готова, — это займёт несколько минут.",
                                order_id=active["id"])
        since = now - DAY
        used = self.db.count_orders_since(user_id, since, include_errors=False)
        if used >= limit:
            oldest = self.db.oldest_counted_since(user_id, since) or now
            wait = max(60.0, oldest + DAY - now)
            raise LimitError(
                f"Вы уже создали {used} {ru_plural(used, 'сказку', 'сказки', 'сказок')} за последние 24 часа — "
                f"это дневной лимит ({limit}). Новую сказку можно будет создать через {human_wait(wait)}.")
        attempts = self.db.count_orders_since(user_id, since, include_errors=True)
        if attempts >= limit * 3 + 3:
            raise LimitError("Слишком много попыток за сутки. Подождите и попробуйте завтра.")
        if self.db.count_status("queued") >= QUEUE_MAX:
            raise BusyError("Сейчас очень много заказов. Попробуйте через несколько минут.")

    # ------------------------------------------------------------------ создание заказа
    async def create_order(self, user: TgUser, payload: dict, photo_raw: bytes | None) -> str:
        if not isinstance(payload, dict):
            raise ValidationError("Анкета пришла в неверном виде. Обновите приложение и попробуйте ещё раз.")
        has_photo = photo_raw is not None
        if has_photo:
            if not payload.get("photo_consent") in (True, "true", 1, "1"):
                raise ValidationError("Чтобы использовать фото, нужно отметить согласие родителя на обработку фото.",
                                      field="photo_consent")
            if not self.photo_supported():
                raise ValidationError("Сейчас фото не принимается. Создайте сказку без фото.", field="photo")
        profile = Profile.from_payload(payload, has_photo=has_photo)
        photo = prepare_photo(photo_raw) if has_photo else None

        check = await self.payment.authorize(user.id)
        if not check.ok:
            raise AppError(check.message or "Для этого заказа нужна оплата.")
        self._check_limits(user.id)

        order_id = secrets.token_urlsafe(9)
        odir = self.order_dir(order_id)
        odir.mkdir(parents=True, exist_ok=True)
        if photo:
            (odir / "photo.jpg").write_bytes(photo)
        self.db.create_order(order_id, user.id, json.dumps(profile.to_dict(), ensure_ascii=False), paid=check.paid)
        task = asyncio.create_task(self._run(order_id), name=f"order-{order_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        log.info("Заказ %s создан (возраст %s, язык %s, место %s, ценность %s, фото %s)",
                 order_id, profile.age, profile.language, profile.place, profile.value, has_photo)
        return order_id

    # ------------------------------------------------------------------ генерация
    async def _run(self, order_id: str) -> None:
        row = self.db.get_order(order_id)
        profile = Profile.from_dict(json.loads(row["profile_json"]))
        user_id = row["user_id"]
        odir = self.order_dir(order_id)
        photo_path = odir / "photo.jpg"
        photo = photo_path.read_bytes() if photo_path.exists() else None

        async def on_status(status: str) -> None:
            self.db.update_order(order_id, status=status)

        async def on_story(story: Story) -> None:
            self.db.update_order(order_id, title=story.title)

        try:
            async with self.gen_sem:
                result = await build_book(
                    profile, self.text, self.image, odir, photo=photo, image_sem=self.image_sem,
                    mock=self.settings.uses_mock, on_status=on_status, on_story=on_story,
                )
            self.db.update_order(order_id, status="done", finished_at=time.time())
            log.info("Заказ %s готов", order_id)
            await self._after_done(order_id, user_id, result)
        except asyncio.CancelledError:
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
            photo_path.unlink(missing_ok=True)      # фото больше не нужно — не храним ни дня

    async def _after_done(self, order_id: str, user_id: int, result: BookResult) -> None:
        if result.failed_pages:
            await self.notifier.notify_admin(
                f"Заказ {order_id}: не нарисовались {len(result.failed_pages)} из 9 иллюстраций "
                f"({', '.join(result.failed_pages)}). Вместо них — заглушки. " + "; ".join(result.failure_notes[:3]))
        await self._deliver(order_id, user_id, result.story, result.pdf_path)

    async def _deliver(self, order_id: str, user_id: int, story: Story, pdf_path: Path) -> bool:
        filename = safe_filename(story.title)
        caption = f"🎉 Готово! «{story.title}» — персональная сказка. Сохраните файл или откройте его на любом устройстве 💛"
        try:
            ok = await self.notifier.send_book(user_id, pdf_path, filename, caption)
        except Exception:  # noqa: BLE001
            log.exception("Заказ %s: ошибка отправки PDF в чат", order_id)
            ok = False
        self.db.update_order(order_id, delivered=1 if ok else 0)
        try:
            await self.notifier.send_admin_book(pdf_path, filename, f"Копия книги. Заказ {order_id}, пользователь {user_id}.")
        except Exception:  # noqa: BLE001
            log.exception("Заказ %s: не удалось отправить копию администратору", order_id)
        return ok

    async def resend(self, order_id: str, viewer: TgUser) -> bool:
        row = self._owned_order(order_id, viewer.id)
        pdf = self.order_dir(order_id) / "book.pdf"
        if row["status"] != "done" or row["files_deleted"] or not pdf.exists():
            raise NotFoundError("Книга ещё не готова или уже удалена.")
        story = Story.from_dict(json.loads((self.order_dir(order_id) / "story.json").read_text(encoding="utf-8")))
        return await self._deliver(order_id, viewer.id, story, pdf)

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
                                "Создайте сказку заново.")
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
        pages_done = sum(1 for i in range(1, 9) if (odir / f"p{i}.jpg").exists()) if not files_deleted else 0
        pages = []
        if story:
            for i, page in enumerate(story.pages, start=1):
                pages.append({"text": page.text,
                              "image_url": url(f"img/p{i}.jpg") if (odir / f"p{i}.jpg").exists() else None})

        view = {
            "id": order_id,
            "status": status,
            "mock": self.settings.uses_mock,
            "language": profile.language,
            "title": row["title"],
            "progress": self._progress(status, cover_ready, pages_done),
            "cover_url": url("img/cover.jpg") if cover_ready else None,
            "cover_color": hex_color(band_color(str(odir / "cover.jpg"))) if cover_ready else None,
            "pages": pages,
            "book": book_labels(story, profile) if story else None,
            "pdf_url": url("book.pdf") if status == "done" and (odir / "book.pdf").exists() and not files_deleted else None,
            "delivered": None if row["delivered"] is None else bool(row["delivered"]),
            "files_deleted": files_deleted,
            "error": row["error"] if status == "error" else None,
        }
        if status == "error" and (is_admin or self.settings.dev_mode) and row["error_detail"]:
            view["error_detail"] = row["error_detail"]
        return view

    @staticmethod
    def _progress(status: str, cover_ready: bool, pages_done: int) -> dict:
        base = {"images_done": pages_done, "images_total": 8, "cover_ready": cover_ready}
        if status == "queued":
            return {**base, "percent": 2, "stage": -1, "label": "Жду очереди"}
        if status == "writing":
            return {**base, "percent": 8, "stage": 0, "label": "Пишу сказку"}
        if status == "drawing":
            if not cover_ready:
                return {**base, "percent": 15, "stage": 1, "label": "Рисую обложку"}
            return {**base, "percent": 20 + round(70 * pages_done / 8), "stage": 2,
                    "label": f"Иллюстрации {pages_done} из 8"}
        if status == "assembling":
            return {**base, "percent": 95, "stage": 3, "label": "Собираю PDF"}
        if status == "done":
            return {**base, "percent": 100, "stage": 4, "label": "Готово"}
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
            f"Отзыв по заказу {order_id}: {mark}; за {self.settings.price_text}: {pay}."
            + (f"\nКомментарий: {comment}" if comment else ""))
        log.info("Отзыв по заказу %s сохранён", order_id)

    # ------------------------------------------------------------------ уборка
    def cleanup(self) -> int:
        """Удаляет файлы заказов старше KEEP_FILES_DAYS и стирает личные данные из анкеты."""
        cutoff = time.time() - self.settings.keep_files_days * DAY
        removed = 0
        for row in self.db.orders_with_files_older_than(cutoff):
            shutil.rmtree(self.orders_dir / row["id"], ignore_errors=True)
            profile = Profile.from_dict(json.loads(row["profile_json"]))
            self.db.update_order(row["id"], files_deleted=1,
                                 profile_json=json.dumps(profile.scrubbed(), ensure_ascii=False))
            removed += 1
        # осиротевшие папки (например, после сбоя) тоже убираем
        for path in self.orders_dir.iterdir():
            if path.is_dir() and path.stat().st_mtime < cutoff and self.db.get_order(path.name) is None:
                shutil.rmtree(path, ignore_errors=True)
        if removed:
            log.info("Удалены файлы старых заказов: %s", removed)
        return removed
