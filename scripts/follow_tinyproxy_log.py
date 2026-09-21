#!/usr/bin/env python3
"""Стрим лога tinyproxy с телефона на хост в logs/tinyproxy.log.

Запускается фоново (utils.own_mobile_proxy._start_log_follower) при старте своего
мобильного прокси и останавливается вместе с ним. Переподключается при обрыве SSH.

Запуск вручную:
    python scripts/follow_tinyproxy_log.py --remote-log /data/data/com.termux/files/home/tinyproxy.log
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config
from utils.own_mobile_proxy import LOCAL_LOG, stream_remote_log


def main(argv=None):
    parser = argparse.ArgumentParser(description="Стрим лога tinyproxy с телефона на хост")
    parser.add_argument("--config", default="config.toml", help="Путь к config.toml")
    parser.add_argument("--remote-log", required=True,
                        help="Путь к логу tinyproxy на телефоне")
    parser.add_argument("--local-log", default=str(LOCAL_LOG),
                        help=f"Файл лога на хосте (по умолчанию {LOCAL_LOG})")
    args = parser.parse_args(argv)

    config = load_avito_config(args.config)
    stream_remote_log(config.own_mobile_proxy.ssh, args.remote_log, args.local_log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
