"""SQLite: пользователи, заказы, отзывы. Фото в базу не попадает никогда."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

ACTIVE_STATUSES = ("queued", "writing", "drawing", "assembling")
PAYMENT_STATUSES = ("awaiting_payment", "payment_review")      # ждём оплату / проверяем чек
BLOCKING_STATUSES = ACTIVE_STATUSES + PAYMENT_STATUSES          # у человека может быть только один такой заказ

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    language_code TEXT,
    created_at REAL NOT NULL,
    last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS orders(
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    profile_json TEXT NOT NULL,          -- анкета без фото
    title TEXT,
    paid INTEGER NOT NULL DEFAULT 0,
    payment_charge_id TEXT,
    error TEXT,                          -- понятный текст для родителя
    error_detail TEXT,                   -- техническая причина для администратора
    delivered INTEGER,                   -- NULL: не пытались, 1: отправлено в чат, 0: не удалось
    files_deleted INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    rating INTEGER,                      -- 1 понравилось, 0 нет
    comment TEXT,
    would_pay TEXT,                      -- yes | maybe | no
    created_at REAL NOT NULL,
    UNIQUE(order_id, user_id)
);
"""

_ORDER_COLUMNS = {
    "status", "title", "paid", "payment_charge_id", "error", "error_detail", "delivered",
    "files_deleted", "finished_at", "profile_json", "receipt_at", "pay_note", "paid_at",
}
# колонки, добавленные после первой версии: старая база на сервере получит их при запуске
_ORDER_MIGRATIONS = {"receipt_at": "REAL", "pay_note": "TEXT", "paid_at": "REAL"}


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            have = {row["name"] for row in self._conn.execute("PRAGMA table_info(orders)")}
            for column, kind in _ORDER_MIGRATIONS.items():
                if column not in have:
                    self._conn.execute(f"ALTER TABLE orders ADD COLUMN {column} {kind}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _one(self, sql: str, args=()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def _all(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def _exec(self, sql: str, args=()) -> None:
        with self._lock:
            self._conn.execute(sql, args)

    # ------------------------------------------------------------------ пользователи
    def upsert_user(self, user_id: int, username: str | None, first_name: str | None,
                    language_code: str | None) -> None:
        now = time.time()
        self._exec(
            """INSERT INTO users(id, username, first_name, language_code, created_at, last_seen)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name,
               language_code=excluded.language_code, last_seen=excluded.last_seen""",
            (user_id, username, first_name, language_code, now, now),
        )

    # ------------------------------------------------------------------ заказы
    def create_order(self, order_id: str, user_id: int, profile_json: str, *, paid: bool = False,
                     status: str = "queued") -> None:
        now = time.time()
        self._exec(
            """INSERT INTO orders(id, user_id, status, profile_json, paid, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (order_id, user_id, status, profile_json, 1 if paid else 0, now, now),
        )

    def get_order(self, order_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM orders WHERE id=?", (order_id,))

    def update_order(self, order_id: str, **fields) -> None:
        bad = set(fields) - _ORDER_COLUMNS
        if bad:
            raise ValueError(f"Неизвестные поля заказа: {bad}")
        fields["updated_at"] = time.time()
        sets = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE orders SET {sets} WHERE id=?", (*fields.values(), order_id))

    def active_order(self, user_id: int) -> sqlite3.Row | None:
        marks = ",".join("?" * len(BLOCKING_STATUSES))
        return self._one(
            f"SELECT * FROM orders WHERE user_id=? AND status IN ({marks}) ORDER BY created_at DESC LIMIT 1",
            (user_id, *BLOCKING_STATUSES),
        )

    def count_orders_since(self, user_id: int, since: float, *, include_errors: bool) -> int:
        sql = "SELECT COUNT(*) FROM orders WHERE user_id=? AND created_at>=?"
        if not include_errors:
            sql += " AND status NOT IN ('error','cancelled')"
        return self._one(sql, (user_id, since))[0]

    def oldest_counted_since(self, user_id: int, since: float) -> float | None:
        row = self._one("SELECT MIN(created_at) FROM orders WHERE user_id=? AND created_at>=? AND status NOT IN ('error','cancelled')",
                        (user_id, since))
        return row[0] if row else None

    def count_status(self, status: str) -> int:
        return self._one("SELECT COUNT(*) FROM orders WHERE status=?", (status,))[0]

    def interrupt_unfinished(self, message: str, detail: str) -> int:
        """После перезапуска сервера недописанные заказы помечаем ошибкой (в лимит они не входят)."""
        marks = ",".join("?" * len(ACTIVE_STATUSES))
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE orders SET status='error', error=?, error_detail=?, updated_at=? WHERE status IN ({marks}) AND paid=0",
                (message, detail, time.time(), *ACTIVE_STATUSES),
            )
            return cur.rowcount

    def unfinished_paid(self) -> list[sqlite3.Row]:
        marks = ",".join("?" * len(ACTIVE_STATUSES))
        return self._all(f"SELECT * FROM orders WHERE status IN ({marks}) AND paid=1", ACTIVE_STATUSES)

    def orders_with_files_older_than(self, ts: float) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM orders WHERE created_at<? AND files_deleted=0 AND status NOT IN "
                         "('queued','writing','drawing','assembling','awaiting_payment','payment_review')", (ts,))

    # ------------------------------------------------------------------ оплата и настройки
    def orders_with_status(self, status: str, *, limit: int = 100) -> list[sqlite3.Row]:
        order = "receipt_at" if status == "payment_review" else "created_at"
        return self._all(f"SELECT * FROM orders WHERE status=? ORDER BY {order} ASC LIMIT ?", (status, limit))

    def recent_paid(self, limit: int = 10) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM orders WHERE paid_at IS NOT NULL ORDER BY paid_at DESC LIMIT ?", (limit,))

    def count_paid_since(self, since: float) -> int:
        return self._one("SELECT COUNT(*) FROM orders WHERE paid_at IS NOT NULL AND paid_at>=?", (since,))[0]

    def unpaid_older_than(self, ts: float) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM orders WHERE status='awaiting_payment' AND created_at<?", (ts,))

    def get_user(self, user_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM users WHERE id=?", (user_id,))

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._exec("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, value))

    # ------------------------------------------------------------------ отзывы
    def upsert_feedback(self, order_id: str, user_id: int, rating: int | None, comment: str,
                        would_pay: str | None) -> None:
        self._exec(
            """INSERT INTO feedback(order_id, user_id, rating, comment, would_pay, created_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(order_id, user_id) DO UPDATE SET rating=COALESCE(excluded.rating, rating),
               comment=excluded.comment, would_pay=COALESCE(excluded.would_pay, would_pay),
               created_at=excluded.created_at""",
            (order_id, user_id, rating, comment, would_pay, time.time()),
        )

    def get_feedback(self, order_id: str, user_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM feedback WHERE order_id=? AND user_id=?", (order_id, user_id))
