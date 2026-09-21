#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
avito_cookies.py

Скрипт для получения, сохранения и загрузки кук Avito через мобильный прокси.
Использует curl_cffi (имитация Chrome 131 на Android) и pickle для хранения.

Использование:
    python avito_cookies.py fetch   # получить и сохранить куки
    python avito_cookies.py use     # загрузить куки и сделать запрос
    python avito_cookies.py show    # показать сохранённые куки
"""

import sys
import time
import pickle
from pathlib import Path
from typing import Iterator, Tuple, Any

from curl_cffi import requests


# ======================= НАСТРОЙКИ =======================
PROXY_URL = "http://mrsadman:jUQdWbQU6Mr9tZmUcaHJ8RB9thdK@90.189.153.8:5556"
TARGET_URL = "https://www.avito.ru/"
COOKIES_FILE = Path("avito_cookies.pkl")
IMPERSONATE = "chrome131_android"

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "referer": "https://www.avito.ru/",
}

PROXIES = {
    "http": PROXY_URL,
    "https": PROXY_URL,
}
# =========================================================


# ----------------------- УТИЛИТЫ -------------------------

def iter_cookies(cookies: Any) -> Iterator[Tuple[str, str]]:
    """
    Универсальный итератор по кукам.
    Работает и с curl_cffi.requests.Cookies (dict-like),
    и с классическим http.cookiejar.CookieJar.
    Возвращает пары (name, value).
    """
    # Вариант 1: dict-подобный объект (curl_cffi)
    if hasattr(cookies, "items"):
        try:
            for name, value in cookies.items():
                yield str(name), str(value)
            return
        except Exception:
            pass

    # Вариант 2: классический CookieJar
    for c in cookies:
        if hasattr(c, "name") and hasattr(c, "value"):
            yield str(c.name), str(c.value)


def cookies_to_dict(cookies: Any) -> dict:
    """Преобразует любое хранилище кук в обычный dict."""
    return dict(iter_cookies(cookies))


# ----------------------- СЕССИЯ --------------------------

def build_session() -> requests.Session:
    """Создаёт сессию с имитацией браузера и прокси."""
    s = requests.Session(impersonate=IMPERSONATE)
    s.proxies = PROXIES
    return s


def fetch_cookies(session: requests.Session, url: str) -> bool:
    """Выполняет запрос и наполняет сессию куками от сервера."""
    try:
        r = session.get(url, headers=HEADERS, timeout=30)
        print(f"[+] GET {url} -> {r.status_code}")

        cookies_list = list(iter_cookies(session.cookies))
        print(f"[+] Получено кук: {len(cookies_list)}")
        for name, value in cookies_list:
            preview = value[:40] + "..." if len(value) > 40 else value
            print(f"    - {name} = {preview}")

        return r.status_code == 200
    except Exception as e:
        print(f"[!] Ошибка при запросе: {e}", file=sys.stderr)
        return False


# ------------------- СОХРАНЕНИЕ / ЗАГРУЗКА --------------

def save_cookies(session: requests.Session, path: Path) -> None:
    """Сохраняет куки сессии в файл через pickle (в виде обычного dict)."""
    payload = {
        "cookies": cookies_to_dict(session.cookies),  # обычный dict
        "proxy": PROXY_URL,
        "impersonate": IMPERSONATE,
        "saved_at": time.time(),
    }
    with open(path, "wb") as f:
        pickle.dump(payload, f)
    print(
        f"[+] Куки сохранены в {path.resolve()} ({len(payload['cookies'])} шт.)")


def load_cookies(path: Path) -> requests.Session:
    """Загружает куки из pickle и возвращает готовую сессию."""
    if not path.exists():
        raise FileNotFoundError(f"Файл кук не найден: {path}")

    with open(path, "rb") as f:
        payload = pickle.load(f)

    s = requests.Session(impersonate=payload["impersonate"])
    s.proxies = {
        "http": payload["proxy"],
        "https": payload["proxy"],
    }
    s.cookies.update(payload["cookies"])

    saved_at = payload.get("saved_at")
    count = len(payload["cookies"])
    if saved_at:
        age_min = (time.time() - saved_at) / 60
        print(
            f"[+] Куки загружены (возраст: {age_min:.1f} мин., всего: {count})")
    else:
        print(f"[+] Куки загружены (всего: {count})")

    return s


# --------------------- ПРОВЕРКИ -------------------------

def check_proxy_ip(session: requests.Session) -> None:
    """Проверяет, какой IP видит сервер, и какие куки отправляются."""
    try:
        ip_resp = session.get("https://httpbin.org/ip", timeout=20)
        print(f"[i] IP, видимый серверу: {ip_resp.json().get('origin')}")
    except Exception as e:
        print(f"[!] Не удалось проверить IP: {e}", file=sys.stderr)

    try:
        ck_resp = session.get("https://httpbin.org/cookies", timeout=20)
        print(
            f"[i] Куки, отправленные серверу: {ck_resp.json().get('cookies')}")
    except Exception as e:
        print(f"[!] Не удалось проверить куки: {e}", file=sys.stderr)


# ------------------------- CLI --------------------------

def cmd_fetch() -> None:
    """Получить свежие куки и сохранить."""
    s = build_session()
    check_proxy_ip(s)
    if fetch_cookies(s, TARGET_URL):
        save_cookies(s, COOKIES_FILE)
    else:
        print("[!] Куки не получены, файл не сохранён.", file=sys.stderr)
        sys.exit(1)


def cmd_use() -> None:
    """Загрузить куки и выполнить пробный запрос."""
    s = load_cookies(COOKIES_FILE)
    check_proxy_ip(s)
    r = s.get(TARGET_URL, headers=HEADERS, timeout=30)
    print(
        f"[+] Тестовый запрос -> {r.status_code}, длина ответа: {len(r.text)} байт")


def cmd_show() -> None:
    """Показать содержимое файла кук без запроса."""
    if not COOKIES_FILE.exists():
        print(f"[!] Файл не найден: {COOKIES_FILE}", file=sys.stderr)
        sys.exit(1)

    with open(COOKIES_FILE, "rb") as f:
        payload = pickle.load(f)

    cookies = payload.get("cookies", {})
    print(f"[i] Файл: {COOKIES_FILE.resolve()}")
    print(f"[i] Прокси: {payload.get('proxy')}")
    print(f"[i] Impersonate: {payload.get('impersonate')}")
    if payload.get("saved_at"):
        age_min = (time.time() - payload["saved_at"]) / 60
        print(f"[i] Возраст: {age_min:.1f} мин.")
    print(f"[i] Кук в файле: {len(cookies)}")
    print("-" * 60)
    for name, value in cookies.items():
        preview = value[:80] + "..." if len(value) > 80 else value
        print(f"{name} = {preview}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python avito_cookies.py fetch   # получить и сохранить куки")
        print("  python avito_cookies.py use     # загрузить куки и сделать запрос")
        print("  python avito_cookies.py show    # показать сохранённые куки")
        sys.exit(0)

    action = sys.argv[1].lower()
    if action == "fetch":
        cmd_fetch()
    elif action == "use":
        cmd_use()
    elif action == "show":
        cmd_show()
    else:
        print(f"[!] Неизвестная команда: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
