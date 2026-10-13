import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from dto import AvitoConfig
from load_config import load_avito_config
from parser.cancellation import Cancellation, ParseCancelled
from parser.cookies.external_api import ExternalApiCookiesProvider
from parser.http.base import BaseHttpClient, UnblockTimeoutError


class ScriptedClient(BaseHttpClient):
    def _send(self, method, url, **kwargs):
        return self.send(method, url, **kwargs)

    def _reset(self):
        self.resets += 1

    def close(self):
        pass


class SpfaWaitTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = 1000.0
        self.clock = patch('time.monotonic', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.provider = ExternalApiCookiesProvider(
            AvitoConfig(), storage_path=Path(self.directory.name) / 'cookies.json')
        self.provider.last_id = 'test-id'
        self.provider.last_cookies = {'test': 'cookie'}
        self.provider._save_to_disk = Mock()
        self.provider._get_new_cookies = Mock()
        self.post = patch('parser.cookies.external_api.requests.post',
                          return_value=Mock(status_code=202)).start()
        self.addCleanup(patch.stopall)
        self.client = ScriptedClient(Mock(rotate_with_retries=Mock(return_value=True)),
                                     cookies=self.provider, max_retries=2, block_threshold=1)
        self.client.get_current_ip = Mock(return_value=None)
        self.client.resets = 0
        self.sent = []
        self.statuses = []
        self.client.send = Mock(side_effect=self.send)
        self.cancellation = Cancellation()
        self.cancellation.wait = self.wait

    def wait(self, seconds):
        self.now += seconds

    def send(self, method, url, **kwargs):
        self.sent.append(self.now)
        status = self.statuses.pop(0) if self.statuses else 429
        if isinstance(status, Exception):
            raise status
        response = requests.Response()
        response.status_code = status
        response.url = url
        return response

    def request(self):
        return self.client.request('GET', 'https://m.avito.ru/test', cancellation=self.cancellation)

    def test_success_after_ordinary_budget_with_one_ip_rotation(self):
        self.statuses = [429] * 5 + [200]
        self.assertEqual(self.request().status_code, 200)
        self.assertEqual(self.sent, [1000, 1030, 1060, 1090, 1120, 1150])
        self.client.proxy.rotate_with_retries.assert_called_once()
        self.post.assert_called_once()
        self.assertEqual(self.client.resets, 1)
        self.assertIsNone(self.provider.get_unblock_state())
        self.provider._get_new_cookies.assert_not_called()

    def test_timeout_finishes_current_request_without_restarting_unblock(self):
        self.provider.UNBLOCK_TIMEOUT = 90
        with self.assertRaisesRegex(UnblockTimeoutError, 'последний HTTP-статус: 429'):
            self.request()
        self.assertEqual(self.sent, [1000, 1030, 1060])
        self.assertEqual(self.now, 1090)
        self.client.proxy.rotate_with_retries.assert_called_once()
        self.post.assert_called_once()
        self.assertIsNone(self.provider.get_unblock_state())
        # Следующее задание может начать новый цикл; старое не зациклилось.
        self.statuses = [429, 200]
        self.assertEqual(self.request().status_code, 200)
        self.assertEqual(self.post.call_count, 2)

    def test_pending_task_survives_request_boundary_without_rotation(self):
        self.provider.unblock_started_at = 970
        self.statuses = [429, 200]
        self.assertEqual(self.request().status_code, 200)
        self.assertEqual(self.sent, [1030, 1060])
        self.client.proxy.rotate_with_retries.assert_not_called()
        self.post.assert_not_called()

    def test_pending_task_prevents_direct_rotation_and_cookie_purchase(self):
        self.provider.unblock_started_at = self.now
        self.provider.status_history = [429] * 20
        self.provider.purchase_cooldown = 0
        self.provider.handle_block()
        self.client._rotate(self.cancellation)
        self.provider._get_new_cookies.assert_not_called()
        self.client.proxy.rotate_with_retries.assert_not_called()
        self.post.assert_not_called()

    def test_network_errors_during_probes_do_not_change_ip_or_extend_deadline(self):
        self.provider.UNBLOCK_TIMEOUT = 90
        self.statuses = [429, requests.ConnectionError('offline'), requests.Timeout('timeout')]
        with self.assertRaises(UnblockTimeoutError):
            self.request()
        self.assertEqual(self.sent, [1000, 1030, 1060])
        self.assertEqual(self.now, 1090)
        self.client.proxy.rotate_with_retries.assert_called_once()

    def test_cancellation_during_wait_preserves_active_task(self):
        self.cancellation.wait = Mock(side_effect=ParseCancelled)
        with self.assertRaises(ParseCancelled):
            self.request()
        self.assertEqual(self.sent, [1000])
        self.assertIsNotNone(self.provider.get_unblock_state())
        self.cancellation.wait = self.wait
        self.statuses = [200]
        self.assertEqual(self.request().status_code, 200)
        self.client.proxy.rotate_with_retries.assert_called_once()

    def test_unblock_on_last_ordinary_attempt_still_gets_control_request(self):
        self.client.block_threshold = 2
        self.statuses = [429, 429, 200]
        self.assertEqual(self.request().status_code, 200)
        self.assertEqual(self.sent, [1000, 1005, 1035])
        self.post.assert_called_once()

    def test_spfa_409_uses_same_bounded_wait(self):
        self.post.return_value.status_code = 409
        self.statuses = [429, 200]
        self.assertEqual(self.request().status_code, 200)
        self.assertEqual(self.sent, [1000, 1030])
        self.post.assert_called_once()

    def test_expired_task_does_not_send_another_probe(self):
        self.provider.unblock_started_at = self.now - self.provider.UNBLOCK_TIMEOUT
        with self.assertRaises(UnblockTimeoutError):
            self.request()
        self.client.send.assert_not_called()
        self.client.proxy.rotate_with_retries.assert_not_called()

    def test_probe_timeout_does_not_exceed_remaining_window(self):
        self.provider.UNBLOCK_TIMEOUT = 40
        self.statuses = [429, 200]
        self.assertEqual(self.request().status_code, 200)
        self.assertEqual(self.client.send.call_args.kwargs['timeout'], 10)

    def test_config_wait_parameters_round_trip_and_validation(self):
        path = Path(self.directory.name) / 'config.toml'
        path.write_text('[avito]\nspfa_unblock_timeout = 120\nspfa_unblock_check_interval = 15\n')
        config = load_avito_config(path)
        provider = ExternalApiCookiesProvider(config, storage_path=path.parent / 'missing.json')
        self.assertEqual(provider.UNBLOCK_TIMEOUT, 120)
        self.assertEqual(provider.unblock_check_interval, 15)
        for values in ({'spfa_unblock_timeout': 0}, {'spfa_unblock_timeout': float('inf')},
                       {'spfa_unblock_check_interval': True}, {'spfa_unblock_check_interval': -1},
                       {'spfa_unblock_check_interval': 300}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                AvitoConfig(**values)
