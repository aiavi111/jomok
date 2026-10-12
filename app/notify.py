"""Уведомления: отправка книги в чат пользователя и сообщения администратору.

Настоящая реализация (через Telegram) — в app/bot.py; здесь интерфейс и «пустая» версия,
которая работает без бота (режим заглушек и тесты).

Дополнительные методы необязательны, сервис вызывает их через getattr и без них просто пропускает шаг:
  notify_payment(order_id, receipt_path, text) — чек владельцу с кнопками;
  notify_user(user_id, text)                   — сообщение человеку;
  notify_order(text)                           — отчёт о заказе (новый, заявка ждёт решения, готов) в чат заказов (ORDERS_CHAT_ID, иначе владельцу);
  send_print_offer(user_id, text, whatsapp_url) — предложение печатной версии после книги (кнопка «Заказать в WhatsApp»);
  notify_request(order_id, text)               — карточка заявки клиента с кнопками «Принять и начать» / «Отклонить» (REVIEW_CHAT_ID, иначе владельцу);
  notify_review(order_id, text)                — карточка готовой книги с кнопками проверки (REVIEW_CHAT_ID, иначе владельцу, рядом с двумя PDF).
Флаги can_approve_requests и can_review_books говорят, может ли уведомитель показать эти кнопки человеку. Если нет (бот не подключён),
ручная проверка заявок и книг не включается, иначе заказы навсегда остались бы без решения.
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
        """PDF для проверки и копия книги: REVIEW_CHAT_ID, иначе владельцу (ADMIN_CHAT_ID), иначе в чат заказов."""

    async def notify_admin(self, text: str) -> None:
        """Короткое сообщение администратору (сбои, отзывы)."""


class NullNotifier:
    """Ничего не отправляет, только пишет в лог. Книга остаётся доступной по ссылке в Mini App."""

    can_approve_requests = False        # кнопок нет: проверка заявок и книг вручную здесь невозможна
    can_review_books = False

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

    async def notify_request(self, order_id, text) -> None:
        log.info("Заявка (бот не подключён): %s", text[:200])

    async def notify_review(self, order_id, text) -> None:
        log.info("Книга на проверку (бот не подключён): %s", text[:200])
