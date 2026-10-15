import gzip
import json
from pathlib import Path
import re
from unittest.mock import Mock, patch

import pytest
from loguru import logger

from engine.app import AvitoParse
from engine.catalog_snapshots import save_catalog_response
from utils.logging_setup import configure_app_logging


URL = "https://www.avito.ru/web/1/js/items?query=X470+GAMING+PLUS+MAX&page=1"


def parser_for(response):
    parser = object.__new__(AvitoParse)
    parser._is_stopped = Mock(return_value=False)
    parser._request = Mock(return_value=response)
    parser.good_request_count = parser.bad_request_count = 0
    return parser


def test_each_response_is_complete_and_has_a_working_grafana_reference(tmp_path):
    # Larger than Loki's line limit; the full body must only be in the file.
    payload = {"count": 20, "totalCount": 20, "mainCount": 20,
               "catalog": {"items": [{"id": 123, "title": "Материнская плата"}]},
               "extra": "x" * 300_000}
    handlers = configure_app_logging(tmp_path)
    try:
        paths = [save_catalog_response(payload, url=URL, page=1, status_code=200,
                                       directory=tmp_path / "catalog_responses") for _ in range(2)]
    finally:
        for handler in handlers:
            logger.remove(handler)
    assert paths[0] != paths[1]
    for path in paths:
        assert json.loads(gzip.decompress(path.read_bytes())) == payload
    assert not list(tmp_path.rglob("*.tmp"))
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    datasource = Path("monitoring/grafana/provisioning/datasources/loki.yml").read_text()
    matcher = re.search(r"matcherRegex: '([^']+)'", datasource).group(1)
    for event, path in zip(events, paths):
        assert event["catalog_items"] == event["catalog_ads"] == 1
        assert event["catalog_count"] == event["catalog_total_count"] == event["catalog_main_count"] == 20
        assert event["catalog_query"] == "X470 GAMING PLUS MAX"
        assert event["catalog_url"] == URL
        assert event["subsystem"] == "scanning"
        # Grafana's derived field must work on both raw events and line_format(message).
        for line in (json.dumps(event), event["message"]):
            reference = re.search(matcher, line).group(1)
            assert reference == event["catalog_snapshot"]
            assert tmp_path / "catalog_responses" / (reference + ".gz") == path
        assert len(json.dumps(event)) < 5000


@pytest.mark.parametrize("payload", [{"catalog": {"items": []}}, {"unexpected": [1, 2]}, []])
def test_empty_and_unexpected_json_is_saved_before_validation(tmp_path, payload):
    response = Mock(status_code=200, json=Mock(return_value=payload))
    parser = parser_for(response)
    with patch("engine.app.save_catalog_response", side_effect=lambda data, **kw:
               save_catalog_response(data, directory=tmp_path, **kw)):
        assert parser.fetch_api_data(URL, 1) is payload
    paths = list(tmp_path.rglob("*.json.gz"))
    assert len(paths) == 1
    assert json.loads(gzip.decompress(paths[0].read_bytes())) == payload
    assert parser.bad_request_count == 0


def test_disk_failure_does_not_discard_response_or_retry_request(tmp_path):
    blocked_directory = tmp_path / "not-a-directory"
    blocked_directory.write_text("occupied")
    payload = {"catalog": {"items": [{"id": 123}]}}
    parser = parser_for(Mock(status_code=200, json=Mock(return_value=payload)))
    with patch("engine.app.save_catalog_response", side_effect=lambda data, **kw:
               save_catalog_response(data, directory=blocked_directory, **kw)):
        assert parser.fetch_api_data(URL, 1) is payload
    parser._request.assert_called_once()
    assert parser.bad_request_count == 0
    assert blocked_directory.read_text() == "occupied"


def test_partial_write_is_not_published(tmp_path):
    with patch("utils.log_storage.gzip.compress", side_effect=OSError("disk full")):
        assert save_catalog_response({}, url=URL, page=1, status_code=200, directory=tmp_path) is None
    assert not list(tmp_path.rglob("*.json.gz"))
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize("status", [403, 429, 500])
def test_failed_http_responses_are_not_published(tmp_path, status):
    assert save_catalog_response({}, url=URL, page=1, status_code=status, directory=tmp_path) is None
    assert not list(tmp_path.iterdir())


def test_invalid_json_and_failed_requests_do_not_create_snapshots():
    parser = parser_for(Mock(status_code=200, json=Mock(side_effect=ValueError("not JSON"))))
    with patch("engine.app.save_catalog_response") as save:
        assert parser.fetch_api_data(URL, 1) is None
        parser._request.side_effect = TimeoutError("offline")
        assert parser.fetch_api_data(URL, 1) is None
        save.assert_not_called()


def test_metadata_whitelist_does_not_export_request_secrets(tmp_path):
    handlers = configure_app_logging(tmp_path)
    try:
        logger.bind(catalog_snapshot="example.json", catalog_page=1,
                    cookies={"session": "private-cookie"}, authorization="private-auth").info("saved")
    finally:
        for handler in handlers:
            logger.remove(handler)
    text = (tmp_path / "events.jsonl").read_text()
    assert json.loads(text)["catalog_snapshot"] == "example.json"
    assert "private-cookie" not in text
    assert "private-auth" not in text


def test_snapshot_preserves_both_arrays_and_reports_combined_unique_ads(tmp_path):
    payload = {"catalog": {"items": [{"id": 1}], "extraBlockItems": [
        {"type": "header"}, {"id": 1}, {"id": 2},
    ]}}
    handlers = configure_app_logging(tmp_path)
    try:
        path = save_catalog_response(payload, url=URL, page=1, status_code=200,
                                     directory=tmp_path / "catalog_responses")
    finally:
        for handler in handlers:
            logger.remove(handler)
    assert json.loads(gzip.decompress(path.read_bytes())) == payload
    event = json.loads((tmp_path / "events.jsonl").read_text())
    assert event["catalog_main_items"] == 1
    assert event["catalog_extra_items"] == 3
    assert event["catalog_items"] == event["catalog_ads"] == 2
