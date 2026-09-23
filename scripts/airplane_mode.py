#!/usr/bin/env python3
"""Переключение устройства в режим полёта и обратно (смена IP) через adb.

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
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.own_mobile_proxy import AIRPLANE_OFF_SLEEP, AIRPLANE_ON_SLEEP


def _adb(serial, *args):
    """Выполняет adb (с -s serial, если задан). Возвращает CompletedProcess или None."""
    cmd = ["adb"] + (["-s", str(serial)] if serial else []) + list(args)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        print("❌ adb не найден в PATH", file=sys.stderr)
        return None
    except Exception as err:
        print(f"❌ Ошибка adb {list(args)}: {err}", file=sys.stderr)
        return None


def _check_device(serial) -> bool:
    state = _adb(serial, "get-state")
    if state is None or state.returncode != 0:
        err = state.stderr.strip() if state is not None else "adb недоступен"
        device = f"adb -s {serial}" if serial else "adb"
        print(f"❌ Устройство не найдено ({device}): {err}", file=sys.stderr)
        return False
    return True


def set_airplane(serial, enable: bool) -> bool:
    """Включает (True) или выключает (False) режим полёта через adb."""
    value = "1" if enable else "0"
    state = "true" if enable else "false"
    label = "включаю" if enable else "выключаю"

    res = _adb(serial, "shell", "settings", "put", "global", "airplane_mode_on", value)
    if res is None or res.returncode != 0:
        err = (res.stderr.strip() if res else "adb недоступен")
        print(f"❌ Не удалось {label} режим полёта: {err}", file=sys.stderr)
        return False
    _adb(serial, "shell", "am", "broadcast",
         "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", state)
    print(f"✈️  Режим полёта: {'включён' if enable else 'выключен'}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Переключение устройства в режим полёта и обратно (смена IP)"
    )
    parser.add_argument("--serial", default=None, help="Серийник устройства (adb -s SERIAL)")
    parser.add_argument("--config", default="config.toml", help="config.toml для adb_serial")
    parser.add_argument("--on", action="store_true", help="Только включить режим полёта")
    parser.add_argument("--off", action="store_true", help="Только выключить режим полёта")
    parser.add_argument("--on-sleep", type=float, default=AIRPLANE_ON_SLEEP,
                        help=f"Пауза в режиме полёта, сек (по умолчанию {AIRPLANE_ON_SLEEP})")
    parser.add_argument("--off-sleep", type=float, default=AIRPLANE_OFF_SLEEP,
                        help=f"Пауза после выключения, сек (по умолчанию {AIRPLANE_OFF_SLEEP})")
    args = parser.parse_args(argv)

    serial = args.serial
    if not serial:
        try:
            from load_config import load_avito_config
            config = load_avito_config(args.config)
            serial = getattr(config.own_mobile_proxy, "adb_serial", "") or None
        except Exception:
            serial = None

    if not _check_device(serial):
        return 1

    if args.on:
        return 0 if set_airplane(serial, True) else 1
    if args.off:
        return 0 if set_airplane(serial, False) else 1

    # полный цикл: вкл → пауза → выкл → пауза
    if not set_airplane(serial, True):
        return 1
    time.sleep(args.on_sleep)
    if not set_airplane(serial, False):
        return 1
    time.sleep(args.off_sleep)
    print("✅ Цикл режима полёта завершён (IP обновлён)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
