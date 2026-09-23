#!/usr/bin/env python3
"""Запуск/перезапуск tinyproxy → получение cookies → запрос по ссылке.

Полный цикл для отладки одной ссылки:
  1. перезапускает свой мобильный прокси (tinyproxy на телефоне: стоп → update_network.sh → старт);
  2. собирает прокси и cookies (по конфигу: own_cookies → curl_cffi GET Avito,
     либо use_bypass_api → SPFA);
  3. делает GET по ссылке через тот же прокси/отпечаток/cookies и печатает результат.

Запуск:
    python scripts/test_link.py "https://www.avito.ru/..."
    python scripts/test_link.py "https://www.avito.ru/..." --config config.toml
    python scripts/test_link.py "https://www.avito.ru/..." --no-proxy      # без tinyproxy
    python scripts/test_link.py "https://www.avito.ru/..." --no-restart    # не перезапускать tinyproxy
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curl_cffi import requests as cffi_requests

from load_config import load_avito_config
from parser.cookies.factory import build_cookies_provider
from parser.cookies.fetch_own import FetchOwnCookiesProvider
from parser.detail import parse_ad_html
from parser.proxies.proxy_factory import build_proxy
from utils.own_mobile_proxy import ensure_own_mobile_proxy, proxy_address, start_proxy


def _get_cookies(provider):
    """Возвращает dict cookies (для own_cookies — принудительно свежие)."""
    if provider is None:
        return {}
    if isinstance(provider, FetchOwnCookiesProvider):
        provider.last_cookies = None  # заставляем перевыпустить куки под текущий IP
    try:
        return provider.get()
    except Exception as err:
        print(f"⚠️ Не удалось получить cookies: {err}", file=sys.stderr)
        return {}


def _make_request(proxy, provider, url, timeout):
    fingerprint = provider.get_fingerprint() if provider else None
    fingerprint = fingerprint if isinstance(fingerprint, dict) else {}
    headers = dict(fingerprint.get("headers") or {})
    impersonate = fingerprint.get("impersonate") or "chrome"

    user_agent = provider.get_user_agent() if provider else None
    if user_agent and "user-agent" not in headers:
        headers["user-agent"] = user_agent

    session = cffi_requests.Session(impersonate=impersonate)
    if proxy is not None:
        proxy_url = proxy.get_httpx_proxy()
        if proxy_url:
            session.proxies = {"http": proxy_url, "https": proxy_url}

    cookies = _get_cookies(provider)
    if cookies:
        session.cookies.update(cookies)
    if headers:
        session.headers.update(headers)

    print(f"[*] GET {url} (impersonate={impersonate}, cookies={len(cookies)})")
    response = session.get(url, timeout=timeout)
    return response


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Запуск/перезапуск tinyproxy + cookies + запрос по ссылке"
    )
    parser.add_argument("url", help="Ссылка на объявление Avito")
    parser.add_argument("--config", default="config.toml", help="Путь к config.toml")
    parser.add_argument("--no-proxy", action="store_true",
                        help="Не запускать tinyproxy (запрос напрямую/через конфиг-прокси)")
    parser.add_argument("--no-restart", action="store_true",
                        help="Не перезапускать tinyproxy, только убедиться, что он работает")
    parser.add_argument("--timeout", type=int, default=30, help="Таймаут запроса, сек")
    args = parser.parse_args(argv)

    config = load_avito_config(args.config)

    # 1. tinyproxy (свой мобильный прокси)
    if not args.no_proxy and getattr(config.own_mobile_proxy, "use", False):
        if args.no_restart:
            print("Убеждаюсь, что tinyproxy запущен...")
            ensure_own_mobile_proxy(config, config_path=args.config)
        else:
            print("Перезапускаю tinyproxy...")
            if start_proxy(config, config_path=args.config) != 0:
                print("⚠️ tinyproxy не перезапущен — продолжаю с текущим прокси", file=sys.stderr)
    elif not args.no_proxy:
        print("Свой мобильный прокси выключен (use = false) — tinyproxy не запускаю")

    # 2. прокси + cookies
    proxy = build_proxy(config)
    cookies_provider = build_cookies_provider(config, proxy=proxy)

    if getattr(config.own_mobile_proxy, "use", False):
        print(f"Прокси: {proxy_address(config.own_mobile_proxy)}")
    else:
        print(f"Прокси: {getattr(proxy, 'host', None) or 'нет'}")

    # 3. запрос
    response = _make_request(proxy, cookies_provider, args.url, args.timeout)

    print("\n=== РЕЗУЛЬТАТ ===")
    print(f"URL: {response.url}")
    print(f"Статус: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type', '')}")
    body = response.text or ""
    print(f"Длина тела: {len(body)} симв.")

    parsed = parse_ad_html(body) if body else {}
    if parsed.get("available"):
        print("\n--- Распознано как объявление ---")
        for key in ("id", "title", "price", "city", "address", "has_delivery",
                    "seller_rating", "seller_reviews", "available", "removed"):
            if parsed.get(key) is not None:
                print(f"  {key}: {parsed.get(key)!r}")

    print("\n--- Тело (первые 3000 симв.) ---")
    print(body[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
