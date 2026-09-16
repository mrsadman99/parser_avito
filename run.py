#!/usr/bin/env python3
"""Запуск веб-сервера (React), REST API и парсера одной командой.

    python run.py

Порты берутся из config.toml: server_port (REST API), web_server_port (React).
Ссылки для парсинга берутся из веб-интерфейса (storage/web.db) динамически;
если пользователи ещё не добавили ссылки — используется [avito.links] из config.toml.
"""

import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

from load_config import load_avito_config

WEB_DIR = Path("web-server")


def ensure_web_deps() -> None:
    """Ставит npm-зависимости при первом запуске."""
    if (WEB_DIR / "node_modules").exists():
        return
    print("Устанавливаю зависимости web-server (npm install)...")
    subprocess.run(["npm", "install"], cwd=WEB_DIR, check=True)


def main():
    config = load_avito_config("config.toml")

    from server import store
    store.init_db()

    ensure_web_deps()

    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app",
         "--host", "0.0.0.0", "--port", str(config.server_port)]
    )

    web = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(config.web_server_port)],
        cwd=WEB_DIR,
    )

    from parser_cls import AvitoParse

    def links_provider():
        return store.get_all_links()

    print(f"REST API:  http://localhost:{config.server_port}")
    print(f"Web:       http://localhost:{config.web_server_port}")
    print("Парсер:    запущен (Ctrl+C — остановить всё)")

    try:
        while True:
            parser = AvitoParse(config, links_provider=links_provider)
            parser.parse()
            if config.one_time_start:
                logger.info("Парсинг завершён (one_time_start = true)")
                break
            if config.retry_on_failure and parser.run_failed:
                logger.info(
                    f"Парсинг не удался. Повтор через {config.retry_on_failure_delay} сек"
                )
                time.sleep(config.retry_on_failure_delay)
                continue
            time.sleep(config.pause_general)
    except KeyboardInterrupt:
        print("\nОстановка...")
    finally:
        for proc in (api, web):
            if proc.poll() is None:
                proc.terminate()
        api.wait()
        web.wait()


if __name__ == "__main__":
    main()
