#!/usr/bin/env python3
"""Запуск tinyproxy на Android через adb → Termux (run-as).

Поток: adb (по device_serial) → run-as com.termux → Termux bash → tinyproxy -d.
Окружение Termux выставляем вручную (PREFIX/HOME/PATH/LD_LIBRARY_PATH/TMPDIR),
конфиг — абсолютным путём. Вывод tinyproxy течёт обратно через adb (без трюка с логом).

  * detached_mode = true  — tinyproxy в фоне (nohup … &), без tmux, лог в файл;
  * detached_mode = false — tinyproxy в foreground, tmux-сессия "proxy",
                            вывод (лог tinyproxy) течёт прямо в tmux.

Запуск:
    python scripts/start_adb_proxy.py
    python scripts/start_adb_proxy.py --serial emulator-5554
    python scripts/start_adb_proxy.py --detached
    python scripts/start_adb_proxy.py --device-log /sdcard/tinyproxy.log
    python scripts/start_adb_proxy.py --no-attach
"""
import argparse
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config

SESSION_NAME = "proxy"
TERMUX_PREFIX = "/data/data/com.termux/files/usr"
TERMUX_HOME = "/data/data/com.termux/files/home"
TERMUX_BASH = f"{TERMUX_PREFIX}/bin/bash"
TINYPROXY_CONF = f"{TERMUX_PREFIX}/etc/tinyproxy/tinyproxy.conf"
DEFAULT_DEVICE_LOG = "/sdcard/tinyproxy.log"


def load_settings(config_path: str = "config.toml"):
    """Возвращает (device_serial, detached_mode) из config.toml."""
    try:
        config = load_avito_config(config_path)
    except Exception as err:
        print(
            f"⚠️ Не удалось загрузить {config_path}: {err}. "
            f"Продолжаю без device_serial и в tmux",
            file=sys.stderr,
        )
        return "", False
    serial = (config.adb_proxy.device_serial or "").strip()
    detached = bool(getattr(config, "detached_mode", False))
    return serial, detached


def build_device_script(device_log: str, background: bool) -> str:
    """Скрипт для Termux (одна строка): окружение + запуск tinyproxy -d."""
    parts = [
        f"export PREFIX={TERMUX_PREFIX}",
        f"export HOME={TERMUX_HOME}",
        "export PATH=$PREFIX/bin:$PATH",
        "export LD_LIBRARY_PATH=$PREFIX/lib",
        "export TMPDIR=$PREFIX/tmp",
        "mkdir -p $TMPDIR",
        'if pgrep -x tinyproxy > /dev/null; then echo "tinyproxy уже запущен."; exit 0; fi',
    ]
    if background:
        parts.append(
            f'nohup tinyproxy -d -c {TINYPROXY_CONF} >> "{device_log}" 2>&1 & '
            f'echo "tinyproxy запущен (pid $!)."'
        )
    else:
        parts.append(f"exec tinyproxy -d -c {TINYPROXY_CONF}")
    return "; ".join(parts)


def build_device_command(device_log: str, background: bool) -> str:
    """Команда на устройстве: run-as com.termux <bash> -c '<script>'."""
    script = build_device_script(device_log, background)
    return f"run-as com.termux {TERMUX_BASH} -c '{script}'"


def _adb_base(serial: str) -> list:
    return ["adb", "-s", serial] if serial else ["adb"]


def _adb_prefix(serial: str) -> str:
    return f"adb -s '{serial}'" if serial else "adb"


def run_detached(serial: str, device_log: str) -> int:
    """detached: run-as → Termux bash → nohup tinyproxy -d & (без tmux)."""
    cmd = _adb_base(serial) + ["shell", build_device_command(device_log, background=True)]

    print("detached_mode: запускаю tinyproxy -d в Termux через run-as (фон)...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("❌ adb не найден в PATH", file=sys.stderr)
        return 1

    out = (result.stdout or "").strip()
    if out:
        print(out)
    if result.returncode == 0:
        print("tinyproxy запущен в Termux (detached, background).")
        print(f"Лог: {_adb_prefix(serial)} shell \"tail -n 50 -f {device_log}\"")
        return 0
    print(f"❌ Ошибка adb (код {result.returncode}): {(result.stderr or '').strip()}",
          file=sys.stderr)
    return 1


def run_attached(serial: str, device_log: str, attach: bool) -> int:
    """attached: run-as → Termux bash → tinyproxy -d в foreground (вывод в tmux)."""
    cmd = _adb_base(serial) + ["shell", build_device_command(device_log, background=False)]
    shell_cmd = " ".join(shlex.quote(c) for c in cmd)

    try:
        exists = subprocess.run(
            ["tmux", "has-session", "-t", SESSION_NAME], capture_output=True
        ).returncode == 0
    except FileNotFoundError:
        print("❌ tmux не найден. Включите detached_mode = true в config.toml или установите tmux",
              file=sys.stderr)
        return 1

    if not exists:
        print(f"Создаю tmux-сессию '{SESSION_NAME}' (вывод tinyproxy)...")
        result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", SESSION_NAME, shell_cmd],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"❌ Ошибка создания tmux-сессии: {result.stderr}", file=sys.stderr)
            return 1
    else:
        print(f"tmux-сессия '{SESSION_NAME}' уже существует.")

    if attach:
        print(f"Прикрепляюсь к tmux-сессии '{SESSION_NAME}' (Ctrl+B, D — отцепиться)...")
        return subprocess.run(["tmux", "attach", "-t", SESSION_NAME]).returncode

    print(f"Подключиться: tmux attach -t {SESSION_NAME}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Запуск tinyproxy на Android через adb → Termux (run-as)"
    )
    parser.add_argument("--config", default="config.toml",
                        help="Путь к config.toml (device_serial и detached_mode берутся отсюда)")
    parser.add_argument("--serial", default=None,
                        help="Серийный номер устройства (переопределяет config.toml)")
    parser.add_argument("--detached", action="store_true",
                        help="Принудительно detached: фоновый Termux без tmux")
    parser.add_argument("--no-attach", action="store_true",
                        help="Не прикрепляться к tmux (для запуска из run.py)")
    parser.add_argument("--device-log", default=DEFAULT_DEVICE_LOG,
                        help=f"Файл лога на устройстве (по умолчанию {DEFAULT_DEVICE_LOG})")
    args = parser.parse_args(argv)

    default_serial, detached = load_settings(args.config)
    serial = args.serial if args.serial is not None else default_serial
    if args.detached:
        detached = True

    if serial:
        print(f"Устройство (adb -s): {serial}")
    else:
        print("device_serial не задан — использую adb без -s")

    if detached:
        return run_detached(serial, args.device_log)

    attach = not args.no_attach and sys.stdin.isatty() and sys.stdout.isatty()
    return run_attached(serial, args.device_log, attach)


if __name__ == "__main__":
    sys.exit(main())
