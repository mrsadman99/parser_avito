import sqlite3
from datetime import datetime, timezone

from models import Item
from parser.specs import extract_specs


def _now_iso() -> str:
    """Текущее время в формате ISO (UTC)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Колонки, которые должны быть в таблице viewed (для миграции старых БД)
_MIGRATION_COLUMNS = {
    "scanned_at": "TEXT",
    "ai_score": "REAL",
    "description": "TEXT",
    "cpu": "TEXT",
    "socket": "TEXT",
    "ram": "TEXT",
    "storage": "TEXT",
    "gpu": "TEXT",
}


def _ad_specs(ad: Item) -> dict:
    """Характеристики ПК: из DeepSeek (ai_specs), иначе из текста regex'ом."""
    specs = getattr(ad, "ai_specs", None)
    if not specs:
        specs = extract_specs(f"{ad.title or ''} {ad.description or ''}")
    return specs or {}


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
                    ai_score REAL,
                    description TEXT,
                    cpu TEXT,
                    socket TEXT,
                    ram TEXT,
                    storage TEXT,
                    gpu TEXT
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
        """Добавляет новую запись в таблицу viewed (со всеми данными объявления)."""
        specs = _ad_specs(ad)
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO viewed
                    (id, price, scanned_at, ai_score, description, cpu, socket, ram, storage, gpu)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ad.id,
                    ad.priceDetailed.value,
                    _now_iso(),
                    getattr(ad, "ai_score", 0) or 0,
                    _ad_desc(ad),
                    specs.get("cpu", ""),
                    specs.get("socket", ""),
                    specs.get("ram", ""),
                    specs.get("storage", ""),
                    specs.get("gpu", ""),
                ),
            )
            conn.commit()

    def add_record_from_page(self, ads: list[Item]):
        """Добавляет несколько записей в таблицу viewed (со всеми данными объявлений)."""
        now = _now_iso()
        records = []
        for ad in ads:
            specs = _ad_specs(ad)
            records.append((
                ad.id,
                ad.priceDetailed.value,
                now,
                getattr(ad, "ai_score", 0) or 0,
                _ad_desc(ad),
                specs.get("cpu", ""),
                specs.get("socket", ""),
                specs.get("ram", ""),
                specs.get("storage", ""),
                specs.get("gpu", ""),
            ))

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT OR REPLACE INTO viewed
                    (id, price, scanned_at, ai_score, description, cpu, socket, ram, storage, gpu)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
