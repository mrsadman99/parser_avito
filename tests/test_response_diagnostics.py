import json
import unittest

from parser.response_diagnostics import json_structure


class ResponseDiagnosticsTests(unittest.TestCase):
    def test_only_known_keys_and_types_are_saved(self):
        payload = {'success': {'mobile': {'id': 123456, 'title': 'Private title',
                   'seller': {'name': 'Private Name'}, 'images': [{'640x480': 'https://private/image'}]}},
                   'error': {'message': 'private token secret'}, 'PrivateKey': 'password',
                   'https://private/url': {'code': 17}}
        structure = json_structure(payload)
        for secret in ('123456', 'Private', 'password', 'token', 'https://', '640x480'):
            self.assertNotIn(secret, structure)
        parsed = json.loads(structure)
        mobile = parsed['fields']['success']['fields']['mobile']['fields']
        self.assertEqual(mobile['id'], 'number')
        self.assertEqual(mobile['title'], 'string')
        self.assertIn('<field_3>', parsed['fields'])

    def test_large_and_deep_responses_have_bounded_schema(self):
        payload = {'title': ['secret'] * 10000}
        for _ in range(100):
            payload = {'data': payload, 'items': [payload] * 10}
        structure = json_structure(payload)
        self.assertLess(len(structure), 10000)
        self.assertNotIn('secret', structure)
        self.assertEqual(json.loads(structure)['type'], 'object')

    def test_scalar_response_values_are_not_logged(self):
        for payload, expected in [('secret', 'string'), (False, 'boolean'), (None, 'null'), (127, 'number')]:
            self.assertEqual(json.loads(json_structure(payload)), expected)
