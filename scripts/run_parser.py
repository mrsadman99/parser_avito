#!/usr/bin/env python3
"""Запуск парсера с ссылками из веб-БД (для tmux/detached-режима).

Используется run.py, чтобы запустить парсер отдельным процессом. В отличие от
`python parser_cls.py`, передаёт links_provider из server.store, поэтому
подхватывает ссылки, добавленные через веб-интерфейс (а также config.toml).

Запуск:
    python scripts/run_parser.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config


def main():
    config = load_avito_config("config.toml")

    from server import store
    store.init_db()

    from parser_cls import AvitoParse

    AvitoParse(config, links_provider=store.get_all_links).parse()


if __name__ == "__main__":
    main()
