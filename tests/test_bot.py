"""Бот: приветствие с кнопкой Mini App, /id, кнопка меню, отправка PDF — на поддельной сессии, без сети."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError,
                                TelegramUnauthorizedError)
from aiogram.methods import (GetMe, SendDocument, SendMessage, SetChatMenuButton, SetMyCommands, SetMyDescription,
                             SetMyName, SetMyShortDescription, TelegramMethod)
from aiogram.types import Chat, Message, Update, User

from app.bot import (ADMIN_COMMANDS, BOT_NAME, BUTTON_TEXT, CLOSED_REMINDER, DESCRIPTION, HELP, INVALID_INVITE, NOT_READY,
                     OWNER_INVITE, PAGES_TEXT, PUBLIC_COMMANDS, SHORT_DESCRIPTION, WELCOME, BotRuntime, TelegramNotifier, build_router,
                     closed_text, granted_text, webapp_keyboard)
from app.service import CLOSED_TEXT

from .conftest import ADMIN_ID, BOT_TOKEN, make_service, make_settings

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


def make_dp(url: str, service=None) -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(build_router())
    dp["webapp_url"] = url
    dp["runtime"] = SimpleNamespace(service=service)       # так бот видит сервис, как в BotRuntime
    return dp


@pytest.fixture
def service(tmp_path):
    """Закрытый бот; у человека 555 (он пишет в тестах) есть одна книга."""
    svc = make_service(tmp_path)
    svc.db.add_credits(555, 1)
    yield svc
    svc.db.close()


def sent_messages(session: FakeSession) -> list[SendMessage]:
    return [c for c in session.calls if isinstance(c, SendMessage)]


async def test_start_sends_welcome_with_web_app_button(service):
    session = FakeSession()
    bot = make_bot(session)
    await make_dp(WEBAPP, service).feed_update(bot, command_update(bot, "/start"))
    (message,) = sent_messages(session)
    assert "персональные сказки" in message.text and "Bala story bot" in message.text and PAGES_TEXT in message.text
    button = message.reply_markup.inline_keyboard[0][0]
    assert button.text == BUTTON_TEXT and "Создать сказку" in button.text
    assert button.web_app.url == WEBAPP and button.url is None


@pytest.mark.parametrize("url", ["", "http://insecure.example.test"])
async def test_start_without_https_webapp_url_explains_and_has_no_button(url, service):
    session = FakeSession()
    bot = make_bot(session)
    await make_dp(url, service).feed_update(bot, command_update(bot, "/start"))
    (message,) = sent_messages(session)
    assert message.text == NOT_READY and message.reply_markup is None
    assert webapp_keyboard(url) is None


async def test_id_command_answers_with_chat_number(service):
    """/id работает для любого человека, даже без доступа: по нему владелец узнаёт свой номер."""
    session = FakeSession()
    bot = make_bot(session)
    await make_dp(WEBAPP, service).feed_update(bot, command_update(bot, "/id", chat_id=987654321))
    (message,) = sent_messages(session)
    assert "<code>987654321</code>" in message.text and "ADMIN_CHAT_ID" in message.text


async def test_any_other_text_gets_the_button_again(service):
    session = FakeSession()
    bot = make_bot(session)
    await make_dp(WEBAPP, service).feed_update(bot, command_update(bot, "привет"))
    (message,) = sent_messages(session)
    assert message.text == CLOSED_REMINDER
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
    for command in PUBLIC_COMMANDS + ADMIN_COMMANDS:
        assert 3 <= len(command.description) <= 256 and command.command.islower()
    assert [c.command for c in PUBLIC_COMMANDS] == ["start", "help"] and [c.command for c in ADMIN_COMMANDS] == ["admin", "id"]
    assert "<b>" in WELCOME and WELCOME.count("<b>") == WELCOME.count("</b>")


def test_bot_name_and_texts_describe_personal_links_and_page_count_of_the_pdf():
    from app.story import PAGES
    assert BOT_NAME == "Bala story bot" and PAGES_TEXT.startswith(f"{PAGES} стран")
    for text in (WELCOME, HELP, DESCRIPTION, SHORT_DESCRIPTION):
        assert PAGES_TEXT in text and "PDF" in text         # число страниц в тексте всегда равно story.PAGES
    for text in (HELP, DESCRIPTION):
        assert "личной ссылк" in text                                  # книга создаётся после получения личной ссылки
    assert "Bala story bot" in WELCOME and "Bala story bot" in DESCRIPTION
    assert "Персональная сказка" not in DESCRIPTION + WELCOME + HELP     # старое имя бота нигде не осталось


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
    assert scopes["BotCommandScopeChat"] == ["start", "help", "admin", "id"]           # /admin и /id — только владельцу


async def test_setup_profile_with_name_and_without_admin():
    session = FakeSession()
    runtime = BotRuntime(make_settings(Path("."), admin_chat_id=None), {}, bot=make_bot(session))
    await runtime.setup_profile(include_name=True)
    assert [c.name for c in session.calls if isinstance(c, SetMyName)] == [BOT_NAME]
    assert not any(type(c.scope).__name__ == "BotCommandScopeChat" for c in session.calls if isinstance(c, SetMyCommands))


# ----------------------------------------------------------------------- закрытый бот и личные ссылки
def inline_buttons(message: SendMessage) -> list:
    return [b for row in (message.reply_markup.inline_keyboard if message.reply_markup else []) for b in row]


async def feed(service, text: str, *, chat_id: int = 555, url: str = WEBAPP) -> list[SendMessage]:
    session = FakeSession()
    bot = make_bot(session)
    await make_dp(url, service).feed_update(bot, command_update(bot, text, chat_id=chat_id))
    return sent_messages(session)


@pytest.mark.parametrize("text", ["/start", "/help", "привет", "/start abc"])
async def test_user_without_access_gets_closed_text_and_no_mini_app_button(service, text):
    (message,) = await feed(service, text, chat_id=999)
    assert message.text == CLOSED_TEXT == closed_text("")
    assert "личным ссылкам" in message.text and "WhatsApp" in message.text
    assert message.reply_markup is None


async def test_closed_text_has_whatsapp_link_when_the_number_is_set(service):
    service.desk.update({"whatsapp": "+996 555 123 456"})
    (message,) = await feed(service, "/start", chat_id=999)
    assert message.text == closed_text("996555123456") and message.text.startswith(CLOSED_TEXT[:-1])
    assert 'href="https://wa.me/996555123456?text=' in message.text and ">+996555123456</a>" in message.text
    assert message.reply_markup is None


async def test_invite_link_gives_access_and_shows_the_mini_app_button(service):
    token = service.create_invite({"credits": 2, "note": "Мама Айдара"})["token"]
    (message,) = await feed(service, f"/start inv_{token}", chat_id=999)
    assert message.text == granted_text(2) and "Доступ открыт: у вас 2 книги" in message.text
    (button,) = inline_buttons(message)
    assert button.text == BUTTON_TEXT and button.web_app.url == WEBAPP
    assert service.db.get_credits(999) == 2
    assert service.access_state(999)["granted"] is True
    # человек теперь видит приложение и в обычном /start
    (again,) = await feed(service, "/start", chat_id=999)
    assert again.text == WELCOME and inline_buttons(again)[0].web_app.url == WEBAPP
    # владельцу пришло сообщение о том, что ссылка использована, с заметкой
    assert any("Ссылка доступа использована" in t and "2 книги" in t and "Мама Айдара" in t
               for t in service.notifier.admin_texts)


@pytest.mark.parametrize("credits, word", [(1, "1 книга"), (2, "2 книги"), (5, "5 книг"), (21, "21 книга")])
def test_granted_text_uses_correct_russian_plural(credits, word):
    assert f"Доступ открыт: у вас {word}" in granted_text(credits)


async def test_invite_link_works_only_once_and_invalid_tokens_are_refused(service):
    token = service.create_invite({"credits": 1})["token"]
    (first,) = await feed(service, f"/start inv_{token}", chat_id=901)
    assert "Доступ открыт" in first.text
    for who, arg in ((902, f"inv_{token}"), (902, "inv_doesNotExist1"), (902, "inv_"), (902, "inv_" + "x" * 200)):
        (message,) = await feed(service, f"/start {arg}", chat_id=who)
        assert message.text.startswith(INVALID_INVITE) and message.reply_markup is None
    assert service.db.get_credits(902) == 0 and service.access_state(902)["granted"] is False
    assert service.db.get_credits(901) == 1                              # второй переход ничего не добавил


async def test_invalid_invite_message_includes_whatsapp_link_when_set(service):
    service.desk.update({"whatsapp": "996555123456"})
    (message,) = await feed(service, "/start inv_nope12345", chat_id=902)
    assert message.text.startswith(INVALID_INVITE) and 'href="https://wa.me/996555123456' in message.text


async def test_second_link_adds_books_to_the_account(service):
    a, b = service.create_invite({"credits": 1})["token"], service.create_invite({"credits": 3})["token"]
    await feed(service, f"/start inv_{a}", chat_id=903)
    await feed(service, f"/start inv_{b}", chat_id=903)
    assert service.db.get_credits(903) == 4


async def test_owner_always_sees_the_app_and_does_not_burn_a_link(service):
    (message,) = await feed(service, "/start", chat_id=ADMIN_ID)
    assert message.text == WELCOME and inline_buttons(message)[0].web_app.url == WEBAPP
    token = service.create_invite({"credits": 1})["token"]
    (checked,) = await feed(service, f"/start inv_{token}", chat_id=ADMIN_ID)
    assert checked.text == OWNER_INVITE and inline_buttons(checked)
    assert service.invite_available(token) is True and service.db.get_credits(ADMIN_ID) == 0   # ссылку можно отправить клиенту
    (client,) = await feed(service, f"/start inv_{token}", chat_id=904)
    assert "Доступ открыт" in client.text


async def test_open_mode_lets_everybody_in(service):
    service.set_closed(False)
    (message,) = await feed(service, "/start", chat_id=999)
    assert message.text == WELCOME and inline_buttons(message)


async def test_invite_without_https_url_still_grants_access_and_explains(service):
    token = service.create_invite({"credits": 1})["token"]
    (message,) = await feed(service, f"/start inv_{token}", chat_id=905, url="")
    assert "Доступ открыт" in message.text and NOT_READY in message.text and message.reply_markup is None
    assert service.db.get_credits(905) == 1


async def test_bot_without_connected_service_says_it_is_not_ready():
    session = FakeSession()
    bot = make_bot(session)
    await make_dp(WEBAPP, None).feed_update(bot, command_update(bot, "/start"))
    (message,) = sent_messages(session)
    assert message.text == NOT_READY


async def test_print_offer_has_whatsapp_url_button_only_when_link_is_given():
    session = FakeSession()
    notifier = TelegramNotifier(make_bot(session), admin_chat_id=777)
    await notifier.send_print_offer(42, "Хотите заказать печатную версию? 590 сом: PDF, 1 290 сом: мягкая фотокнига",
                                    "https://wa.me/996555123456?text=x")
    await notifier.send_print_offer(43, "Хотите заказать печатную версию?", None)
    with_button, without = sent_messages(session)
    assert with_button.chat_id == 42 and with_button.text.startswith("Хотите заказать печатную версию?")
    (button,) = inline_buttons(with_button)
    assert button.text == "Заказать в WhatsApp" and button.url == "https://wa.me/996555123456?text=x" and button.web_app is None
    assert without.chat_id == 43 and without.reply_markup is None


async def test_print_offer_failure_never_raises():
    session = FakeSession(raise_on={SendMessage: TelegramForbiddenError})
    await TelegramNotifier(make_bot(session), admin_chat_id=777).send_print_offer(42, "текст", "https://wa.me/1")
