"""Фоновые обновления: очередь, индивидуальные сроки и сохранность базы при ошибках."""
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from persistence.ads import SQLiteDBHandler
from domain.config import AvitoConfig, LinkConfig, ParseTarget
from load_config import load_avito_config
from domain.item import Item, PriceDetailed
from engine.cancellation import Cancellation, ParseCancelled
from engine.mobile_detail import parse_mobile_detail
from engine.request_queue import RequestThrottle
from engine.proxies.proxy import ProxyRotationError
from engine.http.client import HttpClient
from engine.http.base import UnblockTimeoutError
from engine.app import AvitoParse


def item(i=1):
    return Item(id=i, title='CPU', description='Old', isReserved=True,
                urlPath=f'/cpu_{i}', priceDetailed=PriceDetailed(
                    enabled=True, fullString='500', hasValue=True, postfix='', string='500',
                    stringWithoutDiscount=None, title={}, titleDative='', value=500,
                    wasLowered=False, exponent=''))


def payload(i=1):
    return {'success': {'mobile': {
        'id': i, 'title': 'New title', 'description': 'Full description',
        'price': {'value': '28\xa0900'}, 'time': 1700000000,
        'seo': {'canonicalUrl': f'https://www.avito.ru/cpu_{i}'},
        'sellerAddressInfo': {'fullAddress': {'locality': 'Новосибирск'}, 'isWithDelivery': True},
        'seller': {'domain': 'seller-slug', 'userHash': 'different-id',
                   'rating': {'scoreFloat': 5, 'text': '58 отзывов'}},
        'images': [{'10x10': 'small', '100x100': 'large'}],
        'coords': {'lat': 55, 'lng': 82}, 'isReserved': False,
    }}}


