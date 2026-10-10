#!/usr/bin/env python3
"""Переключение устройства в режим полёта и обратно (смена IP) через транспорт из config.toml.

По умолчанию делает полный цикл: включить режим полёта → подождать → выключить
→ подождать (смена IP мобильного устройства).

Запуск:
    python scripts/airplane_mode.py                 # toggle (серийник из config.toml)
    python scripts/airplane_mode.py --serial X      # явно указать устройство
    python scripts/airplane_mode.py --on            # только включить режим полёта
    python scripts/airplane_mode.py --off           # только выключить режим полёта
    python scripts/airplane_mode.py --on-sleep 5 --off-sleep 12
"""
import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.own_mobile_proxy import AIRPLANE_OFF_SLEEP, AIRPLANE_ON_SLEEP, set_airplane_adb


from utils.adb import run_adb as _adb


def _check_device(serial) -> bool:
    state = _adb(serial, "get-state")
    if state is None or state.returncode != 0:
        err = state.stderr.strip() if state is not None else "adb недоступен"
        device = f"adb -s {serial}" if serial else "adb"
        print(f"❌ Устройство не найдено ({device}): {err}", file=sys.stderr)
        return False
    return True


def set_airplane(serial, enable: bool) -> bool:
    """Включает или выключает режим полёта через ADB/root."""
    if not set_airplane_adb(serial, enable):
        return False
    print(f"✈️  Режим полёта: {'включён' if enable else 'выключен'}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Переключение устройства в режим полёта и обратно (смена IP)"
    )
    parser.add_argument("--serial", default=None, help="Серийник устройства (adb -s SERIAL)")
    parser.add_argument("--config", default="config.toml", help="config.toml с настройками транспорта")
    parser.add_argument("--on", action="store_true", help="Только включить режим полёта")
    parser.add_argument("--off", action="store_true", help="Только выключить режим полёта")
    parser.add_argument("--on-sleep", type=float, default=AIRPLANE_ON_SLEEP,
                        help=f"Пауза в режиме полёта, сек (по умолчанию {AIRPLANE_ON_SLEEP})")
    parser.add_argument("--off-sleep", type=float, default=AIRPLANE_OFF_SLEEP,
                        help=f"Пауза после выключения, сек (по умолчанию {AIRPLANE_OFF_SLEEP})")
    args = parser.parse_args(argv)

    if args.on and args.off:
        parser.error("Выберите только --on или --off")
    if any(not math.isfinite(v) or v < 0 for v in (args.on_sleep, args.off_sleep)):
        parser.error("Паузы должны быть конечными неотрицательными числами")
    try:
        from load_config import load_avito_config
        config = load_avito_config(args.config)
    except Exception as err:
        print(f"Не удалось прочитать конфигурацию: {err}", file=sys.stderr)
        return 1
    own = config.own_mobile_proxy
    if own.transport == "ssh":
        if args.serial:
            parser.error("--serial применяется только при transport=adb")
        from utils.own_mobile_proxy import _connect, _run_remote, _rotate_airplane_ssh, REMOTE_ENV
        if not args.on and not args.off:
            return 0 if _rotate_airplane_ssh(own.ssh, args.on_sleep, args.off_sleep) else 1
        client = None
        try:
            client = _connect(own.ssh)
            action = "enable" if args.on else "disable"
            code, _, err = _run_remote(client, REMOTE_ENV +
                f"su -c 'cmd connectivity airplane-mode {action}'")
            if code:
                print(err, file=sys.stderr)
            return 0 if code == 0 else 1
        except Exception as err:
            print(f"SSH: не удалось подтвердить переключение режима полёта: {err}", file=sys.stderr)
            return 1
        finally:
            if client is not None:
                client.close()
    serial = args.serial or own.adb_serial or None

    if not _check_device(serial):
        return 1

    if args.on:
        return 0 if set_airplane(serial, True) else 1
    if args.off:
        return 0 if set_airplane(serial, False) else 1

    # полный цикл: вкл → пауза → выкл → пауза
    if not set_airplane(serial, True):
        return 1
    try:
        time.sleep(args.on_sleep)
    finally:
        off = set_airplane(serial, False)
    if not off:
        return 1
    time.sleep(args.off_sleep)
    print("✅ Цикл режима полёта завершён (IP обновлён)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
