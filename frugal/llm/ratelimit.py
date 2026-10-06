"""Per-model client-side rate limiting so free-tier quotas don't turn into 429 storms."""

from __future__ import annotations

import threading
import time


class _Limiter:
    def __init__(self, rpm: int):
        self.interval = 60.0 / max(rpm, 1)
        self.next_ok = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            sleep_for = self.next_ok - now
            self.next_ok = max(now, self.next_ok) + self.interval
        if sleep_for > 0:
            time.sleep(sleep_for)


_limiters: dict[str, _Limiter] = {}
_guard = threading.Lock()


def acquire(model_key: str, rpm: int) -> None:
    with _guard:
        if model_key not in _limiters:
            _limiters[model_key] = _Limiter(rpm)
    _limiters[model_key].wait()
