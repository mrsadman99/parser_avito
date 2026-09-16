#!/usr/bin/env python3
"""Миграция ранее обработанных объявлений в веб-интерфейс.

До появления привязки к ссылке записи в database.db (таблица viewed) сохранялись
без source_url, поэтому не видны в вебе. Скрипт для каждой записи без source_url:
  - ставит source_url;
  - восстанавливает ad_url = https://www.avito.ru/{id};
  - заполняет title первой строкой описания (если пуст).

Режимы:
    python migrate_ads.py                    # показать, сколько объявлений без ссылки
    python migrate_ads.py --url "..."        # привязать ВСЕ старые объявления к одной ссылке
    python migrate_ads.py --auto             # сопоставить по ключевым словам ссылки (q=...)
    python migrate_ads.py --dry-run          # только показать, не изменяя
"""

import argparse
import sqlite3
import sys
from urllib.parse import parse_qsl, urlsplit

from db_service import SQLiteDBHandler

DB = "database.db"
WEB_DB = "storage/web.db"


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def available_links() -> list[str]:
    try:
        with _connect(WEB_DB) as conn:
            rows = conn.execute("SELECT DISTINCT url FROM links ORDER BY url").fetchall()
        return [r["url"] for r in rows]
    except sqlite3.Error:
        return []


def unassigned_rows() -> list[sqlite3.Row]:
    with _connect(DB) as conn:
        return conn.execute(
            "SELECT rowid, id, price, description FROM viewed "
            "WHERE source_url IS NULL OR source_url = ''"
        ).fetchall()


def assign_row(url: str, rowid: int) -> None:
    with _connect(DB) as conn:
        conn.execute(
            """
            UPDATE viewed SET
                source_url = ?,
                ad_url = CASE WHEN ad_url IS NULL OR ad_url = '' THEN 'https://www.avito.ru/' || id ELSE ad_url END,
                title = CASE WHEN title IS NULL OR title = '' THEN substr(COALESCE(description, ''), 1, 120) ELSE title END
            WHERE rowid = ?
            """,
            (url, rowid),
        )
        conn.commit()


def link_keywords(url: str) -> list[str]:
    query = dict(parse_qsl(urlsplit(url).query))
    return [t for t in query.get("q", "").split() if len(t) >= 2]


def migrate_all(url: str) -> int:
    rows = unassigned_rows()
    for row in rows:
        assign_row(url, row["rowid"])
    return len(rows)


def migrate_auto() -> tuple[int, int]:
    """Сопоставляет каждое объявление со ссылкой по ключевым словам (q=...)."""
    links = available_links()
    matched, unmatched = 0, 0
    for row in unassigned_rows():
        desc = (row["description"] or "").lower()
        best = None
        for url in links:
            keywords = link_keywords(url)
            if keywords and any(k.lower() in desc for k in keywords):
                best = url
                break
        if best:
            assign_row(best, row["rowid"])
            matched += 1
        else:
            unmatched += 1
    return matched, unmatched


def main(argv=None):
    parser = argparse.ArgumentParser(description="Миграция обработанных объявлений в веб-интерфейс")
    parser.add_argument("--url", help="Ссылка, к которой привязать все старые объявления")
    parser.add_argument("--auto", action="store_true", help="Сопоставить по ключевым словам ссылок")
    parser.add_argument("--dry-run", action="store_true", help="Только показать, не изменяя")
    args = parser.parse_args(argv)

    SQLiteDBHandler()  # гарантирует наличие новых колонок в database.db

    rows = unassigned_rows()
    links = available_links()

    print(f"Объявлений без привязки к ссылке: {len(rows)}")
    if links:
        print("Доступные ссылки (web.db):")
        for link in links:
            print(f"  - {link}")
    else:
        print("В storage/web.db нет ссылок (добавьте их в веб-интерфейсе).")

    if args.dry_run:
        print("Dry-run: изменения не применялись.")
        return 0

    if not rows:
        print("Мигрировать нечего — все объявления уже привязаны.")
        return 0

    if args.auto:
        matched, unmatched = migrate_auto()
        print(f"Сопоставлено: {matched}, не удалось сопоставить: {unmatched}")
        return 0

    url = args.url
    if not url:
        if len(links) == 1:
            url = links[0]
            print(f"Использую единственную ссылку: {url}")
        else:
            print("Укажите --url или используйте --auto (ссылок несколько).")
            return 1

    updated = migrate_all(url)
    print(f"Привязано объявлений: {updated} к {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
