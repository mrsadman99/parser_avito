#!/usr/bin/env python3
"""Запуск парсера с ссылками из веб-БД (для tmux/detached-режима).

Используется run.py, чтобы запустить парсер отдельным процессом. В отличие от
`python -m engine.app`, передаёт links_provider из persistence.store, поэтому
подхватывает ссылки, добавленные через веб-интерфейс (а также config.toml).

Запуск:
    python scripts/run_parser.py
"""
import sys
import multiprocessing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config


def main():
    from utils.logging_setup import configure_app_logging
    configure_app_logging()

    config = load_avito_config("config.toml")

    from persistence import store
    store.init_db()

    from engine.app import AvitoParse

    parser = AvitoParse(config, links_provider=store.get_all_links)
    try:
        parser.parse()
    finally:
        parser.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
