"""Диагностика SQLite без содержимого БД и SQL-параметров."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import threading
import time
import traceback

from loguru import logger


def _os_error(error):
    return {"error": str(error), "errno": getattr(error, "errno", None)}


def _path_info(path):
    result = {"path": str(path)}
    try:
        info = path.stat()
        result.update(exists=True, mode=stat.filemode(info.st_mode), uid=info.st_uid,
                      gid=info.st_gid, size=info.st_size, is_directory=stat.S_ISDIR(info.st_mode))
        kwargs = {"effective_ids": True} if os.access in os.supports_effective_ids else {}
        result["access"] = {name: os.access(path, flag, **kwargs) for name, flag in
                            (("read", os.R_OK), ("write", os.W_OK), ("execute", os.X_OK))}
        result["symlink"] = path.is_symlink()
    except OSError as error:
        result.update(_os_error(error))
        if isinstance(error, FileNotFoundError):
            result["exists"] = False
    return result


def _file_descriptors(database):
    result = {}
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        result.update(soft_limit=soft, hard_limit=hard)
    except (ImportError, OSError, ValueError) as error:
        result["limits_error"] = str(error)
    directory = Path("/proc/self/fd") if Path("/proc/self").is_dir() else Path("/dev/fd")
    try:
        # No subprocesses/lsof: even opening another pipe may fail at the FD limit.
        entries = os.listdir(directory)
        result.update(count=sum(name.isdigit() for name in entries), source=str(directory))
        counts = {"database": 0, "wal": 0, "shm": 0, "journal": 0}
        targets = {str(database): "database", str(database) + "-wal": "wal",
                   str(database) + "-shm": "shm", str(database) + "-journal": "journal"}
        for name in entries:
            try:
                target = os.readlink(directory / name).removesuffix(" (deleted)")
            except OSError:
                continue
            if target in targets:
                counts[targets[target]] += 1
        result["matching_database_files"] = counts
    except OSError as error:
        result.update(_os_error(error))
    return result


def database_environment(path):
    """Best effort: ошибки отдельных проверок тоже становятся частью диагностики."""
    path = Path(path)
    result = {"configured_path": str(path), "pid": os.getpid(),
              "thread": threading.current_thread().name, "thread_count": threading.active_count()}
    try:
        result["cwd"] = os.getcwd()
        absolute = Path(os.path.abspath(path))
        result["absolute_path"] = str(absolute)
    except OSError as error:
        result["cwd_error"] = _os_error(error)
        absolute = path
    try:
        result["resolved_path"] = str(absolute.resolve())
    except (OSError, RuntimeError) as error:
        result["resolve_error"] = _os_error(error)
    for name in ("getuid", "geteuid", "getgid", "getegid", "getgroups"):
        getter = getattr(os, name, None)
        if getter is not None:
            try:
                result[name.removeprefix("get")] = getter()
            except OSError as error:
                result[name] = _os_error(error)
    result["files"] = [_path_info(Path(str(absolute) + suffix))
                       for suffix in ("", "-wal", "-shm", "-journal")]
    result["directories"] = [_path_info(parent) for parent in list(absolute.parents)[:12]]
    try:
        disk = os.statvfs(absolute.parent)
        result["filesystem"] = {
            "available_bytes": disk.f_bavail * disk.f_frsize,
            "free_inodes": disk.f_favail,
            "read_only": bool(disk.f_flag & getattr(os, "ST_RDONLY", 1)),
        }
    except (OSError, AttributeError) as error:
        result["filesystem"] = _os_error(error)
    result["file_descriptors"] = _file_descriptors(absolute)
    return result


@dataclass
class _State:
    ready: bool = False
    failures: int = 0
    suppressed: int = 0
    first_failure: float = 0
    last_log: float = 0
    signature: tuple = ()


class DatabaseDiagnostics:
    """Первый сбой, затем раз в 30с/при смене ошибки, и сообщение о восстановлении."""
    def __init__(self, interval=30, clock=None):
        self.interval = interval
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._states = {}

    def failure(self, path, error, *, stage, operation):
        # Lets the parser avoid repeating this same error hundreds of times.
        error._db_diagnostic_reported = True
        key = (str(path), operation)
        now = self._clock()
        signature = (stage, type(error).__name__, str(error),
                     getattr(error, "sqlite_errorcode", None), getattr(error, "errno", None))
        with self._lock:
            state = self._states.setdefault(key, _State())
            state.failures += 1
            if state.failures == 1:
                state.first_failure = now
            if state.failures > 1 and signature == state.signature and now - state.last_log < self.interval:
                state.suppressed += 1
                return
            details = dict(failures=state.failures, suppressed_since_last=state.suppressed,
                           failure_duration_seconds=round(now - state.first_failure, 3))
            state.last_log, state.signature, state.suppressed = now, signature, 0
        details.update(stage=stage, operation=operation, exception_type=type(error).__name__,
                       error=str(error), sqlite_errorcode=getattr(error, "sqlite_errorcode", None),
                       sqlite_errorname=getattr(error, "sqlite_errorname", None),
                       errno=getattr(error, "errno", None),
                       traceback="".join(traceback.format_exception(type(error), error, error.__traceback__)))
        try:
            details["environment"] = database_environment(path)
        except Exception as diagnostic_error:
            details["diagnostic_error"] = str(diagnostic_error)
        logger.bind(log_category="scanning").error(
            "DB_DIAGNOSTIC failure: {}", json.dumps(details, ensure_ascii=False))

    def success(self, path, *, operation):
        key = (str(path), operation)
        with self._lock:
            state = self._states.setdefault(key, _State())
            if state.ready and not state.failures:
                return
            recovered = bool(state.failures)
            details = dict(operation=operation, failures=state.failures,
                           suppressed_since_last=state.suppressed,
                           failure_duration_seconds=round(self._clock() - state.first_failure, 3)
                           if recovered else 0)
            self._states[key] = _State(ready=True)
        try:
            details["environment"] = database_environment(path)
        except Exception as diagnostic_error:
            details["diagnostic_error"] = str(diagnostic_error)
        logger.bind(log_category="scanning").info(
            "DB_DIAGNOSTIC {}: {}", "recovered" if recovered else "ready",
            json.dumps(details, ensure_ascii=False))


web_database_diagnostics = DatabaseDiagnostics()
