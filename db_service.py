import sqlite3
from datetime import datetime, timezone

from models import Item


def _now_iso() -> str:
    """Текущее время в формате ISO (UTC)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SQLiteDBHandler:
    """Работа с БД sqlite"""
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(SQLiteDBHandler, cls).__new__(cls)
        return cls._instance

    def __init__(self, db_name="database.db"):
        if not hasattr(self, "_initialized"):
            self.db_name = db_name
            self._create_table()
            self._migrate()
            self._initialized = True

    def _create_table(self):
        """Создает таблицу viewed, если она не существует (с датой сканирования)."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS viewed (
                    id INTEGER,
                    price INTEGER,
                    scanned_at TEXT
                )
                """
            )
            conn.commit()

    def _migrate(self):
        """Добавляет колонку scanned_at в старые БД и помечает старые строки текущей датой."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            columns = [row[1] for row in cursor.execute("PRAGMA table_info(viewed)")]
            if "scanned_at" not in columns:
                cursor.execute("ALTER TABLE viewed ADD COLUMN scanned_at TEXT")
            # миграция: старым строкам без даты ставим текущий момент
            cursor.execute(
                "UPDATE viewed SET scanned_at = ? WHERE scanned_at IS NULL",
                (_now_iso(),),
            )
            conn.commit()

    def add_record(self, ad: Item):
        """Добавляет новую запись в таблицу viewed (с датой сканирования)."""

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO viewed (id, price, scanned_at) VALUES (?, ?, ?)",
                (ad.id, ad.priceDetailed.value, _now_iso()),
            )
            conn.commit()

    def add_record_from_page(self, ads: list[Item]):
        """Добавляет несколько записей в таблицу viewed (с датой сканирования)."""
        now = _now_iso()
        records = [(ad.id, ad.priceDetailed.value, now) for ad in ads]

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT OR REPLACE INTO viewed (id, price, scanned_at)
                VALUES (?, ?, ?)
                """,
                records,
            )
            conn.commit()

    def record_exists(self, record_id, price):
        """Проверяет, существует ли запись с заданными id и price."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM viewed WHERE id = ? AND price = ?",
                (record_id, price),
            )
            return cursor.fetchone() is not None
