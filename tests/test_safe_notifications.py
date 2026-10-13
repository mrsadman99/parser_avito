import unittest
from unittest.mock import Mock, patch

import requests
from loguru import logger

from hide_private_data import redact_log_text, mask_sensitive_data
from integrations.notifications.transport import send_with_retries
from integrations.notifications.telegram import TelegramNotifier


class SafeNotificationsTests(unittest.TestCase):
    token = '123456789:' + 'AbC_def-' * 5

    def setUp(self):
        self.messages = []
        self.sink = logger.add(lambda message: self.messages.append(str(message)), format='{message}', diagnose=True)
        self.addCleanup(logger.remove, self.sink)

    def test_token_redaction_in_console_messages_config_and_traceback(self):
        token = self.token
        url = f'https://api.telegram.org/bot{token}/sendPhoto'
        for text in (url, token, url.replace(':AbC', '%3AAbC')):
            self.assertNotIn(token, redact_log_text(text))
            self.assertNotIn('AbC_def-', redact_log_text(text))
        self.assertNotIn(token, mask_sensitive_data(f"tg_token='{token}'"))
        try:
            try:
                raise ValueError(url)
            except ValueError:
                raise RuntimeError('outer failure')
        except RuntimeError:
            logger.exception('Request failed')
        logger.warning('Request failed: {}', url)
        self.assertNotIn(token, ''.join(self.messages))
        self.assertNotIn('AbC_def-', ''.join(self.messages))
        self.assertIn('sendPhoto', ''.join(self.messages))

    def test_http400_preserves_response_adds_description_and_hides_token(self):
        response = requests.Response()
        response.status_code = 400
        response.url = f'https://api.telegram.org/bot{self.token}/sendMessage'
        response._content = b'{"ok":false,"description":"Bad Request: cannot parse entities"}'
        send = Mock(return_value=response)
        try:
            send_with_retries(send)
        except requests.HTTPError as error:
            self.assertIs(error.response, response)
            self.assertIn('cannot parse entities', str(error))
            self.assertNotIn(self.token, str(error))
            logger.exception('Delivery failed')
        else:
            self.fail('Expected HTTPError')
        send.assert_called_once()
        self.assertNotIn(self.token, ''.join(self.messages))
        self.assertIn('cannot parse entities', ''.join(self.messages))

    def test_connection_error_retries_without_token_in_message(self):
        send = Mock(side_effect=requests.ConnectionError(f'Failed /bot{self.token}/sendPhoto'))
        with self.assertRaises(requests.ConnectionError) as raised:
            send_with_retries(send, retries=2, delay=0)
        self.assertEqual(send.call_count, 2)
        self.assertNotIn(self.token, str(raised.exception))
        self.assertNotIn(self.token, ''.join(self.messages))

    def test_non_json_error_does_not_dump_body_or_request(self):
        response = requests.Response()
        response.status_code = 502
        response.url = f'https://api.telegram.org/bot{self.token}/sendPhoto'
        response._content = b'<html>private diagnostic content</html>'
        with self.assertRaises(requests.HTTPError):
            send_with_retries(Mock(return_value=response), retries=1)
        self.assertNotIn('private diagnostic content', ''.join(self.messages))
        self.assertNotIn(self.token, ''.join(self.messages))

    def test_photo_diagnostics_keep_route_without_proxy_credentials(self):
        notifier = TelegramNotifier('unused', 'unused', proxy='127.0.0.1:5222',
                                    photo_proxy='login:secret@127.0.0.1:8888')
        with patch('integrations.notifications.photos.requests.Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.get.side_effect = requests.exceptions.SSLError('EOF')
            with self.assertRaises(requests.exceptions.SSLError):
                notifier._download_photo('https://90.img.avito.st/image/test')
        output = ''.join(self.messages)
        self.assertIn('http://127.0.0.1:8888', output)
        self.assertIn('avito_proxy', output)
        self.assertIn('SSLError', output)
        self.assertNotIn('secret', output)
        self.assertNotIn('login', output)
        self.assertNotIn('verify', session.get.call_args.kwargs)
        session.proxies.update.assert_called_once_with(notifier.photo_proxy)
        self.assertFalse(session.trust_env)
