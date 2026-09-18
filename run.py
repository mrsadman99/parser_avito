#!/usr/bin/env python3
"""Запуск веб-приложения, REST API, ADB-прокси и парсера одной командой.

run.py запускает всё в фоне и сразу завершается — процессы продолжают работать
после выхода из run.py (и после отключения от SSH).

Режим берётся из config.toml, ключ [avito].detached_mode:
  * false (по умолчанию) — всё в tmux-сессиях: api, web (--dev), proxy, parser;
  * true — независимые фоновые процессы, логи в logs/api.log и logs/parser.log.

    python run.py          # production: сборка фронта + API + прокси + парсер
    python run.py --dev    # dev: Vite dev-сервер вместо собранного фронта

Порты берутся из config.toml: [avito.server] server_port (REST API + фронт),
web_server_port (только --dev). Интерфейс — server_host (по умолчанию 127.0.0.1;
для публикации наружу лучше ставить за reverse-proxy с HTTPS, а не 0.0.0.0 напрямую).
"""

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

from load_config import load_avito_config

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web-server"
LOGS_DIR = ROOT / "logs"


def ensure_web_deps() -> None:
    if (WEB_DIR / "node_modules").exists():
        return
    print("Устанавливаю зависимости web-server (npm install)...")
    subprocess.run(["npm", "install"], cwd=WEB_DIR, check=True)


def build_frontend() -> None:
    if (WEB_DIR / "dist").exists():
        return
    ensure_web_deps()
    print("Собираю фронтенд (npm run build)...")
    subprocess.run(["npm", "run", "build"], cwd=WEB_DIR, check=True)


def _tmux_has_session(name: str) -> bool:
    try:
        return subprocess.run(
            ["tmux", "has-session", "-t", name], capture_output=True
        ).returncode == 0
    except FileNotFoundError:
        return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_pid(path: Path):
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def launch(name: str, cmd: list, detached: bool, cwd: Path = None) -> None:
    """Запускает процесс: detached (фон, лог logs/<name>.log) или в tmux-сессии <name>."""
    if detached:
        LOGS_DIR.mkdir(exist_ok=True)
        pid_file = LOGS_DIR / f"{name}.pid"
        pid = _read_pid(pid_file)
        if pid and _pid_alive(pid):
            print(f"  {name}: уже запущен (pid {pid})")
            return
        log = open(LOGS_DIR / f"{name}.log", "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        pid_file.write_text(str(proc.pid))
        print(f"  {name}: фоновый процесс (pid {proc.pid}, лог logs/{name}.log)")
        return

    if _tmux_has_session(name):
        print(f"  {name}: tmux-сессия '{name}' уже существует (tmux attach -t {name})")
        return
    tmux_cmd = ["tmux", "new-session", "-d", "-s", name]
    if cwd is not None:
        tmux_cmd += ["-c", str(cwd)]
    tmux_cmd.append(" ".join(shlex.quote(str(c)) for c in cmd))
    try:
        result = subprocess.run(tmux_cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print(f"  {name}: ❌ tmux не найден. Включите detached_mode = true в config.toml")
        return
    if result.returncode != 0:
        print(f"  {name}: ошибка tmux: {result.stderr.strip()}")
        return
    print(f"  {name}: tmux-сессия '{name}' (tmux attach -t {name})")


def start_adb_proxy(config) -> None:
    """Запускает прокси на телефоне (detached или tmux решает сам скрипт)."""
    if not getattr(config.adb_proxy, "use", False):
        return
    script = ROOT / "scripts" / "start_adb_proxy.py"
    if not script.exists():
        print(f"  proxy: ADB-прокси включён, но не найден {script}")
        return
    print("  proxy: запускаю scripts/start_adb_proxy.py...")
    subprocess.run([sys.executable, str(script), "--no-attach"], check=False)


def main():
    parser = argparse.ArgumentParser(description="Запуск веб-приложения, API и парсера")
    parser.add_argument("--dev", action="store_true",
                        help="Vite dev-сервер вместо собранного фронта")
    args = parser.parse_args()

    config = load_avito_config("config.toml")
    detached = bool(getattr(config, "detached_mode", False))

    from server import store
    store.init_db()

    if args.dev:
        ensure_web_deps()
    else:
        build_frontend()

    print(f"Режим запуска: {'detached (фоновые процессы)' if detached else 'tmux'}")

    if args.dev:
        launch(
            "web",
            ["npm", "run", "dev", "--", "--port", str(config.server.web_server_port)],
            detached=detached, cwd=WEB_DIR,
        )

    launch(
        "api",
        [sys.executable, "-m", "uvicorn", "server.main:app",
         "--host", config.server.server_host, "--port", str(config.server.server_port)],
        detached=detached, cwd=ROOT,
    )

    start_adb_proxy(config)

    launch(
        "parser",
        [sys.executable, str(ROOT / "scripts" / "run_parser.py")],
        detached=detached, cwd=ROOT,
    )

    print()
    print(f"REST API:  http://localhost:{config.server.server_port}")
    if args.dev:
        print(f"Web (dev): http://localhost:{config.server.web_server_port}")
    else:
        print(f"Web:       http://localhost:{config.server.server_port}  (собранный фронт)")
    if detached:
        print("Логи:      logs/api.log, logs/parser.log; pid: logs/*.pid")
    else:
        print("tmux:      tmux ls;  tmux attach -t api|web|proxy|parser")
    print("run.py завершает работу — процессы продолжают работать в фоне.")


if __name__ == "__main__":
    main()
