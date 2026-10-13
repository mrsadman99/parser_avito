"""Регрессии MarkdownV2 и постоянной очереди доставки; без сетевых вызовов."""
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from persistence.ads import NOTIFICATION_MAX_ATTEMPTS, SQLiteDBHandler
from notifications.telegram import TelegramNotifier
from notifications.transport import is_permanent_delivery_error, send_with_retries
from notifications.utils import escape_markdown_v2
from domain.item import Item
from engine.app import AvitoParse


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f'HTTP {status}', response=response)


class MarkdownTests(unittest.TestCase):
    def test_reserved_characters_and_existing_backslashes(self):
        self.assertEqual(escape_markdown_v2('CPU *OEM*'), r'CPU \*OEM\*')
        self.assertEqual(escape_markdown_v2(r'x\]'), r'x\\\]')
        self.assertEqual(escape_markdown_v2(r'x\.'), r'x\\\.')
        self.assertEqual(escape_markdown_v2('end\\'), 'end\\\\')
        self.assertEqual(escape_markdown_v2('_*[]()~`>#+-=|{}.!\\'),
                         r'\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!\\')

    def test_full_ad_format_keeps_markup_but_escapes_user_fields(self):
        ad = SimpleNamespace(id=42, title='CPU *OEM*', description=r'boxed\]',
                             sellerId='seller\\', priceDetailed=SimpleNamespace(value=100),
                             seller_rating=4.9, seller_reviews=2)
        self.assertEqual(TelegramNotifier('unused', 'unused').format(ad),
                         '*100*\n[CPU \\*OEM\\*](https://avito.ru/42)\n'
                         + r'boxed\\\]' + '\nПродавец: seller\\\\\n⭐ Рейтинг: 4\\.9 · 2 оценок')


class NotificationQueueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.previous = SQLiteDBHandler._instance
        SQLiteDBHandler._instance = None
        self.addCleanup(setattr, SQLiteDBHandler, '_instance', self.previous)
        self.db = SQLiteDBHandler(str(Path(self.directory.name) / 'ads.db'))
        self.target = Mock()
        self.parser = AvitoParse.__new__(AvitoParse)
        self.parser.db_handler = self.db
        self.parser.stop_event = None
        self.parser._shutdown = threading.Event()
        self.parser.notifier = Mock(delivery_targets=Mock(return_value={'recipient': self.target}))
        with sqlite3.connect(self.db.db_name) as conn:
            conn.execute('''INSERT INTO notification_outbox
                (source_key, ad_id, price, recipient, payload) VALUES ('search', 1, 100, 'recipient', ?)''',
                (Item(id=1, title='CPU').model_dump_json(),))

    def row(self):
        with sqlite3.connect(self.db.db_name) as conn:
            conn.row_factory = sqlite3.Row
            return dict(conn.execute('SELECT * FROM notification_outbox').fetchone())

    def restart(self):
        name = self.db.db_name
        SQLiteDBHandler._instance = None
        self.db = SQLiteDBHandler(name)
        self.parser.db_handler = self.db

    def test_permanent_error_stops_retries_without_marking_delivered(self):
        error = http_error(400)
        token = '123456789:' + 'x' * 30
        error.args = (f'https://api.telegram.org/bot{token}/sendMessage',)
        self.target.notify.side_effect = error
        self.parser._deliver_pending_notifications()
        self.restart()
        with patch('persistence.ads.time.time', return_value=10**12):
            self.parser._deliver_pending_notifications()
            self.assertEqual(self.db.pending_notifications(['recipient']), [])
        self.target.notify.assert_called_once()
        row = self.row()
        self.assertEqual((row['sent'], row['failed'], row['attempts']), (0, 1, 1))
        self.assertNotIn(token, row['last_error'])
        self.assertIn('<redacted-token>', row['last_error'])

    def test_transient_failure_budget_survives_restart(self):
        self.target.notify.side_effect = requests.Timeout('network timeout')
        for attempt in range(NOTIFICATION_MAX_ATTEMPTS):
            with patch('persistence.ads.time.time', return_value=1000 + 61 * attempt):
                self.parser._deliver_pending_notifications()
                self.assertEqual(self.db.pending_notifications(['recipient']), [])
            if attempt == 4:
                self.restart()
        with patch('persistence.ads.time.time', return_value=10**12):
            self.parser._deliver_pending_notifications()
        self.assertEqual(self.target.notify.call_count, NOTIFICATION_MAX_ATTEMPTS)
        row = self.row()
        self.assertEqual((row['sent'], row['failed'], row['attempts']), (0, 1, NOTIFICATION_MAX_ATTEMPTS))
        self.assertEqual(row['last_error'], 'network timeout')

    def test_temporary_http_errors_remain_retryable(self):
        for status in (408, 425, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.assertFalse(is_permanent_delivery_error(http_error(status)))
        for status in (400, 401, 403, 404, 413):
            with self.subTest(status=status):
                self.assertTrue(is_permanent_delivery_error(http_error(status)))
        self.target.notify.side_effect = [http_error(429), None]
        with patch('persistence.ads.time.time', return_value=1000):
            self.parser._deliver_pending_notifications()
        self.assertEqual(self.row()['failed'], 0)
        with patch('persistence.ads.time.time', return_value=1061):
            self.parser._deliver_pending_notifications()
        self.assertEqual(self.target.notify.call_count, 2)
        row = self.row()
        self.assertEqual((row['sent'], row['failed'], row['attempts'], row['last_error']), (1, 0, 2, None))

    def test_expired_final_lease_is_not_retried_after_crash(self):
        for attempt in range(NOTIFICATION_MAX_ATTEMPTS):
            with patch('persistence.ads.time.time', return_value=1000 + attempt * 601):
                entry = self.db.claim_notification(['recipient'])
                self.assertEqual(entry['attempts'], attempt + 1)
                self.assertIsNone(self.db.claim_notification(['recipient']))
                self.assertEqual(self.row()['failed'], 0)
        self.restart()
        with patch('persistence.ads.time.time', return_value=10**12):
            self.assertIsNone(self.db.claim_notification(['recipient']))
        self.assertEqual(self.row()['failed'], 1)
        self.assertIn('неизвестен', self.row()['last_error'])

    def test_invalid_saved_payload_stops_retries(self):
        with sqlite3.connect(self.db.db_name) as conn:
            conn.execute("UPDATE notification_outbox SET payload = 'broken json'")
        self.parser._deliver_pending_notifications()
        self.target.notify.assert_not_called()
        self.assertEqual((self.row()['failed'], self.row()['sent']), (1, 0))

    def test_migration_preserves_old_pending_and_delivered_records(self):
        path = str(Path(self.directory.name) / 'legacy.db')
        with sqlite3.connect(path) as conn:
            conn.execute('''CREATE TABLE notification_outbox (
                id INTEGER PRIMARY KEY, source_key TEXT, ad_id INTEGER, price INTEGER,
                recipient TEXT, payload TEXT, sent INTEGER DEFAULT 0, retry_at REAL DEFAULT 0,
                UNIQUE(source_key, ad_id, price, recipient))''')
            conn.executemany('''INSERT INTO notification_outbox
                (source_key, ad_id, price, recipient, payload, sent, retry_at)
                VALUES ('search', ?, 100, 'recipient', '{}', ?, ?)''', [(1, 0, 123), (2, 1, 0)])
        SQLiteDBHandler._instance = None
        self.db = SQLiteDBHandler(path)
        self.restart()
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute('SELECT sent, retry_at, attempts, failed FROM notification_outbox ORDER BY id').fetchall(),
                             [(0, 123, 0, 0), (1, 0, 0, 0)])
        with patch('persistence.ads.time.time', return_value=1000):
            self.assertEqual([r['ad_id'] for r in self.db.pending_notifications(['recipient'])], [1])

    def test_transport_retries_request_timeout_status(self):
        response = requests.Response()
        response.status_code = 408
        ok = requests.Response()
        ok.status_code = 200
        send = Mock(side_effect=[response, ok])
        self.assertIs(send_with_retries(send, delay=0), ok)
        self.assertEqual(send.call_count, 2)
