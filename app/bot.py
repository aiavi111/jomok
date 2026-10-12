"""Telegram-бот (aiogram 3): закрытый доступ по личным ссылкам, кнопка Mini App, /id, отправка готовой книги в чат."""
from __future__ import annotations

import asyncio
import html
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (TelegramAPIError, TelegramForbiddenError, TelegramNetworkError,
                                TelegramRetryAfter, TelegramUnauthorizedError)
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BotCommand, BotCommandScopeChat, BotCommandScopeDefault, ForceReply, FSInputFile,
                           InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, MenuButtonWebApp, Message, WebAppInfo,
                           CallbackQuery)

from .config import Settings
from .errors import AppError, ValidationError
from .service import ACCESS_MESSAGE, CLOSED_TEXT, PRINT_BUTTON, whatsapp_url
from .story import PAGES
from .textutil import ru_plural

log = logging.getLogger(__name__)

BUTTON_TEXT = "✨ Создать книгу"
PAGES_TEXT = f"{PAGES} {ru_plural(PAGES, 'страница', 'страницы', 'страниц')}"      # «8 страниц»: число берётся из story.PAGES
WELCOME = (
    "✨ <b>Привет! Это Bala story bot.</b>\n\n"
    "Я делаю <b>персональные книги</b>, где главный герой — ваш малыш 👶\n\n"
    "📝 Вы отвечаете на несколько вопросов — 1–2 минуты. Можно выбрать тему и написать, какие герои и истории вам нужны\n"
    "🎨 Мы придумываем короткую добрую историю, рисуем большие иллюстрации и сами проверяем книгу — обычно 1–2 часа\n"
    f"📖 Присылаем PDF-книгу: {PAGES_TEXT} с яркими картинками и несколькими строками текста на каждой\n\n"
    "На русском или кыргызском, с горами, джайлоо и Иссык-Кулем 🏔️\n\n"
    "Нажмите кнопку ниже, и начнём 👇"
)
NOT_READY = "🌙 Приложение пока не подключено. Загляните сюда чуть позже — мы скоро откроемся!"
HELP = (
    "❓ <b>Как это работает</b>\n\n"
    "Книги создаются по личной ссылке: её вы получаете после оплаты, напишите нам в WhatsApp.\n\n"
    "1️⃣ Нажмите кнопку «✨ Создать книгу» — откроется приложение.\n"
    "2️⃣ Ответьте на вопросы о малыше: имя, возраст, любимые занятия, характер. Выберите тему и напишите, "
    "какие герои и что вы хотите увидеть в книге.\n"
    "3️⃣ Подождите: мы проверим заявку и сами посмотрим готовую книгу, обычно это 1–2 часа. Приложение можно закрыть.\n"
    f"4️⃣ Готовую книгу, PDF из {PAGES_TEXT} с яркими иллюстрациями, я пришлю сюда 💌\n\n"
    "Если кнопки не видно, отправьте /start."
)
CLOSED_REMINDER = "Книги создаются в приложении — нажмите кнопку ниже 👇"
INVALID_INVITE = "Эта ссылка уже использована или недействительна. Напишите нам, и мы пришлём новую."
OWNER_INVITE = ("Вы владелец бота: доступ у вас открыт всегда. Эта ссылка осталась неиспользованной, "
                "отправьте её клиенту.")


def granted_text(credits: int) -> str:
    return (f"🎉 Доступ открыт: у вас {credits} {ru_plural(credits, 'книга', 'книги', 'книг')}.\n\n"
            "Нажмите кнопку ниже, ответьте на вопросы о малыше, выберите тему и героев, и мы создадим для него книгу: "
            f"PDF из {PAGES_TEXT} с яркими иллюстрациями 💛")


def whatsapp_link(digits: str) -> str:
    return f'<a href="{html.escape(whatsapp_url(digits, ACCESS_MESSAGE), quote=True)}">+{digits}</a>'


