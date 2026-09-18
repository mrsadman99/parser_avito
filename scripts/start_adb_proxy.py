#!/usr/bin/env python3
"""Запуск tinyproxy на Android-устройстве через adb → Termux (+ стрим лога в tmux).

Поток: adb (по device_serial) → Termux (am broadcast com.termux.RUN_COMMAND) → tinyproxy.

tinyproxy всегда запускается как `tinyproxy -d` (foreground, без демонизации — в Termux
это надёжнее) и пишет лог в общий файл на устройстве (по умолчанию /sdcard/tinyproxy.log),
который доступен и Termux, и adb. Режимы:

  * detached_mode = true  — Termux background (RUN_COMMAND_BACKGROUND=true), без tmux;
  * detached_mode = false — RUN_COMMAND_BACKGROUND=false, tmux-сессия "proxy",
                            которая стримит лог через `adb shell tail -f`.

Запуск:
    python scripts/start_adb_proxy.py
    python scripts/start_adb_proxy.py --serial emulator-5554
    python scripts/start_adb_proxy.py --detached
    python scripts/start_adb_proxy.py --device-log /sdcard/tinyproxy.log
    python scripts/start_adb_proxy.py --no-attach
"""
import argparse
import base64
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config

SESSION_NAME = "proxy"
TINYPROXY_CONF = "$PREFIX/etc/tinyproxy/tinyproxy.conf"
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


def build_termux_script(device_log: str) -> str:
    """Скрипт, который выполнится в Termux: запускает tinyproxy -d и пишет лог в общий файл."""
    return f"""
LOG="{device_log}"
if pgrep -x tinyproxy > /dev/null; then
    echo "tinyproxy уже запущен."
    exit 0
fi
echo "Запускаю tinyproxy -d, лог: $LOG"
tinyproxy -d -c {TINYPROXY_CONF} >> "$LOG" 2>&1
echo "tinyproxy остановлен."
"""


def build_am_cmd(device_log: str, background: bool) -> str:
    """Команда am broadcast для Termux (RUN_COMMAND)."""
    termux_script = build_termux_script(device_log)
    b64_script = base64.b64encode(termux_script.encode()).decode()
    inner_cmd = f"echo {b64_script} | base64 -d | bash"
    bg = "true" if background else "false"
    return (
        f"am broadcast --user 0 "
        f"-a com.termux.RUN_COMMAND "
        f"--es com.termux.RUN_COMMAND_PATH /data/data/com.termux/files/usr/bin/bash "
        f"--esa com.termux.RUN_COMMAND_ARGUMENTS \"-c,{inner_cmd}\" "
        f"--es com.termux.RUN_COMMAND_WORKDIR /data/data/com.termux/files/home "
        f"--ez com.termux.RUN_COMMAND_BACKGROUND {bg}"
    )


def _adb_prefix(serial: str) -> str:
    return f"adb -s '{serial}'" if serial else "adb"


def _adb_base(serial: str) -> list:
    return ["adb", "-s", serial] if serial else ["adb"]


def run_detached(serial: str, device_log: str) -> int:
    """detached: adb → Termux broadcast в фоне (RUN_COMMAND_BACKGROUND=true), без tmux."""
    am_cmd = build_am_cmd(device_log, background=True)
    adb_cmd = _adb_base(serial) + ["shell", am_cmd]

    print("detached_mode: запускаю tinyproxy -d в фоне Termux (без tmux)...")
    try:
        result = subprocess.run(adb_cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("❌ adb не найден в PATH", file=sys.stderr)
        return 1

    out = (result.stdout or "").strip()
    if out:
        print(out)
    if result.returncode == 0:
        print("tinyproxy запущен в Termux (detached, background).")
        print(f"Лог: {_adb_prefix(serial)} shell 'tail -n 50 -f {device_log}'")
        return 0
    print(f"❌ Ошибка adb (код {result.returncode}): {(result.stderr or '').strip()}",
          file=sys.stderr)
    return 1


def run_attached(serial: str, device_log: str, attach: bool) -> int:
    """attached: broadcast в foreground + tmux-сессия, стримящая лог через `adb shell tail -f`."""
    am_cmd = build_am_cmd(device_log, background=False)
    adb = _adb_prefix(serial)

    # Временный shell-скрипт для tmux: запускаем tinyproxy в Termux и стримим лог.
    script_content = f"""#!/bin/bash
echo "Запуск tinyproxy -d в Termux через adb..."
{adb} shell '{am_cmd}'
echo "Стримлю лог {device_log} (Ctrl+C / detach — выйти из стрима)..."
{adb} shell 'until [ -f {device_log} ]; do sleep 1; done; tail -n 50 -f {device_log}'
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(script_content)
        script_path = f.name
    os.chmod(script_path, 0o755)

    try:
        exists = subprocess.run(
            ["tmux", "has-session", "-t", SESSION_NAME], capture_output=True
        ).returncode == 0
    except FileNotFoundError:
        print("❌ tmux не найден. Включите detached_mode = true в config.toml или установите tmux",
              file=sys.stderr)
        return 1

    if not exists:
        print(f"Создаю tmux-сессию '{SESSION_NAME}' (стрим лога)...")
        result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", SESSION_NAME, f"bash {script_path}"],
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
        description="Запуск tinyproxy на Android через adb → Termux (+ стрим лога в tmux)"
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
