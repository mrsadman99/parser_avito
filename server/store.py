"""Хранилище веб-приложения: пользователи и ссылки (SQLite).

Общий источник данных для REST API (server/main.py) и парсера (run.py):
парсер через get_all_links() подхватывает ссылки динамически.
"""

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dto import LinkConfig

DB_PATH = Path("storage/web.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                token TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                min_price INTEGER,
                max_price INTEGER,
                white_list TEXT NOT NULL DEFAULT '[]',
                black_list TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()


def _hash_password(password: str, salt: str = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000
    )
    return salt, digest.hex()


# --------------------------------------------------------------------------- #
# Пользователи
# --------------------------------------------------------------------------- #
def register(username: str, password: str) -> dict | None:
    """Создаёт пользователя. Возвращает {id, username} или None, если имя занято."""
    username = username.strip()
    if not username or not password:
        return None
    salt, pwd_hash = _hash_password(password)
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                (username, pwd_hash, salt, _now_iso()),
            )
            conn.commit()
            return {"id": cur.lastrowid, "username": username}
    except sqlite3.IntegrityError:
        return None


def login(username: str, password: str) -> str | None:
    """Проверяет логин/пароль и возвращает токен сессии."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        if row is None:
            return None
        _, digest = _hash_password(password, row["salt"])
        if not secrets.compare_digest(digest, row["password_hash"]):
            return None
        token = secrets.token_hex(32)
        conn.execute("UPDATE users SET token = ? WHERE id = ?", (token, row["id"]))
        conn.commit()
        return token


def get_user_by_token(token: str) -> dict | None:
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
        return dict(row) if row else None


# --------------------------------------------------------------------------- #
# Ссылки
# --------------------------------------------------------------------------- #
def _link_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "url": row["url"],
        "min_price": row["min_price"],
        "max_price": row["max_price"],
        "white_list": json.loads(row["white_list"] or "[]"),
        "black_list": json.loads(row["black_list"] or "[]"),
    }


def _fetch_link(conn, link_id: int, user_id: int):
    row = conn.execute(
        "SELECT * FROM links WHERE id = ? AND user_id = ?", (link_id, user_id)
    ).fetchone()
    return row


def list_links(user_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM links WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
    return [_link_to_dict(r) for r in rows]


def create_link(user_id: int, data: dict) -> dict:
    url = (data.get("url") or "").strip()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO links (user_id, url, min_price, max_price, white_list, black_list, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                url,
                data.get("min_price"),
                data.get("max_price"),
                json.dumps(data.get("white_list") or [], ensure_ascii=False),
                json.dumps(data.get("black_list") or [], ensure_ascii=False),
                _now_iso(),
            ),
        )
        conn.commit()
        row = _fetch_link(conn, cur.lastrowid, user_id)
    return _link_to_dict(row)


def update_link(user_id: int, link_id: int, data: dict) -> dict | None:
    with _connect() as conn:
        row = _fetch_link(conn, link_id, user_id)
        if row is None:
            return None
        conn.execute(
            """
            UPDATE links SET
                url = ?, min_price = ?, max_price = ?, white_list = ?, black_list = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                (data.get("url") or "").strip(),
                data.get("min_price"),
                data.get("max_price"),
                json.dumps(data.get("white_list") or [], ensure_ascii=False),
                json.dumps(data.get("black_list") or [], ensure_ascii=False),
                _now_iso(),
                link_id,
                user_id,
            ),
        )
        conn.commit()
        row = _fetch_link(conn, link_id, user_id)
    return _link_to_dict(row)


def delete_link(user_id: int, link_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM links WHERE id = ? AND user_id = ?", (link_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0


def get_all_links() -> dict[str, LinkConfig]:
    """Все ссылки всех пользователей (для парсера).

    Дубликаты по URL схлопываются — берётся последняя запись.
    """
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM links ORDER BY id").fetchall()

    result: dict[str, LinkConfig] = {}
    for row in rows:
        result[row["url"]] = LinkConfig(
            min_price=row["min_price"],
            max_price=row["max_price"],
            white_list=json.loads(row["white_list"] or "[]"),
            black_list=json.loads(row["black_list"] or "[]"),
        )
    return result


# --------------------------------------------------------------------------- #
# Админка (все ссылки всех пользователей)
# --------------------------------------------------------------------------- #
def list_all_links() -> list[dict]:
    """Все ссылки всех пользователей (для админа), с именем владельца."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT l.*, u.username
            FROM links l JOIN users u ON u.id = l.user_id
            ORDER BY l.id
            """
        ).fetchall()

    result = []
    for row in rows:
        link = _link_to_dict(row)
        link["user_id"] = row["user_id"]
        link["username"] = row["username"]
        result.append(link)
    return result


def update_link_any(link_id: int, data: dict) -> dict | None:
    with _connect() as conn:
        exists = conn.execute("SELECT id FROM links WHERE id = ?", (link_id,)).fetchone()
        if exists is None:
            return None
        conn.execute(
            """
            UPDATE links SET
                url = ?, min_price = ?, max_price = ?, white_list = ?, black_list = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                (data.get("url") or "").strip(),
                data.get("min_price"),
                data.get("max_price"),
                json.dumps(data.get("white_list") or [], ensure_ascii=False),
                json.dumps(data.get("black_list") or [], ensure_ascii=False),
                _now_iso(),
                link_id,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT l.*, u.username FROM links l JOIN users u ON u.id = l.user_id WHERE l.id = ?",
            (link_id,),
        ).fetchone()

    link = _link_to_dict(row)
    link["user_id"] = row["user_id"]
    link["username"] = row["username"]
    return link


def delete_link_any(link_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
        conn.commit()
        return cur.rowcount > 0
