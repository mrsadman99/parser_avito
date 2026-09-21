#!/usr/bin/env python3
"""Запуск веб-приложения и REST API БЕЗ парсера.

Поднимает (в фоне, как run.py — процесс сразу завершается):
  * ADB-прокси (если включён [avito.adb_proxy].use) — через единую точку utils.adb_proxy;
  * REST API (uvicorn server.main:app);
  * при --dev — ещё и Vite dev-сервер; иначе раздаётся собранный фронтенд.

Парсер НЕ запускается — его можно стартовать отдельно:
    python run.py                 # всё вместе (web + api + adb-proxy + парсер)
    python scripts/run_parser.py  # только парсер (ссылки из веб-БД)

    python scripts/run_server.py          # production: сборка фронта + API + adb-proxy
    python scripts/run_server.py --dev    # Vite dev-сервер вместо собранного фронта
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config
from run import ROOT, WEB_DIR, build_frontend, ensure_web_deps, launch
from utils.adb_proxy import ensure_adb_proxy


def main():
    parser = argparse.ArgumentParser(
        description="Запуск веб-приложения и API (без парсера)"
    )
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

    ensure_adb_proxy(config)

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

    print()
    print(f"REST API:  http://localhost:{config.server.server_port}")
    if args.dev:
        print(f"Web (dev): http://localhost:{config.server.web_server_port}")
    else:
        print(f"Web:       http://localhost:{config.server.server_port}  (собранный фронт)")
    print("Парсер не запущен (запуск: python run.py или python scripts/run_parser.py)")
    print("Остановить всё: python scripts/stop.py")


if __name__ == "__main__":
    main()
