"""Уведомления: отправка книги в чат пользователя и сообщения администратору.

Настоящая реализация (через Telegram) — в app/bot.py; здесь интерфейс и «пустая» версия,
которая работает без бота (режим заглушек и тесты).

Дополнительные методы необязательны, сервис вызывает их через getattr и без них просто пропускает шаг:
  notify_payment(order_id, receipt_path, text) — чек владельцу с кнопками;
  notify_user(user_id, text)                   — сообщение человеку;
  notify_order(text)                           — карточка заказа (новый, готов) в чат заказов (ORDERS_CHAT_ID, иначе владельцу);
  send_print_offer(user_id, text, whatsapp_url) — предложение печатной версии после книги (кнопка «Заказать в WhatsApp»).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


class Notifier(Protocol):
    async def send_book(self, user_id: int, pdf_path: Path, filename: str, caption: str) -> bool:
        """Отправляет PDF в чат пользователя. False — не получилось (пользователь не запускал бота)."""

    async def send_admin_book(self, pdf_path: Path, filename: str, caption: str) -> None:
        """Копия книги администратору (если задан ADMIN_CHAT_ID)."""

    async def notify_admin(self, text: str) -> None:
        """Короткое сообщение администратору (сбои, отзывы)."""


class NullNotifier:
    """Ничего не отправляет, только пишет в лог. Книга остаётся доступной по ссылке в Mini App."""

    async def send_book(self, user_id, pdf_path, filename, caption) -> bool:
        log.info("Бот не подключён: PDF в чат не отправлен")
        return False

    async def send_admin_book(self, pdf_path, filename, caption) -> None:
        return None

    async def notify_admin(self, text: str) -> None:
        log.info("Сообщение администратору (бот не подключён): %s", text)

    async def notify_order(self, text: str) -> None:
        log.info("Карточка заказа (бот не подключён): %s", text[:200])

    async def send_print_offer(self, user_id, text, whatsapp_url) -> None:
        return None
