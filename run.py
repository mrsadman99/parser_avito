#!/usr/bin/env python3
"""Запуск веб-приложения, REST API и парсера одной командой.

    python run.py          # production: собирает фронт и раздаёт его через API (один порт)
    python run.py --dev    # dev: Vite dev-сервер + API (для разработки с HMR)

Порты берутся из config.toml: server_port (REST API + фронт), web_server_port (только --dev).
Интерфейс — server_host (по умолчанию 127.0.0.1; для публикации наружу лучше ставить
за reverse-proxy с HTTPS, а не 0.0.0.0 напрямую).
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

from load_config import load_avito_config

WEB_DIR = Path("web-server")


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


def main():
    args = argparse.ArgumentParser(description="Запуск веб-приложения, API и парсера")
    args.add_argument("--dev", action="store_true", help="Vite dev-сервер вместо собранного фронта")
    args = args.parse_args()

    config = load_avito_config("config.toml")

    from server import store
    store.init_db()

    web = None
    if args.dev:
        ensure_web_deps()
        web = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(config.web_server_port)],
            cwd=WEB_DIR,
        )
    else:
        build_frontend()

    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app",
         "--host", config.server_host, "--port", str(config.server_port)]
    )

    from parser_cls import AvitoParse

    def links_provider():
        return store.get_all_links()

    print(f"REST API:  http://localhost:{config.server_port}")
    if args.dev:
        print(f"Web (dev): http://localhost:{config.web_server_port}")
    else:
        print(f"Web:       http://localhost:{config.server_port}  (собранный фронт)")
    print("Парсер:    запущен (Ctrl+C — остановить всё)")

    try:
        while True:
            avito = AvitoParse(config, links_provider=links_provider)
            avito.parse()
            if config.one_time_start:
                logger.info("Парсинг завершён (one_time_start = true)")
                break
            if config.retry_on_failure and avito.run_failed:
                logger.info(f"Парсинг не удался. Повтор через {config.retry_on_failure_delay} сек")
                time.sleep(config.retry_on_failure_delay)
                continue
            time.sleep(config.pause_general)
    except KeyboardInterrupt:
        print("\nОстановка...")
    finally:
        api.terminate()
        if web is not None:
            web.terminate()
        api.wait()
        if web is not None:
            web.wait()


if __name__ == "__main__":
    main()
