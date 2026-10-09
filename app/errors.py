"""Ошибки проекта. Тексты — по-русски, чтобы их можно было показать человеку."""
from __future__ import annotations


class AppError(Exception):
    """Ошибка, которую можно показать пользователю как есть."""

    status = 400
    code = "error"

    def __init__(self, message: str, *, field: str | None = None, **extra):
        super().__init__(message)
        self.message = message
        self.field = field
        self.extra = extra


class ValidationError(AppError):
    status = 400
    code = "invalid"


class AuthError(AppError):
    status = 401
    code = "auth"


class ForbiddenError(AppError):
    status = 403
    code = "forbidden"


class ClosedError(AppError):
    """Бот закрыт: создавать книги могут только те, кто открыл личную ссылку (и владелец)."""

    status = 403
    code = "closed"


class NotFoundError(AppError):
    status = 404
    code = "not_found"


class LimitError(AppError):
    status = 429
    code = "limit"


class BusyError(AppError):
    status = 503
    code = "busy"


class ConflictError(AppError):
    status = 409
    code = "conflict"


class ProviderError(Exception):
    """Сбой внешнего сервиса (текст или картинки).

    fatal   — повторять бессмысленно для всех страниц (неверный ключ, нет денег,
              нет такой модели): заказ останавливается сразу.
    no_retry — эту одну картинку повторять не надо (например, фильтр безопасности).
    """

    def __init__(self, message: str, *, fatal: bool = False, no_retry: bool = False,
                 status: int | None = None):
        super().__init__(message)
        self.message = message
        self.fatal = fatal
        self.no_retry = no_retry
        self.status = status


class StoryValidationError(ValueError):
    """Ответ модели не прошёл проверку схемы."""


class StoryError(Exception):
    """Не удалось получить корректный план или текст книги даже после повторов."""
