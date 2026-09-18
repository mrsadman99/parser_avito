#!/usr/bin/env python3
import base64
import os
import subprocess
import sys
import tempfile

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


def main():
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
adb shell '{am_cmd}'
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
