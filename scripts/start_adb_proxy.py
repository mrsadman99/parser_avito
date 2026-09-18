#!/usr/bin/env python3
"""Запуск tinyproxy на Android-устройстве через adb (Termux).

Серийный номер устройства берётся из config.toml: [avito.adb_proxy].device_serial.
Если он не задан — adb вызывается без -s (первое/единственное устройство).

Запуск:
    python scripts/start_adb_proxy.py
    python scripts/start_adb_proxy.py --serial emulator-5554
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

# Команда, которая выполнится в Termux.
# Запускаем tinyproxy как демон (по умолчанию он демонизируется).
# Проверяем, не запущен ли уже.
TERMUX_SCRIPT = f"""
if pgrep -x tinyproxy > /dev/null; then
    echo "tinyproxy уже запущен."
    exit 0
fi
tinyproxy -c {TINYPROXY_CONF}
echo "tinyproxy запущен."
"""


def device_serial(config_path: str = "config.toml") -> str:
    """Серийный номер устройства из config.toml ([avito.adb_proxy].device_serial)."""
    try:
        config = load_avito_config(config_path)
    except Exception as err:
        print(
            f"⚠️ Не удалось загрузить {config_path}: {err}. Использую adb без -s",
            file=sys.stderr,
        )
        return ""
    return (config.adb_proxy.device_serial or "").strip()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Запуск tinyproxy на Android через adb (Termux)"
    )
    parser.add_argument("--config", default="config.toml",
                        help="Путь к config.toml (откуда берётся device_serial)")
    parser.add_argument("--serial", default=None,
                        help="Серийный номер устройства (переопределяет config.toml)")
    args = parser.parse_args(argv)

    serial = args.serial if args.serial is not None else device_serial(args.config)
    if serial:
        print(f"Устройство (adb -s): {serial}")
        adb_prefix = f"adb -s '{serial}'"
    else:
        print("device_serial не задан — использую adb без -s")
        adb_prefix = "adb"

    # Кодируем скрипт Termux в base64, чтобы избежать проблем с кавычками
    b64_script = base64.b64encode(TERMUX_SCRIPT.encode()).decode()
    inner_cmd = f"echo {b64_script} | base64 -d | bash"

    # Формируем команду am broadcast для Termux
    am_cmd = (
        f"am broadcast --user 0 "
        f"-a com.termux.RUN_COMMAND "
        f"--es com.termux.RUN_COMMAND_PATH /data/data/com.termux/files/usr/bin/bash "
        f"--esa com.termux.RUN_COMMAND_ARGUMENTS \"-c,{inner_cmd}\" "
        f"--es com.termux.RUN_COMMAND_WORKDIR /data/data/com.termux/files/home "
        f"--ez com.termux.RUN_COMMAND_BACKGROUND true"
    )

    # Создаём временный shell-скрипт для tmux
    # Внутри: выполняем adb shell с командой am broadcast, затем ждём (sleep infinity),
    # чтобы tmux-сессия не закрылась и можно было посмотреть вывод.
    script_content = f"""#!/bin/bash
echo "Запуск tinyproxy в Termux через adb..."
{adb_prefix} shell '{am_cmd}'
echo "Команда отправлена. Сессия остаётся активной. Для выхода закройте tmux (Ctrl+C или detach)."
sleep infinity
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(script_content)
        script_path = f.name
    os.chmod(script_path, 0o755)

    # Проверяем, нет ли уже такой tmux-сессии
    check = subprocess.run(
        ["tmux", "has-session", "-t", SESSION_NAME], capture_output=True)
    if check.returncode == 0:
        print(
            f"tmux-сессия '{SESSION_NAME}' уже существует. Подключитесь: tmux attach -t {SESSION_NAME}")
        sys.exit(0)

    # Создаём detached tmux-сессию на ПК
    print(f"Создаём tmux-сессию '{SESSION_NAME}' на ПК...")
    result = subprocess.run(
        ["tmux", "new-session", "-d", "-s",
            SESSION_NAME, f"bash {script_path}"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Ошибка создания tmux-сессии: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"Готово. tmux-сессия '{SESSION_NAME}' запущена в фоне.")
    print(f"Подключиться: tmux attach -t {SESSION_NAME}")
    print(f"Отключиться (оставив сессию): Ctrl+B, затем D")


if __name__ == "__main__":
    main()
