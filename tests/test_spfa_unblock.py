import unittest
from unittest.mock import Mock, patch

from engine.cookies.external_api import ExternalApiCookiesProvider


class SpfaUnblockTests(unittest.TestCase):
    def provider(self):
        provider = ExternalApiCookiesProvider.__new__(ExternalApiCookiesProvider)
        provider.last_id = 'test-cookie-id'
        provider.last_cookies = {'old': 'cookie'}
        provider.status_history = [429]
        provider.unblock_started_at = 100
        provider.UNBLOCK_TIMEOUT = 300
        provider.unblock_check_interval = 30
        provider._save_to_disk = Mock()
        return provider

    def test_success_clears_timer_and_preserves_cookie_updates(self):
        for status in (200, 204, 206):
            with self.subTest(status=status):
                provider = self.provider()
                provider.update(Mock(status_code=status, cookies={'fresh': 'value'}))
                self.assertIsNone(provider.unblock_started_at)
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
        provider.update(Mock(status_code=200, cookies={}))
        provider.update(Mock(status_code=429, cookies={}))
        with patch('engine.cookies.external_api.time.monotonic', return_value=1000), \
             patch('engine.cookies.external_api.requests.post', return_value=Mock(status_code=202)) as post, \
             patch('engine.cookies.external_api.logger') as log:
            provider.handle_block()
        post.assert_called_once()
        self.assertEqual(provider.unblock_started_at, 1000)
        log.warning.assert_not_called()
