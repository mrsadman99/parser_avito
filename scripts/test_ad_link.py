#!/usr/bin/env python3
"""Запрос мобильной API-карточки клиентом программы; вывод полного JSON."""
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_config import load_avito_config
from engine.proxies.proxy_factory import build_proxy
from scripts.retrieve_ad_links import _build_request_client
from mobile_proxy.own_mobile_proxy import ensure_own_mobile_proxy, start_proxy


def api_url(value):
    parts = urlsplit(value)
    if (parts.scheme != 'https' or parts.netloc != 'm.avito.ru'
            or not re.fullmatch(r'/api/1/card/items/[1-9][0-9]*', parts.path)
            or parts.fragment):
        raise argparse.ArgumentTypeError(
            'Ожидается https://m.avito.ru/api/1/card/items/ID из retrieve_ad_links.py')
    return value


def save_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', type=api_url)
    parser.add_argument('--config', default='config.toml')
    parser.add_argument('--mobile-proxy', action='store_true', help='Требовать мобильный прокси в конфигурации')
    parser.add_argument('--no-restart', action='store_true', help='Убедиться, что tinyproxy работает, без перезапуска')
    parser.add_argument('--no-proxy', action='store_true', help='Пропустить управление tinyproxy; настроенный прокси всё равно используется')
    parser.add_argument('--timeout', type=int, help='Переопределить timeout из config.toml, сек')
    parser.add_argument('--save-json', type=Path, help='Сохранить полный JSON ответа карточки')
    parser.add_argument('--save-response', type=Path, help='Сохранить тело последнего ответа, в том числе блокировку или ошибку')
    args = parser.parse_args(argv)
    if args.timeout is not None and args.timeout <= 0:
        parser.error('--timeout должен быть больше нуля')
    if args.save_json and args.save_response and args.save_json.resolve() == args.save_response.resolve():
        parser.error('--save-json и --save-response должны указывать разные файлы')
    client = None
    try:
        config = load_avito_config(args.config)
        if args.mobile_proxy and not (config.own_mobile_proxy.use or config.external_mobile_proxy.proxy_string):
            parser.error('Включите own_mobile_proxy.use или задайте external_mobile_proxy.proxy_string')
        if config.own_mobile_proxy.use and not args.no_proxy:
            if args.no_restart:
                ensure_own_mobile_proxy(config, config_path=args.config)
            elif start_proxy(config, config_path=args.config) != 0:
                raise RuntimeError('Не удалось запустить tinyproxy')
        proxy = build_proxy(config)
        client = _build_request_client(config, proxy, args.timeout)
        print(f'Клиент: {type(client).__name__}; timeout={client.timeout}; '
              f'попыток HTTP={client.max_retries}; retry_delay={client.retry_delay}; '
              f'block_threshold={client.block_threshold}', file=sys.stderr)
        print(f'Смена IP: попыток={proxy.rotation_attempts}; timeout={proxy.rotation_timeout}; '
              f'пауза={proxy.rotation_retry_delay}', file=sys.stderr)
        # UA, cookies и TLS fingerprint остаются согласованными с клиентом программы.
        response = client.request('GET', args.url, headers={
            'accept': 'application/json, text/plain, */*',
            'referer': 'https://m.avito.ru/',
        })
        print(f'HTTP {response.status_code}: {response.url}', file=sys.stderr)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError('Ответ карточки не является JSON-объектом')
        formatted = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.save_json:
            save_text(args.save_json, formatted + '\n')
        print(formatted)
        if payload.get('success') is False or payload.get('error') or payload.get('errors'):
            raise ValueError('API вернул ошибку; подробности в выведенном JSON')
        return 0
    except Exception as err:
        print(f'Ошибка: {err}', file=sys.stderr)
        return 1
    finally:
        if client is not None:
            try:
                if args.save_response and client.last_response is not None:
                    save_text(args.save_response, client.last_response.text or '')
            finally:
                client.close()


if __name__ == '__main__':
    sys.exit(main())
