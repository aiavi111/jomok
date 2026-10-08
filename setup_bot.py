"""Оформляет бота в Telegram: описание, «о боте», команды, кнопка меню (и по желанию — имя).

    python setup_bot.py           # описание, «о боте», команды и кнопка меню
    python setup_bot.py --name    # ещё и имя бота (Telegram ограничивает, как часто можно менять имя)

Аватарку (логотип) через API поставить нельзя: загрузите её в @BotFather командой /setuserpic.
Те же настройки (кроме имени) бот ставит сам при каждом запуске сервера.
"""
from __future__ import annotations

import asyncio
import sys

from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramUnauthorizedError

from app.bot import BOT_NAME, DESCRIPTION, SHORT_DESCRIPTION, BotRuntime
from app.config import ConfigError, Settings
from app.logging_setup import redact


async def main(with_name: bool) -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as e:
        print(f"Ошибка настройки: {e}")
        return 2
    redact.add(settings.secrets)
    if not settings.telegram_bot_token:
        print("В .env не заполнена строка TELEGRAM_BOT_TOKEN. Токен выдаёт @BotFather.")
        return 2
    runtime = BotRuntime(settings, {})
    try:
        me = await runtime.bot.get_me()
        print(f"Бот @{me.username}")
        await runtime.setup_profile(include_name=with_name)
        print(f"  ✔ описание ({len(DESCRIPTION)} из 512 символов)")
        print(f"  ✔ «о боте» ({len(SHORT_DESCRIPTION)} из 120 символов)")
        print("  ✔ команды: /start, /help" + (" (и /id только в вашем чате)" if settings.admin_chat_id else ""))
        if with_name:
            print(f"  ✔ имя: {BOT_NAME}")
        await runtime.setup_menu_button()
        print("Готово. Логотип загрузите в @BotFather: /setuserpic → ваш бот → картинка.")
        return 0
    except TelegramUnauthorizedError:
        print("Telegram не принял токен. Проверьте строку TELEGRAM_BOT_TOKEN в .env.")
    except TelegramNetworkError:
        print("Нет связи с Telegram. Проверьте интернет и повторите.")
    except TelegramAPIError as e:
        print(f"Telegram ответил ошибкой: {redact(str(e))}")
    finally:
        await runtime.bot.session.close()
    return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main("--name" in sys.argv[1:])))
