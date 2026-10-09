"""Telegram-бот (aiogram 3): приветствие, кнопка Mini App, /id, отправка готовой книги в чат."""
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
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, BotCommandScopeChat, BotCommandScopeDefault, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, MenuButtonWebApp, Message, WebAppInfo, CallbackQuery)

from .config import Settings
from .errors import AppError

log = logging.getLogger(__name__)

BUTTON_TEXT = "✨ Создать сказку"
WELCOME = (
    "✨ <b>Привет! Я — сказочник.</b>\n\n"
    "Я придумываю <b>персональные сказки</b>, где главный герой — ваш малыш 👶\n\n"
    "📝 Вы отвечаете на несколько вопросов — 1–2 минуты\n"
    "🎨 Я пишу сказку и рисую иллюстрации — 5–15 минут\n"
    "📖 Присылаю красивую PDF-книгу прямо сюда\n\n"
    "Сказки добрые, с поучительным смыслом — на русском или кыргызском, "
    "с горами, джайлоо и Иссык-Кулем 🏔️\n\n"
    "Нажмите кнопку ниже, и начнём 👇"
)
NOT_READY = "🌙 Приложение пока не подключено. Загляните сюда чуть позже — мы скоро откроемся!"
HELP = (
    "❓ <b>Как это работает</b>\n\n"
    "1️⃣ Нажмите кнопку «✨ Создать сказку» — откроется приложение.\n"
    "2️⃣ Ответьте на вопросы о малыше: имя, возраст, любимые занятия, характер.\n"
    "3️⃣ Подождите 5–15 минут — приложение можно закрыть.\n"
    "4️⃣ Готовую книгу в PDF я пришлю сюда 💌\n\n"
    "Если кнопки не видно, отправьте /start."
)

# Оформление профиля бота (лимиты Telegram: описание до 512, «о боте» до 120, имя до 64 символов)
BOT_NAME = "Персональная сказка"
SHORT_DESCRIPTION = "✨ Персональные сказки с вашим малышом в главной роли. PDF-книга с иллюстрациями за 5–15 минут"
DESCRIPTION = (
    "✨ Персональные сказки, где главный герой — ваш малыш!\n\n"
    "📝 Ответьте на несколько вопросов — всего 1–2 минуты\n"
    "🎨 Мы напишем сказку и нарисуем иллюстрации\n"
    "📖 Через 5–15 минут пришлём красивую PDF-книгу прямо сюда\n\n"
    "Добрые истории с поучительным смыслом, на русском или кыргызском 🏔️\n\n"
    "Нажмите «Запустить», чтобы начать 👇"
)
PUBLIC_COMMANDS = [
    BotCommand(command="start", description="✨ Создать сказку"),
    BotCommand(command="help", description="❓ Как это работает"),
]
ADMIN_COMMANDS = [
    BotCommand(command="admin", description="⚙️ Админка: оплаты и QR-код"),
    BotCommand(command="id", description="🆔 Узнать свой ID (для владельца)"),
]


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


def build_router() -> Router:
    router = Router()

    @router.message(CommandStart())
    async def on_start(message: Message, webapp_url: str) -> None:
        keyboard = webapp_keyboard(webapp_url)
        await message.answer(WELCOME if keyboard else NOT_READY, reply_markup=keyboard)

    @router.message(Command("id"))
    async def on_id(message: Message) -> None:
        await message.answer(
            f"🆔 Ваш ID: <code>{message.chat.id}</code>\n\n"
            "Если вы владелец бота, впишите это число в строку ADMIN_CHAT_ID в файле .env — "
            "и копии книг и отзывы будут приходить сюда 💌"
        )

    @router.message(Command("admin"))
    async def on_admin(message: Message, webapp_url: str, runtime: "BotRuntime") -> None:
        if runtime.settings.admin_chat_id is None or message.chat.id != runtime.settings.admin_chat_id:
            await message.answer("Эта команда только для владельца бота.")
            return
        if not webapp_ready(webapp_url):
            await message.answer(NOT_READY)
            return
        await message.answer(
            "⚙️ <b>Админка</b>: чеки на подтверждение, QR-код, цена и текст для покупателей.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⚙️ Открыть админку", web_app=WebAppInfo(url=admin_url(webapp_url)))]]))

    @router.callback_query(F.data.startswith("pay:"))
    async def on_payment_button(call: CallbackQuery, runtime: "BotRuntime") -> None:
        admin = runtime.settings.admin_chat_id
        if admin is None or call.from_user.id != admin:
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
                note = "✅ Оплата подтверждена, сказка создаётся"
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

    @router.message(Command("help"))
    async def on_help(message: Message, webapp_url: str) -> None:
        await message.answer(HELP, reply_markup=webapp_keyboard(webapp_url))

    @router.message()
    async def on_other(message: Message, webapp_url: str) -> None:
        keyboard = webapp_keyboard(webapp_url)
        await message.answer(
            "Сказки создаются в приложении — нажмите кнопку ниже 👇" if keyboard else NOT_READY,
            reply_markup=keyboard,
        )

    return router


class TelegramNotifier:
    """Отправка книг и сообщений через Bot API."""

    def __init__(self, bot: Bot, admin_chat_id: int | None, webapp_url: str = ""):
        self.bot = bot
        self.admin_chat_id = admin_chat_id
        self.webapp_url = webapp_url

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
        if self.admin_chat_id is None:
            return
        try:
            await self._send_document(self.admin_chat_id, pdf_path, filename, caption)
        except Exception as e:  # noqa: BLE001
            log.warning("Копия книги администратору не отправлена: %s", type(e).__name__)

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
        self.notifier = TelegramNotifier(self.bot, settings.admin_chat_id, settings.webapp_url)
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
        admin = self.settings.admin_chat_id
        if admin is not None:           # команда /id видна только владельцу
            try:
                await self.bot.set_my_commands(PUBLIC_COMMANDS + ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin))
            except TelegramAPIError as e:
                log.warning("Не удалось добавить команды для владельца: %s", e)

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
