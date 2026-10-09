"""Касса: оплата переводом по QR-коду владельца и подтверждение чеков вручную.

Как это работает: владелец загружает в админке свой QR (банковский или кошелька), указывает цену и текст-подсказку.
Покупатель платит у себя в банковском приложении и присылает фото чека. Владелец сверяет поступление и нажимает
«Подтвердить» — только после этого заказ уходит в генерацию. Платёжных систем здесь нет: деньги идут прямо владельцу.
Настройки лежат в SQLite (таблица settings), QR — файлом в папке данных, поэтому меняются без перезапуска.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .db import Database
from .errors import ValidationError

log = logging.getLogger(__name__)

DEFAULT_INSTRUCTIONS = ("Откройте банковское приложение, отсканируйте QR-код и переведите точную сумму. "
                        "Потом нажмите кнопку «Отправить чек» и приложите скриншот или фото чека.")
MAX_PRICE_LEN = 40
MAX_INSTRUCTIONS_LEN = 400
MAX_SIDE_QR = 1400
MAX_SIDE_RECEIPT = 1600


def prepare_image(raw: bytes, *, max_side: int, fmt: str, min_side: int = 0) -> bytes:
    """Открывает картинку, поворачивает по EXIF, уменьшает и сохраняет заново (заодно убирает лишние метаданные)."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError("Не получилось открыть картинку. Выберите файл в формате JPEG или PNG.")
    img = ImageOps.exif_transpose(img)
    if min(img.size) < min_side:
        raise ValidationError("Картинка слишком маленькая. Загрузите QR-код побольше.")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    out = io.BytesIO()
    if fmt == "PNG":
        img.convert("RGBA" if "A" in img.getbands() else "RGB").save(out, "PNG", optimize=True)
    else:
        img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


class PaymentDesk:
    def __init__(self, db: Database, data_dir: Path | str, default_price_text: str):
        self.db = db
        self.dir = Path(data_dir) / "payment"
        self.default_price_text = default_price_text

    # ------------------------------------------------------------------ настройки
    @property
    def qr_path(self) -> Path:
        return self.dir / "qr.png"

    def has_qr(self) -> bool:
        return self.qr_path.exists()

    def enabled(self) -> bool:
        return self.db.get_setting("pay_enabled", "0") == "1"

    def required(self) -> bool:
        """Нужно ли платить за книгу: приём оплаты включён и QR загружен."""
        return self.enabled() and self.has_qr()

    def price_text(self) -> str:
        return self.db.get_setting("pay_price", "") or self.default_price_text

    def instructions(self) -> str:
        return self.db.get_setting("pay_instructions", "") or DEFAULT_INSTRUCTIONS

    def settings(self) -> dict:
        return {"enabled": self.enabled(), "price_text": self.price_text(), "instructions": self.instructions(),
                "has_qr": self.has_qr(), "default_instructions": DEFAULT_INSTRUCTIONS}

    def update(self, data: dict) -> dict:
        if not isinstance(data, dict):
            raise ValidationError("Настройки пришли в неверном виде.")
        if "price_text" in data:
            price = " ".join(str(data["price_text"] or "").split())
            if not price or len(price) > MAX_PRICE_LEN:
                raise ValidationError(f"Цена: от 1 до {MAX_PRICE_LEN} символов, например «499 сом».", field="price_text")
            self.db.set_setting("pay_price", price)
        if "instructions" in data:
            text = str(data["instructions"] or "").strip()
            if len(text) > MAX_INSTRUCTIONS_LEN:
                raise ValidationError(f"Подсказка для покупателя: не длиннее {MAX_INSTRUCTIONS_LEN} символов.",
                                      field="instructions")
            self.db.set_setting("pay_instructions", text)
        if "enabled" in data:
            want = data["enabled"] in (True, 1, "1", "true")
            if want and not self.has_qr():
                raise ValidationError("Сначала загрузите QR-код, потом включайте приём оплаты.", field="enabled")
            self.db.set_setting("pay_enabled", "1" if want else "0")
        return self.settings()

    def save_qr(self, raw: bytes) -> None:
        data = prepare_image(raw, max_side=MAX_SIDE_QR, fmt="PNG", min_side=120)
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.qr_path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(self.qr_path)
        log.info("QR-код для оплаты обновлён")

    # ------------------------------------------------------------------ чеки
    @staticmethod
    def prepare_receipt(raw: bytes) -> bytes:
        return prepare_image(raw, max_side=MAX_SIDE_RECEIPT, fmt="JPEG", min_side=60)
