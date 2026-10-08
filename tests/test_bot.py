"""Бот: приветствие с кнопкой Mini App, /id, кнопка меню, отправка PDF — на поддельной сессии, без сети."""
from datetime import datetime
from pathlib import Path

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError,
                                TelegramUnauthorizedError)
from aiogram.methods import (GetMe, SendDocument, SendMessage, SetChatMenuButton, SetMyCommands, SetMyDescription,
                             SetMyName, SetMyShortDescription, TelegramMethod)
from aiogram.types import Chat, Message, Update, User

from app.bot import (ADMIN_COMMAND, BOT_NAME, BUTTON_TEXT, DESCRIPTION, HELP, NOT_READY, PUBLIC_COMMANDS, SHORT_DESCRIPTION,
                     WELCOME, BotRuntime, TelegramNotifier, build_router, webapp_keyboard)

from .conftest import BOT_TOKEN, make_settings

WEBAPP = "https://tale.example.test"


class FakeSession(BaseSession):
    def __init__(self, raise_on: dict | None = None):
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self.raise_on = raise_on or {}

    async def close(self):
        return None

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        error = self.raise_on.get(type(method))
        if error:
            raise error(method=method, message="тест") if isinstance(error, type) else error
        if isinstance(method, (SendMessage, SendDocument)):
            return Message(message_id=1, date=datetime.now(), chat=Chat(id=int(method.chat_id), type="private"),
                           text=getattr(method, "text", None))
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="Сказки", username="skazka_test_bot")
        return True

    async def stream_content(self, *a, **k):  # pragma: no cover
        yield b""


def make_bot(session: FakeSession) -> Bot:
    return Bot(token=BOT_TOKEN, session=session)


def command_update(bot: Bot, text: str, chat_id: int = 555) -> Update:
    """Собираем обновление из словаря, как его присылает Telegram (так вложенные объекты привязываются к боту)."""
    message = {
        "message_id": 1, "date": int(datetime.now().timestamp()),
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": chat_id, "is_bot": False, "first_name": "Мама"},
        "text": text,
    }
    if text.startswith("/"):
        message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    return Update.model_validate({"update_id": 1, "message": message}, context={"bot": bot})


def make_dp(url: str) -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(build_router())
    dp["webapp_url"] = url
    return dp


def sent_messages(session: FakeSession) -> list[SendMessage]:
    return [c for c in session.calls if isinstance(c, SendMessage)]


async def test_start_sends_welcome_with_web_app_button():
    session = FakeSession()
    bot = make_bot(session)
    await make_dp(WEBAPP).feed_update(bot, command_update(bot, "/start"))
    (message,) = sent_messages(session)
    assert "персональные сказки" in message.text
    button = message.reply_markup.inline_keyboard[0][0]
    assert button.text == BUTTON_TEXT and "Создать сказку" in button.text
    assert button.web_app.url == WEBAPP and button.url is None


@pytest.mark.parametrize("url", ["", "http://insecure.example.test"])
async def test_start_without_https_webapp_url_explains_and_has_no_button(url):
    session = FakeSession()
    bot = make_bot(session)
    await make_dp(url).feed_update(bot, command_update(bot, "/start"))
    (message,) = sent_messages(session)
    assert message.text == NOT_READY and message.reply_markup is None
    assert webapp_keyboard(url) is None


async def test_id_command_answers_with_chat_number():
    session = FakeSession()
    bot = make_bot(session)
    await make_dp(WEBAPP).feed_update(bot, command_update(bot, "/id", chat_id=987654321))
    (message,) = sent_messages(session)
    assert "<code>987654321</code>" in message.text and "ADMIN_CHAT_ID" in message.text


async def test_any_other_text_gets_the_button_again():
    session = FakeSession()
    bot = make_bot(session)
    await make_dp(WEBAPP).feed_update(bot, command_update(bot, "привет"))
    (message,) = sent_messages(session)
    assert message.reply_markup.inline_keyboard[0][0].web_app.url == WEBAPP


async def test_menu_button_is_set_to_same_web_app_url():
    session = FakeSession()
    runtime = BotRuntime(make_settings(Path("."), webapp_url=WEBAPP), {}, bot=make_bot(session))
    await runtime.setup_menu_button()
    (call,) = [c for c in session.calls if isinstance(c, SetChatMenuButton)]
    assert call.menu_button.type == "web_app" and call.menu_button.web_app.url == WEBAPP
    assert call.menu_button.text == BUTTON_TEXT


@pytest.mark.parametrize("url", ["", "http://insecure.example.test"])
async def test_menu_button_is_skipped_without_https_url(url):
    session = FakeSession()
    runtime = BotRuntime(make_settings(Path("."), webapp_url=url), {}, bot=make_bot(session))
    await runtime.setup_menu_button()
    assert not [c for c in session.calls if isinstance(c, SetChatMenuButton)]


async def test_invalid_token_stops_bot_politely_without_crashing_the_site():
    session = FakeSession(raise_on={GetMe: TelegramUnauthorizedError})
    info: dict = {}
    runtime = BotRuntime(make_settings(Path(".")), info, bot=make_bot(session))
    await runtime.run()            # не бросает исключение
    assert "username" not in info


