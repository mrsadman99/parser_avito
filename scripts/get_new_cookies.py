#!/usr/bin/env python3
"""Стенд для ExternalApiCookiesProvider._get_new_cookies (покупка cookies у SPFA).

Повторяет логику парсера: POST на /api/cookies/mobile/ с api_key, mobile и proxy,
и печатает полученные данные. Удобно для отладки без запуска всего парсера.

Значения api_key и proxy по умолчанию берутся из config.toml (как в парсере):
proxy резолвится так же — для use_adb_proxy это adb-прокси
(login:pass@127.0.0.1:{adb_local_port}), иначе proxy_string.
Сам запрос отправляется через config.messengers.proxy_notifier, если он задан.

Примеры:
    python3 scripts/get_new_cookies.py
    python3 scripts/get_new_cookies.py --config config.toml
    python3 scripts/get_new_cookies.py --proxy "login:pass@127.0.0.1:5555"
    python3 scripts/get_new_cookies.py --notifier "login:pass@notifier:3128"
    python3 scripts/get_new_cookies.py --api-key KEY --no-mobile
    python3 scripts/get_new_cookies.py --output storage/cookies_debug.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

DEFAULT_ENDPOINT = "https://spfa.pro/api/cookies/mobile/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def get_new_cookies(
    api_key: str,
    proxy: str = "",
    mobile: bool = True,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: int = 30,
    proxies: dict | None = None,
):
    """Покупает cookies у SPFA. Возвращает (response, payload_or_None)."""
    response = requests.post(
        endpoint,
        json={
            "api_key": api_key,
            "mobile": mobile,
            "proxy": proxy,
        },
        headers=HEADERS,
        timeout=timeout,
        proxies=proxies,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response, payload


def _build_request_proxies(notifier: str | None) -> dict | None:
    """Прокси для самого запроса к SPFA (по образцу scripts/send_tg_test.py)."""
    if not notifier:
        return None
    if "://" in notifier:
        return {"http": notifier, "https": notifier}
    return {"http": f"http://{notifier}", "https": f"http://{notifier}"}


def _mask_proxy(proxy: str) -> str:
    if "@" in proxy:
        head, _, host = proxy.rpartition("@")
        if ":" in head:
            user, _, _ = head.partition(":")
            return f"{user}:***@{host}"
    return proxy


def load_config_defaults(config_path: str):
    """Читает config.toml и возвращает {api_key, proxy, mobile} как в парсере.

    proxy резолвится так же, как ExternalApiCookiesProvider: при use_adb_proxy
    берётся adb-прокси (login:pass@127.0.0.1:{adb_local_port}), иначе proxy_string.
    """
    try:
        from load_config import load_avito_config
        from parser.proxies.proxy_factory import build_proxy
    except Exception as err:
        print(f"⚠️ Не удалось импортировать модули парсера: {err}", file=sys.stderr)
        return {}

    try:
        config = load_avito_config(config_path)
    except Exception as err:
        print(f"⚠️ Не удалось загрузить {config_path}: {err}", file=sys.stderr)
        return {}

    proxy_obj = build_proxy(config)
    adb_proxy = proxy_obj.get_spfa_proxy_string() if proxy_obj is not None else None
    proxy = adb_proxy or (config.mobile_proxy.proxy_string or "")

    return {
        "api_key": config.cookies_api_key or "",
        "proxy": proxy,
        "mobile": True,
        "proxy_notifier": config.messengers.proxy_notifier or "",
    }


def _print_result(response, payload):
    print(f"HTTP {response.status_code}  {response.url}")
    if payload is None:
        print("Ответ не является JSON:")
        print(response.text[:2000])
        return False

    print(f"success: {payload.get('success')}")
    if not payload.get("success"):
        print("Полный ответ:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return False

    data = payload.get("results", {})
    print(f"id:         {data.get('id')}")
    print(f"mobile:     {data.get('mobile')}")
    print(f"user_agent: {data.get('user_agent')}")

    cookies = data.get("cookies")
    if isinstance(cookies, dict):
        print(f"cookies:    {len(cookies)} шт")
        print(json.dumps(cookies, ensure_ascii=False, indent=2))
    else:
        print(f"cookies:    {cookies!r}")

    fingerprint = data.get("fingerprint")
    if isinstance(fingerprint, dict):
        print("fingerprint:")
        print(json.dumps(fingerprint, ensure_ascii=False, indent=2))

    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Покупка cookies у SPFA (аналог ExternalApiCookiesProvider._get_new_cookies)"
    )
    parser.add_argument("--config", default="config.toml",
                        help="Путь к config.toml, откуда берутся api_key/proxy по умолчанию")
    parser.add_argument("--api-key", default=None,
                        help="API-ключ spfa.pro (по умолчанию: config.toml -> SPFA_API_KEY)")
    parser.add_argument("--proxy", default=None,
                        help="Прокси для привязки cookies (по умолчанию из config.toml: adb-прокси или proxy_string)")
    parser.add_argument("--notifier", default=None,
                        help="Прокси, через который отправляется сам запрос (по умолчанию config.messengers.proxy_notifier)")
    parser.add_argument("--mobile", default=True, action=argparse.BooleanOptionalAction,
                        help="Запрашивать мобильные cookies (по умолчанию true)")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                        help=f"URL запроса (по умолчанию {DEFAULT_ENDPOINT})")
    parser.add_argument("--timeout", type=int, default=30, help="Таймаут запроса, сек")
    parser.add_argument("--output", default="",
                        help="Путь к файлу, куда сохранить сырой JSON-ответ")
    args = parser.parse_args(argv)

    cfg = load_config_defaults(args.config)

    api_key = args.api_key or cfg.get("api_key") or os.environ.get("SPFA_API_KEY")
    if not api_key:
        parser.error("укажите --api-key, переменную SPFA_API_KEY или cookies_api_key в config.toml")

    proxy = args.proxy if args.proxy is not None else cfg.get("proxy", "")
    if proxy:
        print(f"Прокси для привязки cookies: {_mask_proxy(proxy)}")

    notifier = args.notifier if args.notifier is not None else cfg.get("proxy_notifier", "")
    request_proxies = _build_request_proxies(notifier)
    if request_proxies:
        print(f"Запрос через proxy_notifier: {_mask_proxy(notifier)}")

    response, payload = get_new_cookies(
        api_key=api_key,
        proxy=proxy,
        mobile=args.mobile,
        endpoint=args.endpoint,
        timeout=args.timeout,
        proxies=request_proxies,
    )

    ok = _print_result(response, payload)

    if args.output and payload is not None:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\nОтвет сохранён в {args.output}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
