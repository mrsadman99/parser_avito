"""HTTP-аудит: JSONL для Loki и полные обмены с маскировкой секретов на диске."""
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
from http.cookiejar import CookieJar
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4
from types import SimpleNamespace

from hide_private_data import redact_log_text
from utils.log_storage import append_log, save_payload


http_operation = ContextVar('http_operation', default='other')
_directory = Path('logs')
_lock = threading.RLock()
_forward = None
_last_warning = float('-inf')
REDACTED = '<redacted>'
_SENSITIVE = re.compile(r'password|passwd|secret|token|api.?key|proxy.?key|authorization|csrf|signature', re.I)


def configure_http_logging(directory='logs'):
    global _directory
    with _lock:
        _directory = Path(directory).absolute()


def http_log_directory():
    return str(_directory.absolute())


def _audit_warning(error):
    global _last_warning
    if time.monotonic() - _last_warning >= 60:
        _last_warning = time.monotonic()
        from loguru import logger
        logger.warning('HTTP-аудит: не удалось сохранить обмен ({}); проверьте каталог логов',
                       type(error).__name__)


def forward_http_logs(callback):
    """Spawn-процесс отправляет обмены родителю вместо записи общего JSONL."""
    global _forward
    _forward = callback


def _sensitive(key):
    return bool(_SENSITIVE.search(str(key))) or str(key).lower() in {'key', 'auth', 'sig'}


def _cookie(key):
    return str(key).lower() in {'cookie', 'cookies', 'set-cookie', 'set_cookie'}


def _mapping(value):
    jar = getattr(value, 'jar', value)
    if isinstance(jar, CookieJar):
        # Cookie jars can contain the same name for several domains/paths.
        return {f'{cookie.name} [{cookie.domain}{cookie.path}]': cookie.value for cookie in jar}
    if isinstance(value, Mapping):
        return dict(value)
    if type(value).__module__.startswith(('requests.', 'curl_cffi.')):
        try:
            return dict(value)
        except (TypeError, ValueError):
            pass
    return {}


def _collect(value, secrets, key=''):
    if isinstance(value, Mapping):
        for name, child in value.items():
            _collect(child, secrets, key if _cookie(key) or _sensitive(key) else str(name))
    elif isinstance(value, (list, tuple)):
        for child in value:
            _collect(child, secrets, key)
    elif isinstance(value, str) and value:
        if _sensitive(key) or _cookie(key):
            secrets.add(value)
            if 'authorization' in str(key).lower() and ' ' in value:
                secrets.add(value.split(' ', 1)[1])
            if _cookie(key):
                for part in value.split(';'):
                    if '=' in part:
                        secrets.add(part.split('=', 1)[1].strip())
        if str(key).lower() in {'proxy', 'http', 'https', 'all'} and '@' in value:
            credentials = value.rsplit('@', 1)[0].split('://')[-1]
            secrets.add(credentials)
            if ':' in credentials:
                secrets.add(credentials.split(':', 1)[1])


def _text(value, secrets):
    value = redact_log_text(str(value))
    value = re.sub(r'((?:api_key|access_token|proxy_key|password|secret)\s*[=:]\s*)[^\s&<>]+',
                   r'\1<redacted>', value, flags=re.I)
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        value = value.replace(secret, REDACTED)
    return value


def _url(value, secrets):
    parts = urlsplit(str(value))
    host = parts.netloc.rsplit('@', 1)[-1]
    if '@' in parts.netloc:
        host = '<redacted-auth>@' + host
    query = urlencode([(k, REDACTED if _sensitive(k) else _text(v, secrets))
                       for k, v in parse_qsl(parts.query, keep_blank_values=True)])
    return _text(urlunsplit((parts.scheme, host, parts.path, query, parts.fragment)), secrets)


