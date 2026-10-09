"""Точка входа: веб-сервер (Mini App + API) и бот работают в одном процессе."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from aiohttp import web

from .config import ConfigError, Settings
from .db import Database
from .links import load_or_create_secret
from .logging_setup import setup_logging
from .notify import NullNotifier
from .payments import make_payment_provider
from .providers import make_image_provider, make_text_provider
from .service import CLEANUP_PERIOD, OrderService
from .web import create_app

log = logging.getLogger("skazka")

DEV_WARNING = """
############################################################
#  ВНИМАНИЕ: включён DEV_MODE=1.                            #
#  Подпись Telegram НЕ проверяется: любой может выдать себя  #
#  за любого пользователя. Только для теста на своём        #
#  компьютере! Для работы с людьми поставьте DEV_MODE=0.    #
############################################################"""


async def cleanup_loop(service: OrderService) -> None:
    """Раз в час (CLEANUP_PERIOD): фото старше суток, файлы старых заказов, неоплаченные заказы."""
    while True:
        try:
            await asyncio.to_thread(service.cleanup)
        except Exception:  # noqa: BLE001
            log.exception("Ошибка при уборке старых файлов")
        await asyncio.sleep(CLEANUP_PERIOD)


async def amain() -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as e:
        print(f"Ошибка настройки: {e}", file=sys.stderr)
        return 2
    setup_logging(settings.secrets)
    if settings.dev_mode:
        print(DEV_WARNING, file=sys.stderr)
        log.warning("DEV_MODE=1: проверка подписи Telegram отключена")

    try:
        text_provider = make_text_provider(settings)
        image_provider = make_image_provider(settings)
    except ConfigError as e:
        log.error("Ошибка настройки: %s", e)
        return 2

    db = Database(settings.data_dir / "skazka.sqlite3")
    secret = load_or_create_secret(settings.data_dir)
    bot_info: dict = {}

    runtime = None
    if settings.telegram_bot_token:
        from .bot import BotRuntime
        runtime = BotRuntime(settings, bot_info)
        notifier = runtime.notifier
    else:
        log.warning("TELEGRAM_BOT_TOKEN не задан: бот выключен, PDF в чат не отправляется.")
        notifier = NullNotifier()

    service = OrderService(settings, db, text_provider, image_provider, notifier,
                           make_payment_provider(settings), secret)
    service.recover()
    service.resume_paid()
    if runtime:
        runtime.service = service            # кнопки «Подтвердить/Отклонить» в чате владельца
    await asyncio.to_thread(service.cleanup)

    app = create_app(settings, db, service, bot_info)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, settings.host, settings.port).start()
    except OSError:
        log.error("Порт %s занят: возможно, сервер уже запущен. Закройте его или поставьте другой PORT в .env.",
                  settings.port)
        await runner.cleanup()
        return 2

    log.info("Сервер запущен: http://localhost:%s  (текст: %s, картинки: %s)",
             settings.port, settings.text_provider, settings.image_provider)
    if service.closed():
        log.info("Бот закрыт: книги создают только по личным ссылкам (ссылки делает владелец в админке) и сам владелец.")
    else:
        log.info("Бот открыт для всех (закрытый режим выключен в админке).")
    if settings.uses_mock:
        log.info("Работают заглушки (mock): ключи не нужны, картинки нарисованы Pillow.")
    if not settings.dev_mode:
        log.info("Открывайте Mini App из Telegram. Для проверки в обычном браузере поставьте DEV_MODE=1 в .env.")

    tasks = [asyncio.create_task(cleanup_loop(service), name="cleanup")]
    if runtime:
        tasks.append(asyncio.create_task(runtime.run(), name="bot"))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):      # Windows
            pass
    try:
        await stop.wait()
    finally:
        log.info("Останавливаюсь…")
        logging.getLogger("aiogram").setLevel(logging.CRITICAL)      # при выключении aiogram шумит про оборванный запрос
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if runtime:
            await runtime.close()
        await service.shutdown()
        await runner.cleanup()
        db.close()
    return 0


def main() -> None:
    try:
        sys.exit(asyncio.run(amain()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
