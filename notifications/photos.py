"""Загрузка фотографий через прокси Avito, отдельно от API мессенджеров."""
import ssl
from contextlib import nullcontext
from urllib.parse import urlsplit

import requests
import urllib3
from loguru import logger


def download_photo(photo_url: str, proxies: dict | None = None, *, guard=None) -> bytes:
    with guard() if guard else nullcontext():
        return _download_photo(photo_url, proxies)


def _download_photo(photo_url: str, proxies: dict | None = None) -> bytes:
    selected = requests.utils.select_proxy(photo_url, proxies or {})
    if selected:
        address = urlsplit(selected)
        route = f'{address.scheme}://{address.hostname}:{address.port}'
        source = 'avito_proxy'
    else:
        route, source = 'direct', 'direct'
    logger.debug(
        '[notify photo] host={}; route={} ({}); requests={}; urllib3={}; TLS={}',
        urlsplit(photo_url).hostname, route, source, requests.__version__,
        urllib3.__version__, ssl.OPENSSL_VERSION,
    )
    try:
        with requests.Session() as session:
            # CDN использует только маршрут Avito, включая редиректы.
            # Переменные HTTP(S)_PROXY не должны подменять его на proxy_notifier.
            session.trust_env = False
            session.proxies.update(proxies or {})
            with session.get(photo_url, timeout=15) as img:
                img.raise_for_status()
                content = img.content
                logger.debug('[notify photo] HTTP {}; content-type={}; bytes={}',
                             img.status_code, img.headers.get('content-type', ''), len(content))
                return content
    except requests.RequestException as error:
        logger.warning('[notify photo] host={}; route={} ({}); error={}',
                       urlsplit(photo_url).hostname, route, source, type(error).__name__)
        raise
