"""Локальные регрессии: временные базы, без Avito, SSH и мессенджеров."""
import importlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, call, patch

from fastapi.testclient import TestClient
from loguru import logger

from db_service import SQLiteDBHandler
from dto import AvitoConfig, LinkConfig, web_link_key
from integrations.notifications.base import Notifier
from integrations.notifications.composite import CompositeNotifier, NullNotifier
from integrations.notifications.telegram import TelegramNotifier
from integrations.notifications.vk import VKNotifier
from models import Item, PriceDetailed
from parser.cancellation import Cancellation, ParseCancelled
from parser.http.client import HttpClient
from parser.http.camoufox_client import CamoufoxClient
from parser.url_converter import AvitoUrlConverter
from parser.proxies.proxy import NoProxy, ProxyRotationError, ServerProxy, Proxy, ExternalMobileProxy
from parser.proxies.proxy_factory import build_proxy
from parser.proxies.rotation import rotate_with_retries
from load_config import load_avito_config
from server import store


def ad(ad_id=1, price=500):
    return Item(
        id=ad_id, title=f"Объявление {ad_id}", description="Описание",
        urlPath=f"/ad_{ad_id}", sortTimeStamp=1700000000000, images=[],
        priceDetailed=PriceDetailed(
            enabled=True, fullString=str(price), hasValue=True, postfix="",
            string=str(price), stringWithoutDiscount=None, title={},
            titleDative="", value=price, wasLowered=False, exponent="",
        ),
    )


class RecordingNotifier(Notifier):
    def __init__(self, key, fail=False):
        self.delivery_key = key
        self.fail = fail
        self.calls = []

    def notify(self, ad=None, message=None):
        self.calls.append(ad.id if ad else message)
        if self.fail:
            raise RuntimeError("Simulated delivery failure")


