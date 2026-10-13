import json
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest
from loguru import logger

from domain.config import AvitoConfig, LinkConfig, ParseTarget
from engine.app import AvitoParse
from persistence import store
from utils.db_diagnostics import DatabaseDiagnostics, database_environment
from utils.logging_setup import configure_app_logging


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "storage" / "web.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(store, "web_database_diagnostics", DatabaseDiagnostics())
    return path


def test_web_connection_closes_after_commit_and_rolls_back_on_error(database):
    with store._connect() as conn:
        conn.execute("CREATE TABLE sample (value INTEGER)")
        conn.execute("INSERT INTO sample VALUES (1)")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")

    with pytest.raises(RuntimeError, match="rollback"):
        with store._connect() as failed:
            failed.execute("INSERT INTO sample VALUES (2)")
            raise RuntimeError("rollback")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        failed.execute("SELECT 1")
    with store._connect() as check:
        assert [row[0] for row in check.execute("SELECT value FROM sample")] == [1]


def test_cantopen_records_cause_limits_and_suppression_then_recovery(database, tmp_path, monkeypatch):
    database.mkdir(parents=True)  # A directory at the database path causes real SQLITE_CANTOPEN.
    clock = Mock(return_value=100.0)
    monkeypatch.setattr(store, "web_database_diagnostics", DatabaseDiagnostics(clock=clock))
    parser = object.__new__(AvitoParse)
    parser.config = AvitoConfig()
    parser.links_provider = store.get_all_links
    old = {"cached": ParseTarget("https://example.invalid", LinkConfig())}
    parser._provider_links = old
    handlers = configure_app_logging(tmp_path / "logs")
    try:
        for _ in range(100):
            assert parser._current_links() == old
        clock.return_value = 131.0
        assert parser._current_links() == old
        database.rmdir()
        store.init_db()
        assert parser._current_links() == {}
    finally:
        for handler in handlers:
            logger.remove(handler)
    events = [json.loads(line) for line in (tmp_path / "logs/events.jsonl").read_text().splitlines()]
    failures = [event for event in events if event["message"].startswith("DB_DIAGNOSTIC failure:")]
    assert len(failures) == 2
    details = [json.loads(event["message"].split(": ", 1)[1]) for event in failures]
    assert details[0]["sqlite_errorcode"] == sqlite3.SQLITE_CANTOPEN
    assert details[0]["sqlite_errorname"] == "SQLITE_CANTOPEN"
    assert details[0]["stage"] == "connect"
    environment = details[0]["environment"]
    assert environment["absolute_path"] == str(database)
    assert environment["files"][0]["is_directory"] is True
    assert "file_descriptors" in environment
    assert "cwd" in environment
    assert details[1]["failures"] == 101
    assert details[1]["suppressed_since_last"] == 99
    recovered = next(event for event in events if event["message"].startswith("DB_DIAGNOSTIC recovered:"))
    assert json.loads(recovered["message"].split(": ", 1)[1])["failures"] == 101
    assert not any("Не удалось получить ссылки из провайдера" in event["message"] for event in events)


def test_parent_file_error_has_os_errno_and_mkdir_stage(database):
    database.parent.parent.mkdir(exist_ok=True)
    database.parent.write_text("file instead of directory")
    messages = []
    sink = logger.add(lambda message: messages.append(message.record["message"]))
    try:
        with pytest.raises(FileExistsError):
            store.get_all_links()
    finally:
        logger.remove(sink)
    details = json.loads(next(m for m in messages if m.startswith("DB_DIAGNOSTIC failure:")).split(": ", 1)[1])
    assert details["stage"] == "mkdir"
    assert details["errno"] is not None


def test_diagnostic_survives_fd_exhaustion_during_inspection(database):
    with patch("utils.db_diagnostics.os.listdir", side_effect=OSError(24, "Too many open files")):
        details = database_environment(database)
    assert details["file_descriptors"]["errno"] == 24
    assert "files" in details


def test_concurrent_failures_emit_one_diagnostic_per_interval(database):
    diagnostic = DatabaseDiagnostics(clock=lambda: 100.0)
    messages = []
    sink = logger.add(lambda message: messages.append(message.record["message"]))
    try:
        def fail(_):
            diagnostic.failure(database, sqlite3.OperationalError("unable to open database file"),
                               stage="connect", operation="get_all_links")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(fail, range(80)))
        diagnostic.success(database, operation="get_all_links")
    finally:
        logger.remove(sink)
    assert sum(m.startswith("DB_DIAGNOSTIC failure:") for m in messages) == 1
    recovery = json.loads(next(m for m in messages if m.startswith("DB_DIAGNOSTIC recovered:")).split(": ", 1)[1])
    assert recovery["failures"] == 80
    assert recovery["suppressed_since_last"] == 79


def test_diagnostic_failure_does_not_mask_original_database_error(database):
    database.mkdir(parents=True)
    with patch("utils.db_diagnostics.database_environment", side_effect=RuntimeError("inspection unavailable")):
        with pytest.raises(sqlite3.OperationalError) as caught:
            store.get_all_links()
    assert caught.value.sqlite_errorcode == sqlite3.SQLITE_CANTOPEN
