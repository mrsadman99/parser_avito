import io
import json
from pathlib import Path
import re
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from utils import http_logging as audit
from utils.logging_setup import log_operation


@pytest.fixture
def journal(tmp_path):
    previous = audit.http_log_directory()
    audit.configure_http_logging(tmp_path)
    yield tmp_path
    audit.configure_http_logging(previous)


def response(body=b'{}', status=200, headers=None, url='https://example.test/api'):
    result = requests.Response()
    result.status_code = status
    result._content = body
    result.url = url
    result.headers.update(headers or {'Content-Type': 'application/json'})
    return result


def events(directory):
    return [json.loads(line) for line in (directory / 'http.jsonl').read_text().splitlines()]


def test_spfa_202_body_headers_and_correlation_without_secrets(journal):
    payload = {'success': True, 'results': {'id': 203679, 'cookies': {'session': 'cookie-secret'}},
               'echo': 'api-secret bearer-secret proxy-password', 'cookie_id': 203679}
    result = response(json.dumps(payload).encode(), 202, {'Set-Cookie': 'sid=server-cookie; Path=/',
                                                        'Content-Type': 'application/json'})
    send = Mock(return_value=result)
    url = 'https://spfa.test/unblock/?api_key=query-secret'

    @log_operation('refresh')
    def run():
        return audit.http_call('spfa', 'POST', send, url,
                               json={'api_key': 'api-secret', 'id': 203679,
                                     'proxy': 'user:proxy-password@proxy.test:1234'},
                               headers={'Authorization': 'Bearer bearer-secret'},
                               cookies={'sid': 'request-cookie'}, timeout=30)

    assert run() is result
    send.assert_called_once()
    start, end = events(journal)
    assert start['phase'] == 'request'
    assert end['phase'] == 'response' and end['status'] == 202
    assert end['operation'] == 'refresh' and end['http_tag'] == 'spfa'
    assert end['duration_ms'] >= 0
    assert start['request_id'] == end['request_id']
    saved = json.loads((journal / 'http' / end['http_file']).read_text())
    assert saved == end
    assert saved['response']['body']['value']['results']['id'] == 203679
    assert saved['response']['body']['value']['cookie_id'] == 203679
    assert saved['response']['body']['value']['results']['cookies'] == {'session': audit.REDACTED}
    for text in ((journal / 'http.jsonl').read_text(), json.dumps(saved)):
        for secret in ('api-secret', 'bearer-secret', 'proxy-password', 'query-secret',
                       'cookie-secret', 'server-cookie', 'request-cookie'):
            assert secret not in text


def test_long_avito_body_preserved_but_loki_line_bounded_and_link_works(journal):
    payload = {'catalog': {'items': [{'id': 42, 'title': 'Материнская плата'}]}, 'extra': 'ы' * 300_000}
    audit.http_call('avito', 'GET', Mock(return_value=response(json.dumps(payload).encode())),
                    'https://avito.test/catalog')
    end = events(journal)[-1]
    assert end['response']['truncated'] is True
    assert max(len(line.encode()) for line in (journal / 'http.jsonl').read_text().splitlines()) < 256_000
    full = json.loads((journal / 'http' / end['http_file']).read_text())
    assert full['response']['body']['value'] == payload
    datasource = Path('monitoring/grafana/provisioning/datasources/loki.yml').read_text()
    matcher = re.findall(r"matcherRegex: '([^']+)'", datasource)[-1]
    assert re.search(matcher, end['message']).group(1) == end['http_file']
    assert not list(journal.rglob('*.tmp'))


def test_failure_logged_before_reraise_and_does_not_add_retries(journal):
    failure = requests.exceptions.SSLError('UNEXPECTED_EOF_WHILE_READING api_key=private-key')

    def send(url, **kwargs):
        assert events(journal)[-1]['phase'] == 'request'
        raise failure

    with pytest.raises(requests.exceptions.SSLError) as raised:
        audit.http_call('avito', 'GET', send, 'https://cdn.test/image')
    assert raised.value is failure
    start, end = events(journal)
    assert end['phase'] == 'error' and end['error']['type'] == 'SSLError'
    assert 'UNEXPECTED_EOF' in end['error']['message']
    assert 'private-key' not in (journal / 'http.jsonl').read_text()


