import os
import unittest
from unittest.mock import Mock, patch

import requests

from domain.config import AvitoConfig
from notifications.factory import build_notifier
from notifications.photos import download_photo
from notifications.telegram import TelegramNotifier
from notifications.vk import VKNotifier
from engine.proxies.proxy import OwnMobileProxy
from proxy_helpers import build_proxies_dict


PHOTO_URL = 'https://b50.img.avito.st/image/test'
MOBILE = 'user:secret@127.0.0.1:8888'
NOTIFIER = '127.0.0.1:5222'


def response(body=b'photo', status=200, payload=None):
    result = requests.Response()
    result.status_code = status
    result._content = body
    if payload is not None:
        result.json = Mock(return_value=payload)
    return result


class PhotoRoutingTests(unittest.TestCase):
    def test_cdn_redirects_keep_mobile_proxy_despite_environment(self):
        calls = []

        def send(request, **kwargs):
            calls.append((request.url, dict(kwargs['proxies'])))
            result = response(status=302 if len(calls) == 1 else 200)
            result.url = request.url
            result.request = request
            if len(calls) == 1:
                result.headers['Location'] = 'https://c70.img.avito.st/image/test'
            return result

        proxies = build_proxies_dict(MOBILE)
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://' + NOTIFIER,
                                     'ALL_PROXY': 'http://' + NOTIFIER}), \
             patch('requests.adapters.HTTPAdapter.send', side_effect=send):
            self.assertEqual(download_photo(PHOTO_URL, proxies), b'photo')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], PHOTO_URL)
        self.assertEqual(calls[1][0], 'https://c70.img.avito.st/image/test')
        for _, actual in calls:
            self.assertEqual(actual['https'], 'http://' + MOBILE)

    def test_no_avito_proxy_does_not_use_notifier_from_environment(self):
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://' + NOTIFIER}), \
             patch('requests.adapters.HTTPAdapter.send', return_value=response()) as send:
            download_photo(PHOTO_URL)
        self.assertFalse(send.call_args.kwargs['proxies'])

    def test_cdn_http_failure_is_not_returned_as_image(self):
        with patch('requests.adapters.HTTPAdapter.send', return_value=response(status=403)):
            with self.assertRaises(requests.HTTPError):
                download_photo(PHOTO_URL, build_proxies_dict(MOBILE))

    def test_telegram_downloads_once_and_uploads_bytes_via_notifier(self):
        notifier = TelegramNotifier('unused', '42', NOTIFIER, photo_proxy=MOBILE)
        with patch('requests.adapters.HTTPAdapter.send', return_value=response()) as get, \
             patch('notifications.telegram.requests.post', return_value=response()) as post:
            notifier._send_photo(PHOTO_URL, 'caption')
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0].url, PHOTO_URL)
        self.assertEqual(get.call_args.kwargs['proxies']['https'], 'http://' + MOBILE)
        post.assert_called_once()
        self.assertTrue(post.call_args.args[0].endswith('/sendPhoto'))
        self.assertEqual(post.call_args.kwargs['files']['photo'][1], b'photo')
        self.assertEqual(post.call_args.kwargs['proxies'], build_proxies_dict(NOTIFIER))
        self.assertNotIn('json', post.call_args.kwargs)

    def test_telegram_photo_failure_falls_back_to_text_via_notifier(self):
        notifier = TelegramNotifier('unused', '42', NOTIFIER, photo_proxy=MOBILE)
        ad = Mock(main_image_url=Mock(return_value=PHOTO_URL))
        with patch.object(notifier, 'format', return_value='caption'), \
             patch('requests.adapters.HTTPAdapter.send', side_effect=requests.ConnectionError('mobile down')), \
             patch('notifications.telegram.requests.post', return_value=response()) as post:
            notifier.notify_ad(ad)
        post.assert_called_once()
        self.assertTrue(post.call_args.args[0].endswith('/sendMessage'))
        self.assertEqual(post.call_args.kwargs['proxies'], build_proxies_dict(NOTIFIER))

    def test_vk_download_and_all_upload_steps_use_separate_proxies(self):
        notifier = VKNotifier('unused', '42', NOTIFIER, photo_proxy=MOBILE)
        ad = Mock(main_image_url=Mock(return_value=PHOTO_URL))
        results = [response(payload={'response': {'upload_url': 'https://upload.vk.test/photo'}}),
                   response(payload={'photo': 'photo', 'server': 1, 'hash': 'hash'}),
                   response(payload={'response': [{'owner_id': 1, 'id': 2}]}),
                   response(payload={'response': 123})]
        with patch.object(notifier, 'format_ad', return_value='caption'), \
             patch('requests.adapters.HTTPAdapter.send', return_value=response()) as get, \
             patch('notifications.vk.requests.post', side_effect=results) as post:
            notifier.notify_ad(ad)
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs['proxies']['https'], 'http://' + MOBILE)
        self.assertEqual(post.call_count, 4)
        for call in post.call_args_list:
            self.assertEqual(call.kwargs['proxies'], build_proxies_dict(NOTIFIER))
        self.assertEqual(post.call_args_list[1].kwargs['files']['photo'][1], b'photo')
        self.assertEqual(post.call_args.kwargs['data']['attachment'], 'photo1_2')

    def test_vk_text_uses_notifier_proxy(self):
        notifier = VKNotifier('unused', '42', NOTIFIER, photo_proxy=MOBILE)
        with patch('notifications.vk.requests.post', return_value=response()) as post:
            notifier.notify_message('text')
        self.assertEqual(post.call_args.kwargs['proxies'], build_proxies_dict(NOTIFIER))

    def test_factory_uses_configured_own_or_external_avito_proxy(self):
        for own in (True, False):
            with self.subTest(own=own):
                config = AvitoConfig()
                config.messengers.tg_token = config.messengers.vk_token = 'unused'
                config.messengers.tg_chat_id = config.messengers.vk_user_id = ['42']
                config.messengers.proxy_notifier = NOTIFIER
                config.own_mobile_proxy.use = own
                config.own_mobile_proxy.server = '127.0.0.1:9999'
                config.external_mobile_proxy.proxy_string = MOBILE
                config.external_mobile_proxy.change_urls = ['https://example.test/change']
                notifier = build_notifier(config)
                expected = '127.0.0.1:9999' if own else MOBILE
                self.assertEqual(len(notifier.notifiers), 2)
                for target in notifier.notifiers:
                    self.assertEqual(target.photo_proxy, build_proxies_dict(expected))
                    self.assertEqual(target.proxy, build_proxies_dict(NOTIFIER))

    def test_factory_reuses_parser_proxy_without_building_another(self):
        config = AvitoConfig()
        config.messengers.tg_token = 'unused'
        config.messengers.tg_chat_id = ['42']
        proxy = OwnMobileProxy(server='127.0.0.1:7777')
        with patch('notifications.factory.build_proxy') as build:
            notifier = build_notifier(config, avito_proxy=proxy)
        build.assert_not_called()
        self.assertEqual(notifier.notifiers[0].photo_proxy['https'], 'http://127.0.0.1:7777')
