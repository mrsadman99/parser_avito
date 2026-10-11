"""Прямой TCP-проброс ADB: порт сервера → порт tinyproxy на телефоне."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

from loguru import logger

from utils.adb import run_adb

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "logs" / "tinyproxy_forward.json"
LOCK = ROOT / "logs" / "tinyproxy_forward.lock"
LOG = ROOT / "logs" / "tinyproxy_forward.log"
SCRIPT = ROOT / "scripts" / "watch_tinyproxy_forward.py"


def proxy_address(server, ports):
    address = (server or "").strip() or "127.0.0.1"
    try:
        parsed = urlsplit("//" + address)
        host, port = parsed.hostname, parsed.port
    except ValueError as err:
        raise ValueError("own_mobile_proxy.server должен быть host или host:port с портом от 1 до 65535") from err
    if (not host or parsed.username is not None or parsed.path or parsed.query or parsed.fragment
            or address.endswith(":") or any(char.isspace() for char in address)
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("own_mobile_proxy.server должен быть host или host:port с портом от 1 до 65535")
    if ":" in host:
        host = f"[{host}]"
    return f"{host}:{port if port is not None else ports[0]}"


@contextmanager
def _locked():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_state():
    try:
        state = json.loads(STATE.read_text())
        if (type(state.get("pid")) is int and state["pid"] > 0
                and all(type(state.get(key)) is int and 1 <= state[key] <= 65535
                        for key in ("phone_port", "local_port"))):
            return state
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _alive(pid):
    try:
        os.waitpid(pid, os.WNOHANG)
    except (OSError, ChildProcessError):
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _forward(serial, local_port, phone_port):
    result = run_adb(serial, "forward", f"tcp:{local_port}", f"tcp:{phone_port}", timeout=10)
    if result is None or result.returncode != 0:
        error = (result.stderr.strip() or result.stdout.strip()) if result is not None else "ADB недоступен / timeout"
        raise RuntimeError(f"Не удалось пробросить TCP-порт tinyproxy через ADB: {error}")


def _remove_forward(state):
    run_adb(state.get("serial"), "forward", "--remove", f"tcp:{state['local_port']}", timeout=10)


def _stop(state):
    if _alive(state["pid"]):
        os.kill(state["pid"], signal.SIGTERM)
        deadline = time.monotonic() + 15
        while _alive(state["pid"]) and time.monotonic() < deadline:
            time.sleep(0.1)
        if _alive(state["pid"]):
            os.kill(state["pid"], signal.SIGKILL)
            raise RuntimeError("TCP-проброс не завершился после SIGTERM; повторите остановку")
    if _read_state() == state:
        _remove_forward(state)
        STATE.unlink(missing_ok=True)


def stop_forward():
    with _locked():
        state = _read_state()
        if state:
            _stop(state)


def ensure_forward(serial, ports):
    """Создаёт adb forward на заданный порт и запускает монитор восстановления."""
    local_port, phone_port = ports
    serial = serial or ""
    with _locked():
        state = _read_state()
        if state and _alive(state["pid"]):
            if ("public_port" not in state and
                    (state.get("serial"), state["local_port"], state["phone_port"]) == (serial, local_port, phone_port)):
                _forward(serial, state["local_port"], phone_port)
                return
            _stop(state)
        elif state:
            _stop(state)
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as output:
            proc = subprocess.Popen(
                [sys.executable, str(SCRIPT), "--serial", serial, "--ports", str(local_port), str(phone_port)],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = _read_state()
            if state and state["pid"] == proc.pid and proc.poll() is None:
                logger.info("ADB forward: tcp:{} → телефон tcp:{}", local_port, phone_port)
                return
            if proc.poll() is not None:
                raise RuntimeError(f"TCP-проброс tinyproxy не запущен (код {proc.returncode}); см. {LOG}")
            time.sleep(0.1)
        proc.terminate()
        try:
            proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        raise RuntimeError(f"Timeout запуска TCP-проброса tinyproxy; см. {LOG}")


def watch_forward(serial, ports, retry_delay=5):
    """Восстанавливает adb forward; TCP-соединения обслуживает сам ADB-сервер."""
    local_port, phone_port = ports
    state = dict(pid=os.getpid(), serial=serial or "", phone_port=phone_port,
                 local_port=local_port)
    created = False

    def terminate(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        _forward(serial, local_port, phone_port)
        created = True
        STATE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(state))
        temporary.replace(STATE)
        logger.info("Монитор ADB forward: tcp:{} → телефон tcp:{}", local_port, phone_port)
        while True:
            time.sleep(retry_delay)
            try:
                _forward(serial, local_port, phone_port)
            except Exception as err:
                logger.warning("{}; повтор через {} секунд", err, retry_delay)
    finally:
        if created:
            _remove_forward(state)
        if _read_state() == state:
            STATE.unlink(missing_ok=True)
