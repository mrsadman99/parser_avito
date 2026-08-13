"""
Получение / смена IP мобильного прокси (changeip.mobileproxy.space).

Берёт proxy_string / proxy_change_url / proxy_notifier из config.toml.

Запуск:
    python get_proxy_ip.py            # сменить IP и показать новый
    python get_proxy_ip.py --check    # только показать текущий IP (без смены)
"""
import sys

import requests

from load_config import load_avito_config


def proxies_for(proxy_string: str):
    """Собирает словарь proxies для requests из строки login:pass@host:port."""
    if not proxy_string:
        return None
    proxy = f"http://{proxy_string}"
    return {"http": proxy, "https": proxy}


def change_ip(change_url: str, notifier_proxy: str = None):
    """Дёргает changeip и возвращает new_ip (от провайдера)."""
    proxies = proxies_for(notifier_proxy)
    resp = requests.get(
        change_url,
        params={"format": "json"},
        proxies=proxies,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("new_ip"), data


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

    if not (cfg.proxy_string and cfg.proxy_change_url):
        print("❌ В config.toml не настроен мобильный прокси (нужны proxy_string и proxy_change_url)")
        return

    host = cfg.proxy_string.split("@")[-1] if "@" in cfg.proxy_string else cfg.proxy_string
    print(f"🛰 Мобильный прокси: {host}")

    if not only_check:
        print("🔄 Меняю IP через changeip...")
        try:
            new_ip, _ = change_ip(cfg.proxy_change_url, cfg.proxy_notifier)
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
