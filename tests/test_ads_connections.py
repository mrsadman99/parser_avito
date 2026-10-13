"""Соединения базы объявлений закрываются без ожидания сборщика мусора."""
import json
import sqlite3
from contextlib import closing

import pytest
from loguru import logger

from domain.item import Item, PriceDetailed
from persistence import ads
from utils.db_diagnostics import DatabaseDiagnostics


@pytest.fixture
def tracked_database(tmp_path, monkeypatch):
    connections = []
    original_connect = sqlite3.connect

    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        connections.append(conn)  # Удерживаем ссылки: GC не может закрыть их за нас.
        return conn

    monkeypatch.setattr(ads.SQLiteDBHandler, '_instance', None)
    monkeypatch.setattr(ads, 'ads_database_diagnostics', DatabaseDiagnostics())
    monkeypatch.setattr(ads.sqlite3, 'connect', connect)
    db = ads.SQLiteDBHandler(tmp_path / 'ads.db')
    yield db, connections
    for conn in connections:
        conn.close()


def assert_closed(connections):
    assert connections
    for conn in connections:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            conn.execute('SELECT 1')


def test_all_ad_operations_close_connections(tracked_database):
    db, connections = tracked_database
    item = Item(id=1, title='CPU', priceDetailed=PriceDetailed(
        enabled=True, fullString='500', hasValue=True, postfix='', string='500',
        stringWithoutDiscount=None, title={}, titleDative='', value=500,
        wasLowered=False, exponent=''))
    db.add_record(item)
    db.add_record_from_page([item], 'search', 'one', ['recipient'])
    db.update_catalog_status([item])
    db.next_ad_for_refresh(60)
    db.finish_ad_refresh(1)
    assert db.list_ads('search')
    assert db.list_ads_for_refresh()
    assert db.pending_notifications(['recipient'])
    job = db.claim_notification(['recipient'])
    db.finish_notification(job['id'], True)
    assert db.claim_notification(['recipient']) is None
    db.update_ad(1, {'description': 'updated'}, mark_refreshed=True)
    for _ in range(500):
        assert db.record_exists(1, 500, 'one')
    db.delete_ad(1)
    assert not db.record_exists(1, 500, 'one')
    assert_closed(connections)


def test_connection_closes_and_transaction_rolls_back_on_failure(tracked_database):
    db, connections = tracked_database
    with pytest.raises(RuntimeError, match='rollback'):
        with db._connect('test_rollback') as conn:
            conn.execute("INSERT INTO viewed(id, price) VALUES (99, 100)")
            raise RuntimeError('rollback')
    assert not db.record_exists(99, 100)
    assert_closed(connections)


def test_relative_database_path_does_not_follow_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(ads.SQLiteDBHandler, '_instance', None)
    monkeypatch.chdir(tmp_path)
    db = ads.SQLiteDBHandler('ads.db')
    other = tmp_path / 'other'
    other.mkdir()
    monkeypatch.chdir(other)
    assert not db.record_exists(1, 100)
    assert db.db_name == str(tmp_path / 'ads.db')
    assert not (other / 'ads.db').exists()


def test_cantopen_logs_real_ads_path_and_operation_then_recovers(tracked_database):
    db, _ = tracked_database
    path = ads.Path(db.db_name)
    backup = path.with_suffix('.saved')
    path.rename(backup)
    path.mkdir()
    messages = []
    sink = logger.add(lambda message: messages.append(message.record['message']))
    try:
        with pytest.raises(sqlite3.OperationalError) as caught:
            db.record_exists(1, 500)
        assert caught.value.sqlite_errorcode == sqlite3.SQLITE_CANTOPEN
        path.rmdir()
        backup.rename(path)
        assert not db.record_exists(1, 500)
    finally:
        logger.remove(sink)
    failure = next(m for m in messages if m.startswith('DB_DIAGNOSTIC failure:'))
    details = json.loads(failure.split(': ', 1)[1])
    assert details['operation'] == 'record_exists'
    assert details['stage'] == 'connect'
    assert details['environment']['absolute_path'] == db.db_name
    assert details['environment']['files'][0]['is_directory'] is True
    assert any(m.startswith('DB_DIAGNOSTIC recovered:') for m in messages)


def test_migration_closes_backup_connection(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.db'
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('CREATE TABLE viewed (id INTEGER, price INTEGER)')
        conn.execute('INSERT INTO viewed VALUES (1, 500)')
    original_connect = sqlite3.connect
    connections = []

    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        connections.append(conn)
        return conn

    monkeypatch.setattr(ads.SQLiteDBHandler, '_instance', None)
    monkeypatch.setattr(ads.sqlite3, 'connect', connect)
    try:
        db = ads.SQLiteDBHandler(path)
        assert db.record_exists(1, 500)
        assert len(list(tmp_path.glob('legacy.db.before-subscriptions-*.bak'))) == 1
        assert_closed(connections)
    finally:
        for conn in connections:
            conn.close()
