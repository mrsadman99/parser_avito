"""Контракты, потерянные при декомпозиции; без браузера и внешней сети."""
import subprocess
import shlex
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from curl_cffi import requests as curl_requests
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.config import AvitoConfig, ServerConfig
from domain.item import Item, Rating
from engine import app as parser_app
from engine.cancellation import Cancellation, ParseCancelled
from engine.enrich import add_seller_rating
from engine.http.camoufox_client import CamoufoxClient
from engine.http.client import HttpClient
from engine.proxies.proxy import NoProxy
from server import app as server_app
from utils.logging_setup import log_category


def browser_client(**kwargs):
    client = CamoufoxClient(retry_delay=0, **kwargs)
    client.get_current_ip = Mock(return_value=None)
    client._reset = Mock()
    client._page = Mock()
    return client


@pytest.mark.parametrize("status", [404, 500])
def test_browser_returns_http_error_without_retry(status):
    client = browser_client(max_retries=4)
    client._page.goto.return_value = Mock(status=status, text=Mock(return_value="error body"))
    response = client.request("GET", "https://example.invalid")
    assert (response.status_code, response.text) == (status, "error body")
    client._page.goto.assert_called_once()
    client._reset.assert_not_called()
    assert client.error_count == 0


def test_browser_retains_block_count_across_network_error():
    proxy = Mock(rotate_with_retries=Mock(return_value=True))
    client = browser_client(proxy=proxy, max_retries=5, block_threshold=3)
    blocked = Mock(status=403, text=Mock(return_value="blocked"))
    client._page.goto.side_effect = [
        blocked, TimeoutError("offline"), blocked, blocked,
        Mock(status=200, text=Mock(return_value="ok")),
    ]
    assert client.request("GET", "https://example.invalid").status_code == 200
    proxy.rotate_with_retries.assert_called_once()
    assert client.block_count == 3
    assert client.error_count == 1
    assert client._block_attempts == 0


@pytest.mark.parametrize("stage", ["launch", "navigation"])
def test_browser_stops_at_cancellation_boundary(stage):
    client = browser_client()
    cancelled = threading.Event()
    response = Mock(status=200)
    page = client._page

    def launch():
        if stage == "launch":
            cancelled.set()
        return page

    def navigate(*args, **kwargs):
        cancelled.set()
        return response

    client._ensure_page = launch
    page.goto.side_effect = navigate
    with pytest.raises(ParseCancelled):
        client.request("GET", "https://example.invalid", cancellation=Cancellation(cancelled.is_set))
    assert page.goto.call_count == (0 if stage == "launch" else 1)
    response.text.assert_not_called()
    client._reset.assert_not_called()


def test_curl_keeps_retry_and_block_reset_semantics():
    with patch.object(HttpClient, "_build_client", return_value=Mock()):
        client = HttpClient(NoProxy(), max_retries=4, retry_delay=0, block_threshold=3)
    client._cookies_revision = None  # _build_client подменён и не инициализирует поле.
    client.get_current_ip = Mock(return_value=None)
    client.proxy = Mock()
    blocked = Mock(status_code=403)
    success = Mock(status_code=200)
    client._client.request.side_effect = [
        blocked, curl_requests.RequestsError("offline"), blocked, success,
    ]
    assert client.request("GET", "https://example.invalid") is success
    client.proxy.rotate_with_retries.assert_not_called()
    assert client.error_count == 1
    assert client.block_count == 2
    assert "cancellation" not in client._client.request.call_args.kwargs


def test_curl_ip_lookup_preserves_transport_and_fingerprint():
    with patch.object(HttpClient, "_build_client", return_value=Mock()):
        client = HttpClient(NoProxy())
    with patch("engine.http.client.requests.get", return_value=Mock(
        status_code=200, json=Mock(return_value={"ip": "192.0.2.1"}),
    )) as get:
        assert client.get_current_ip() == "192.0.2.1"
    get.assert_called_once_with(
        "https://api.ipify.org?format=json", proxies=None, timeout=10, impersonate="chrome",
    )