def test_disk_error_does_not_retry_paid_request(journal, monkeypatch):
    result = response()
    send = Mock(return_value=result)
    def fail(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(Path, 'write_text', fail)
    assert audit.http_call('spfa', 'POST', send, result.url) is result
    send.assert_called_once_with(result.url)


def test_binary_photo_and_multipart_not_dumped_or_consumed(journal):
    photo = b'\xff\xd8image-data'
    upload = io.BytesIO(photo)
    audit.http_call('notify', 'POST', Mock(return_value=response(photo, headers={'Content-Type': 'image/jpeg'})),
                    'https://notify.test/photo', data={'chat_id': '123'}, files={'photo': ('photo.jpg', upload)})
    end = events(journal)[-1]
    assert end['request']['body']['format'] == 'form'
    assert end['response']['body']['format'] == 'binary'
    assert end['response']['body']['bytes'] == len(photo)
    assert len(end['response']['body']['sha256']) == 64
    assert upload.tell() == 0
    assert 'image-data' not in (journal / 'http.jsonl').read_text()


def test_streaming_response_not_consumed(journal):
    class StreamingResponse:
        status_code = 200
        headers = {}
        url = 'https://example.test/stream'
        @property
        def content(self):
            pytest.fail('audit must not read streamed response')
        @property
        def text(self):
            pytest.fail('audit must not read streamed response')
    result = StreamingResponse()
    assert audit.http_call('other', 'GET', Mock(return_value=result), result.url, stream=True) is result
    assert events(journal)[-1]['response']['body']['format'] == 'stream'


def test_session_headers_redirects_and_prepared_request_are_sanitized(journal):
    session = requests.Session()
    session.headers['X-Api-Key'] = 'session-secret'
    session.auth = ('username', 'auth-password')
    result = response(b'{"echo":"prepared-secret session-secret auth-password"}')
    result.request = requests.Request('GET', result.url, headers={'Authorization': 'Bearer prepared-secret'}).prepare()
    redirect = response(b'redirect-body', 302, {'Location': result.url, 'Set-Cookie': 'sid=hop-cookie'})
    result.history = [redirect]
    audit.http_call('other', 'GET', Mock(return_value=result), 'https://user:url-password@example.test/start', session=session)
    end = events(journal)[-1]
    assert end['redirects'][0]['status'] == 302
    raw = (journal / 'http.jsonl').read_text()
    for secret in ('prepared-secret', 'session-secret', 'auth-password', 'url-password', 'hop-cookie'):
        assert secret not in raw


def test_duplicate_cookie_names_do_not_disable_audit(journal):
    from curl_cffi.requests import Session
    session = Session()
    session.cookies.set('sid', 'cookie-domain-a', domain='a.test')
    session.cookies.set('sid', 'cookie-domain-b', domain='b.test')
    try:
        audit.http_call('avito', 'GET', Mock(return_value=response()), 'https://a.test/', session=session)
    finally:
        session.close()
    end = events(journal)[-1]
    assert len(end['request']['cookies']) == 2
    assert all(v == audit.REDACTED for v in end['request']['cookies'].values())


def test_thread_operation_tags_and_unique_requests(journal):
    barrier = threading.Barrier(2)
    def worker(operation):
        @log_operation(operation)
        def run():
            barrier.wait(timeout=5)
            audit.http_call('avito', 'GET', Mock(return_value=response()), f'https://avito.test/{operation}')
        run()
        assert audit.http_operation.get() == 'other'
    threads = [threading.Thread(target=worker, args=(operation,)) for operation in ('scan', 'refresh')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    rows = events(journal)
    assert len(rows) == 4 and len({e['request_id'] for e in rows}) == 2
    assert {e['operation'] for e in rows} == {'scan', 'refresh'}
    for row in rows:
        assert row['url'].endswith(row['operation'])


def test_browser_resources_failures_and_close_are_logged(journal):
    page = Mock()
    browser = audit.BrowserHttpLogger(page)
    assert {call.args[0] for call in page.on.call_args_list} == {'request', 'requestfinished', 'requestfailed'}
    request = Mock(method='GET', url='https://avito.test/item', post_data=None)
    request.all_headers.return_value = {'Cookie': 'sid=browser-cookie'}
    request.response.return_value = SimpleNamespace(status=403, url=request.url,
        all_headers=lambda: {'Content-Type': 'text/html'}, body=lambda: b'blocked')
    browser.start(request)
    browser.finish(request)
    request.failure = 'net::ERR_CONNECTION_RESET'
    browser.start(request)
    browser.failed(request)
    browser.start(request)
    browser.close()
    rows = events(journal)
    assert [e['phase'] for e in rows] == ['request', 'response', 'request', 'error', 'request', 'error']
    assert rows[1]['status'] == 403 and rows[1]['response']['body']['value'] == 'blocked'
    assert 'browser-cookie' not in (journal / 'http.jsonl').read_text()


class HttpRotationProxy:
    rotation_timeout = 5
    def handle_block(self):
        audit.http_call('other', 'GET', lambda url: response(), 'https://rotate.test/')
        return True


def test_spawned_http_reaches_parent_journal_with_operation(journal):
    from engine.cancellation import Cancellation
    from engine.proxies.rotation import _rotation_attempt
    @log_operation('refresh')
    def run():
        return _rotation_attempt(HttpRotationProxy(), Cancellation())
    assert run() == (True, None)
    rows = events(journal)
    assert len(rows) == 2
    assert all(row['http_tag'] == 'other' and row['operation'] == 'refresh' for row in rows)