async def test_valid_token_registers_username_for_the_mini_app(monkeypatch):
    session = FakeSession()
    info: dict = {}
    runtime = BotRuntime(make_settings(Path("."), webapp_url=WEBAPP), info, bot=make_bot(session))

    async def no_polling(*a, **k):
        return None
    monkeypatch.setattr(runtime.dp, "start_polling", no_polling)
    await runtime.run()
    assert info["username"] == "skazka_test_bot"
    assert any(isinstance(c, SetChatMenuButton) for c in session.calls)


# ----------------------------------------------------------------------- отправка PDF
@pytest.fixture
def pdf(tmp_path) -> Path:
    path = tmp_path / "book.pdf"
    path.write_bytes(b"%PDF-1.4 test")
    return path


async def test_book_is_sent_to_user_chat_with_user_id_as_chat_id(pdf):
    session = FakeSession()
    notifier = TelegramNotifier(make_bot(session), admin_chat_id=777)
    assert await notifier.send_book(42, pdf, "Сказка.pdf", "Готово!") is True
    (call,) = [c for c in session.calls if isinstance(c, SendDocument)]
    assert call.chat_id == 42 and call.document.filename == "Сказка.pdf" and call.caption == "Готово!"
    await notifier.send_admin_book(pdf, "Сказка.pdf", "Копия")
    admin_call = [c for c in session.calls if isinstance(c, SendDocument)][-1]
    assert admin_call.chat_id == 777


@pytest.mark.parametrize("error", [TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError])
async def test_failed_delivery_returns_false_instead_of_raising(pdf, error):
    session = FakeSession(raise_on={SendDocument: error})
    notifier = TelegramNotifier(make_bot(session), admin_chat_id=None)
    assert await notifier.send_book(42, pdf, "a.pdf", "x") is False


async def test_admin_messages_are_skipped_without_admin_id_and_escaped_with_it(pdf):
    session = FakeSession()
    quiet = TelegramNotifier(make_bot(session), admin_chat_id=None)
    await quiet.notify_admin("текст")
    await quiet.send_admin_book(pdf, "a.pdf", "c")
    assert session.calls == []
    loud = TelegramNotifier(make_bot(session), admin_chat_id=777)
    await loud.notify_admin("Ошибка <b>тест</b> & ещё")
    (message,) = sent_messages(session)
    assert message.chat_id == 777 and "&lt;b&gt;" in message.text and message.parse_mode is None


async def test_admin_notification_failure_never_raises():
    session = FakeSession(raise_on={SendMessage: TelegramForbiddenError})
    await TelegramNotifier(make_bot(session), admin_chat_id=777).notify_admin("x")


# ----------------------------------------------------------------------- оформление бота
def test_profile_texts_fit_telegram_limits_and_are_lively():
    assert len(DESCRIPTION) <= 512 and len(SHORT_DESCRIPTION) <= 120 and len(BOT_NAME) <= 64
    for text in (WELCOME, HELP, DESCRIPTION, SHORT_DESCRIPTION):
        assert any(ord(ch) > 0x2600 for ch in text), "в тексте нет эмодзи"
    for command in PUBLIC_COMMANDS + [ADMIN_COMMAND]:
        assert 3 <= len(command.description) <= 256 and command.command.islower()
    assert [c.command for c in PUBLIC_COMMANDS] == ["start", "help"] and ADMIN_COMMAND.command == "id"
    assert "<b>" in WELCOME and WELCOME.count("<b>") == WELCOME.count("</b>")


async def test_setup_profile_sets_description_about_and_commands_but_not_name_by_default():
    session = FakeSession()
    runtime = BotRuntime(make_settings(Path("."), admin_chat_id=777), {}, bot=make_bot(session))
    await runtime.setup_profile()
    kinds = [type(c) for c in session.calls]
    assert SetMyDescription in kinds and SetMyShortDescription in kinds and SetMyName not in kinds
    assert [c.description for c in session.calls if isinstance(c, SetMyDescription)] == [DESCRIPTION]
    assert [c.short_description for c in session.calls if isinstance(c, SetMyShortDescription)] == [SHORT_DESCRIPTION]
    scopes = {type(c.scope).__name__: [x.command for x in c.commands] for c in session.calls if isinstance(c, SetMyCommands)}
    assert scopes["BotCommandScopeDefault"] == ["start", "help"]                       # всем — без /id
    assert scopes["BotCommandScopeChat"] == ["start", "help", "id"]                    # /id — только владельцу


async def test_setup_profile_with_name_and_without_admin():
    session = FakeSession()
    runtime = BotRuntime(make_settings(Path("."), admin_chat_id=None), {}, bot=make_bot(session))
    await runtime.setup_profile(include_name=True)
    assert [c.name for c in session.calls if isinstance(c, SetMyName)] == [BOT_NAME]
    assert not any(type(c.scope).__name__ == "BotCommandScopeChat" for c in session.calls if isinstance(c, SetMyCommands))
