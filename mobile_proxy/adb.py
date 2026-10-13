"""Все обращения к ADB и их вывод сохраняются в logs/adb.log (JSON Lines)."""
import codecs
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import threading
import time
import uuid

from loguru import logger

ADB_LOG = Path(__file__).resolve().parent.parent / "logs" / "adb.log"
_log_lock = threading.Lock()


def _record(request_id, event, **values):
    entry = dict(time=datetime.now(timezone.utc).isoformat(), pid=os.getpid(),
                 request_id=request_id, event=event, **values)
    data = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    # Отдельная запись одним append, без Loguru rotation между процессами.
    with _log_lock:
        ADB_LOG.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(ADB_LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)


def _command(serial, args):
    return ["adb"] + (["-s", str(serial)] if serial else []) + list(args)


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def run_adb(serial, *args, timeout=30):
    command = _command(serial, args)
    request_id = uuid.uuid4().hex
    started = time.monotonic()
    _record(request_id, "start", command=command, timeout=timeout)
    logger.debug("ADB [{}]: {} (timeout={}s)", request_id, shlex.join(command), timeout)
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as err:
        _record(request_id, "timeout", elapsed=time.monotonic() - started,
                stdout=_text(err.stdout), stderr=_text(err.stderr), error=str(err))
        logger.warning("ADB [{}]: timeout после {}s; stdout={!r}; stderr={!r}",
                       request_id, timeout, _text(err.stdout), _text(err.stderr))
        return None
    except Exception as err:
        _record(request_id, "error", elapsed=time.monotonic() - started,
                error=f"{type(err).__name__}: {err}")
        logger.warning("ADB [{}]: {}: {}", request_id, type(err).__name__, err)
        return None
    _record(request_id, "finish", elapsed=time.monotonic() - started,
            returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    if result.returncode != 0 or result.stderr:
        logger.warning("ADB [{}]: code={}; stdout={!r}; stderr={!r}", request_id,
                       result.returncode, result.stdout, result.stderr)
    else:
        logger.debug("ADB [{}]: code=0; stdout={!r}", request_id, result.stdout)
    return result


def stream_adb(serial, args, output):
    """Вывод tail пишется сразу в output и журнал; stderr читается параллельно."""
    command = _command(serial, args)
    request_id = uuid.uuid4().hex
    started = time.monotonic()
    _record(request_id, "start", command=command, timeout=None, streaming=True)
    logger.debug("ADB stream [{}]: {}", request_id, shlex.join(command))
    proc = None
    readers = []
    failures = []

    def drain(pipe, name):
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while True:
                chunk = pipe.read1(8192)
                if not chunk:
                    break
                if name == "stdout":
                    output.write(chunk)
                    output.flush()
                decoded = decoder.decode(chunk)
                if decoded:
                    _record(request_id, name, data=decoded)
                    if name == "stderr":
                        logger.warning("ADB stream [{}] stderr: {}", request_id, decoded)
            rest = decoder.decode(b"", final=True)
            if rest:
                _record(request_id, name, data=rest)
        except Exception as err:
            failures.append(err)
            _record(request_id, "error", stream=name, error=f"{type(err).__name__}: {err}")
            proc.terminate()
        finally:
            pipe.close()

    try:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _record(request_id, "spawn", child_pid=proc.pid)
        for pipe, name in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
            thread = threading.Thread(target=drain, args=(pipe, name))
            readers.append(thread)
            thread.start()
        code = proc.wait()
        for thread in readers:
            thread.join()
        if failures:
            raise RuntimeError("Ошибка чтения ADB stream") from failures[0]
        return code
    except BaseException as err:
        _record(request_id, "error", error=f"{type(err).__name__}: {err}")
        raise
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            for thread in readers:
                thread.join()
            _record(request_id, "finish", elapsed=time.monotonic() - started,
                    returncode=proc.returncode, streaming=True)

