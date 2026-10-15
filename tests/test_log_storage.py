import gzip
import json
import multiprocessing
import os
from pathlib import Path
import time

from utils.log_storage import append_log, remove_legacy_logs, save_payload


def test_gzip_preserves_full_body_and_removes_oldest_by_size_and_age(tmp_path):
    root = tmp_path / 'http'
    day = root / '2026-10-14'
    day.mkdir(parents=True)
    old = day / 'old.json'
    old.write_text('{"old":true}')
    os.utime(old, (time.time() - 8 * 86400,) * 2)
    payload = {'body': 'Повторяемые данные ответа ' * 10000}
    first = save_payload(day / 'one.json', payload)
    assert not old.exists()
    assert json.loads(gzip.decompress(first.read_bytes())) == payload
    assert first.stat().st_size < len(json.dumps(payload).encode()) / 10
    os.utime(first, (time.time() - 60,) * 2)
    budget = first.stat().st_size + 10
    second = save_payload(day / 'two.json', payload, max_bytes=budget)
    assert second.exists() and not first.exists()
    assert sum(p.stat().st_size for p in day.iterdir()) <= budget
    assert not list(root.rglob('*.tmp'))


def test_count_limit_and_oversize_does_not_destroy_saved_response(tmp_path):
    day = tmp_path / 'http' / '2026-10-14'
    first = save_payload(day / 'first.json', {'ok': 1})
    os.utime(first, (time.time() - 60,) * 2)
    second = save_payload(day / 'second.json', {'ok': 2}, max_files=1)
    assert second.exists() and not first.exists()
    try:
        save_payload(day / 'too-large.json', {'body': 'hello'}, max_bytes=1)
    except ValueError:
        pass
    else:
        raise AssertionError('oversized payload accepted')
    assert second.exists()


def _writer(directory, identity):
    for number in range(30):
        append_log(Path(directory) / 'events.jsonl', json.dumps({'writer': identity, 'n': number}) + '\n',
                   max_bytes=300, backups=50)


def test_spawned_writers_and_rotation_preserve_all_records(tmp_path):
    context = multiprocessing.get_context('spawn')
    processes = [context.Process(target=_writer, args=(str(tmp_path), i)) for i in range(3)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
        process.close()
    records = [json.loads(line) for path in tmp_path.glob('events.jsonl*')
               for line in path.read_text().splitlines()]
    assert len(records) == 90
    assert {(r['writer'], r['n']) for r in records} == {(i, n) for i in range(3) for n in range(30)}


def test_rotation_limits_archive_count_and_cleanup_is_scoped(tmp_path):
    for n in range(30):
        append_log(tmp_path / 'app.log', f'event {n}\n', max_bytes=20, backups=2)
    assert len(list(tmp_path.glob('app.log*'))) == 3
    removed = ['scanning.log', 'blocking.2026-10-14.log', 'notifications.log.1',
               'tinyproxy_follow.log', 'tinyproxy_forward.log']
    retained = ['tinyproxy.log', 'adb.log', 'tinyproxy_forward.json', 'scanning-notes.txt']
    for name in removed + retained:
        (tmp_path / name).write_text('keep or remove')
    remove_legacy_logs(tmp_path)
    assert all(not (tmp_path / name).exists() for name in removed)
    assert all((tmp_path / name).exists() for name in retained)
    assert (tmp_path / 'app.log').exists()