def test_curl_http_error_is_retried_unless_explicitly_accepted():
    with patch.object(HttpClient, "_build_client", return_value=Mock()):
        client = HttpClient(NoProxy(), max_retries=2, retry_delay=0)
    client._cookies_revision = None  # _build_client подменён и не инициализирует поле.
    client.get_current_ip = Mock(return_value=None)
    response = Mock(status_code=404)
    response.raise_for_status.side_effect = curl_requests.RequestsError("HTTP 404")
    client._client.request.return_value = response
    with pytest.raises(RuntimeError):
        client.request("GET", "https://example.invalid")
    assert client._client.request.call_count == 2
    assert client.error_count == 2
    client._client.request.reset_mock()
    assert client.request("GET", "https://example.invalid", accepted_statuses=(404,)) is response
    client._client.request.assert_called_once()


def test_zero_reviews_replaces_previous_value():
    ad = Item(id=1, rating=Rating(score=5, summary="0 отзывов"), seller_reviews=9)
    add_seller_rating([ad])
    assert ad.seller_reviews == 0


@pytest.mark.parametrize("value, expected", [
    (None, None), (123, 123), ("123", 123),
    ({"id": 123}, 123), ({"value": 123}, 123),
    ({"id": "123"}, 123), ({"value": "123"}, 123),
    ({"value": "invalid", "id": "123"}, 123), ({}, None),
])
def test_id_normalization(value, expected):
    ad = Item(id=value, categoryId=value, locationId=value)
    assert (ad.id, ad.categoryId, ad.locationId) == (expected,) * 3


def test_server_logs_are_not_scanning_logs():
    record = dict(name="server.app", file=SimpleNamespace(name="app.py"),
                  function="lifespan", extra={})
    assert log_category(record) is None


@pytest.mark.parametrize("failure", [None, KeyboardInterrupt(), RuntimeError("parse failed")])
def test_console_entrypoint_closes_parser(failure):
    parser = Mock()
    parser.parse.side_effect = failure
    with patch.object(parser_app, "configure_app_logging"), \
         patch.object(parser_app, "load_avito_config", return_value=AvitoConfig(use_bypass_api=False)), \
         patch.object(parser_app, "AvitoParse", return_value=parser):
        if isinstance(failure, RuntimeError):
            with pytest.raises(SystemExit) as exc:
                parser_app.main()
            assert exc.value.code == 1
        else:
            parser_app.main()
    parser.close.assert_called_once_with()


def test_module_entrypoint_without_pythonpath(tmp_path):
    root = Path(__file__).resolve().parent.parent
    # Изолированный каталог без config.toml: запуск должен дойти до его загрузки.
    for path in root.glob("*.py"):
        (tmp_path / path.name).symlink_to(path)
    for name in ("engine", "domain", "persistence", "notifications", "mobile_proxy", "utils"):
        (tmp_path / name).symlink_to(root / name, target_is_directory=True)
    command = shlex.split((root / "entrypoint.sh").read_text().splitlines()[-1])
    result = subprocess.run(
        [sys.executable, "-E", *command[1:]], cwd=tmp_path,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 1
    assert "Ошибка загрузки конфига" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr


def test_server_import_has_no_config_or_database_side_effects():
    code = """
from unittest.mock import patch
with patch('load_config.load_avito_config') as load, patch('persistence.store.init_db') as init:
    from server.main import app
    load.assert_not_called()
    init.assert_not_called()
"""
    result = subprocess.run(
        [sys.executable, "-E", "-c", code], cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("origins", [["https://frontend.example"], ["*"]])
def test_lazy_config_preserves_cors_and_lifespan(origins):
    config = AvitoConfig(server=ServerConfig(web_server_port=3456, cors_origins=origins))
    with patch.object(server_app, "_config", server_app._CONFIG_UNSET), \
         patch.object(server_app, "load_avito_config", return_value=config) as load, \
         patch.object(server_app.store, "init_db") as init:
        app = server_app.create_app()
        load.assert_not_called()
        with TestClient(app) as client:
            init.assert_called_once_with()
            for origin in ("http://localhost:3456", "https://frontend.example"):
                response = client.options("/api/links", headers={
                    "Origin": origin, "Access-Control-Request-Method": "POST",
                })
                assert response.status_code == 200
                assert response.headers["access-control-allow-origin"] == origin
            assert client.get("/api/health").json() == {"status": "ok"}
        load.assert_called_once_with("config.toml")


def test_failed_config_load_is_cached():
    with patch.object(server_app, "_config", server_app._CONFIG_UNSET), \
         patch.object(server_app, "load_avito_config", side_effect=ValueError("bad config")) as load:
        assert server_app.get_config() is None
        assert server_app.get_config() is None
        load.assert_called_once_with("config.toml")
