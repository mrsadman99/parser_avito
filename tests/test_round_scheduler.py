"""Общие раунды, окна обновления и приоритет запросов без реальной сети."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from dto import AvitoConfig, LinkConfig, ParseTarget
from load_config import load_avito_config
from parser.request_queue import RequestThrottle
from parser_cls import AvitoParse


class RoundSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.parser = AvitoParse.__new__(AvitoParse)
        self.parser.config = AvitoConfig(pause_general=.3, ad_refresh_interval=60)
        self.parser.stop_event = threading.Event()
        self.parser._shutdown = threading.Event()
        self.parser._fatal_error = None
        self.parser.throttle = RequestThrottle(0, 0)
        self.parser.url_converter = Mock(convert=Mock(return_value="https://example.invalid"))
        self.parser.db_handler = Mock(next_ad_for_refresh=Mock(return_value=None))
        self.parser._notification_cycle = Mock()
        self.links = {key: ParseTarget(key, LinkConfig()) for key in ("fast", "slow")}
        self.parser._current_links = lambda: self.links.copy()
        self.releases = []

    def start(self):
        thread = threading.Thread(target=self.parser._run_scheduler, daemon=True)

        def cleanup():
            self.parser.stop_event.set()
            for event in self.releases:
                event.set()
            thread.join(2)
            self.assertFalse(thread.is_alive())

        self.addCleanup(cleanup)
        thread.start()
        return thread

    def test_all_links_finish_before_refresh_then_next_round_overtakes_refresh(self):
        slow_started, fast_finished, refresh_started = (threading.Event() for _ in range(3))
        release_slow, release_refresh = threading.Event(), threading.Event()
        self.releases.extend([release_slow, release_refresh])
        next_round_started, finished = threading.Event(), threading.Event()
        calls, order = {}, []

        def process(url, config, api_url, cancellation, **kwargs):
            calls[url] = calls.get(url, 0) + 1
            if url == "slow" and calls[url] == 1:
                slow_started.set()
                release_slow.wait(2)
            if calls[url] == 2:
                next_round_started.set()
            self.parser.throttle.run(order.append, url, cancellation=cancellation)
            if url == "fast":
                fast_finished.set()

        def refresh(ad_id, cancellation):
            order.append(f"refresh{ad_id}")
            if ad_id == 1:
                refresh_started.set()
                release_refresh.wait(2)
            else:
                finished.set()
                self.parser.stop_event.set()

        self.parser._process_link = process
        self.parser._refresh_ad = refresh
        self.parser.db_handler.next_ad_for_refresh.side_effect = [1, 2]
        thread = self.start()
        self.assertTrue(slow_started.wait(1))
        self.assertTrue(fast_finished.wait(1))
        self.assertFalse(refresh_started.wait(.15))
        self.assertEqual(calls, {"fast": 1, "slow": 1})
        self.parser.db_handler.next_ad_for_refresh.assert_not_called()
        release_slow.set()
        self.assertTrue(refresh_started.wait(1))
        self.assertEqual(set(order[:2]), {"fast", "slow"})
        self.assertTrue(next_round_started.wait(1))
        # Начатое обновление завершается, новые поисковые запросы ждут этот слот.
        self.assertEqual(len(order), 3)
        release_refresh.set()
        self.assertTrue(finished.wait(2))
        thread.join(1)
        self.assertEqual(set(order[3:5]), {"fast", "slow"})
        self.assertEqual(order[2], "refresh1")
        self.assertEqual(order[5], "refresh2")
        self.assertEqual(self.parser.throttle._foreground, 0)
        self.assertEqual(self.parser.throttle._queue, [])

    def test_failure_is_attempted_once_per_round(self):
        self.links.pop("slow")
        self.parser.config.pause_general = 10
        attempted = threading.Event()

        def fail(*args, **kwargs):
            attempted.set()
            raise ValueError("invalid catalog")

        self.parser._process_link = Mock(side_effect=fail)
        self.start()
        self.assertTrue(attempted.wait(1))
        time.sleep(.25)
        self.parser._process_link.assert_called_once()

    def test_new_link_during_pause_starts_immediately(self):
        self.links.pop("slow")
        self.parser.config.pause_general = 10
        paused, added = threading.Event(), threading.Event()
        self.parser.db_handler.next_ad_for_refresh.side_effect = lambda _: paused.set()
        self.parser._process_link = lambda url, *a, **k: added.set() if url == "new" else None
        self.start()
        self.assertTrue(paused.wait(1))
        self.links["new"] = ParseTarget("new", LinkConfig())
        self.assertTrue(added.wait(1))

    def test_zero_pause_does_not_enqueue_refresh(self):
        self.links.pop("slow")
        self.parser.config.pause_general = 0
        calls = []

        def process(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                self.parser.stop_event.set()

        self.parser._process_link = process
        thread = self.start()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(calls), 2)
        self.parser.db_handler.next_ad_for_refresh.assert_not_called()
        self.assertEqual(self.parser.throttle._foreground, 0)

    def test_no_links_still_allows_refresh_and_clean_shutdown(self):
        self.links.clear()
        self.parser.db_handler.next_ad_for_refresh.return_value = 1
        self.parser._refresh_ad = lambda *args: self.parser.stop_event.set()
        thread = self.start()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.parser.db_handler.next_ad_for_refresh.assert_called_once()
        self.assertEqual(self.parser.throttle._queue, [])

    def test_pause_config_load_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[avito]\npause_general = 12.5\n")
            self.assertEqual(load_avito_config(str(path)).pause_general, 12.5)
        for value in (-1, True, float("nan"), float("inf"), "60"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                AvitoConfig(pause_general=value)
