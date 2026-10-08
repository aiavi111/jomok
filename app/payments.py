"""Оплата. В прототипе книга бесплатна (FreePayment); оплата Telegram Stars — только заготовка.

Stars подключаем по отдельной команде владельца проекта. Порядок, который описан в документации Telegram:
  1. сервер создаёт ссылку на счёт: createInvoiceLink(currency="XTR", provider_token="", prices=[одна позиция]);
  2. Mini App показывает окно оплаты: Telegram.WebApp.openInvoice(link, callback);
  3. бот отвечает на pre_checkout_query через answerPreCheckoutQuery(ok=True);
  4. по successful_payment заказ ставится в очередь, telegram_payment_charge_id сохраняется в orders;
  5. возврат — refundStarPayment(user_id, telegram_payment_charge_id).
Оплату картой или кошельком в Кыргызстане (GoPay, FreedomPay, MBank, O!Money) здесь не подключаем.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PaymentCheck:
    ok: bool                      # можно ли запускать заказ
    paid: bool = False            # оплачено деньгами/Stars
    message: str = ""             # что показать, если нельзя


class PaymentProvider(ABC):
    name = "base"
    requires_payment = False

    @abstractmethod
    async def authorize(self, user_id: int) -> PaymentCheck:
        """Вызывается при создании заказа: можно ли его запускать."""


class FreePayment(PaymentProvider):
    """Тест: книга бесплатна, ограничение — лимит книг на пользователя в сутки."""

    name = "free"

    async def authorize(self, user_id: int) -> PaymentCheck:
        return PaymentCheck(ok=True, paid=False)


class StarsPayment(PaymentProvider):
    """Заготовка оплаты Telegram Stars. Пока не подключена и не используется."""

    name = "stars"
    requires_payment = True

    async def authorize(self, user_id: int) -> PaymentCheck:
        raise NotImplementedError("Оплата Telegram Stars будет подключена по отдельной команде.")


def make_payment_provider(_settings=None) -> PaymentProvider:
    return FreePayment()