class QueueTests(unittest.TestCase):
    def test_background_waits_for_entire_foreground_scan(self):
        queue = RequestThrottle(0, 0)
        done = threading.Event()
        with queue.foreground():
            thread = threading.Thread(target=lambda: queue.run(done.set, background=True))
            thread.start()
            self.assertFalse(done.wait(.12))
            self.assertEqual(queue.run(lambda: 'page'), 'page')
            self.assertFalse(done.is_set())
        thread.join(1)
        self.assertTrue(done.is_set())

    def test_foreground_overtakes_queued_background_and_no_overlap(self):
        queue = RequestThrottle(0, 0)
        order = []
        queue._lock.acquire()
        threads = []
        try:
            for name, bg in [('refresh', True), ('page1', False), ('page2', False)]:
                thread = threading.Thread(target=lambda n=name, b=bg: queue.run(order.append, n, background=b))
                thread.start()
                threads.append(thread)
                deadline = time.monotonic() + 1
                while len(queue._queue) < len(threads) and time.monotonic() < deadline:
                    time.sleep(.005)
        finally:
            queue._lock.release()
        for thread in threads:
            thread.join(1)
        self.assertEqual(order, ['page1', 'page2', 'refresh'])

    def test_cancelled_background_leaves_queue(self):
        queue = RequestThrottle(0, 0)
        with self.assertRaises(ParseCancelled):
            queue.run(Mock(), background=True, cancellation=Cancellation(lambda: True))
        self.assertEqual(queue._queue, [])
        self.assertEqual(queue.run(lambda: 1), 1)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.previous = SQLiteDBHandler._instance
        SQLiteDBHandler._instance = None
        self.db = SQLiteDBHandler(str(Path(self.tmp.name) / 'ads.db'))
        self.addCleanup(setattr, SQLiteDBHandler, '_instance', self.previous)
        with patch('persistence.ads.time.time', return_value=100):
            self.db.add_record_from_page([item()], 'search', 'one', ['recipient'])
        self.parser = AvitoParse.__new__(AvitoParse)
        self.parser.db_handler = self.db
        self.parser.http = Mock()
        self.parser.camoufox = None
        self.parser.good_request_count = 0
        self.parser.bad_request_count = 0
        self.parser.config = AvitoConfig(ad_refresh_interval=60)
        self.parser._shutdown = threading.Event()
        self.parser.stop_event = None
        self.parser._fatal_error = None
        self.parser.throttle = RequestThrottle(0, 0)

    def last_attempt(self):
        with sqlite3.connect(self.db.db_name) as conn:
            return conn.execute('SELECT last_attempt FROM ad_refresh_state WHERE ad_id = 1').fetchone()[0]

    def test_refresh_crossing_round_boundary_is_not_repeated(self):
        """Настоящие очередь, обновление и SQLite; подменяется только сеть."""
        self.db.add_record_from_page([item(2)], 'search', 'one')
        self.db.finish_ad_refresh(2, now=101)
        self.parser.config.pause_general = .3
        self.parser.url_converter = Mock(convert=Mock(return_value='https://example.invalid'))
        self.parser._notification_cycle = Mock()
        self.parser._current_links = lambda: {'search': ParseTarget('search', LinkConfig())}
        first_started, next_round_queued, release_first, finished = (
            threading.Event() for _ in range(4))
        order = []
        scans = []

        def process(url, config, api_url, cancellation, **kwargs):
            scans.append(url)
            if len(scans) == 2:
                next_round_queued.set()
            self.parser.throttle.run(order.append, f'search:{len(scans)}', cancellation=cancellation)

        def request(method, url, **kwargs):
            ad_id = int(url.rsplit('/', 1)[-1])
            order.append(f'ad:{ad_id}')
            if ad_id == 1:
                first_started.set()
                release_first.wait(3)
            return Mock(status_code=200, json=lambda: payload(ad_id))

        select_due = self.db.next_ad_for_refresh

        def next_due(interval):
            result = select_due(interval)
            if result is None:
                finished.set()
                self.parser._shutdown.set()
            return result

        self.db.next_ad_for_refresh = next_due
        self.db.update_ad = Mock(wraps=self.db.update_ad)
        self.parser.http.request.side_effect = request
        self.parser._process_link = process
        worker = threading.Thread(target=self.parser._run_scheduler, daemon=True)

        def cleanup():
            self.parser._shutdown.set()
            release_first.set()
            worker.join(2)
            self.assertFalse(worker.is_alive())

        self.addCleanup(cleanup)
        worker.start()
        self.assertTrue(first_started.wait(2))
        self.assertTrue(next_round_queued.wait(2))
        self.assertEqual(order, ['search:1', 'ad:1'])
        release_first.set()
        self.assertTrue(finished.wait(2))
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(order, ['search:1', 'ad:1', 'search:2', 'ad:2'])
        self.assertEqual(scans, ['search', 'search'])
        self.assertEqual(self.parser.http.request.call_count, 2)
        self.assertEqual([call.args[0] for call in self.db.update_ad.call_args_list], [1, 2])
        self.assertIsNone(select_due(60))
        self.assertTrue(all(row['refreshed_at'] for row in self.db.list_ads('search')))
        self.assertEqual(self.parser.throttle._queue, [])

    def test_each_ad_has_persistent_deadline_not_reset_by_catalog(self):
        with patch('persistence.ads.time.time', return_value=130):
            self.db.add_record_from_page([item(2)], 'search', 'one')
            self.db.add_record_from_page([item()], 'other-search', 'two')
        self.assertIsNone(self.db.next_ad_for_refresh(60, now=159))
        self.assertEqual(self.db.next_ad_for_refresh(60, now=160), 1)
        self.db.finish_ad_refresh(1, now=160)
        self.assertIsNone(self.db.next_ad_for_refresh(60, now=189))
        self.assertEqual(self.db.next_ad_for_refresh(60, now=190), 2)
        SQLiteDBHandler._instance = None
        reopened = SQLiteDBHandler(self.db.db_name)
        self.assertEqual(reopened.next_ad_for_refresh(60, now=190), 2)

    def test_success_updates_all_subscriptions_and_timestamps(self):
        self.db.add_record_from_page([item()], 'search', 'two')
        old_scan = self.db.list_ads('search')[0]['scanned_at']
        new_scan = '2030-01-02T03:04:05+00:00'
        self.parser.http.request.return_value = Mock(status_code=200, json=lambda: payload())
        with patch('persistence.ads.now_iso', return_value=new_scan), \
             patch('persistence.ads.time.time', return_value=200):
            self.parser._refresh_ad(1, Cancellation())
        rows = self.db.list_ads('search')
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['price'], 28900)
            self.assertEqual(row['description'], 'Full description')
            self.assertEqual(row['seller_id'], 'seller-slug')
            self.assertEqual(row['seller_reviews'], 58)
            self.assertEqual(row['photo_url'], 'large')
            self.assertEqual(row['is_reserved'], 0)
            self.assertEqual(row['refreshed_at'], new_scan)
            self.assertEqual(row['scanned_at'], old_scan)
        self.assertEqual(self.last_attempt(), 200)
        self.assertIsNone(self.db.next_ad_for_refresh(60, now=259))
        self.assertEqual(self.db.next_ad_for_refresh(60, now=260), 1)
        self.parser.http.request.assert_called_once()

    def test_unknown_reservation_preserves_previous_status(self):
        data = payload()
        mobile = data['success']['mobile']
        del mobile['isReserved']
        mobile['uxFeedbackConfig'] = {'attributes': {'boolAttrs': {'is_reserved_or_out_of_stock': True}}}
        fields = parse_mobile_detail(data, 1)['fields']
        self.assertNotIn('is_reserved', fields)
        self.db.update_ad(1, fields)
        self.assertEqual(self.db.list_ads('search')[0]['is_reserved'], 1)
        mobile['uxFeedbackConfig']['attributes']['boolAttrs']['is_reserved_or_out_of_stock'] = False
        self.assertEqual(parse_mobile_detail(data, 1)['fields']['is_reserved'], 0)

    def test_confirmed_removal_deletes_all_subscriptions_and_pending_notifications(self):
        self.db.add_record_from_page([item()], 'other', 'two')
        self.parser.http.request.return_value = Mock(status_code=404, json=lambda: {'error': {'code': 'item_not_found'}})
        self.parser._refresh_ad(1, Cancellation())
        self.assertEqual(self.db.list_ads('search'), [])
        self.assertEqual(self.db.list_ads('other'), [])
        self.assertEqual(self.db.pending_notifications(['recipient']), [])
        self.assertIsNone(self.db.next_ad_for_refresh(1, now=time.time()))

    def test_bad_json_generic_404_wrong_id_and_network_error_preserve_ad(self):
        old_rows = self.db.list_ads('search')
        for response in [Mock(status_code=404, json=lambda: {}),
                         Mock(status_code=200, json=Mock(side_effect=ValueError('HTML'))),
                         Mock(status_code=200, json=lambda: payload(999))]:
            self.parser.http.request.return_value = response
            with self.assertRaises(ValueError):
                self.parser._refresh_ad(1, Cancellation())
            self.assertEqual(self.db.list_ads('search'), old_rows)
            self.assertEqual(self.last_attempt(), 100)
        self.parser.http.request.side_effect = RuntimeError('attempts exhausted')
        with patch('persistence.ads.time.time', return_value=200):
            with self.assertRaises(RuntimeError):
                self.parser._refresh_ad(1, Cancellation())
        self.assertEqual(self.last_attempt(), 100)
        self.assertEqual(self.db.list_ads('search'), old_rows)
        self.assertEqual(self.db.next_ad_for_refresh(60, now=200), 1)

    def test_timeout_and_cancellation_keep_timestamps_and_allow_retry(self):
        old_rows = self.db.list_ads('search')
        for error in (UnblockTimeoutError('SPFA timeout'), ParseCancelled()):
            with self.subTest(error=type(error).__name__):
                self.parser.http.request.side_effect = error
                with self.assertRaises(type(error)):
                    self.parser._refresh_ad(1, Cancellation())
                self.assertEqual(self.last_attempt(), 100)
                self.assertEqual(self.db.list_ads('search'), old_rows)
                self.assertEqual(self.db.next_ad_for_refresh(60, now=200), 1)
        self.parser.http.request.side_effect = None
        self.parser.http.request.return_value = Mock(status_code=200, json=lambda: payload())
        with patch('persistence.ads.time.time', return_value=200):
            self.parser._refresh_ad(1, Cancellation())
        self.assertEqual(self.last_attempt(), 200)
        self.assertIsNone(self.db.next_ad_for_refresh(60, now=200))

    def test_database_failure_rolls_back_fields_and_all_timestamps(self):
        old_rows = self.db.list_ads('search')
        # Ошибка при записи срока уже после UPDATE полей должна откатить всё.
        with sqlite3.connect(self.db.db_name) as conn:
            conn.execute('''CREATE TRIGGER fail_refresh BEFORE UPDATE ON ad_refresh_state
                BEGIN SELECT RAISE(ABORT, 'test write failure'); END''')
        self.parser.http.request.return_value = Mock(status_code=200, json=lambda: payload())
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'test write failure'):
            self.parser._refresh_ad(1, Cancellation())
        self.assertEqual(self.db.list_ads('search'), old_rows)
        self.assertEqual(self.last_attempt(), 100)
        self.assertEqual(self.db.next_ad_for_refresh(60, now=200), 1)
        self.assertEqual(self.parser.good_request_count, 0)

    def test_rotation_failure_stops_parser(self):
        failure = ProxyRotationError('failed')
        self.parser.http.request.side_effect = failure
        self.parser._refresh_cycle()
        self.assertIs(self.parser._fatal_error, failure)
        self.assertTrue(self.parser._shutdown.is_set())
        self.assertEqual(len(self.db.list_ads('search')), 1)
        self.assertEqual(self.last_attempt(), 100)

    def test_unexpected_card_logs_only_schema_and_preserves_existing_data(self):
        self.parser.http.request.return_value = Mock(status_code=200, json=lambda: {
            'error': {'message': 'private cookie password'}, 'private-user': {'id': 12345}})
        with patch('engine.app.logger') as log, self.assertRaises(ValueError):
            self.parser._refresh_ad(1, Cancellation())
        args = log.bind.return_value.warning.call_args.args
        self.assertEqual(args[1:4], (1, 200, 'ValueError'))
        schema = args[4]
        for secret in ('private', 'cookie', 'password', '12345'):
            self.assertNotIn(secret, schema)
        self.assertIn('"message":"string"', schema)
        self.assertEqual(self.db.list_ads('search')[0]['price'], 500)

    def test_non_json_diagnostic_does_not_log_body_or_decoder_error(self):
        self.parser.http.request.return_value = Mock(
            status_code=200, json=Mock(side_effect=ValueError('private response body')))
        with patch('engine.app.logger') as log, self.assertRaisesRegex(ValueError, 'некорректный JSON'):
            self.parser._refresh_ad(1, Cancellation())
        self.assertIn('invalid_json', log.bind.return_value.warning.call_args.args[0])
        self.assertNotIn('private', str(log.bind.return_value.warning.call_args))
        self.assertEqual(self.db.list_ads('search')[0]['price'], 500)

    def test_refresh_uses_shared_http_block_recovery_and_attempt_budget(self):
        proxy = Mock(get_httpx_proxy=Mock(return_value=None), rotate_with_retries=Mock(return_value=True))
        session = Mock()
        session.request.side_effect = [Mock(status_code=439), Mock(status_code=439),
                                       Mock(status_code=200, json=lambda: payload())]
        with patch('engine.http.client.requests.Session', return_value=session), \
             patch.object(HttpClient, 'get_current_ip', return_value=None):
            client = HttpClient(proxy, max_retries=3, block_threshold=2, retry_delay=0)
            self.parser.http = client
            try:
                self.parser._refresh_ad(1, Cancellation())
            finally:
                client.close()
        self.assertEqual(session.request.call_count, 3)
        proxy.rotate_with_retries.assert_called_once()
        self.assertEqual(self.db.list_ads('search')[0]['price'], 28900)

    def test_confirmed_404_uses_one_http_attempt(self):
        proxy = Mock(get_httpx_proxy=Mock(return_value=None))
        session = Mock()
        session.request.return_value = Mock(status_code=404, json=lambda: {'error': {'code': 'item_deleted'}})
        with patch('engine.http.client.requests.Session', return_value=session), \
             patch.object(HttpClient, 'get_current_ip', return_value=None):
            client = HttpClient(proxy, retry_delay=0)
            self.parser.http = client
            try:
                self.parser._refresh_ad(1, Cancellation())
            finally:
                client.close()
        session.request.assert_called_once()
        proxy.rotate_with_retries.assert_not_called()
        self.assertEqual(self.db.list_ads('search'), [])

    def test_catalog_updates_reservation_even_for_filtered_known_ads(self):
        ad = item()
        ad.isReserved = False
        self.db.update_catalog_status([ad])
        self.assertEqual(self.db.list_ads('search')[0]['is_reserved'], 0)

    def test_config_interval_loaded_and_validated(self):
        path = Path(self.tmp.name) / 'config.toml'
        path.write_text('[avito]\nad_refresh_interval = 120\n')
        self.assertEqual(load_avito_config(str(path)).ad_refresh_interval, 120)
        for value in (-1, True, float('inf'), '60'):
            with self.assertRaises(ValueError):
                AvitoConfig(ad_refresh_interval=value)
        self.assertEqual(AvitoConfig(ad_refresh_interval=0).ad_refresh_interval, 0)
