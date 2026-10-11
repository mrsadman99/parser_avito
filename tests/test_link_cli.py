"""Проверочный CLI использует реальные циклы клиента; сеть и смена IP подменены."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from curl_cffi import requests

from dto import AvitoConfig, OwnMobileProxyConfig
from parser.http.client import HttpClient
from parser.http.camoufox_client import CamoufoxClient
from scripts import test_link


class LinkCliTests(unittest.TestCase):
    url = 'https://www.avito.ru/test_ad_123'

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.html = Path(self.directory.name) / 'ad.html'
        self.fields = Path(self.directory.name) / 'ad.json'
        self.config = AvitoConfig(
            own_mobile_proxy=OwnMobileProxyConfig(use=True),
            timeout=17, max_count_of_retry=5, block_threshold=3, retry_delay=0,
            ip_rotation_attempts=3, ip_rotation_timeout=12, ip_rotation_retry_delay=0,
        )
        self.config.camoufox.use = False
        self.provider = Mock()
        self.provider.get_fingerprint.return_value = {'impersonate': 'chrome', 'headers': {}}
        self.provider.get_user_agent.return_value = 'test-agent'
        self.provider.get.return_value = {'cookie': 'value'}
        patch.object(test_link, 'load_avito_config', return_value=self.config).start()
        self.cookie_factory = patch.object(test_link, 'build_cookies_provider', return_value=self.provider).start()
        patch.object(HttpClient, 'get_current_ip', return_value=None).start()
        patch.object(CamoufoxClient, 'get_current_ip', return_value=None).start()
        self.addCleanup(patch.stopall)

    def response(self, status, body=None):
        return Mock(status_code=status, text=body or f'<html>HTTP {status}</html>',
                    url=self.url, headers={'content-type': 'text/html'})

    def run_cli(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return test_link.main([self.url, '--mobile-proxy', '--no-proxy',
                                   '--save-html', str(self.html), '--save-json', str(self.fields), *extra])

    def test_failed_rotation_stops_at_threshold_and_saves_last_blocked_html(self):
        session = Mock()
        blocked = self.response(439)
        session.request.return_value = blocked
        with patch('parser.http.client.requests.Session', return_value=session) as factory, \
             patch('parser.proxies.rotation._rotation_attempt', return_value=(False, 'timeout')) as rotate:
            self.assertEqual(self.run_cli(), 1)
            self.assertEqual(session.request.call_count, 3)
            self.assertEqual(rotate.call_count, 3)
            proxy = rotate.call_args.args[0]
            self.assertEqual((proxy.rotation_attempts, proxy.rotation_timeout, proxy.rotation_retry_delay), (3, 12, 0))
            factory.assert_called_once()
        self.assertEqual(self.html.read_text(), blocked.text)
        self.assertFalse(json.loads(self.fields.read_text())['available'])
        self.provider.handle_block.assert_not_called()
        self.provider.handle_ip_change.assert_not_called()
        session.close.assert_called_once()

    def test_successful_rotation_refreshes_cookies_and_retries_same_url(self):
        first, second = Mock(), Mock()
        first.request.side_effect = [self.response(403), self.response(429), self.response(439)]
        success = self.response(200, '<script type="application/ld+json">'
                                '{"@type":"Product","sku":"123","name":"Test item",'
                                '"offers":{"price":"28900"}}</script>')
        second.request.return_value = success
        with patch('parser.http.client.requests.Session', side_effect=[first, second]), \
             patch('parser.proxies.rotation._rotation_attempt', side_effect=[(False, 'offline'), (True, None)]) as rotate:
            self.assertEqual(self.run_cli(), 0)
            self.assertEqual(rotate.call_count, 2)
        self.provider.handle_block.assert_called_once()
        self.provider.handle_ip_change.assert_called_once()
        self.assertEqual(first.request.call_count, 3)
        second.request.assert_called_once_with('GET', self.url, timeout=17)
        self.assertEqual(self.html.read_text(), success.text)
        self.assertEqual(json.loads(self.fields.read_text())['price'], 28900)
        first.close.assert_called_once()
        second.close.assert_called_once()

    def test_continuous_blocks_exhaust_http_limit_even_after_successful_rotation(self):
        first, second = Mock(), Mock()
        first.request.return_value = self.response(439)
        second.request.return_value = self.response(439)
        with patch('parser.http.client.requests.Session', side_effect=[first, second]), \
             patch('parser.proxies.rotation._rotation_attempt', return_value=(True, None)) as rotate:
            self.assertEqual(self.run_cli(), 1)
            self.assertEqual(first.request.call_count + second.request.call_count, 5)
            rotate.assert_called_once()
        self.assertEqual(self.html.read_text(), second.request.return_value.text)

    def test_network_failures_use_configured_count_without_ip_rotation(self):
        self.config.max_count_of_retry = 2
        session = Mock()
        session.request.side_effect = requests.RequestsError('test network failure')
        with patch('parser.http.client.requests.Session', return_value=session), \
             patch('parser.proxies.rotation._rotation_attempt') as rotate:
            self.assertEqual(self.run_cli('--timeout', '25'), 1)
            self.assertEqual(session.request.call_count, 2)
            self.assertEqual(session.request.call_args.kwargs['timeout'], 25)
            rotate.assert_not_called()
        self.assertFalse(self.html.exists())
        session.close.assert_called_once()

    def test_camoufox_uses_same_block_and_rotation_limits_and_saves_failure(self):
        self.config.camoufox.use = True
        page = Mock()
        browser_response = Mock(status=439)
        browser_response.text.return_value = '<html>Browser blocked</html>'
        page.goto.return_value = browser_response
        with patch.object(CamoufoxClient, '_ensure_page', return_value=page), \
             patch('parser.proxies.rotation._rotation_attempt', return_value=(False, 'timeout')) as rotate:
            self.assertEqual(self.run_cli(), 1)
            self.assertEqual(page.goto.call_count, 3)
            self.assertEqual(rotate.call_count, 3)
        self.cookie_factory.assert_not_called()
        self.assertEqual(self.html.read_text(), '<html>Browser blocked</html>')

    def test_proxy_startup_failure_does_not_send_request(self):
        with patch.object(test_link, 'start_proxy', return_value=1), \
             patch.object(test_link, '_build_request_client') as build, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(test_link.main([self.url]), 1)
            build.assert_not_called()


if __name__ == '__main__':
    unittest.main()