def closed_text(whatsapp: str = "") -> str:
    """Что видит человек без доступа; если задан номер владельца, он идёт ссылкой на WhatsApp."""
    if not whatsapp:
        return CLOSED_TEXT
    return f"{CLOSED_TEXT[:-1]} {whatsapp_link(whatsapp)}."


# Оформление профиля бота (лимиты Telegram: описание до 512, «о боте» до 120, имя до 64 символов)
BOT_NAME = "Bala story bot"
SHORT_DESCRIPTION = f"✨ Персональные книги с малышом в главной роли: PDF из {PAGES_TEXT}. Доступ по личной ссылке"
DESCRIPTION = (
    "✨ Bala story bot: персональные книги, где главный герой — ваш малыш!\n\n"
    "📝 Ответьте на несколько вопросов за 1–2 минуты: выберите тему и напишите, какие герои вам нужны\n"
    "🎨 Мы придумаем короткую добрую историю и нарисуем большие иллюстрации\n"
    f"📖 Обычно в течение 1–2 часов пришлём PDF-книгу: {PAGES_TEXT} с яркими картинками\n\n"
    "Книга создаётся по личной ссылке, которую вы получите после оплаты: напишите нам в WhatsApp 💬\n\n"
    "На русском или кыргызском 🏔️"
)
PUBLIC_COMMANDS = [
    BotCommand(command="start", description="✨ Создать книгу"),
    BotCommand(command="help", description="❓ Как это работает"),
]
ADMIN_COMMANDS = [
    BotCommand(command="admin", description="⚙️ Админка: ссылки, оплаты, QR-код"),
    BotCommand(command="mobile", description="📱 Прежние книги в новом формате для телефона"),
    BotCommand(command="id", description="🆔 Узнать свой ID (для владельца)"),
]
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)       # у ссылки на WhatsApp не нужна карточка


def webapp_ready(url: str) -> bool:
    return url.startswith("https://") and len(url) > len("https://")


def webapp_keyboard(url: str) -> InlineKeyboardMarkup | None:
    if not webapp_ready(url):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=BUTTON_TEXT, web_app=WebAppInfo(url=url))
    ]])


def admin_url(url: str) -> str:
    return url + ("&" if "?" in url else "?") + "admin=1"


def _user_id(message: Message) -> int:
    return message.from_user.id if message.from_user else message.chat.id


async def _answer_closed(message: Message, service) -> None:
    await message.answer(closed_text(service.whatsapp()), link_preview_options=NO_PREVIEW)


def request_keyboard(order_id: str) -> InlineKeyboardMarkup:
    """Кнопки под заявкой клиента."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять и начать", callback_data=f"req:ok:{order_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"req:no:{order_id}")]])


def review_keyboard(order_id: str) -> InlineKeyboardMarkup:
    """Кнопки под готовой книгой: отправить, сделать заново, исправить страницу или текст."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить клиенту", callback_data=f"rev:ok:{order_id}")],
        [InlineKeyboardButton(text="🔁 Сделать заново", callback_data=f"rev:redo:{order_id}")],
        [InlineKeyboardButton(text="🖼 Исправить страницу", callback_data=f"rev:page:{order_id}"),
         InlineKeyboardButton(text="✏️ Исправить текст", callback_data=f"rev:text:{order_id}")]])


