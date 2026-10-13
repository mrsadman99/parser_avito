"""Очередь и CDN не обращаются к Avito во время восстановления SPFA."""
import threading
from unittest.mock import Mock, patch

import pytest
import requests

from domain.config import AvitoConfig
from engine.cancellation import Cancellation, ParseCancelled
from engine.cookies.external_api import ExternalApiCookiesProvider
from engine.http.client import HttpClient
from engine.request_queue import RequestThrottle
from notifications.photos import download_photo


def provider_at(tmp_path):
    provider = ExternalApiCookiesProvider(AvitoConfig(), storage_path=tmp_path / 'cookies.json')
    provider.last_id = 123
    provider.last_cookies = {'old': 'cookie'}
    provider.user_agent = 'test Mobile agent'
    provider.fingerprint = {'impersonate': 'chrome', 'headers': {'user-agent': provider.user_agent}}
    provider.WAIT_FOR_NEW = 0
    return provider


def response(status):
    result = requests.Response()
    result.status_code = status
    return result


def spfa_success(provider):
    return Mock(status_code=200, ok=True, json=lambda: {
        'success': True, 'results': {
            'id': 123, 'cookies': {'fresh': 'cookie'}, 'user_agent': provider.user_agent,
            'fingerprint': provider.fingerprint, 'mobile': True,
        },
    })


@pytest.mark.parametrize('purchase', [False, True])
def test_queue_and_photos_wait_for_spfa(tmp_path, purchase):
    provider = provider_at(tmp_path)
    if purchase:
        provider.status_history = [429] * 19
    old, new = Mock(cookies={}), Mock(cookies={})
    old.request.return_value = response(429)

    def fresh_request(*args, **kwargs):
        assert new.cookies == {'fresh': 'cookie'}
        return response(200)

    new.request.side_effect = fresh_request
    started, release, photo_attempted = (threading.Event() for _ in range(3))
    errors = []

    def spfa(*args, **kwargs):
        assert args[0].endswith('/cookies/mobile/' if purchase else '/unblock/')
        started.set()
        assert release.wait(3)
        return spfa_success(provider)

    def worker(action):
        try:
            action()
        except BaseException as error:
            errors.append(error)

    with patch('engine.http.client.requests.Session', side_effect=[old, new]), \
         patch.object(HttpClient, 'get_current_ip', return_value=None), \
         patch('engine.cookies.external_api.requests.post', side_effect=spfa), \
         patch('notifications.photos._download_photo', return_value=b'photo') as download:
        client = HttpClient(Mock(get_httpx_proxy=Mock(return_value=None),
                                 rotate_with_retries=Mock(return_value=True)),
                            cookies=provider, block_threshold=1, retry_delay=0)
        queue = RequestThrottle(0, 0)
        threads = []
        try:
            def enqueue():
                queue.run(client.request, 'GET', 'https://m.avito.ru/test')

            def photo():
                photo_attempted.set()
                download_photo('https://cdn.example/photo',
                               guard=lambda: provider.photo_access(Cancellation()))

            threads.append(threading.Thread(target=worker, args=(enqueue,)))
            threads[0].start()
            assert started.wait(2)
            for action in (enqueue, photo):
                thread = threading.Thread(target=worker, args=(action,))
                threads.append(thread)
                thread.start()
            assert photo_attempted.wait(1)
            threads[-1].join(.05)
            assert threads[-1].is_alive()
            old.request.assert_called_once()
            new.request.assert_not_called()
            download.assert_not_called()
        finally:
            release.set()
            for thread in threads:
                thread.join(3)
            client.close()
        assert not any(thread.is_alive() for thread in threads)
        assert not errors
        assert new.request.call_count == 2
        download.assert_called_once()
        assert provider.last_cookies == {'fresh': 'cookie'}


def test_cancellation_after_spfa_success_cannot_reuse_old_session(tmp_path):
    provider = provider_at(tmp_path)
    old, new = Mock(cookies={}), Mock(cookies={})
    old.request.return_value = response(429)
    new.request.return_value = response(200)
    cancelled = threading.Event()

    def spfa(*args, **kwargs):
        cancelled.set()
        return spfa_success(provider)

    with patch('engine.http.client.requests.Session', side_effect=[old, new]), \
         patch.object(HttpClient, 'get_current_ip', return_value=None), \
         patch('engine.cookies.external_api.requests.post', side_effect=spfa):
        client = HttpClient(Mock(get_httpx_proxy=Mock(return_value=None),
                                 rotate_with_retries=Mock(return_value=True)),
                            cookies=provider, block_threshold=1, retry_delay=0)
        try:
            with pytest.raises(ParseCancelled):
                client.request('GET', 'https://m.avito.ru/test',
                               cancellation=Cancellation(cancelled.is_set))
            client.request('GET', 'https://m.avito.ru/test')
            assert new.cookies == {'fresh': 'cookie'}
            old.request.assert_called_once()
            new.request.assert_called_once()
        finally:
            client.close()
