"""
Получение / смена IP мобильного прокси (changeip.mobileproxy.space).

Берёт proxy_string / proxy_change_url / proxy_change_urls / proxy_notifier из config.toml.
Если ссылок смены IP несколько — перебирает их, пока одна не сработает.

Запуск:
    python get_proxy_ip.py            # сменить IP и показать новый
    python get_proxy_ip.py --check    # только показать текущий IP (без смены)
"""
import sys

import requests

from load_config import load_avito_config
from proxy_helpers import build_proxies_dict, BROWSER_USER_AGENT


def proxies_for(proxy_string: str):
    """Собирает словарь proxies из строки (поддерживает http/https/socks5)."""
    return build_proxies_dict(proxy_string)


def change_ip(change_urls: list, notifier_proxy: str = None):
    """Перебирает ссылки смены IP и возвращает (new_ip, url) по первой удачной."""
    proxies = proxies_for(notifier_proxy)
    last_err = None
    for url in change_urls:
        try:
            resp = requests.get(
                url,
                params={"format": "json"},
                proxies=proxies,
                timeout=30,
                headers={"User-Agent": BROWSER_USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
            new_ip = data.get("new_ip")
            if new_ip:
                return new_ip, url
        except Exception as err:
            last_err = err
            print(f"  ⚠️ ссылка не сработала: {url} — {err}")
    raise RuntimeError(f"ни одна ссылка не смогла сменить IP: {last_err}")


def current_ip(proxy_string: str):
    """Текущий внешний IP ЧЕРЕЗ прокси (тот, что видит Avito)."""
    proxies = proxies_for(proxy_string)
    for service in ("https://api.ipify.org?format=json", "https://ipinfo.io/ip"):
        try:
            resp = requests.get(service, proxies=proxies, timeout=15)
            if resp.status_code != 200:
                continue
            if "ipify" in service:
                return resp.json().get("ip")
            return resp.text.strip()
        except Exception as err:
            print(f"  ⚠️ не удалось через {service}: {err}")
    return None


def main():
    only_check = "--check" in sys.argv

    try:
        cfg = load_avito_config("config.toml")
    except Exception as err:
        print(f"❌ Не удалось загрузить config.toml: {err}")
        return

    change_urls = []
    if cfg.proxy_change_url:
        change_urls.append(cfg.proxy_change_url)
    for cu in (cfg.proxy_change_urls or []):
        if cu and cu not in change_urls:
            change_urls.append(cu)

    if not (cfg.proxy_string and change_urls):
        print("❌ В config.toml не настроен мобильный прокси (нужны proxy_string и proxy_change_url)")
        return

    host = cfg.proxy_string.split("@")[-1] if "@" in cfg.proxy_string else cfg.proxy_string
    print(f"🛰 Мобильный прокси: {host}")

    if not only_check:
        print(f"🔄 Меняю IP через changeip (ссылок: {len(change_urls)})...")
        try:
            new_ip, _ = change_ip(change_urls, cfg.proxy_notifier)
            print(f"✅ Новый IP (от провайдера): {new_ip}")
        except Exception as err:
            print(f"❌ Ошибка смены IP: {err}")

    print("🌐 Проверяю фактический IP через прокси...")
    ip = current_ip(cfg.proxy_string)
    if ip:
        print(f"🌐 IP (через прокси): {ip}")
    else:
        print("❌ Не удалось определить IP через прокси")


if __name__ == "__main__":
    main()