def pages_keyboard(order_id: str, action: str) -> InlineKeyboardMarkup:
    """Ряд кнопок 1–8: какую страницу исправить (action: pn — перерисовать, text — текст)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=str(n), callback_data=f"rev:{action}:{order_id}:{n}") for n in range(1, PAGES + 1)]])


DASHES = ("-", "—", "–", "−")
ALERT_MAX = 190                 # Telegram: текст всплывающего окна на кнопке не длиннее 200 символов


async def _answer(call: CallbackQuery, text: str | None = None, alert: bool = False) -> bool:
    try:
        await call.answer(text, show_alert=alert)
        return True
    except (TelegramAPIError, TelegramNetworkError, OSError):     # кнопка устарела, на неё уже ответили или нет связи
        return False


async def _drop_keyboard(call: CallbackQuery) -> None:
    if call.message is None:
        return
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except (TelegramAPIError, TelegramNetworkError, OSError):
        pass


async def _say(call: CallbackQuery, text: str, **kw) -> None:
    if call.message is None:
        return
    try:
        await call.message.answer(text, **kw)
    except (TelegramAPIError, TelegramNetworkError, OSError) as e:
        log.info("Ответ администратору не отправлен: %s", type(e).__name__)


async def _tell_problem(call: CallbackQuery, text: str) -> None:
    """Объяснение, почему кнопка не сработала: короткое во всплывающем окне, длинное сообщением в чат."""
    if len(text) <= ALERT_MAX and await _answer(call, text, True):
        return
    await _answer(call)
    await _say(call, html.escape(text))


def build_router() -> Router:
    router = Router()

    private = F.chat.type == "private"       # в группах (чат заказов) бот отвечает только на /id: остальное там не для клиентов

    @router.message(CommandStart(), private)
    async def on_start(message: Message, command: CommandObject, webapp_url: str, runtime: "BotRuntime") -> None:
        service = runtime.service
        if service is None:
            await message.answer(NOT_READY)
            return
        user_id = _user_id(message)
        keyboard = webapp_keyboard(webapp_url)
        arg = (command.args or "").strip()
        if arg.startswith("inv_"):                       # личная ссылка: t.me/<бот>?start=inv_<токен>
            token = arg[len("inv_"):]
            if service.is_admin(user_id):               # владелец проверяет ссылку: не тратим её
                await message.answer(OWNER_INVITE if service.invite_available(token) else INVALID_INVITE,
                                     reply_markup=keyboard)
                return
            user = message.from_user
            credits = await service.redeem_invite(token, user_id, first_name=user.first_name if user else None,
                                                  username=user.username if user else None,
                                                  language_code=user.language_code if user else None)
            if credits is None:
                wa = service.whatsapp()
                await message.answer(INVALID_INVITE + (f" {whatsapp_link(wa)}" if wa else ""),
                                     link_preview_options=NO_PREVIEW)
                return
            await message.answer(granted_text(credits) + ("" if keyboard else "\n\n" + NOT_READY), reply_markup=keyboard)
            return
        if not service.access_state(user_id)["granted"]:
            await _answer_closed(message, service)
            return
        await message.answer(WELCOME if keyboard else NOT_READY, reply_markup=keyboard)

    @router.message(Command("id"))
    async def on_id(message: Message) -> None:
        if message.chat.type != "private":
            await message.answer(
                f"🆔 ID этого чата: <code>{message.chat.id}</code>\n\n"
                "Если это чат для заказов, впишите это число (вместе с минусом) в Railway → Variables → ORDERS_CHAT_ID — "
                "и карточки новых заказов будут приходить сюда 🧾"
            )
            return
        await message.answer(
            f"🆔 Ваш ID: <code>{message.chat.id}</code>\n\n"
            "Если вы владелец бота, впишите это число в строку ADMIN_CHAT_ID в файле .env — "
            "и копии книг и отзывы будут приходить сюда 💌"
        )

    @router.message(Command("mobile"), private)
    async def on_mobile(message: Message, runtime: "BotRuntime") -> None:
        if not runtime.settings.is_admin_id(_user_id(message)) or runtime.service is None:
            await message.answer("Эта команда только для владельца бота.")
            return
        await message.answer("Собираю вариант для телефона у последних книг…")
        sent = await runtime.service.send_recent_mobile(10)
        await message.answer(f"Готово: отправил {sent} шт." if sent else "Подходящих книг пока нет: у них удалены файлы или книг ещё не было.")

    @router.message(Command("admin"), private)
    async def on_admin(message: Message, webapp_url: str, runtime: "BotRuntime") -> None:
        if not runtime.settings.is_admin_id(_user_id(message)):
            await message.answer("Эта команда только для владельца бота.")
            return
        if not webapp_ready(webapp_url):
            await message.answer(NOT_READY)
            return
        await message.answer(
            "⚙️ <b>Админка</b>: личные ссылки доступа, цены, чеки на подтверждение и QR-код.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⚙️ Открыть админку", web_app=WebAppInfo(url=admin_url(webapp_url)))]]))

    @router.callback_query(F.data.startswith("pay:"))
    async def on_payment_button(call: CallbackQuery, runtime: "BotRuntime") -> None:
        if not runtime.settings.is_admin_id(call.from_user.id):
            await call.answer("Это действие только для владельца.", show_alert=True)
            return
        service = runtime.service
        parts = (call.data or "").split(":", 2)
        if service is None or len(parts) != 3 or parts[1] not in ("ok", "no"):
            await call.answer("Не получилось. Откройте админку.", show_alert=True)
            return
        try:
            if parts[1] == "ok":
                await service.approve(parts[2])
                note = "✅ Оплата подтверждена, книга создаётся"
            else:
                await service.reject(parts[2], None)
                note = "❌ Чек отклонён, покупателю отправлено сообщение"
        except AppError as e:
            await call.answer(e.message, show_alert=True)
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except TelegramAPIError:
                pass
            return
        await call.answer(note)
        try:
            await call.message.edit_reply_markup(reply_markup=None)
            await call.message.reply(note)
        except TelegramAPIError:
            pass

    @router.callback_query(F.data.startswith("req:"))
    async def on_request_button(call: CallbackQuery, runtime: "BotRuntime") -> None:
        """«Принять и начать» / «Отклонить» под заявкой клиента. Только администраторы; повторное нажатие ничего не ломает."""
        service = runtime.service
        if service is None or not service.can_review(call.from_user.id):
            await _answer(call, "Это действие только для владельца.", True)
            return
        parts = (call.data or "").split(":", 2)
        if len(parts) != 3 or parts[1] not in ("ok", "no"):
            await _answer(call, "Не получилось. Откройте админку.", True)
            return
        try:
            if parts[1] == "ok":
                await service.accept_request(parts[2])
                note = "✅ Заявка принята, книга создаётся"
            else:
                await service.decline_request(parts[2])
                note = "❌ Заявка отклонена, клиенту отправлено сообщение, книга возвращена на счёт"
        except AppError as e:
            await _tell_problem(call, e.message)
            await _drop_keyboard(call)
            return
        await _answer(call, note[:ALERT_MAX])
        await _drop_keyboard(call)
        await _say(call, note)

    @router.callback_query(F.data.startswith("rev:"))
    async def on_review_button(call: CallbackQuery, runtime: "BotRuntime") -> None:
        """Кнопки проверки готовой книги: rev:ok / redo / page / text (и rev:pn, rev:text с номером страницы)."""
        service = runtime.service
        if service is None or not service.can_review(call.from_user.id):
            await _answer(call, "Это действие только для владельца.", True)
            return
        parts = (call.data or "").split(":")
        action = parts[1] if len(parts) > 1 else ""
        order_id = parts[2] if len(parts) > 2 else ""
        number = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
        chat_id = call.message.chat.id if call.message else call.from_user.id
        try:
            if action == "ok":
                service.review_row(order_id)                           # уже отправлена? скажем во всплывающем окне, а не после «Отправляю…»
                await _answer(call, "Отправляю клиенту…")
                await service.approve_book(order_id)
                await _drop_keyboard(call)
                await _say(call, "✅ Книга отправлена клиенту")
            elif action == "redo":
                await service.redo_book(order_id)
                await _answer(call, "Делаю заново")
                await _drop_keyboard(call)
                await _say(call, "🔁 Делаю книгу заново по той же анкете. Пришлю её сюда, когда будет готова: это несколько минут.")
            elif action == "page" and number is None:
                service.check_page_redraw(order_id)                    # фото удалено или книга уже отправлена: говорим сразу, а не после пометки
                await _answer(call)
                await _say(call, "Какую страницу перерисовать?", reply_markup=pages_keyboard(order_id, "pn"))
            elif action == "pn" and number is not None:
                service.check_page_redraw(order_id, number)
                service.expect_edit(chat_id, call.from_user.id, "page", order_id, number)
                await _answer(call)
                await _say(call, f"Страница {number}. Напишите одним сообщением, что на ней исправить "
                                 "(например: «убрать лишнюю собаку» или «сделать день, а не ночь»). "
                                 "Если ничего писать не нужно, отправьте «-»: страница просто нарисуется заново.",
                           reply_markup=ForceReply(force_reply=True, input_field_placeholder="Что исправить? Или «-»"))
            elif action == "text" and number is None:
                service.review_row(order_id)
                await _answer(call)
                await _say(call, "Текст какой страницы исправить?", reply_markup=pages_keyboard(order_id, "text"))
            elif action == "text":
                service.review_row(order_id)
                current = service.page_text(order_id, number)
                service.expect_edit(chat_id, call.from_user.id, "text", order_id, number)
                await _answer(call)
                await _say(call, f"Страница {number}. Сейчас там написано:\n\n{html.escape(current)}\n\n"
                                 "Пришлите новый текст страницы одним сообщением. Чтобы ничего не менять, отправьте «-».",
                           reply_markup=ForceReply(force_reply=True, input_field_placeholder="Новый текст страницы"))
            else:
                await _answer(call, "Не получилось. Нажмите кнопку на самой карточке книги.", True)
        except AppError as e:
            await _tell_problem(call, e.message)
            if service.order_status(order_id) != "in_review":       # книга уже обработана: старые кнопки больше не нужны
                await _drop_keyboard(call)

    async def has_pending_edit(message: Message, runtime: "BotRuntime") -> bool:
        service = getattr(runtime, "service", None)
        if service is None or message.from_user is None or not message.text or message.text.startswith("/"):
            return False
        return service.pending_edit(message.chat.id, message.from_user.id) is not None

    @router.message(has_pending_edit)
    async def on_pending_edit(message: Message, runtime: "BotRuntime") -> None:
        """Следующее сообщение администратора после «Исправить страницу» (пометка) или «Исправить текст» (новый текст)."""
        service = runtime.service
        key = (message.chat.id, message.from_user.id)
        pending = service.pending_edit(*key)
        if pending is None:
            return
        text = (message.text or "").strip()
        if not service.can_review(message.from_user.id):
            service.finish_edit(*key)
            return
        if pending.kind == "page":
            service.finish_edit(*key)
            try:
                await service.start_page_redraw(pending.order_id, pending.page, "" if text in DASHES else text)
            except AppError as e:
                await message.answer(html.escape(e.message))
                return
            await message.answer(f"🖼 Перерисовываю страницу {pending.page}. Это около минуты, потом пришлю обе версии книги.")
            return
        if text in DASHES:
            service.finish_edit(*key)
            await message.answer("Хорошо, текст не меняю.")
            return
        await message.answer("✏️ Проверяю текст и собираю книгу заново…")
        try:
            await service.set_page_text(pending.order_id, pending.page, text)
        except ValidationError as e:                     # текст не прошёл проверку: ждём исправленный
            await message.answer(f"{html.escape(e.message)}\n\nПришлите исправленный текст ещё раз или «-», чтобы отменить.")
            return
        except AppError as e:
            service.finish_edit(*key)
            await message.answer(html.escape(e.message))
            return
        service.finish_edit(*key)

    @router.message(Command("help"), private)
    async def on_help(message: Message, webapp_url: str, runtime: "BotRuntime") -> None:
        service = runtime.service
        if service is None:
            await message.answer(NOT_READY)
        elif not service.access_state(_user_id(message))["granted"]:
            await _answer_closed(message, service)
        else:
            await message.answer(HELP, reply_markup=webapp_keyboard(webapp_url))

    @router.message(private)
    async def on_other(message: Message, webapp_url: str, runtime: "BotRuntime") -> None:
        service = runtime.service
        if service is None:
            await message.answer(NOT_READY)
        elif not service.access_state(_user_id(message))["granted"]:
            await _answer_closed(message, service)
        else:
            keyboard = webapp_keyboard(webapp_url)
            await message.answer(CLOSED_REMINDER if keyboard else NOT_READY, reply_markup=keyboard)

    return router


class TelegramNotifier:
    """Отправка книг и сообщений через Bot API."""

    def __init__(self, bot: Bot, admin_chat_id: int | None, webapp_url: str = "", orders_chat_id: int | None = None,
                 review_chat_id: int | None = None):
        self.bot = bot
        self.review_chat_id = review_chat_id
        self.admin_chat_id = admin_chat_id
        self.orders_chat_id = orders_chat_id if orders_chat_id is not None else admin_chat_id
        self.webapp_url = webapp_url

    @property
    def can_approve_requests(self) -> bool:
        """Заявку можно показать человеку с кнопками, только если есть хоть один чат (проверяющего, владельца или заказов)."""
        return bool(self._work_chats())

    @property
    def can_review_books(self) -> bool:
        """Книгу на проверку присылаем проверяющим (REVIEW_CHAT_ID и владельцу) вместе с двумя PDF; нет чатов, то в чат заказов."""
        return bool(self._work_chats())

    def _work_chats(self) -> list[int]:
        """Все чаты, куда может уйти проверка: проверяющий (REVIEW_CHAT_ID), владелец (ADMIN_CHAT_ID), затем группа заказов."""
        return [c for c in dict.fromkeys((self.review_chat_id, self.admin_chat_id, self.orders_chat_id)) if c is not None]

    async def _to_reviewers(self, what: str, send) -> None:
        """Шлёт всем проверяющим сразу (REVIEW_CHAT_ID и владельцу); если не дошло ни до кого, пробует группу заказов."""
        reviewers = [c for c in dict.fromkeys((self.review_chat_id, self.admin_chat_id)) if c is not None]
        fallback = [c for c in self._work_chats() if c not in reviewers]
        for group, last_resort in ((reviewers, False), (fallback, True)):
            reached = False
            for chat in group:
                try:
                    await send(chat)
                    reached = True
                except Exception as e:  # noqa: BLE001
                    log.warning("%s не отправлено в чат %s: %s", what, chat, type(e).__name__)
            if reached or last_resort:
                return

    async def notify_request(self, order_id: str, text: str) -> None:
        """Заявка клиента проверяющим (REVIEW_CHAT_ID и владельцу; не дошла — в чат заказов) с кнопками «Принять и начать» / «Отклонить»."""
        if not self._work_chats():
            log.warning("Ни одного чата для заявок не задано: заявка %s не отправлена, её видно только в базе", order_id)
            return
        # без разметки: текст родителей показываем как есть; сбой не страшен, заявка уже в базе и напоминание пришлёт её снова
        await self._to_reviewers(f"Заявка {order_id}", lambda chat: self.bot.send_message(
            chat, text[:4000], reply_markup=request_keyboard(order_id), parse_mode=None))

    async def notify_review(self, order_id: str, text: str) -> None:
        """Карточка готовой книги проверяющим (рядом с двумя PDF) с кнопками проверки."""
        if not self._work_chats():
            log.warning("ADMIN_CHAT_ID и чат заказов не заданы: книга %s ждёт проверки, но карточку отправить некуда", order_id)
            return
        await self._to_reviewers(f"Карточка проверки {order_id}", lambda chat: self.bot.send_message(
            chat, text[:4000], reply_markup=review_keyboard(order_id), parse_mode=None))

    async def notify_payment(self, order_id: str, receipt_path: Path, text: str) -> None:
        """Чек владельцу: фото и кнопки «Подтвердить» / «Отклонить» (и вход в админку)."""
        if self.admin_chat_id is None:
            log.warning("ADMIN_CHAT_ID не задан: чек по заказу %s виден только в админке", order_id)
            return
        rows = [[InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"pay:ok:{order_id}"),
                 InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pay:no:{order_id}")]]
        if webapp_ready(self.webapp_url):
            rows.append([InlineKeyboardButton(text="⚙️ Админка", web_app=WebAppInfo(url=admin_url(self.webapp_url)))])
        markup = InlineKeyboardMarkup(inline_keyboard=rows)
        try:
            await self.bot.send_photo(self.admin_chat_id, FSInputFile(receipt_path), caption=text[:1000],
                                      reply_markup=markup, parse_mode=None)
        except TelegramAPIError as e:
            log.warning("Чек владельцу не отправлен: %s", type(e).__name__)
            await self.notify_admin(text)

    async def notify_user(self, user_id: int, text: str) -> None:
        try:
            await self.bot.send_message(user_id, html.escape(text)[:4000], parse_mode=None)
        except (TelegramForbiddenError, TelegramAPIError, TelegramNetworkError, OSError) as e:
            log.info("Сообщение пользователю не отправлено: %s", type(e).__name__)

    async def send_print_offer(self, user_id: int, text: str, whatsapp_url: str | None) -> None:
        """Второе сообщение под книгой: цены и кнопка-ссылка «Заказать в WhatsApp» (если номер владельца задан)."""
        markup = None
        if whatsapp_url:
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=PRINT_BUTTON, url=whatsapp_url)]])
        try:
            await self.bot.send_message(user_id, text[:4000], reply_markup=markup, parse_mode=None)
        except (TelegramAPIError, TelegramNetworkError, OSError) as e:
            log.info("Предложение печатной версии не отправлено: %s", type(e).__name__)

    async def _send_document(self, chat_id: int, pdf_path: Path, filename: str, caption: str) -> None:
        document = FSInputFile(pdf_path, filename=filename)
        try:
            await self.bot.send_document(chat_id=chat_id, document=document, caption=caption[:1024])
        except TelegramRetryAfter as e:
            await asyncio.sleep(min(e.retry_after, 30))
            await self.bot.send_document(chat_id=chat_id, document=FSInputFile(pdf_path, filename=filename),
                                         caption=caption[:1024])

    async def send_book(self, user_id: int, pdf_path: Path, filename: str, caption: str) -> bool:
        try:
            await self._send_document(user_id, pdf_path, filename, caption)
            return True
        except TelegramForbiddenError:
            log.info("PDF не отправлен: пользователь не запускал бота или заблокировал его")
        except TelegramAPIError as e:
            log.warning("PDF не отправлен в чат: %s", e.message if hasattr(e, "message") else type(e).__name__)
        except (TelegramNetworkError, OSError):
            log.warning("PDF не отправлен: нет связи с Telegram")
        return False

    async def send_admin_book(self, pdf_path: Path, filename: str, caption: str) -> None:
        """PDF для проверки и копии книг: проверяющим (REVIEW_CHAT_ID и владельцу), не дошло — в чат заказов."""
        await self._to_reviewers("PDF", lambda chat: self._send_document(chat, pdf_path, filename, caption))

    async def notify_order(self, text: str) -> None:
        """Карточка заказа в чат заказов (ORDERS_CHAT_ID, может быть группой); не задан — в чат владельца."""
        if self.orders_chat_id is None:
            log.info("Чат заказов не задан, карточка не отправлена: %s", text[:200])
            return
        try:
            await self.bot.send_message(self.orders_chat_id, html.escape(text)[:4000], parse_mode=None)
        except Exception as e:  # noqa: BLE001 — карточка не критична: заказ уже принят
            log.warning("Карточка заказа не отправлена: %s", type(e).__name__)

    async def notify_admin(self, text: str) -> None:
        if self.admin_chat_id is None:
            log.info("ADMIN_CHAT_ID не задан, сообщение администратору не отправлено: %s", text[:200])
            return
        try:
            await self.bot.send_message(self.admin_chat_id, html.escape(text)[:4000], parse_mode=None)
        except Exception as e:  # noqa: BLE001
            log.warning("Сообщение администратору не отправлено: %s", type(e).__name__)


class BotRuntime:
    """Запускает бота в одном процессе с веб-сервером (long polling)."""

    def __init__(self, settings: Settings, bot_info: dict, bot: Bot | None = None):
        self.settings = settings
        self.bot_info = bot_info
        self.bot = bot or Bot(token=settings.telegram_bot_token,
                              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.notifier = TelegramNotifier(self.bot, settings.admin_chat_id, settings.webapp_url, settings.orders_chat_id,
                                        settings.review_chat_id)
        self.service = None                  # сервис заказов подключается в main.py
        self.dp = Dispatcher()
        self.dp.include_router(build_router())
        self.dp["webapp_url"] = settings.webapp_url
        self.dp["runtime"] = self

    async def setup_menu_button(self) -> None:
        url = self.settings.webapp_url
        if not url:
            log.warning("WEBAPP_URL не задан: кнопка меню не установлена. Заполните его в .env (см. README).")
            return
        if not webapp_ready(url):
            log.warning("WEBAPP_URL должен начинаться с https:// — Telegram не принимает другие адреса. "
                        "Кнопка меню не установлена.")
            return
        await self.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text=BUTTON_TEXT, web_app=WebAppInfo(url=url)))
        log.info("Кнопка меню «%s» установлена", BUTTON_TEXT)

    async def setup_profile(self, *, include_name: bool = False) -> None:
        """Описание, «о боте» и список команд. Имя меняется только по просьбе (у Telegram есть лимит на смену имени)."""
        if include_name:
            await self.bot.set_my_name(name=BOT_NAME)
        await self.bot.set_my_description(description=DESCRIPTION)
        await self.bot.set_my_short_description(short_description=SHORT_DESCRIPTION)
        await self.bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
        admins = [x for x in (self.settings.admin_chat_id, *self.settings.extra_admin_ids) if x is not None]
        for admin in admins:           # команда /admin видна только администраторам
            try:
                await self.bot.set_my_commands(PUBLIC_COMMANDS + ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin))
            except TelegramAPIError as e:
                log.warning("Не удалось добавить команды администратору: %s", e)

    async def run(self) -> None:
        try:
            me = await self.bot.get_me()
        except TelegramUnauthorizedError:
            log.error("Telegram не принял TELEGRAM_BOT_TOKEN. Проверьте строку в .env: токен выдаёт @BotFather. "
                      "Бот выключен, сайт работает.")
            return
        except (TelegramNetworkError, OSError):
            log.error("Нет связи с Telegram. Проверьте интернет. Бот выключен, сайт работает.")
            return
        except TelegramAPIError as e:
            log.error("Telegram ответил ошибкой при запуске бота: %s. Бот выключен, сайт работает.", e)
            return
        self.bot_info["username"] = me.username
        log.info("Бот @%s запущен", me.username)
        try:
            await self.bot.delete_webhook(drop_pending_updates=False)   # webhook мешает long polling
            await self.setup_menu_button()
            await self.setup_profile()
        except TelegramAPIError as e:
            log.warning("Не удалось настроить бота: %s", e)
        try:
            await self.dp.start_polling(self.bot, handle_signals=False, allowed_updates=["message", "callback_query"])
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Бот остановился из-за ошибки; сайт продолжает работать")

    async def close(self) -> None:
        try:
            await self.dp.stop_polling()
        except Exception:  # noqa: BLE001
            pass
        await self.bot.session.close()
