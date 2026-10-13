import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from scripts.retrieve_ad_links import collect_links, extract_item_links


class CatalogLinksTests(unittest.TestCase):
    def test_shapes_duplicates_and_non_items(self):
        catalog = {'items': [None, {'id': True}, {'id': -1}, {'id': 'banner'},
                             {'id': 123, 'title': 'CPU', 'urlPath': '/cpu_123?context=abc'},
                             {'id': '123'}, {'id': '456'}]}
        for payload in (catalog, {'catalog': catalog}, {'result': catalog},
                        {'result': {'catalog': catalog}}):
            links = extract_item_links(payload)
            self.assertEqual([x['id'] for x in links], [123, 456])
            self.assertEqual(links[0]['url'], 'https://www.avito.ru/cpu_123?context=abc')
            self.assertEqual(links[0]['api_url'], 'https://m.avito.ru/api/1/card/items/123')
            self.assertIsNone(links[1]['url'])

    def test_invalid_response_is_not_empty_catalog(self):
        for payload in ([], {}, {'error': 'blocked'}):
            with self.assertRaises(ValueError):
                extract_item_links(payload)
        self.assertEqual(extract_item_links({'items': []}), [])

    def test_pages_deduplicate_and_stop_on_empty(self):
        client = Mock()
        client.request.side_effect = [Mock(json=Mock(return_value={'items': items}))
                                      for items in ([{'id': 1}], [{'id': 1}, {'id': 2}], [])]
        with patch('scripts.retrieve_ad_links.AvitoUrlConverter') as converter, \
             patch('scripts.retrieve_ad_links.time.sleep'):
            converter.return_value.convert.return_value = 'https://m.avito.ru/api/9/items?q=cpu&p=9'
            links = collect_links(client, 'https://www.avito.ru/search', 5,
                                  SimpleNamespace(min_delay=0, max_delay=0))
            converter.return_value.convert.assert_called_once_with('https://www.avito.ru/search')
        self.assertEqual([x['id'] for x in links], [1, 2])
        self.assertEqual(client.request.call_count, 3)
        for page, call in enumerate(client.request.call_args_list, 1):
            self.assertEqual(parse_qs(urlsplit(call.args[1]).query), {'q': ['cpu'], 'page': [str(page)]})

    def test_request_failure_propagates_without_another_retry_loop(self):
        client = Mock()
        client.request.side_effect = RuntimeError('exhausted')
        with patch('scripts.retrieve_ad_links.AvitoUrlConverter') as converter:
            converter.return_value.convert.return_value = 'https://m.avito.ru/api/9/items'
            with self.assertRaisesRegex(RuntimeError, 'exhausted'):
                collect_links(client, 'https://www.avito.ru/search', 5, SimpleNamespace())
        client.request.assert_called_once()

    def test_extra_only_pages_continue_and_deduplicate_across_pages(self):
        client = Mock()
        client.request.side_effect = [Mock(json=Mock(return_value={"catalog": {
            "items": [], "extraBlockItems": extra,
        }})) for extra in ([{"id": 1}], [{"id": 1}, {"id": 2}], [{"type": "header"}])]
        with patch('scripts.retrieve_ad_links.AvitoUrlConverter') as converter, \
             patch('scripts.retrieve_ad_links.time.sleep'):
            converter.return_value.convert.return_value = 'https://www.avito.ru/web/1/js/items'
            links = collect_links(client, 'https://www.avito.ru/search', 5,
                                  SimpleNamespace(min_delay=0, max_delay=0))
        self.assertEqual([link['id'] for link in links], [1, 2])
        self.assertEqual(client.request.call_count, 3)
