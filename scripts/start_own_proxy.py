#!/usr/bin/env python3
"""Запуск/остановка своего мобильного прокси.

tmux-сессия живёт на ХОСТЕ, где стартует парсер: внутри неё выполняется
`--foreground`, который держит SSH-соединение с телефоном и запускает там
`tinyproxy -d` (без `adb` и без проброса портов). Адрес прокси собирается из
`own_mobile_proxy.server` и `own_mobile_proxy.port` (пусто = `ssh.host`), парсер
обращается туда напрямую.

Настройки: [avito.own_mobile_proxy] и [avito.own_mobile_proxy.ssh] в config.toml.

Запуск:
    python scripts/start_own_proxy.py              # поднять сервис на хосте (tmux/фон)
    python scripts/start_own_proxy.py --foreground # держать SSH в текущем процессе (для tmux)
    python scripts/start_own_proxy.py --stop       # остановить сервис и tinyproxy на телефоне
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config
from utils.own_mobile_proxy import run_foreground, start_service, stop_service


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Запуск/остановка tinyproxy на телефоне по SSH (tmux на хосте)"
    )
    parser.add_argument("--config", default="config.toml",
                        help="Путь к config.toml (настройки SSH и порт берутся отсюда)")
    parser.add_argument("--foreground", action="store_true",
                        help="Подключиться по SSH и держать tinyproxy в текущем процессе "
                             "(внутренний режим: запускается из tmux на хосте)")
    parser.add_argument("--stop", action="store_true",
                        help="Остановить сервис на хосте и tinyproxy на телефоне")
    args = parser.parse_args(argv)

    try:
        config = load_avito_config(args.config)
    except Exception as err:
        print(f"⚠️ Не удалось загрузить {args.config}: {err}", file=sys.stderr)
        return 1

    if args.stop:
        stop_service(config)
        return 0
    if args.foreground:
        return run_foreground(config)
    return start_service(config, args.config)


if __name__ == "__main__":
    sys.exit(main())