class FileRotationProxy(Proxy):
    """Исполняется в отдельном процессе, без доступа к телефону или сети."""
    def __init__(self, path, succeed_on=0, hang=False):
        self.path = path
        self.succeed_on = succeed_on
        self.hang = hang
        self.rotation_attempts = 3
        self.rotation_timeout = 5
        self.rotation_retry_delay = 0

    def get_httpx_proxy(self):
        return None

    def handle_block(self):
        path = Path(self.path)
        count = int(path.read_text()) + 1 if path.exists() else 1
        path.write_text(str(count))
        if self.hang:
            time.sleep(60)
        return self.succeed_on > 0 and count >= self.succeed_on


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="avito-tests-")
        self.cwd = Path.cwd()
        os.chdir(self.directory.name)
        self.original_db_path = store.DB_PATH
        store.DB_PATH = Path(self.directory.name) / "web.db"
        SQLiteDBHandler._instance = None
        store.init_db()
        self.server = importlib.import_module("server.main")
        self.parser_module = importlib.import_module("parser_cls")
        logger.remove()
        self.client = TestClient(self.server.app)
        self.db = SQLiteDBHandler()
        self.url = "https://www.avito.ru/novosibirsk?q=test"
        self.workers = []

    def tearDown(self):
        for parser, thread in self.workers:
            parser.stop_event.set()
            thread.join(timeout=2)
        self.client.close()
        SQLiteDBHandler._instance = None
        store.DB_PATH = self.original_db_path
        os.chdir(self.cwd)
        self.directory.cleanup()

    def user(self, name):
        user = store.register(name, "test-password")
        return user["id"], {"Authorization": f"Bearer {store.login(name, 'test-password')}"}

    def parser(self, notifier=None):
        parser = self.parser_module.AvitoParse.__new__(self.parser_module.AvitoParse)
        parser.config = AvitoConfig()
        parser.links_provider = store.get_all_links
        parser.db_handler = self.db
        parser.notifier = notifier or NullNotifier()
        parser.result_storage = Mock()
        parser.stop_event = None
        parser._shutdown = threading.Event()
        parser._fatal_error = None
        parser.throttle = self.parser_module.RequestThrottle(0, 0)
        return parser

    def scan(self, parser, key, config=None, ads=None, url=None):
        parser.fetch_api_data = Mock(return_value={"items": [
            item.model_dump(mode="json") for item in (ads or [ad()])
        ]})
        parser._process_link(url or self.url, config or LinkConfig(), "https://example.invalid", key)

    def start_link_worker(self, parser, key):
        parser.stop_event = threading.Event()
        parser.url_converter = Mock(convert=Mock(return_value="https://example.invalid"))
        thread = threading.Thread(target=parser._link_cycle,
                                  args=(key, store.get_all_links()[key]), daemon=True)
        self.workers.append((parser, thread))
        thread.start()
        return thread

    def test_edit_during_page_response_restarts_at_first_page_without_old_results(self):
        owner, headers = self.user("owner")
        link = store.create_link(owner, {"url": self.url})
        key = next(iter(store.get_all_links()))
        parser = self.parser(RecordingNotifier("recipient"))
        parser.config.count = 2
        pages = []

        def fetch(api_url, page, cancellation):
            pages.append(page)
            if len(pages) == 2:
                response = self.client.put(f"/api/links/{link['id']}", headers=headers,
                                           json={"url": self.url, "min_price": 900})
                self.assertEqual(response.status_code, 200)
            item = ad(len(pages), 1000 if len(pages) == 3 else 500)
            return {"items": [item.model_dump(mode="json")]}

        parser.fetch_api_data = fetch
        parser.result_storage.save.side_effect = lambda ads: (
            parser.stop_event.set() if ads[0].id == 3 else None
        )
        thread = self.start_link_worker(parser, key)
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(pages, [1, 2, 1])
        self.assertEqual([row["id"] for row in self.db.list_ads(self.url)], [1, 3])
        self.assertEqual([row["ad_id"] for row in self.db.pending_notifications(["recipient"])], [1, 3])
        self.assertEqual(parser.result_storage.save.call_count, 2)

    def test_delete_during_page_response_stops_without_saving_or_next_page(self):
        owner, headers = self.user("owner")
        link = store.create_link(owner, {"url": self.url})
        key = next(iter(store.get_all_links()))
        parser = self.parser()
        parser.config.count = 2

        def fetch(**kwargs):
            self.assertEqual(self.client.delete(f"/api/links/{link['id']}", headers=headers).status_code, 200)
            return {"items": [ad().model_dump(mode="json")]}

        parser.fetch_api_data = Mock(side_effect=fetch)
        thread = self.start_link_worker(parser, key)
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(parser.fetch_api_data.call_count, 1)
        self.assertEqual(self.db.list_ads(self.url), [])
        parser.result_storage.save.assert_not_called()

    def test_edit_and_delete_interrupt_general_pause(self):
        owner, _ = self.user("owner")
        link = store.create_link(owner, {"url": self.url})
        key = next(iter(store.get_all_links()))
        parser = self.parser()
        parser.config.pause_general = 300
        first = threading.Event()
        second = threading.Event()
        calls = []

        def process(url, config, api_url, **kwargs):
            calls.append(config.min_price)
            (first if len(calls) == 1 else second).set()

        parser._process_link = process
        thread = self.start_link_worker(parser, key)
        self.assertTrue(first.wait(timeout=1))
        # Admin updates must advance the same version as ordinary user updates.
        store.update_link_any(link["id"], {"url": self.url, "min_price": 100})
        self.assertTrue(second.wait(timeout=1))
        store.delete_link_any(link["id"])
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(calls, [None, 100])

    def test_reverted_filters_still_cancel_old_revision(self):
        owner, _ = self.user("owner")
        link = store.create_link(owner, {"url": self.url})
        key = next(iter(store.get_all_links()))
        original = store.get_all_links()[key]
        store.update_link(owner, link["id"], {"url": self.url, "min_price": 100})
        store.update_link(owner, link["id"], {"url": self.url})
        current = store.get_all_links()[key]
        self.assertEqual(current.config, original.config)
        self.assertNotEqual(current, original)

    def test_change_to_another_subscription_does_not_cancel_current_one(self):
        owner, _ = self.user("owner")
        a = store.create_link(owner, {"url": self.url})
        b = store.create_link(owner, {"url": self.url})
        key = web_link_key(a["id"], self.url)
        original = store.get_all_links()[key]
        store.update_link(owner, b["id"], {"url": self.url, "min_price": 100})
        self.assertEqual(store.get_all_links()[key], original)

    def test_throttle_waiting_for_lock_can_be_cancelled(self):
        throttle = self.parser_module.RequestThrottle(0, 0)
        throttle._lock.acquire()
        cancelled = threading.Event()
        done = threading.Event()
        requested = Mock()

        def wait_for_lock():
            try:
                throttle.run(requested, cancellation=Cancellation(cancelled.is_set))
            except ParseCancelled:
                done.set()

        thread = threading.Thread(target=wait_for_lock, daemon=True)
        thread.start()
        try:
            cancelled.set()
            self.assertTrue(done.wait(timeout=1))
            requested.assert_not_called()
        finally:
            throttle._lock.release()
            thread.join(timeout=1)

    def test_throttle_delay_cancellation_releases_lock(self):
        throttle = self.parser_module.RequestThrottle(60, 60)
        throttle.run(lambda: None)
        cancelled = threading.Event()
        requested = Mock()
        with patch("parser.cancellation.time.sleep", side_effect=lambda _: cancelled.set()):
            with self.assertRaises(ParseCancelled):
                throttle.run(requested, cancellation=Cancellation(cancelled.is_set))
        requested.assert_not_called()
        self.assertFalse(throttle._lock.locked())

    def test_http_cancelled_response_has_no_retries_or_cookie_updates(self):
        client = HttpClient.__new__(HttpClient)
        client.get_current_ip = Mock(return_value=None)
        client.max_retries = 5
        client.timeout = 30
        client.cookies = Mock()
        client._client = Mock()
        cancelled = threading.Event()

        def respond(*args, **kwargs):
            cancelled.set()
            return Mock(status_code=403)

        client._client.request.side_effect = respond
        with self.assertRaises(ParseCancelled):
            client.request("GET", self.url, cancellation=Cancellation(cancelled.is_set))
        self.assertEqual(client._client.request.call_count, 1)
        client.cookies.update.assert_not_called()

    def test_http_retry_delay_is_interruptible(self):
        client = HttpClient.__new__(HttpClient)
        client.get_current_ip = Mock(return_value=None)
        client.max_retries = 5
        client.timeout = 30
        client.cookies = None
        client._client = Mock()
        client._client.request.return_value = Mock(status_code=403)
        client._block_attempts = client.block_count = 0
        client.block_threshold = 3
        client.retry_delay = 60
        cancelled = threading.Event()
        with patch("parser.cancellation.time.sleep", side_effect=lambda _: cancelled.set()):
            with self.assertRaises(ParseCancelled):
                client.request("GET", self.url, cancellation=Cancellation(cancelled.is_set))
        self.assertEqual(client._client.request.call_count, 1)

    def rotation_http_client(self):
        client = HttpClient.__new__(HttpClient)
        client.get_current_ip = Mock(return_value=None)
        client.max_retries = 2
        client.timeout = 30
        client.cookies = Mock()
        client.proxy = Mock()
        client.proxy.rotate_with_retries.side_effect = lambda cancellation: client.proxy.handle_block()
        client._client = Mock()
        client._client.request.return_value = Mock(status_code=403)
        client._reset_client = Mock()
        client._block_attempts = client.block_count = client.error_count = 0
        client.block_threshold = 1
        client.retry_delay = 0
        return client

    def test_failed_ip_rotation_preserves_http_session_and_cookies(self):
        for proxy in (Mock(handle_block=Mock(return_value=False)), NoProxy(), ServerProxy("test:8080")):
            with self.subTest(proxy=type(proxy).__name__):
                client = self.rotation_http_client()
                client.proxy = proxy
                if isinstance(proxy, Mock):
                    proxy.rotate_with_retries.side_effect = lambda cancellation: proxy.handle_block()
                else:
                    proxy.rotation_attempts = 1
                    proxy.rotation_retry_delay = 0
                with self.assertRaisesRegex(ProxyRotationError, "Не удалось сменить IP"):
                    client.request("GET", self.url)
                client.cookies.handle_block.assert_not_called()
                client.cookies.handle_ip_change.assert_not_called()
                client._reset_client.assert_not_called()
                self.assertEqual(client._client.request.call_count, 1)
                self.assertEqual(client.get_current_ip.call_count, 1)
                self.assertEqual(client._block_attempts, 1)

    def test_ip_rotation_exception_does_not_rebuild_http_session(self):
        client = self.rotation_http_client()
        failure = RuntimeError("Simulated proxy failure")
        client.proxy.handle_block.side_effect = failure
        with self.assertRaises(ProxyRotationError) as result:
            client.request("GET", self.url)
        self.assertIs(result.exception.__cause__, failure)
        client.cookies.handle_block.assert_not_called()
        client.cookies.handle_ip_change.assert_not_called()
        client._reset_client.assert_not_called()
        self.assertEqual(client._client.request.call_count, 1)

    def test_successful_ip_rotation_refreshes_http_session_before_retry(self):
        client = self.rotation_http_client()
        client.proxy.handle_block.return_value = True
        success = Mock(status_code=200)
        client._client.request.side_effect = [Mock(status_code=403), success]
        sequence = Mock()
        sequence.attach_mock(client.proxy.handle_block, "rotate")
        sequence.attach_mock(client.cookies.handle_block, "invalidate")
        sequence.attach_mock(client.cookies.handle_ip_change, "refresh")
        sequence.attach_mock(client._reset_client, "reset")
        self.assertIs(client.request("GET", self.url), success)
        self.assertEqual(sequence.mock_calls, [call.rotate(), call.invalidate(), call.refresh(), call.reset()])
        self.assertEqual(client._client.request.call_count, 2)
        self.assertEqual(client._block_attempts, 0)

    def test_rotation_completed_after_cancellation_does_not_refresh_session(self):
        client = self.rotation_http_client()
        cancelled = threading.Event()

        def rotate():
            cancelled.set()
            return True

        client.proxy.handle_block.side_effect = rotate
        with self.assertRaises(ParseCancelled):
            client.request("GET", self.url, cancellation=Cancellation(cancelled.is_set))
        client.cookies.handle_block.assert_not_called()
        client.cookies.handle_ip_change.assert_not_called()
        client._reset_client.assert_not_called()

    def test_failed_ip_rotation_does_not_restart_camoufox(self):
        for outcome in (False, RuntimeError("Simulated proxy failure")):
            with self.subTest(outcome=type(outcome).__name__):
                proxy = Mock()
                if isinstance(outcome, Exception):
                    proxy.handle_block.side_effect = outcome
                else:
                    proxy.handle_block.return_value = outcome
                proxy.rotate_with_retries.side_effect = lambda cancellation: proxy.handle_block()
                client = CamoufoxClient(proxy=proxy, max_retries=2, block_threshold=1, retry_delay=0)
                client.get_current_ip = Mock(return_value=None)
                client._reset = Mock()
                page = Mock()
                page.goto.return_value = Mock(status=403, text=Mock(return_value="blocked"))
                client._ensure_page = Mock(return_value=page)
                with self.assertRaises(ProxyRotationError):
                    client.request("GET", self.url)
                client._reset.assert_not_called()
                self.assertEqual(page.goto.call_count, 1)

    def test_successful_ip_rotation_restarts_camoufox_before_retry(self):
        proxy = Mock(handle_block=Mock(return_value=True))
        proxy.rotate_with_retries.side_effect = lambda cancellation: proxy.handle_block()
        client = CamoufoxClient(proxy=proxy, max_retries=2, block_threshold=1, retry_delay=0)
        client.get_current_ip = Mock(return_value=None)
        client._reset = Mock()
        page = Mock()
        page.goto.side_effect = [Mock(status=403, text=lambda: "blocked"), Mock(status=200, text=lambda: "ok")]
        client._ensure_page = Mock(return_value=page)
        response = client.request("GET", self.url)
        self.assertEqual(response.status_code, 200)
        client._reset.assert_called_once()
        self.assertEqual(page.goto.call_count, 2)

    def test_camoufox_cancellation_does_not_reset_browser(self):
        client = CamoufoxClient()
        client.get_current_ip = Mock(return_value=None)
        client._reset = Mock()
        page = Mock()
        client._ensure_page = Mock(return_value=page)
        cancelled = threading.Event()
        page.goto.side_effect = lambda *args, **kwargs: cancelled.set()
        with self.assertRaises(ParseCancelled):
            client.request("GET", self.url, cancellation=Cancellation(cancelled.is_set))
        client._reset.assert_not_called()
        self.assertEqual(page.goto.call_count, 1)

    def test_ip_rotation_retries_false_and_exception_until_success(self):
        proxy = NoProxy()
        proxy.rotation_attempts = 3
        proxy.rotation_retry_delay = 0
        with patch("parser.proxies.rotation._rotation_attempt", side_effect=[
            (False, "failed"), RuntimeError("failed again"), (True, None),
        ]) as attempt:
            self.assertTrue(rotate_with_retries(proxy))
        self.assertEqual(attempt.call_count, 3)

    def test_ip_rotation_stops_after_configured_attempt_count(self):
        proxy = NoProxy()
        proxy.rotation_attempts = 2
        proxy.rotation_retry_delay = 0
        with patch("parser.proxies.rotation._rotation_attempt", return_value=(False, "failed")) as attempt:
            with self.assertRaisesRegex(ProxyRotationError, "после 2 попыток"):
                rotate_with_retries(proxy)
        self.assertEqual(attempt.call_count, 2)

    def test_ip_rotation_retry_pause_honours_cancellation(self):
        proxy = NoProxy()
        proxy.rotation_retry_delay = 300
        cancelled = threading.Event()
        with patch("parser.proxies.rotation._rotation_attempt", return_value=(False, "failed")) as attempt, \
                patch("parser.cancellation.time.sleep", side_effect=lambda _: cancelled.set()):
            with self.assertRaises(ParseCancelled):
                rotate_with_retries(proxy, cancellation=Cancellation(cancelled.is_set))
        self.assertEqual(attempt.call_count, 1)

    def test_real_rotation_worker_retries_without_network(self):
        proxy = FileRotationProxy(str(Path.cwd() / "rotation-count"), succeed_on=2)
        self.assertTrue(rotate_with_retries(proxy))
        self.assertEqual(Path(proxy.path).read_text(), "2")

    def test_real_rotation_worker_timeout_kills_attempt(self):
        proxy = FileRotationProxy(str(Path.cwd() / "rotation-count"), hang=True)
        proxy.rotation_attempts = 1
        proxy.rotation_timeout = 1.5
        started = time.monotonic()
        with self.assertRaisesRegex(ProxyRotationError, "таймаут"):
            rotate_with_retries(proxy)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(Path(proxy.path).read_text(), "1")

    def test_external_proxy_visits_each_fallback_once_per_attempt(self):
        proxy = ExternalMobileProxy("example.invalid:8080", ["https://first.invalid", "https://second.invalid"])
        with patch("parser.proxies.proxy.requests.get", side_effect=[
            Mock(status_code=500), Mock(status_code=200, json=lambda: {"new_ip": "192.0.2.1"}),
        ]) as get:
            self.assertTrue(proxy.handle_block())
        self.assertEqual(get.call_count, 2)

    def test_rotation_config_is_loaded_and_applied_to_proxy(self):
        Path("config.toml").write_text(
            "[avito]\nip_rotation_attempts = 7\nip_rotation_timeout = 12.5\nip_rotation_retry_delay = 0.25\n"
        )
        config = load_avito_config()
        proxy = build_proxy(config)
        self.assertEqual(proxy.rotation_attempts, 7)
        self.assertEqual(proxy.rotation_timeout, 12.5)
        self.assertEqual(proxy.rotation_retry_delay, 0.25)

    def test_invalid_rotation_settings_are_rejected(self):
        for settings in ({"ip_rotation_attempts": 0}, {"ip_rotation_attempts": 1.5},
                         {"ip_rotation_timeout": 0}, {"ip_rotation_timeout": float("inf")},
                         {"ip_rotation_retry_delay": -1}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                AvitoConfig(**settings)

    def test_rotation_failure_stops_all_parser_workers_and_reaches_main_loop(self):
        owner, _ = self.user("owner")
        store.create_link(owner, {"url": self.url})
        parser = self.parser()
        parser.http = Mock(get_current_ip=Mock(return_value=None))
        parser.url_converter = Mock(convert=Mock(return_value="https://example.invalid"))
        failure = ProxyRotationError("all rotation attempts failed")
        parser._process_link = Mock(side_effect=failure)
        with patch.object(self.parser_module, "build_result_storage", return_value=Mock()):
            with self.assertRaises(ProxyRotationError) as result:
                parser.parse()
        self.assertIs(result.exception, failure)
        self.assertTrue(parser._shutdown.is_set())
        self.assertTrue(parser._is_stopped())
        self.assertEqual(parser._process_link.call_count, 1)

    def test_rotation_failure_is_not_swallowed_by_fetch_methods(self):
        parser = self.parser()
        parser._request = Mock(side_effect=ProxyRotationError("all attempts failed"))
        with self.assertRaises(ProxyRotationError):
            parser.fetch_data(self.url)
        with self.assertRaises(ProxyRotationError):
            parser.fetch_api_data(self.url, 1)

    def test_console_parser_exits_nonzero_after_rotation_failure(self):
        project = str(Path(self.parser_module.__file__).parent)
        code = (
            "import sys\nfrom unittest.mock import Mock, patch\n"
            f"sys.path.insert(0, {project!r})\n"
            "from parser.proxies.proxy import ProxyRotationError\n"
            "from scripts.run_parser import main\n"
            "parser = Mock()\nparser.parse.side_effect = ProxyRotationError('rotation exhausted')\n"
            "with patch('scripts.run_parser.load_avito_config'), patch('server.store.init_db'), "
            "patch('parser_cls.AvitoParse', return_value=parser):\n    main()\n"
        )
        result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn("rotation exhausted", result.stderr)

    def test_url_conversion_rate_limit_is_interruptible(self):
        converter = AvitoUrlConverter(min_request_interval=60)
        cancelled = threading.Event()
        with patch.object(AvitoUrlConverter, "_last_request_at", time.monotonic()), \
                patch("parser.cancellation.time.sleep", side_effect=lambda _: cancelled.set()), \
                patch("parser.url_converter.requests.post") as post:
            with self.assertRaises(ParseCancelled):
                converter.convert(self.url, cancellation=Cancellation(cancelled.is_set))
        post.assert_not_called()
        self.assertFalse(converter._request_lock.locked())

    def test_cancelled_conversion_caches_url_for_restarted_scan(self):
        converter = AvitoUrlConverter(min_request_interval=0)
        cancelled = threading.Event()

        def respond(*args, **kwargs):
            cancelled.set()
            return Mock(status_code=200, json=lambda: {"success": True, "api_url": "https://example.invalid"})

        with patch("parser.url_converter.requests.post", side_effect=respond) as post:
            with self.assertRaises(ParseCancelled):
                converter.convert(self.url, cancellation=Cancellation(cancelled.is_set))
            self.assertEqual(converter.convert(self.url), "https://example.invalid")
        self.assertEqual(post.call_count, 1)

    def test_provider_failure_does_not_look_like_link_deletion(self):
        owner, _ = self.user("owner")
        store.create_link(owner, {"url": self.url})
        parser = self.parser()
        original = parser._current_links()
        parser.links_provider = Mock(side_effect=sqlite3.OperationalError("database is locked"))
        self.assertEqual(parser._current_links(), original)

    def test_full_description_response_is_discarded_after_cancel(self):
        parser = self.parser()
        parser.config.open_full_ad = True
        cancelled = threading.Event()

        def fetch(**kwargs):
            cancelled.set()
            return "<html>stale description</html>"

        parser.fetch_data = Mock(side_effect=fetch)
        parser._extract_description = Mock()
        with self.assertRaises(ParseCancelled):
            parser.open_full_ad([ad(), ad(2)], cancellation=Cancellation(cancelled.is_set))
        self.assertEqual(parser.fetch_data.call_count, 1)
        parser._extract_description.assert_not_called()

    def test_ads_require_owner_even_when_both_users_have_same_url(self):
        first, first_headers = self.user("first")
        second, second_headers = self.user("second")
        a = store.create_link(first, {"url": self.url})
        b = store.create_link(second, {"url": self.url})
        self.db.add_record_from_page([ad(1)], self.url, web_link_key(a["id"], self.url))
        self.db.add_record_from_page([ad(2)], self.url, web_link_key(b["id"], self.url))
        self.db.add_record_from_page([ad(3)], self.url)  # legacy/config history
        denied = self.client.get("/api/ads", params={"link_id": a["id"]}, headers=second_headers)
        self.assertEqual(denied.status_code, 404)
        own = self.client.get("/api/ads", params={"link_id": a["id"]}, headers=first_headers)
        self.assertEqual([row["id"] for row in own.json()], [1])
        by_url = self.client.get("/api/ads", params={"url": self.url}, headers=second_headers)
        self.assertEqual([row["id"] for row in by_url.json()], [2])
        self.assertEqual(self.client.get("/api/ads", params={"url": self.url}).status_code, 401)
        self.assertEqual(self.client.get("/api/ads", params={"url": self.url + "x"},
                                        headers=first_headers).status_code, 404)
        self.assertEqual(self.client.get("/api/ads", headers=first_headers).status_code, 422)
        store.delete_link(first, a["id"])
        self.assertEqual(self.client.get("/api/ads", params={"link_id": a["id"]},
                                        headers=first_headers).status_code, 404)

    def test_admin_can_read_owned_and_legacy_results(self):
        user_id, _ = self.user("owner")
        link = store.create_link(user_id, {"url": self.url})
        self.db.add_record_from_page([ad(1)], self.url, web_link_key(link["id"], self.url))
        self.db.add_record_from_page([ad(2)], self.url)
        with patch.object(self.server, "_ADMIN_PASSWORD", "test"), patch.object(self.server, "_ADMIN_TOKEN", "admin-token"):
            headers = {"Authorization": "Bearer admin-token"}
            response = self.client.get("/api/ads", params={"link_id": link["id"]}, headers=headers)
            self.assertEqual([row["id"] for row in response.json()], [1])
            response = self.client.get("/api/ads", params={"url": self.url}, headers=headers)
            self.assertEqual(len(response.json()), 2)

    def test_same_url_keeps_independent_filters_and_results(self):
        first, _ = self.user("first")
        second, _ = self.user("second")
        store.create_link(first, {"url": self.url, "max_price": 200})
        store.create_link(second, {"url": self.url, "min_price": 400})
        parser = self.parser()
        parser.config.links = {self.url: LinkConfig()}
        targets = parser._current_links()
        self.assertEqual(len(targets), 3)
        for key, target in targets.items():
            self.scan(parser, key, target.config, [ad(1, 100), ad(2, 500)])
        web_keys = list(store.get_all_links())
        self.assertEqual([r["id"] for r in self.db.list_ads(self.url, [web_keys[0]])], [1])
        self.assertEqual([r["id"] for r in self.db.list_ads(self.url, [web_keys[1]])], [2])
        self.assertEqual(len(self.db.list_ads(self.url, [self.url])), 2)

    def test_url_edit_creates_new_history_for_same_link(self):
        user_id, _ = self.user("owner")
        link = store.create_link(user_id, {"url": self.url})
        old_key = next(iter(store.get_all_links()))
        parser = self.parser()
        self.scan(parser, old_key)
        new_url = self.url + "&p=2"
        store.update_link(user_id, link["id"], {"url": new_url})
        new_key = next(iter(store.get_all_links()))
        self.assertNotEqual(old_key, new_key)
        self.scan(parser, new_key, url=new_url)
        self.assertEqual(len(self.db.list_ads(new_url, [new_key])), 1)

    def test_repeat_scan_and_overlapping_searches(self):
        parser = self.parser()
        for key in ("first", "second", "first"):
            self.scan(parser, key)
        self.assertEqual(len(self.db.list_ads(self.url)), 2)
        self.scan(parser, "first", ads=[ad(price=600)])
        self.assertEqual(len(self.db.list_ads(self.url, ["first"])), 2)

    def test_storage_deduplicates_and_preserves_price_changes(self):
        for _ in range(2):
            self.db.add_record_from_page([ad(), ad()], self.url, "first", ["recipient"])
        self.db.add_record_from_page([ad(price=600)], self.url, "first", ["recipient"])
        self.db.add_record_from_page([ad()], self.url, "second", ["recipient"])
        self.assertEqual(len(self.db.list_ads(self.url)), 3)
        self.assertEqual(len(self.db.pending_notifications(["recipient"])), 3)
        self.assertFalse(self.db.record_exists(1, 500, "third"))

    def test_failed_recipient_retries_after_restart_without_resending_success(self):
        success = RecordingNotifier("success")
        failure = RecordingNotifier("failure", fail=True)
        notifier = CompositeNotifier([success, failure])
        parser = self.parser(notifier)
        self.scan(parser, "first")
        parser._deliver_pending_notifications()
        self.assertEqual(success.calls, [1])
        self.assertEqual(failure.calls, [1])
        self.assertEqual(self.db.pending_notifications(["failure"]), [])  # backoff
        SQLiteDBHandler._instance = None
        self.db = SQLiteDBHandler()
        resumed = self.parser(notifier)
        failure.fail = False
        with patch("db_service.time.time", return_value=time.time() + 61):
            resumed._deliver_pending_notifications()
        self.assertEqual(success.calls, [1])
        self.assertEqual(failure.calls, [1, 1])
        self.assertEqual(self.db.pending_notifications(["success", "failure"]), [])
        self.scan(resumed, "first")
        self.assertEqual(len(self.db.list_ads(self.url)), 1)

    def test_queue_and_result_roll_back_together(self):
        with sqlite3.connect(self.db.db_name) as conn:
            conn.execute("""CREATE TRIGGER reject_notification BEFORE INSERT ON notification_outbox
                            BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.add_record_from_page([ad()], self.url, "first", ["recipient"])
        self.assertEqual(self.db.list_ads(self.url), [])

    def test_notification_lease_prevents_concurrent_delivery_and_expires(self):
        self.db.add_record_from_page([ad()], self.url, "first", ["recipient"])
        claimed = self.db.claim_notification(["recipient"])
        self.assertIsNotNone(claimed)
        self.assertIsNone(self.db.claim_notification(["recipient"]))
        with patch("db_service.time.time", return_value=time.time() + 601):
            retried = self.db.claim_notification(["recipient"])
        self.assertEqual(claimed["id"], retried["id"])

    def test_legacy_unassigned_rows_can_be_migrated_with_existing_results(self):
        self.db.add_record(ad())
        self.db.add_record_from_page([ad()], self.url)
        with sqlite3.connect(self.db.db_name) as conn:
            rowid = conn.execute("SELECT rowid FROM viewed WHERE source_url IS NULL").fetchone()[0]
        migrate = importlib.import_module("scripts.migrate_ads")
        migrate.assign_row(self.url, rowid)
        self.assertEqual(len(self.db.list_ads(self.url, [self.url])), 1)

    def test_migration_keeps_backup_and_latest_duplicate(self):
        with sqlite3.connect("legacy.db") as conn:
            conn.execute("CREATE TABLE viewed(id INTEGER, price INTEGER, source_url TEXT, description TEXT)")
            conn.executemany("INSERT INTO viewed VALUES (?, ?, ?, ?)", [
                (1, 500, self.url, "old"), (1, 500, self.url, "latest"),
                (1, 600, self.url, "changed price"), (2, 100, None, "unassigned"),
            ])
        SQLiteDBHandler._instance = None
        db = SQLiteDBHandler("legacy.db")
        rows = db.list_ads(self.url, [self.url])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["description"], "latest")
        self.assertTrue(db.record_exists(2, 100))
        backups = list(Path(".").glob("legacy.db.before-subscriptions-*.bak"))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(backups[0]) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM viewed").fetchone()[0], 4)
        SQLiteDBHandler._instance = None
        SQLiteDBHandler("legacy.db")
        self.assertEqual(len(list(Path(".").glob("*.bak"))), 1)

    def test_refresh_can_merge_equal_prices_without_crossing_subscriptions(self):
        for key in ("first", "second"):
            self.db.add_record_from_page([ad(price=500), ad(price=600)], self.url, key)
        self.db.update_ad(1, {"price": 700, "title": "Updated"})
        rows = self.db.list_ads(self.url)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["source_key"] for row in rows}, {"first", "second"})
        self.assertTrue(all(row["price"] == 700 for row in rows))

    def test_recipient_keys_survive_token_rotation(self):
        self.assertEqual(TelegramNotifier("123:old", "42").delivery_key,
                         TelegramNotifier("123:new", "42").delivery_key)
        self.assertNotEqual(TelegramNotifier("123:old", "42").delivery_key,
                            TelegramNotifier("123:old", "43").delivery_key)
        self.assertEqual(VKNotifier("old", "42").delivery_key, VKNotifier("new", "42").delivery_key)

    def test_vk_api_error_is_not_reported_as_delivery_success(self):
        notifier = VKNotifier("test", "42")
        with patch("integrations.notifications.vk.send_with_retries", return_value=Mock(
                json=lambda: {"error": {"error_code": 901, "error_msg": "Denied"}})):
            with self.assertRaises(RuntimeError):
                notifier.notify(ad=ad())


if __name__ == "__main__":
    unittest.main()
