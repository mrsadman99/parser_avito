import unittest
import threading
from unittest.mock import Mock, patch

from engine.cookies.external_api import ExternalApiCookiesProvider


class SpfaUnblockTests(unittest.TestCase):
    def provider(self):
        provider = ExternalApiCookiesProvider.__new__(ExternalApiCookiesProvider)
        provider._recovery_lock = threading.RLock()
        provider.revision = 0
        provider.last_id = 'test-cookie-id'
        provider.last_cookies = {'old': 'cookie'}
        provider.status_history = [429]
        provider.unblock_started_at = 100
        provider.UNBLOCK_TIMEOUT = 300
        provider.unblock_check_interval = 30
        provider._save_to_disk = Mock()
        return provider

    def test_avito_response_cannot_confirm_spfa_completion(self):
        for status in (200, 204, 206):
            with self.subTest(status=status):
                provider = self.provider()
                provider.update(Mock(status_code=status, cookies={'fresh': 'value'}))
                self.assertEqual(provider.unblock_started_at, 100)
                self.assertEqual(provider.last_cookies, {'old': 'cookie', 'fresh': 'value'})
                self.assertEqual(provider.status_history, [429, status])
                provider._save_to_disk.assert_called_once()

    def test_errors_and_redirects_do_not_confirm_unblock(self):
        for status in (301, 302, 403, 404, 429, 439, 500):
            with self.subTest(status=status):
                provider = self.provider()
                provider.update(Mock(status_code=status, cookies={}))
                self.assertEqual(provider.unblock_started_at, 100)

    def test_later_block_starts_new_wait_without_false_timeout(self):
        provider = self.provider()
        provider.purchase_cooldown = 0
        provider.last_purchase_at = 0
        provider.UNBLOCK_TIMEOUT = 300
        provider.headers = {}
        provider.api_key = 'unused'
        provider.proxy = 'unused'
        provider.request_proxies = None
        provider.unblock_started_at = None
        provider.update(Mock(status_code=200, cookies={}))
        provider.update(Mock(status_code=429, cookies={}))
        with patch('engine.cookies.external_api.time.monotonic', return_value=1000), \
             patch('engine.cookies.external_api.requests.post', return_value=Mock(status_code=202)) as post, \
             patch('engine.cookies.external_api.logger') as log:
            provider.handle_block()
        post.assert_called_once()
        self.assertEqual(provider.unblock_started_at, 1000)
        self.assertIn('ответ не подтверждает', log.warning.call_args.args[0])

    def test_202_with_complete_cookies_finishes_unblock(self):
        provider = self.provider()
        provider.last_id = '203679'
        cookies = {f'test_cookie_{i}': f'value_{i}' for i in range(29)}
        response = Mock(status_code=202, json=lambda: {
            'success': True, 'results': {'id': 203679, 'cookies': cookies},
        })
        self.assertTrue(provider._accept_unblock(response))
        self.assertEqual(provider.last_cookies, cookies)
        self.assertIsNone(provider.get_unblock_state())
        self.assertEqual(provider.status_history, [])
        self.assertEqual(provider.revision, 1)
        provider._save_to_disk.assert_called_once()

    def test_202_without_confirmed_cookies_does_not_finish_unblock(self):
        for payload in (
            {'success': True},
            {'success': False, 'results': {'id': 'test-cookie-id', 'cookies': {'new': 'value'}}},
            {'success': True, 'results': {'id': 'other', 'cookies': {'new': 'value'}}},
            {'success': True, 'results': {'id': 'test-cookie-id', 'cookies': {}}},
            {'success': True, 'results': {'id': 'test-cookie-id', 'cookies': {'new': None}}},
        ):
            with self.subTest(payload=payload):
                provider = self.provider()
                self.assertFalse(provider._accept_unblock(Mock(status_code=202, json=lambda: payload)))
                self.assertEqual(provider.last_cookies, {'old': 'cookie'})
                self.assertIsNotNone(provider.get_unblock_state())
                self.assertEqual(provider.revision, 0)
                provider._save_to_disk.assert_not_called()
