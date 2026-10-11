"""Последовательная очередь: обходы подписок имеют приоритет над обновлениями."""
from contextlib import contextmanager
import random
import threading
import time

from parser.cancellation import Cancellation


class RequestThrottle:
    def __init__(self, min_delay, max_delay):
        self.min_delay = max(0.0, float(min_delay))
        self.max_delay = max(self.min_delay, float(max_delay))
        self._lock = threading.Lock()
        self._state = threading.Lock()
        self._queue = []
        self._sequence = 0
        self._foreground = 0
        self._next_at = 0.0

    @contextmanager
    def foreground(self):
        # Включает промежутки между страницами, разбор и сохранение результатов.
        with self._state:
            self._foreground += 1
        try:
            yield
        finally:
            with self._state:
                self._foreground -= 1

    def _ready(self, ticket):
        with self._state:
            return min(self._queue) == ticket and (ticket[0] == 0 or self._foreground == 0)

    def run(self, fn, *args, cancellation=None, background=False, **kwargs):
        cancellation = cancellation or Cancellation()
        with self._state:
            ticket = (int(background), self._sequence)
            self._sequence += 1
            self._queue.append(ticket)
        try:
            while True:
                cancellation.checkpoint()
                if not self._ready(ticket):
                    cancellation.wait(0.05)
                    continue
                if not self._lock.acquire(timeout=0.1):
                    continue
                try:
                    # Приоритет проверяется повторно после блокировки и во время паузы.
                    while self._ready(ticket):
                        cancellation.checkpoint()
                        remaining = self._next_at - time.monotonic()
                        if remaining <= 0:
                            try:
                                return fn(*args, **kwargs)
                            finally:
                                self._next_at = time.monotonic() + random.uniform(self.min_delay, self.max_delay)
                        cancellation.wait(min(remaining, 0.05))
                finally:
                    self._lock.release()
        finally:
            with self._state:
                self._queue.remove(ticket)