def _safe(value, secrets, key=''):
    if _cookie(key):
        return {str(k): REDACTED for k in value} if isinstance(value, Mapping) else REDACTED
    if _sensitive(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(k): _safe(v, secrets, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(child, secrets) for child in value]
    if isinstance(value, str):
        if value.startswith(('http://', 'https://')):
            return _url(value, secrets)
        if key.lower() == 'proxy' and '@' in value:
            return '<redacted-auth>@' + value.rsplit('@', 1)[-1]
        return _text(value, secrets)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return {'type': type(value).__name__}


def _body(value, content_type, secrets):
    if value is None:
        return None
    if isinstance(value, (Mapping, list, tuple)):
        _collect(value, secrets)
        return {'format': 'json', 'value': _safe(value, secrets)}
    if isinstance(value, bytes):
        binary = any(kind in content_type.lower() for kind in
                     ('image/', 'audio/', 'video/', 'octet-stream', 'multipart/', 'application/pdf'))
        if binary:
            return {'format': 'binary', 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
        try:
            value = value.decode('utf-8')
        except UnicodeDecodeError:
            return {'format': 'binary', 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            if 'application/x-www-form-urlencoded' in content_type:
                parsed = dict(parse_qsl(value, keep_blank_values=True))
            else:
                return {'format': 'text', 'value': _text(value, secrets)}
        _collect(parsed, secrets)
        return {'format': 'json', 'value': _safe(parsed, secrets)}
    return {'format': 'stream', 'type': type(value).__name__, 'note': 'stream was not consumed'}


def _files(files):
    entries = files.items() if isinstance(files, Mapping) else files if isinstance(files, (list, tuple)) else []
    result = {}
    for key, value in entries:
        data = value[1] if isinstance(value, tuple) and len(value) > 1 else value
        result[str(key)] = {'type': type(data).__name__}
        if isinstance(data, bytes):
            result[str(key)].update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    return result


def _preview(value):
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded.encode('utf-8')) <= 2048:
        return value
    return {'truncated': True, 'preview': encoded.encode('utf-8')[:2048].decode('utf-8', errors='ignore'),
            'full_bytes': len(encoded.encode('utf-8'))}


def record_http(event):
    """Ошибки журнала никогда не меняют результат сетевого вызова."""
    try:
        if _forward is not None:
            _forward(event)
            return
        with _lock:
            _directory.mkdir(parents=True, exist_ok=True)
            relative = event['http_file']
            destination = _directory / 'http' / relative
            # Сохраняем полный обмен один раз после завершения; отправка уже есть в JSONL.
            if event['phase'] != 'request':
                try:
                    save_payload(destination, event)
                except Exception as error:
                    _audit_warning(error)
            compact = {k: _preview(v) for k, v in event.items()}
            append_log(_directory / 'http.jsonl', json.dumps(compact, ensure_ascii=False) + '\n',
                       max_bytes=5 * 1024 * 1024, backups=5)

    except Exception as error:
        # Даже ошибка маскировки/диска не должна вызвать повтор платного POST.
        _audit_warning(error)


class HttpTrace:
    def __init__(self, tag, method, url, *, session=None, **kwargs):
        self.started = time.monotonic()
        self.stream = kwargs.get('stream', False)
        self.secrets = set()
        headers = {**_mapping(getattr(session, 'headers', None)), **_mapping(kwargs.get('headers'))}
        cookies = {**_mapping(getattr(session, 'cookies', None)), **_mapping(kwargs.get('cookies'))}
        self.raw_request = {
            'method': str(method).upper(), 'url': str(url), 'headers': headers, 'cookies': cookies,
            'params': kwargs.get('params'), 'timeout': kwargs.get('timeout'),
            'proxies': kwargs.get('proxies', getattr(session, 'proxies', None)),
            'proxy': kwargs.get('proxy'), 'auth': kwargs.get('auth', getattr(session, 'auth', None)),
            'verify': kwargs.get('verify', getattr(session, 'verify', None)),
            'allow_redirects': kwargs.get('allow_redirects', True),
        }
        _collect(self.raw_request, self.secrets)
        # Query credentials must also be removed when echoed by the server.
        _collect(dict(parse_qsl(urlsplit(str(url)).query)), self.secrets)
        parts = urlsplit(str(url))
        if parts.password:
            self.secrets.add(parts.password)
        body = kwargs.get('json', kwargs.get('data'))
        _collect(body, self.secrets)
        content_type = next((v for k, v in headers.items() if k.lower() == 'content-type'), '')
        self.raw_request['body'] = _body(body, str(content_type), self.secrets)
        if 'json' not in kwargs and isinstance(body, Mapping):
            self.raw_request['body']['format'] = 'form'
        if kwargs.get('files') is not None:
            self.raw_request['files'] = _files(kwargs['files'])
        now = datetime.now(timezone.utc)
        identity = uuid4().hex
        self.event = {
            'timestamp': now.isoformat(), 'started_at': now.isoformat(), 'level': 'debug',
            'subsystem': 'http', 'operation': http_operation.get(),
            'http_tag': tag if tag in {'avito', 'spfa', 'notify', 'other'} else 'other',
            'phase': 'request', 'request_id': identity,
            'http_file': f'{now:%Y-%m-%d}/{now:%H%M%S%f}_{identity}.json',
            'method': str(method).upper(), 'url': _url(url, self.secrets),
            'request': _safe(self.raw_request, self.secrets),
        }
        self._emit()

    def _emit(self):
        event = self.event
        event['message'] = (f"HTTP {event['http_tag']} {event['phase']} {event['method']} {event['url']} "
                            f"status={event.get('status')} duration_ms={event.get('duration_ms')} "
                            f"request_id={event['request_id']} http_file={event['http_file']}")
        if event.get('error'):
            event['message'] += f" error={event['error']['type']}: {event['error']['message']}"
        record_http(event)

    def finish(self, response=None, error=None):
        self.event.update(timestamp=datetime.now(timezone.utc).isoformat(),
                          duration_ms=round((time.monotonic()-self.started)*1000, 3))
        if error is not None:
            self.event.update(phase='error', level='error',
                              error={'type': type(error).__name__, 'message': _text(str(error), self.secrets)})
        else:
            prepared = getattr(response, 'request', None)
            request_headers = _mapping(getattr(prepared, 'headers', None))
            _collect(request_headers, self.secrets)
            if request_headers:
                self.raw_request['sent_headers'] = request_headers
            prepared_url = getattr(prepared, 'url', None)
            if isinstance(prepared_url, str):
                _collect(dict(parse_qsl(urlsplit(prepared_url).query)), self.secrets)
                self.raw_request['sent_url'] = prepared_url
            headers = _mapping(getattr(response, 'headers', None))
            cookies = _mapping(getattr(response, 'cookies', None))
            _collect({'headers': headers, 'cookies': cookies}, self.secrets)
            content_type = next((v for k, v in headers.items() if k.lower() == 'content-type'), '')
            content = None if self.stream else getattr(response, 'content', None)
            if not isinstance(content, (bytes, str, Mapping, list)):
                content = None if self.stream else getattr(response, 'text', None)
            body = ({'format': 'stream', 'note': 'stream was not consumed'} if self.stream
                    else _body(content, str(content_type), self.secrets))
            status = getattr(response, 'status_code', None)
            status = status if isinstance(status, int) else None
            history = getattr(response, 'history', None)
            if isinstance(history, (list, tuple)):
                redirects = []
                for hop in history:
                    hop_headers = _mapping(getattr(hop, 'headers', None))
                    hop_request = getattr(hop, 'request', None)
                    hop_request_headers = _mapping(getattr(hop_request, 'headers', None))
                    _collect([hop_headers, hop_request_headers], self.secrets)
                    redirects.append({'status': hop.status_code, 'url': hop.url,
                                      'headers': hop_headers, 'request_headers': hop_request_headers,
                                      'body': _body(hop.content, str(hop_headers.get('Content-Type', '')), self.secrets)})
                if redirects:
                    self.event['redirects'] = _safe(redirects, self.secrets)
            self.event.update(phase='response', status=status,
                              level='warning' if status and status >= 400 else 'debug',
                              response={'headers': _safe(headers, self.secrets),
                                        'cookies': _safe(cookies, self.secrets, 'cookies'),
                                        'url': _url(getattr(response, 'url', None) or self.event['url'], self.secrets),
                                        'body': _safe(body, self.secrets)})
            if isinstance(content, (bytes, str)):
                self.event['response']['bytes'] = len(content if isinstance(content, bytes) else content.encode('utf-8'))
        self.event['request'] = _safe(self.raw_request, self.secrets)
        self._emit()


def http_call(tag, method, send, url, *, session=None, with_method=False, **kwargs):
    trace = None
    try:
        trace = HttpTrace(tag, method, url, session=session, **kwargs)
    except Exception as error:
        _audit_warning(error)
    try:
        response = send(method, url, **kwargs) if with_method else send(url, **kwargs)
    except BaseException as error:
        if trace is not None:
            try:
                trace.finish(error=error)
            except Exception as audit_error:
                _audit_warning(audit_error)
        raise
    if trace is not None:
        try:
            trace.finish(response)
        except Exception as error:
            _audit_warning(error)
    return response


class BrowserHttpLogger:
    """События Playwright: навигация, редиректы и ресурсы страницы без новых запросов."""

    def __init__(self, page, proxy=None):
        self.pending = {}
        self.proxy = proxy
        page.on('request', self.start)
        page.on('requestfinished', self.finish)
        page.on('requestfailed', self.failed)

    def start(self, request):
        try:
            self.pending[request] = HttpTrace(
                'avito', request.method, request.url, headers=request.all_headers(),
                data=request.post_data, proxy=self.proxy)
        except Exception as error:
            _audit_warning(error)

    def finish(self, request):
        trace = self.pending.pop(request, None)
        if trace is None:
            return
        try:
            response = request.response()
            if response is None:
                trace.finish(error=RuntimeError('Browser returned no response'))
                return
            headers = response.all_headers()
            try:
                content = response.body()
            except Exception:
                content = {'unavailable': True, 'reason': 'browser did not expose response body'}
            trace.finish(SimpleNamespace(status_code=response.status, url=response.url,
                                         headers=headers, content=content))
        except Exception as error:
            _audit_warning(error)

    def failed(self, request):
        trace = self.pending.pop(request, None)
        if trace is not None:
            try:
                trace.finish(error=RuntimeError(str(request.failure)))
            except Exception as error:
                _audit_warning(error)

    def close(self):
        for trace in list(self.pending.values()):
            try:
                trace.finish(error=RuntimeError('Browser closed before response completed'))
            except Exception as error:
                _audit_warning(error)
        self.pending.clear()
