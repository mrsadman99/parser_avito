#!/usr/bin/env python3
"""Запуск ТОЛЬКО своего мобильного прокси — без парсера, API и веб-сервера.

Свой мобильный прокси: tinyproxy на телефоне; SSH-соединение держит tmux-сессия
`proxy` на этом хосте (или фоновый процесс при `detached_mode = true`). Ничего
другого скрипт не поднимает.

Адрес прокси собирается из `[avito.own_mobile_proxy].server` и `.port`
(если `server` пуст — берётся `[avito.own_mobile_proxy.ssh].host`).

Запуск:
    python scripts/run_proxy.py               # поднять прокси (tmux/фон) и выйти
    python scripts/run_proxy.py --verify      # поднять и проверить IP через прокси
    python scripts/run_proxy.py --foreground  # держать в текущем терминале (Ctrl+C — стоп)
    python scripts/run_proxy.py --stop        # остановить прокси (хост + телефон)
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config
from parser.proxies.proxy import OwnMobileProxy
from parser.proxies.proxy_factory import build_proxy
from utils.own_mobile_proxy import run_foreground, start_service, stop_service


def _display(proxy: OwnMobileProxy) -> str:
    """Адрес прокси для вывода (пароль маскируется)."""
    auth = f"{proxy.login}:***@" if proxy.login and proxy.password else ""
    return f"{auth}{proxy.host}"


def _verify(proxy: OwnMobileProxy, attempts: int = 10, delay: float = 2.0) -> bool:
    """Проверяет внешний IP через прокси (несколько попыток — tinyproxy не сразу готов)."""
    from scripts.get_proxy_ip import current_ip

    for attempt in range(1, attempts + 1):
        ip = current_ip(proxy.get_spfa_proxy_string())
        if ip:
            print(f"✅ IP через прокси: {ip}")
            return True
        if attempt < attempts:
            print(f"⏳ Прокси ещё не готов ({attempt}/{attempts}), повтор...")
            time.sleep(delay)
    print("❌ Не удалось определить IP через прокси")
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Запуск только своего мобильного прокси (tinyproxy на телефоне по SSH)"
    )
    parser.add_argument("--config", default="config.toml", help="Путь к config.toml")
    parser.add_argument("--foreground", action="store_true",
                        help="Держать прокси в текущем терминале (Ctrl+C — остановить)")
    parser.add_argument("--verify", action="store_true",
                        help="После запуска проверить фактический IP через прокси")
    parser.add_argument("--stop", action="store_true",
                        help="Остановить прокси: tmux/процесс на хосте и tinyproxy на телефоне")
    args = parser.parse_args(argv)

    try:
        config = load_avito_config(args.config)
    except Exception as err:
        print(f"❌ Не удалось загрузить {args.config}: {err}", file=sys.stderr)
        return 1

    own = getattr(config, "own_mobile_proxy", None)
    if not getattr(own, "use", False):
        print("❌ [avito.own_mobile_proxy].use = false — прокси не настроен в config.toml",
              file=sys.stderr)
        return 1

    if args.stop:
        stop_service(config)
        return 0

    if args.foreground:
        return run_foreground(config)

    code = start_service(config, args.config)
    if code != 0:
        return code

    proxy = build_proxy(config)
    if not isinstance(proxy, OwnMobileProxy):
        print("❌ Прокси определён не как свой мобильный — проверьте config.toml",
              file=sys.stderr)
        return 1

    print(f"Прокси: {_display(proxy)}")

    if args.verify:
        return 0 if _verify(proxy) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
