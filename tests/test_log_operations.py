import json
from unittest.mock import Mock, patch

import pytest
from loguru import logger

from engine.app import AvitoParse
from engine.cancellation import Cancellation
from utils.logging_setup import configure_app_logging


def test_parser_tags_catalog_and_detail_requests_and_their_failures(tmp_path):
    parser = object.__new__(AvitoParse)
    parser._is_stopped = lambda: False
    parser.good_request_count = parser.bad_request_count = 0
    parser.camoufox = None
    parser.db_handler = Mock()

    def request(*args, **kwargs):
        logger.bind(log_category="blocking").info("HTTP request")
        return Mock(status_code=200, json=Mock(side_effect=ValueError("invalid JSON")))

    parser._request = request
    parser.http = Mock(request=request)
    handlers = configure_app_logging(tmp_path)
    try:
        with patch("engine.app.save_catalog_response") as save:
            assert parser.fetch_api_data("https://example.invalid/search", 1) is None
            save.assert_not_called()
        with pytest.raises(ValueError):
            parser._refresh_ad(123, Cancellation())
        logger.info("after calls")
    finally:
        for handler in handlers:
            logger.remove(handler)
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [event["operation"] for event in events] == ["scan", "scan", "refresh", "refresh", "other"]
    assert events[0]["subsystem"] == events[2]["subsystem"] == "blocking"
    assert parser.bad_request_count == 2
    parser.db_handler.finish_ad_refresh.assert_called_once_with(123)
