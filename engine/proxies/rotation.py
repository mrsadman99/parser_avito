"""Повторные попытки смены IP с ограничением времени всего вызова."""
import multiprocessing
import os
import signal
import subprocess
import time

from loguru import logger

from engine.cancellation import Cancellation, ParseCancelled
from engine.proxies.proxy import ProxyRotationError


def _rotation_worker(proxy, sender):
    if os.name == "posix":
        os.setsid()
    # Spawn не наследует sinks родителя. Передаём сообщения ему же, чтобы
    # сохранять единые журналы и не вращать один файл из нескольких процессов.
    import hide_private_data  # noqa: F401 — маскировка до передачи сообщения
    logger.remove()
    from utils.http_logging import forward_http_logs
    forward_http_logs(lambda event: sender.send(("http", event)))
    logger.add(
        lambda message: sender.send(("log", message.record["level"].name, str(message).rstrip())),
        format="{name}:{function}:{line} - {message}", level="DEBUG", diagnose=False,
    )
    try:
        sender.send((bool(proxy.handle_block()), None))
    except Exception as err:
        sender.send((False, f"{type(err).__name__}: {err}"))
    finally:
        sender.close()


def _stop_worker(process):
    if process.is_alive():
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                process.kill()
        else:
            try:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=5, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if process.is_alive():
                process.kill()
    process.join()
    process.close()


def _rotation_attempt(proxy, cancellation):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_rotation_worker, args=(proxy, sender), daemon=True)
    deadline = time.monotonic() + proxy.rotation_timeout
    try:
        process.start()
        sender.close()
        while True:
            cancellation.checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False, f"таймаут {proxy.rotation_timeout} сек."
            if receiver.poll(min(cancellation.poll_interval, remaining)):
                try:
                    result = receiver.recv()
                except EOFError:
                    return False, "процесс смены IP завершился без результата"
                if result[0] == "log":
                    logger.bind(log_category="blocking").log(result[1], result[2])
                    continue
                if result[0] == "http":
                    from utils.http_logging import record_http, http_operation
                    result[1]['operation'] = http_operation.get()
                    record_http(result[1])
                    continue
                return result
            if not process.is_alive():
                return False, f"процесс смены IP завершился с кодом {process.exitcode}"
    finally:
        receiver.close()
        sender.close()
        if process.pid is not None:
            _stop_worker(process)


def rotate_with_retries(proxy, cancellation=None):
    cancellation = cancellation or Cancellation()
    last_error = None
    for attempt in range(1, proxy.rotation_attempts + 1):
        cancellation.checkpoint()
        logger.info(f"Смена IP: попытка {attempt}/{proxy.rotation_attempts}, таймаут {proxy.rotation_timeout} сек.")
        try:
            success, reason = _rotation_attempt(proxy, cancellation)
        except ParseCancelled:
            raise
        except Exception as err:
            success, reason = False, f"{type(err).__name__}: {err}"
        cancellation.checkpoint()
        if success:
            return True
        last_error = reason or "прокси вернул False"
        logger.warning(f"Смена IP: попытка {attempt} неуспешна: {last_error}")
        if attempt < proxy.rotation_attempts:
            cancellation.wait(proxy.rotation_retry_delay)
    raise ProxyRotationError(
        f"Не удалось сменить IP после {proxy.rotation_attempts} попыток: {last_error}"
    )
