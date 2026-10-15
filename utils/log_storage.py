"""Общее хранилище журналов с блокировкой между процессами и ограничением объёма."""
import gzip
import json
from pathlib import Path
import threading
import time

from mobile_proxy.background_process import locked

_lock = threading.RLock()


def append_log(path, text, *, max_bytes=5_000_000, backups=10):
    """Открываем файл под lock: дочерние процессы переживают ротацию родителем."""
    path = Path(path)
    with _lock, locked(path.parent / '.journal.lock'):
        data = text.encode('utf-8')
        if path.exists() and path.stat().st_size + len(data) > max_bytes:
            oldest = path.with_name(path.name + f'.{backups}')
            oldest.unlink(missing_ok=True)
            for index in range(backups - 1, 0, -1):
                source = path.with_name(path.name + f'.{index}')
                if source.exists():
                    source.replace(path.with_name(path.name + f'.{index + 1}'))
            path.replace(path.with_name(path.name + '.1'))
        with path.open('ab') as output:
            output.write(data)


def save_payload(destination, payload, *, retention_days=7, max_bytes=128 * 1024 * 1024,
                 max_files=10_000):
    """Gzip JSON; бюджет на каталог http или catalog_responses, включая старые JSON.

    Возвращает физический .gz; URL без .gz обслуживается gzip_static шлюза.
    Удаление старейших файлов выполняется при каждой записи под общей блокировкой.
    """
    destination = Path(destination)
    root = destination.parent.parent
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    data = gzip.compress(encoded, compresslevel=6, mtime=0)
    if len(data) > max_bytes:
        raise ValueError('Compressed payload exceeds storage budget')
    compressed = destination.with_suffix(destination.suffix + '.gz')
    temporary = compressed.with_suffix('.tmp')
    with _lock, locked(root / '.payload.lock'):
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            temporary.write_bytes(data)
            temporary.chmod(0o644)
            temporary.replace(compressed)
            destination.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)
        cutoff = time.time() - retention_days * 86400
        files = []
        for path in root.glob('*/*'):
            if path.is_symlink() or not path.is_file() or not (path.name.endswith('.json') or path.name.endswith('.json.gz')):
                continue
            stat = path.stat()
            if stat.st_mtime < cutoff and path != compressed:
                path.unlink()
            else:
                files.append((stat.st_mtime, path, stat.st_size))
        size = sum(entry[2] for entry in files)
        count = len(files)
        for _, path, length in sorted(files):
            if size <= max_bytes and count <= max_files:
                break
            if path != compressed:
                path.unlink()
                size -= length
                count -= 1
        for directory in root.iterdir():
            if directory.is_dir() and not directory.is_symlink():
                try:
                    directory.rmdir()
                except OSError:
                    pass
    return compressed


def remove_legacy_logs(directory):
    """Удалить только отменённые журналы и их архивы при запуске новой версии."""
    directory = Path(directory)
    with _lock, locked(directory / '.journal.lock'):
        for name in ('scanning', 'notifications', 'blocking', 'tinyproxy_follow', 'tinyproxy_forward'):
            for pattern in (name + '.log', name + '.log.*', name + '.*.log'):
                for path in directory.glob(pattern):
                    if path.is_file() and not path.is_symlink():
                        path.unlink()
