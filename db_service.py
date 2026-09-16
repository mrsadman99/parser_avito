import sqlite3
from datetime import datetime, timezone

from models import Item


def _now_iso() -> str:
    """Текущее время в формате ISO (UTC)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Колонки, которые должны быть в таблице viewed (для миграции старых БД)
_MIGRATION_COLUMNS = {
    "scanned_at": "TEXT",
    "description": "TEXT",
    "source_url": "TEXT",
    "title": "TEXT",
    "ad_url": "TEXT",
    "sort_time": "INTEGER",
    "seller_rating": "REAL",
    "seller_reviews": "INTEGER",
    "photo_url": "TEXT",
}


def _ad_desc(ad: Item) -> str:
    """Описание объявления (обрезанное для хранения в БД)."""
    return (ad.description or "")[:2000]


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
        """Создает таблицу viewed, если она не существует."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS viewed (
                    id INTEGER,
                    price INTEGER,
                    scanned_at TEXT,
                    description TEXT,
                    source_url TEXT,
                    title TEXT,
                    ad_url TEXT,
                    sort_time INTEGER,
                    seller_rating REAL,
                    seller_reviews INTEGER,
                    photo_url TEXT
                )
                """
            )
            conn.commit()

    def _migrate(self):
        """Добавляет недостающие колонки в старые БД и заполняет пустые даты."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            existing = {row[1] for row in cursor.execute("PRAGMA table_info(viewed)")}
            for col, col_type in _MIGRATION_COLUMNS.items():
                if col not in existing:
                    cursor.execute(f"ALTER TABLE viewed ADD COLUMN {col} {col_type}")
            # старым строкам без даты ставим текущий момент (только NULL)
            cursor.execute(
                "UPDATE viewed SET scanned_at = ? WHERE scanned_at IS NULL",
                (_now_iso(),),
            )
            conn.commit()

    def add_record(self, ad: Item):
        """Добавляет новую запись в таблицу viewed."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO viewed
                    (id, price, scanned_at, description)
                VALUES (?, ?, ?, ?)
                """,
                (
                    ad.id,
                    ad.priceDetailed.value,
                    _now_iso(),
                    _ad_desc(ad),
                ),
            )
            conn.commit()

    def add_record_from_page(self, ads: list[Item], source_url: str = None):
        """Добавляет несколько записей в таблицу viewed (с привязкой к ссылке)."""
        now = _now_iso()
        records = [
            (
                ad.id,
                ad.priceDetailed.value,
                now,
                _ad_desc(ad),
                source_url,
                (ad.title or "")[:500],
                f"https://www.avito.ru{ad.urlPath}" if ad.urlPath else "",
                ad.sortTimeStamp,
                ad.seller_rating,
                ad.seller_reviews,
                ad.main_image_url(),
            )
            for ad in ads
        ]

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT OR REPLACE INTO viewed
                    (id, price, scanned_at, description, source_url, title, ad_url, sort_time, seller_rating, seller_reviews, photo_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
            conn.commit()

    def list_ads(self, source_url: str) -> list[dict]:
        """Запарсенные объявления по исходной ссылке."""
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM viewed WHERE source_url = ?", (source_url,)
            ).fetchall()
        return [dict(row) for row in rows]

    def record_exists(self, record_id, price):
        """Проверяет, существует ли запись с заданными id и price."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM viewed WHERE id = ? AND price = ?",
                (record_id, price),
            )
            return cursor.fetchone() is not None
