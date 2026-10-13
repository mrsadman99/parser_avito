import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import test_ad_link
from domain.config import AvitoConfig


class AdLinkCliTests(unittest.TestCase):
    url = 'https://m.avito.ru/api/1/card/items/8258446852'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / 'ad.json'
        self.raw = Path(self.tmp.name) / 'response.txt'
        self.config = AvitoConfig()
        self.config.own_mobile_proxy.use = False
        self.client = Mock(last_response=None)
        self.config_patch = patch.object(test_ad_link, 'load_avito_config', return_value=self.config)
        self.config_patch.start()
        patch.object(test_ad_link, 'build_proxy', return_value=Mock()).start()
        self.factory = patch.object(test_ad_link, '_build_request_client', return_value=self.client).start()
        self.addCleanup(patch.stopall)

    def run_cli(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return test_ad_link.main([self.url, '--no-proxy', '--save-json', str(self.output),
                                      '--save-response', str(self.raw)])

    def response(self, payload):
        response = Mock(status_code=200, url=self.url, text=json.dumps(payload))
        response.json.return_value = payload
        self.client.request.return_value = response
        self.client.last_response = response
        return response

    def test_full_json_and_shared_client(self):
        payload = {'success': {'mobile': {'description': 'Текст', 'unknown': [1, 2]}}}
        self.response(payload)
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(json.loads(self.output.read_text()), payload)
        self.assertEqual(json.loads(self.raw.read_text()), payload)
        self.factory.assert_called_once()
        self.assertIs(self.factory.call_args.args[0], self.config)
        self.assertIsNone(self.factory.call_args.args[2])
        self.client.request.assert_called_once_with('GET', self.url, headers={
            'accept': 'application/json, text/plain, */*', 'referer': 'https://m.avito.ru/'})
        self.client.close.assert_called_once()

    def test_exhaustion_saves_block_without_extra_retries(self):
        self.client.request.side_effect = RuntimeError('rotation failed')
        self.client.last_response = Mock(text='<html>blocked</html>')
        self.assertEqual(self.run_cli(), 1)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.raw.read_text(), '<html>blocked</html>')
        self.client.request.assert_called_once()
        self.client.close.assert_called_once()

    def test_non_json_and_api_error(self):
        response = self.response({})
        response.json.side_effect = ValueError('not JSON')
        self.assertEqual(self.run_cli(), 1)
        self.assertFalse(self.output.exists())
        self.response({'success': False, 'error': 'missing'})
        self.assertEqual(self.run_cli(), 1)
        self.assertFalse(json.loads(self.output.read_text())['success'])

    def test_wrong_host_rejected_before_loading_cookies(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            test_ad_link.main(['https://example.com/api/1/card/items/123'])
        self.factory.assert_not_called()
