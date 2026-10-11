#!/usr/bin/env python3
"""Запуск/перезапуск tinyproxy → получение cookies → запрос по ссылке.

Полный цикл для отладки одной ссылки:
  1. перезапускает свой мобильный прокси (tinyproxy на телефоне: стоп → настройка интерфейсов при SSH → старт);
  2. собирает прокси и cookies (по конфигу: own_cookies → curl_cffi GET Avito,
     либо use_bypass_api → SPFA);
  3. делает GET клиентом программы, с её лимитами повторов и обработкой блокировок.
     При camoufox.use=true использует Camoufox, иначе curl_cffi и провайдер cookies.

Запуск:
    python scripts/test_link.py "https://www.avito.ru/..."
    python scripts/test_link.py "https://www.avito.ru/..." --config config.toml
    python scripts/test_link.py "https://www.avito.ru/..." --no-proxy      # без tinyproxy
    python scripts/test_link.py "https://www.avito.ru/..." --no-restart    # не перезапускать tinyproxy
    python scripts/test_link.py "https://www.avito.ru/..." --mobile-proxy --no-restart --save-html ad.html
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config
from parser.cookies.factory import build_cookies_provider
from parser.detail import parse_ad_html
from parser.http.client import HttpClient
from parser.http.camoufox_client import CamoufoxClient
from parser.proxies.proxy_factory import build_proxy
from utils.own_mobile_proxy import ensure_own_mobile_proxy, proxy_address, start_proxy


def _build_request_client(config, proxy, timeout=None):
    settings = dict(proxy=proxy,
                    timeout=config.timeout if timeout is None else timeout,
                    max_retries=config.max_count_of_retry,
                    retry_delay=config.retry_delay,
                    block_threshold=config.block_threshold)
    if config.camoufox.use:
        return CamoufoxClient(os=config.camoufox.os, headless=config.camoufox.headless,
                              humanize=config.camoufox.humanize, geoip=config.camoufox.geoip,
                              **settings)
    provider = build_cookies_provider(config, proxy=proxy)
    return HttpClient(cookies=provider, **settings)


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
    parser.add_argument("--timeout", type=int, help="Таймаут запроса, сек; по умолчанию timeout из config.toml")
    parser.add_argument("--mobile-proxy", action="store_true",
                        help="Требовать свой или внешний мобильный прокси в config.toml")
    parser.add_argument("--save-html", type=Path, help="Сохранить полный HTML ответа, включая страницу блокировки")
    parser.add_argument("--save-json", type=Path, help="Сохранить извлечённые поля объявления в JSON")
    args = parser.parse_args(argv)

    config = load_avito_config(args.config)
    if args.mobile_proxy and not (config.own_mobile_proxy.use or config.external_mobile_proxy.proxy_string):
        parser.error("Для --mobile-proxy включите own_mobile_proxy.use или задайте external_mobile_proxy.proxy_string")

    # 1. tinyproxy (свой мобильный прокси)
    if not args.no_proxy and getattr(config.own_mobile_proxy, "use", False):
        try:
            if args.no_restart:
                print("Убеждаюсь, что tinyproxy запущен...")
                ensure_own_mobile_proxy(config, config_path=args.config)
            else:
                print("Перезапускаю tinyproxy...")
                if start_proxy(config, config_path=args.config) != 0:
                    raise RuntimeError("Не удалось запустить tinyproxy")
        except Exception as err:
            print(f"❌ {err}", file=sys.stderr)
            return 1
    elif not args.no_proxy:
        print("Свой мобильный прокси выключен (use = false) — tinyproxy не запускаю")

    # 2. прокси + cookies
    proxy = build_proxy(config)

    if getattr(config.own_mobile_proxy, "use", False):
        print(f"Прокси: {proxy_address(config.own_mobile_proxy)}")
    else:
        print(f"Прокси: {getattr(proxy, 'host', None) or 'нет'}")

    # 3. запрос
    try:
        client = _build_request_client(config, proxy, args.timeout)
    except Exception as err:
        print(f"❌ Не удалось создать клиент программы: {err}", file=sys.stderr)
        return 1
    print(f"Клиент: {type(client).__name__}; timeout={client.timeout}с; "
          f"попыток HTTP={client.max_retries}; retry_delay={client.retry_delay}с; "
          f"block_threshold={client.block_threshold}")
    print(f"Смена IP: попыток={proxy.rotation_attempts}; timeout={proxy.rotation_timeout}с; "
          f"пауза={proxy.rotation_retry_delay}с")
    result = 0
    try:
        response = client.request("GET", args.url)
    except Exception as err:
        print(f"❌ Запрос завершился ошибкой: {err}", file=sys.stderr)
        response = client.last_response
        result = 1
    finally:
        client.close()
    print(f"Блокировок: {client.block_count}; сетевых ошибок: {client.error_count}")
    if response is None:
        print("HTTP-ответ не получен, сохранять HTML нечего.", file=sys.stderr)
        return 1
    if result:
        print("Сохраняю последний полученный ответ для диагностики.")

    print("\n=== РЕЗУЛЬТАТ ===")
    print(f"URL: {response.url}")
    print(f"Статус: {response.status_code}")
    print(f"Content-Type: {getattr(response, 'headers', {}).get('content-type', '')}")
    body = response.text or ""
    print(f"Длина тела: {len(body)} симв.")
    if args.save_html:
        args.save_html.parent.mkdir(parents=True, exist_ok=True)
        args.save_html.write_text(body, encoding="utf-8")
        print(f"Полный HTML: {args.save_html.resolve()}")

    parsed = parse_ad_html(body) if body else {}
    if args.save_json:
        args.save_json.parent.mkdir(parents=True, exist_ok=True)
        args.save_json.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Поля объявления: {args.save_json.resolve()}")
    if parsed.get("available"):
        print("\n--- Распознано как объявление ---")
        for key in ("id", "title", "price", "city", "address", "has_delivery",
                    "seller_rating", "seller_reviews", "available", "removed"):
            if parsed.get(key) is not None:
                print(f"  {key}: {parsed.get(key)!r}")

    print("\n--- Тело (первые 3000 симв.) ---")
    print(body[:3000])
    return result


if __name__ == "__main__":
    sys.exit(main())
