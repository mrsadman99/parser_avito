#!/usr/bin/env python3
"""Запуск/остановка своего мобильного прокси.

Свой мобильный прокси — это tinyproxy на телефоне (Termux), запущенный в tmux-сессии
по SSH. Порты не пробрасываются (никакого `adb forward`): парсер обращается к
`{ssh.host}:{own_mobile_proxy.port}` напрямую.

Настройки: [avito.own_mobile_proxy] и [avito.own_mobile_proxy.ssh] в config.toml.

Запуск:
    python scripts/start_own_proxy.py
    python scripts/start_own_proxy.py --config config.toml
    python scripts/start_own_proxy.py --device-log /sdcard/tinyproxy.log
    python scripts/start_own_proxy.py --stop
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config
from utils.own_mobile_proxy import DEFAULT_DEVICE_LOG, start_proxy, stop_proxy


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Запуск/остановка tinyproxy на телефоне по SSH"
    )
    parser.add_argument("--config", default="config.toml",
                        help="Путь к config.toml (настройки SSH и порт берутся отсюда)")
    parser.add_argument("--device-log", default=DEFAULT_DEVICE_LOG,
                        help=f"Файл лога на телефоне (по умолчанию {DEFAULT_DEVICE_LOG})")
    parser.add_argument("--stop", action="store_true",
                        help="Остановить прокси на телефоне (tmux + tinyproxy)")
    args = parser.parse_args(argv)

    try:
        config = load_avito_config(args.config)
    except Exception as err:
        print(f"⚠️ Не удалось загрузить {args.config}: {err}", file=sys.stderr)
        return 1

    if args.stop:
        return stop_proxy(config)
    return start_proxy(config, device_log=args.device_log)


if __name__ == "__main__":
    sys.exit(main())
