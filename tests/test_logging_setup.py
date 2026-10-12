import tempfile
import unittest
import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from utils.logging_setup import configure_app_logging, log_category
from parser.cancellation import Cancellation
from parser.proxies.rotation import _rotation_attempt


class LoggingRotationProxy:
    rotation_timeout = 5

    def handle_block(self):
        logger.info("CHILD_ROTATION 123456789:" + "x" * 30)
        return True


class LoggingTests(unittest.TestCase):
    def test_json_events_preserve_multiline_and_redact_secrets_without_extra(self):
        with tempfile.TemporaryDirectory() as directory:
            handlers = configure_app_logging(directory)
            secret = "123456789:" + "x" * 30
            try:
                log = logger.bind(log_category="notifications", private_extra="must-not-be-exported")
                log.info('Сообщение с переносом\n{"braces": true} <tag>')
                try:
                    raise ValueError('request failed for https://api.telegram.org/bot' + secret + '/sendPhoto')
                except ValueError:
                    log.exception('Ошибка отправки')
            finally:
                for handler in handlers:
                    logger.remove(handler)
            raw = (Path(directory) / "events.jsonl").read_text()
            self.assertEqual(len(raw.splitlines()), 2)
            events = [json.loads(line) for line in raw.splitlines()]
            self.assertEqual(events[0]['message'], 'Сообщение с переносом\n{"braces": true} <tag>')
            self.assertEqual(events[0]['level'], 'info')
            self.assertEqual(events[0]['subsystem'], 'notifications')
            self.assertEqual(events[1]['level'], 'error')
            self.assertIn('ValueError', events[1]['exception'])
            self.assertIn('<redacted-token>', events[1]['exception'])
            self.assertIsNotNone(datetime.fromisoformat(events[0]['timestamp']).utcoffset())
            self.assertNotIn(secret, raw)
            self.assertNotIn('must-not-be-exported', raw)

    def test_spawned_rotation_logs_reach_parent_files(self):
        with tempfile.TemporaryDirectory() as directory:
            handlers = configure_app_logging(directory)
            try:
                self.assertEqual(_rotation_attempt(LoggingRotationProxy(), Cancellation()), (True, None))
            finally:
                for handler in handlers:
                    logger.remove(handler)
            for category in ("app", "blocking"):
                content = (Path(directory) / f"{category}.log").read_text()
                self.assertIn("CHILD_ROTATION <redacted-token>", content)
                self.assertNotIn("123456789:", content)
            self.assertNotIn("CHILD_ROTATION", (Path(directory) / "scanning.log").read_text())

    def test_routing_shared_log_and_secret_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            handlers = configure_app_logging(directory)
            try:
                cases = [
                    ("parser_cls", "_run_scheduler", "ROUND", "scanning"),
                    ("parser_cls", "_refresh_ad", "REFRESH", "scanning"),
                    ("parser_cls", "_deliver_pending_notifications", "DELIVERY", "notifications"),
                    ("integrations.notifications.transport", "request", "TELEGRAM", "notifications"),
                    ("parser.http.client", "request", "HTTP", "blocking"),
                    ("parser.cookies.external_api", "unblock", "COOKIES", "blocking"),
                    ("parser.proxies.rotation", "rotate_with_retries", "ROTATE", "blocking"),
                    ("utils.adb", "run_adb", "ADB", "blocking"),
                    ("server.main", "unrelated", "OTHER", None),
                ]
                token = "123456789:" + "x" * 30
                for name, function, message, category in cases:
                    log = logger.patch(lambda record, n=name, f=function: record.update(name=n, function=f))
                    log.info(message + " " + token)
                logger.bind(log_category="blocking").critical("FATAL_ROTATION")
            finally:
                for handler in handlers:
                    logger.remove(handler)
            logs = {category: (Path(directory) / f"{category}.log").read_text()
                    for category in ("app", "scanning", "notifications", "blocking")}
            for name, function, message, expected in cases:
                self.assertIn(message, logs["app"])
                for category in ("scanning", "notifications", "blocking"):
                    self.assertEqual(message in logs[category], category == expected, (message, category))
            for content in logs.values():
                self.assertNotIn(token, content)
            self.assertIn("FATAL_ROTATION", logs["blocking"])
            self.assertIn("FATAL_ROTATION", logs["app"])
            self.assertNotIn("FATAL_ROTATION", logs["scanning"])

    def test_direct_parser_entrypoint_routes_by_filename(self):
        record = dict(name="__main__", file=type("File", (), {"name": "parser_cls.py"})(),
                      function="_notification_cycle", extra={})
        self.assertEqual(log_category(record), "notifications")
        record["function"] = "_link_cycle"
        self.assertEqual(log_category(record), "scanning")
