#!/usr/bin/env python3
"""Запуск/перезапуск tinyproxy → получение cookies → запрос по ссылке.

Полный цикл для отладки одной ссылки:
  1. перезапускает свой мобильный прокси (tinyproxy на телефоне: стоп → настройка интерфейсов при SSH → старт);
  2. собирает прокси и cookies (по конфигу: own_cookies → curl_cffi GET Avito,
     либо use_bypass_api → SPFA);
  3. делает GET клиентом программы, с её лимитами повторов и обработкой блокировок.
     При camoufox.use=true использует Camoufox, иначе curl_cffi и провайдер cookies.

Запуск:
    python scripts/retrieve_ad_links.py "https://www.avito.ru/..."
    python scripts/retrieve_ad_links.py "https://www.avito.ru/..." --config config.toml
    python scripts/retrieve_ad_links.py "https://www.avito.ru/..." --no-proxy      # без tinyproxy
    python scripts/retrieve_ad_links.py "https://www.avito.ru/..." --no-restart    # не перезапускать tinyproxy
    python scripts/retrieve_ad_links.py "https://www.avito.ru/..." --mobile-proxy --no-restart --save-html ad.html
    python scripts/retrieve_ad_links.py "https://www.avito.ru/...?..." --extract-links --pages 3 --save-links links.txt --save-json links.json
"""
import argparse
import json
import sys
import random
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config
from parser.cookies.factory import build_cookies_provider
from parser.detail import parse_ad_html
from parser.http.client import HttpClient
from parser.http.camoufox_client import CamoufoxClient
from parser.proxies.proxy_factory import build_proxy
from parser.url_converter import AvitoUrlConverter
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


def extract_item_links(payload):
    """Распознать каталог; рекламные блоки и повторные ID пропустить."""
    if not isinstance(payload, dict):
        raise ValueError("Ответ каталога должен быть JSON-объектом")
    result = payload.get("result")
    candidates = [payload.get("catalog"),
                  result.get("catalog") if isinstance(result, dict) else None,
                  result, payload]
    catalog = next((c for c in candidates if isinstance(c, dict)
                    and isinstance(c.get("items"), list)), None)
    if catalog is None:
        raise ValueError("В ответе не найден список items каталога")
    links, seen = [], set()
    for item in catalog["items"]:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if isinstance(item_id, bool) or not isinstance(item_id, (int, str)):
            continue
        if not str(item_id).isascii() or not str(item_id).isdigit() or int(item_id) <= 0:
            continue
        item_id = int(item_id)
        if item_id in seen:
            continue
        seen.add(item_id)
        path = item.get("urlPath")
        links.append({"id": item_id, "title": item.get("title"),
                      "url": urljoin("https://www.avito.ru", path) if isinstance(path, str) and path else None,
                      "api_url": f"https://m.avito.ru/api/1/card/items/{item_id}"})
    return links


def collect_links(client, source_url, pages, config):
    api_url = AvitoUrlConverter().convert(source_url)
    parts = urlsplit(api_url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in {"p", "page"}]
    links, seen = [], set()
    for page in range(1, pages + 1):
        if page > 1:
            time.sleep(random.uniform(config.min_delay, config.max_delay))
        url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                         urlencode(query + [("page", str(page))]), ""))
        response = client.request("GET", url)
        items = extract_item_links(response.json())
        print(f"Страница {page}: {len(items)} объявлений")
        if not items:
            break
        for item in items:
            if item["id"] not in seen:
                seen.add(item["id"])
                links.append(item)
    return links


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Запуск/перезапуск tinyproxy + cookies + запрос по ссылке"
    )
    parser.add_argument("url", help="Ссылка на объявление или выдачу Avito")
    parser.add_argument("--extract-links", action="store_true", help="Извлечь ссылки карточек из поисковой выдачи")
    parser.add_argument("--pages", type=int, default=1, help="Число страниц выдачи, по умолчанию 1")
    parser.add_argument("--save-links", type=Path, help="Сохранить API-ссылки по одной на строку")
    parser.add_argument("--config", default="config.toml", help="Путь к config.toml")
    parser.add_argument("--no-proxy", action="store_true",
                        help="Не запускать tinyproxy (запрос напрямую/через конфиг-прокси)")
    parser.add_argument("--no-restart", action="store_true",
                        help="Не перезапускать tinyproxy, только убедиться, что он работает")
    parser.add_argument("--timeout", type=int, help="Таймаут запроса, сек; по умолчанию timeout из config.toml")
    parser.add_argument("--mobile-proxy", action="store_true",
                        help="Требовать свой или внешний мобильный прокси в config.toml")
    parser.add_argument("--save-html", type=Path, help="Сохранить полный HTML ответа, включая страницу блокировки")
    parser.add_argument("--save-json", type=Path, help="Сохранить поля объявления или список ссылок (--extract-links) в JSON")
    args = parser.parse_args(argv)
    if args.pages < 1:
        parser.error("--pages должен быть больше нуля")
    if not args.extract_links and (args.save_links or args.pages != 1):
        parser.error("--pages и --save-links используются с --extract-links")
    if args.extract_links and args.save_html:
        parser.error("--save-html доступен только для проверки отдельной страницы")

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
    if args.extract_links:
        try:
            links = collect_links(client, args.url, args.pages, config)
            for item in links:
                print(item["api_url"])
            if args.save_links:
                args.save_links.parent.mkdir(parents=True, exist_ok=True)
                args.save_links.write_text("".join(item["api_url"] + "\n" for item in links), encoding="utf-8")
            if args.save_json:
                args.save_json.parent.mkdir(parents=True, exist_ok=True)
                args.save_json.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Всего уникальных объявлений: {len(links)}")
            return 0
        except Exception as err:
            print(f"❌ Извлечение ссылок завершилось ошибкой: {err}", file=sys.stderr)
            return 1
        finally:
            client.close()
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
