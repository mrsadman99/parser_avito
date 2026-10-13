"""Кооперативная отмена обхода, в том числе во время ожиданий."""
from contextlib import contextmanager
import time
from typing import Callable


class ParseCancelled(Exception):
    """Подписка изменилась, удалена или парсер остановлен."""


class Cancellation:
    poll_interval = 0.1

    def __init__(self, cancelled: Callable[[], bool] = lambda: False):
        self.cancelled = cancelled

    def checkpoint(self):
        if self.cancelled():
            raise ParseCancelled()

    def wait(self, seconds: float):
        deadline = time.monotonic() + max(0, seconds)
        while True:
            self.checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(self.poll_interval, remaining))


@contextmanager
def cancellable_lock(lock, cancellation: Cancellation):
    cancellation.checkpoint()
    while not lock.acquire(timeout=cancellation.poll_interval):
        cancellation.checkpoint()
    try:
        cancellation.checkpoint()
        yield
    finally:
        lock.release()
