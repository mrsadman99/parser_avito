import sqlite3
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from domain.item import Item

NOTIFICATION_MAX_ATTEMPTS = 10


def now_iso() -> str:
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
    "has_delivery": "INTEGER",
    "city": "TEXT",
    "source_key": "TEXT NOT NULL DEFAULT ''",
    "is_reserved": "INTEGER",
    "refreshed_at": "TEXT",
    "address": "TEXT",
    "seller_id": "TEXT",
    "images_json": "TEXT",
    "coords_json": "TEXT",
    "category_id": "INTEGER",
    "has_video": "INTEGER",
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
                    photo_url TEXT,
                    has_delivery INTEGER,
                    city TEXT
                )
                """
            )
            conn.commit()

    def _migrate(self):
        """Миграция к истории по подпискам; старые URL остаются отдельной историей."""
        with sqlite3.connect(self.db_name) as conn:
            existing = {row[1] for row in conn.execute("PRAGMA table_info(viewed)")}
            if "source_key" not in existing and conn.execute("SELECT 1 FROM viewed LIMIT 1").fetchone():
                backup = Path(f"{self.db_name}.before-subscriptions-{time.time_ns()}.bak")
                with sqlite3.connect(backup) as destination:
                    conn.backup(destination)
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            existing = {row[1] for row in cursor.execute("PRAGMA table_info(viewed)")}
            for col, col_type in _MIGRATION_COLUMNS.items():
                if col not in existing:
                    cursor.execute(f"ALTER TABLE viewed ADD COLUMN {col} {col_type}")
            if "source_key" not in existing:
                cursor.execute("UPDATE viewed SET source_key = COALESCE(source_url, '')")
            indexes = {row[1] for row in cursor.execute("PRAGMA index_list(viewed)")}
            if "viewed_subscription_event" not in indexes:
                # Сохраняем последнюю запись каждого события, включая изменения цены.
                cursor.execute("""
                    DELETE FROM viewed WHERE rowid NOT IN (
                        SELECT MAX(rowid) FROM viewed GROUP BY source_key, id, price
                    )
                """)
                cursor.execute("""
                    CREATE UNIQUE INDEX viewed_subscription_event
                    ON viewed(source_key, id, price)
                """)
            cursor.execute("CREATE INDEX IF NOT EXISTS viewed_source_url ON viewed(source_url)")
            cursor.execute("CREATE INDEX IF NOT EXISTS viewed_id ON viewed(id)")
            cursor.execute("""CREATE TABLE IF NOT EXISTS ad_refresh_state (
                ad_id INTEGER PRIMARY KEY, last_attempt REAL NOT NULL
            )""")
            cursor.execute("CREATE INDEX IF NOT EXISTS ad_refresh_due ON ad_refresh_state(last_attempt)")
            cursor.execute("""INSERT OR IGNORE INTO ad_refresh_state(ad_id, last_attempt)
                SELECT id, COALESCE(MIN(CAST(strftime('%s', scanned_at) AS REAL)), ?)
                FROM viewed WHERE id IS NOT NULL GROUP BY id""", (time.time(),))
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notification_outbox (
                    id INTEGER PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    ad_id INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    recipient TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    sent INTEGER NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    UNIQUE(source_key, ad_id, price, recipient)
                )
            """)
            notification_columns = {row[1] for row in cursor.execute("PRAGMA table_info(notification_outbox)")}
            for name, definition in {
                "attempts": "INTEGER NOT NULL DEFAULT 0",
                "failed": "INTEGER NOT NULL DEFAULT 0",
                "last_error": "TEXT",
            }.items():
                if name not in notification_columns:
                    cursor.execute(f"ALTER TABLE notification_outbox ADD COLUMN {name} {definition}")
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS notification_outbox_pending
                ON notification_outbox(recipient, retry_at) WHERE sent = 0
            """)
            # старым строкам без даты ставим текущий момент (только NULL)
            cursor.execute(
                "UPDATE viewed SET scanned_at = ? WHERE scanned_at IS NULL",
                (now_iso(),),
            )
            conn.commit()

    def add_record(self, ad: Item):
        """Добавляет новую запись в таблицу viewed."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO viewed
                    (id, price, scanned_at, description)
                VALUES (?, ?, ?, ?)
                """,
                (
                    ad.id,
                    ad.priceDetailed.value,
                    now_iso(),
                    _ad_desc(ad),
                ),
            )
            cursor.execute("INSERT OR IGNORE INTO ad_refresh_state(ad_id, last_attempt) VALUES (?, ?)",
                           (ad.id, time.time()))
            self._write_catalog_status(cursor, [ad])
            conn.commit()

    def add_record_from_page(self, ads: list[Item], source_url: str = None,
                             source_key: str | None = None, recipients=()):
        """Сохраняет результаты и очередь уведомлений одной транзакцией."""
        source_key = source_key if source_key is not None else (source_url or "")
        now = now_iso()
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
                1 if ad.has_delivery() else 0,
                ad.city(),
                source_key,
            )
            for ad in ads
        ]

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT OR IGNORE INTO viewed
                    (id, price, scanned_at, description, source_url, title, ad_url, sort_time, seller_rating, seller_reviews, photo_url, has_delivery, city, source_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
            cursor.executemany("""
                INSERT OR IGNORE INTO notification_outbox
                    (source_key, ad_id, price, recipient, payload)
                VALUES (?, ?, ?, ?, ?)
            """, [
                (source_key, ad.id, ad.priceDetailed.value, recipient, ad.model_dump_json())
                for ad in ads for recipient in recipients
            ])
            cursor.executemany("""INSERT OR IGNORE INTO ad_refresh_state(ad_id, last_attempt)
                VALUES (?, ?)""", [(ad.id, time.time()) for ad in ads])
            # Статус из каталога актуален и для уже известных объявлений.
            self._write_catalog_status(cursor, ads)
            conn.commit()

    @staticmethod
    def _write_catalog_status(cursor, ads):
        for ad in ads:
            fields = {
                'is_reserved': int(ad.isReserved) if ad.isReserved is not None else None,
                'address': ad.geo.formattedAddress if ad.geo else None,
                'seller_id': ad.sellerId,
                'category_id': ad.categoryId if isinstance(ad.categoryId, int) else None,
                'has_video': int(ad.hasVideo) if ad.hasVideo is not None else None,
                'coords_json': json.dumps(ad.coords, ensure_ascii=False) if ad.coords else None,
                'images_json': json.dumps([image.model_dump(mode='json') for image in ad.images],
                                          ensure_ascii=False) if ad.images else None,
            }
            fields = {k: v for k, v in fields.items() if v is not None}
            if fields:
                assignments = ', '.join(f'{k} = ?' for k in fields)
                cursor.execute(f"UPDATE viewed SET {assignments} WHERE id = ?", [*fields.values(), ad.id])

    def update_catalog_status(self, ads):
        with sqlite3.connect(self.db_name) as conn:
            self._write_catalog_status(conn.cursor(), ads)

    def next_ad_for_refresh(self, interval, now=None):
        now = time.time() if now is None else now
        with sqlite3.connect(self.db_name) as conn:
            row = conn.execute("""SELECT ad_id FROM ad_refresh_state
                WHERE last_attempt <= ? AND EXISTS (SELECT 1 FROM viewed WHERE id = ad_id)
                ORDER BY last_attempt, ad_id LIMIT 1""", (now - interval,)).fetchone()
            return row[0] if row else None

    def finish_ad_refresh(self, ad_id, now=None):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("UPDATE ad_refresh_state SET last_attempt = ? WHERE ad_id = ?",
                         (time.time() if now is None else now, ad_id))

    def list_ads(self, source_url: str, source_keys: list[str] | None = None) -> list[dict]:
        """Запарсенные объявления по исходной ссылке."""
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM viewed WHERE source_url = ?"
            params = [source_url]
            if source_keys is not None:
                if not source_keys:
                    return []
                query += f" AND source_key IN ({','.join('?' for _ in source_keys)})"
                params.extend(source_keys)
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def pending_notifications(self, recipients: list[str], limit: int = 100) -> list[dict]:
        if not recipients:
            return []
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"""
                SELECT * FROM notification_outbox
                WHERE sent = 0 AND failed = 0 AND attempts < ? AND retry_at <= ?
                  AND recipient IN ({','.join('?' for _ in recipients)})
                ORDER BY id LIMIT ?
            """, [NOTIFICATION_MAX_ATTEMPTS, time.time(), *recipients, limit]).fetchall()
        return [dict(row) for row in rows]

    def finish_notification(self, notification_id: int, success: bool, *,
                            permanent: bool = False, error: str | None = None) -> bool:
        """Сохраняет результат. True означает прекращение автоматических повторов."""
        with sqlite3.connect(self.db_name) as conn:
            row = conn.execute("SELECT attempts FROM notification_outbox WHERE id = ?",
                               (notification_id,)).fetchone()
            if row is None:
                return False
            failed = not success and (permanent or row[0] >= NOTIFICATION_MAX_ATTEMPTS)
            conn.execute(
                """UPDATE notification_outbox SET sent = ?, failed = ?, retry_at = ?, last_error = ?
                   WHERE id = ?""",
                (int(success), int(failed), 0 if success or failed else time.time() + 60,
                 None if success else error, notification_id),
            )
        return failed

    def claim_notification(self, recipients: list[str]) -> dict | None:
        """Резервирует одну отправку; после падения процесса она вернётся через 10 минут."""
        if not recipients:
            return None
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            now = time.time()
            # Последняя разрешённая попытка могла оборваться вместе с процессом.
            # До истечения lease не трогаем ещё выполняющуюся отправку.
            conn.execute("""UPDATE notification_outbox SET failed = 1,
                last_error = COALESCE(last_error, 'Лимит попыток исчерпан; результат последней отправки неизвестен')
                WHERE sent = 0 AND failed = 0 AND attempts >= ? AND retry_at <= ?""",
                (NOTIFICATION_MAX_ATTEMPTS, now))
            row = conn.execute(f"""
                SELECT * FROM notification_outbox
                WHERE sent = 0 AND failed = 0 AND attempts < ? AND retry_at <= ?
                  AND recipient IN ({','.join('?' for _ in recipients)})
                ORDER BY id LIMIT 1
            """, [NOTIFICATION_MAX_ATTEMPTS, now, *recipients]).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE notification_outbox SET retry_at = ?, attempts = attempts + 1 WHERE id = ?",
                         (now + 600, row["id"]))
        return {**dict(row), "attempts": row["attempts"] + 1, "retry_at": now + 600}

    # Поля, которые можно перезаписывать из detail-страницы
    _REFRESH_FIELDS = (
        "price", "scanned_at", "description", "source_url", "title", "ad_url",
        "sort_time", "seller_rating", "seller_reviews", "photo_url",
        "has_delivery", "city",
        "is_reserved", "refreshed_at", "address", "seller_id", "images_json",
        "coords_json", "category_id", "has_video",
    )

    def list_ads_for_refresh(self, only_missing: bool = False) -> list[dict]:
        """Уникальные объявления (по id) для обновления из detail-страниц."""
        where = "WHERE id IS NOT NULL"
        if only_missing:
            where += " AND (city IS NULL OR has_delivery IS NULL)"
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT id, MAX(ad_url) AS ad_url, MAX(source_url) AS source_url
                FROM viewed
                {where}
                GROUP BY id
                ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def update_ad(self, ad_id, fields: dict) -> int:
        """Обновляет поля объявления (все строки с этим id); чужие колонки игнорирует."""
        cols = [col for col in fields if col in self._REFRESH_FIELDS]
        if not cols:
            return 0
        assignments = ", ".join(f"{col} = ?" for col in cols)
        values = [fields[col] for col in cols]
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                f"UPDATE OR REPLACE viewed SET {assignments} WHERE id = ?", values + [ad_id]
            )
            conn.commit()
            return cursor.rowcount

    def delete_ad(self, ad_id) -> int:
        """Удаляет объявление (все строки с этим id)."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute("DELETE FROM viewed WHERE id = ?", (ad_id,))
            conn.execute("DELETE FROM ad_refresh_state WHERE ad_id = ?", (ad_id,))
            conn.execute("DELETE FROM notification_outbox WHERE ad_id = ? AND sent = 0", (ad_id,))
            conn.commit()
            return cursor.rowcount

    def record_exists(self, record_id, price, source_key: str = ""):
        """Проверяет, существует ли запись с заданными id и price."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM viewed WHERE id = ? AND price = ? AND source_key = ?",
                (record_id, price, source_key),
            )
            return cursor.fetchone() is not None
