"""Завершение фонового процесса, запущенного с start_new_session=True."""
from contextlib import contextmanager
import os
import signal
import shlex
import subprocess
import time


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as handle:
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


def alive(pid):
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.waitpid(pid, os.WNOHANG)
    except (OSError, ChildProcessError):
        pass
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop(pid, timeout=15, scripts=()):
    if not isinstance(pid, int) or pid <= 1:
        raise ValueError("Некорректный PID фонового процесса")
    # Сначала только родитель: его finally закрывает ADB/SSH и удаляет проброс.
    if alive(pid):
        if scripts and os.name != "nt":
            command = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                     capture_output=True, text=True, timeout=5)
            if alive(pid) and (command.returncode != 0 or not any(
                    str(script) in shlex.split(command.stdout) for script in scripts)):
                raise RuntimeError(f"PID {pid} не принадлежит ожидаемому фоновому процессу")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + timeout
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
    # PID фонового процесса совпадает с PGID. Не используем getpgid: устаревший
    # PID-файл не должен привести к сигналу группе вызывающего процесса.
    if os.name != "nt":
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif alive(pid):
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if alive(pid):
        raise RuntimeError(f"Фоновый процесс {pid} не завершился")
