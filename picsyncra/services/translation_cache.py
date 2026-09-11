"""Thread-safe bounded cache for successful translation results."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
import threading
import time
from typing import Any, TypeVar


T = TypeVar("T")


class TranslationCache:
    def __init__(self, *, max_entries: int = 2048, ttl_seconds: float = 3600) -> None:
        self._max_entries = max(1, int(max_entries))
        self._ttl_seconds = max(0.0, float(ttl_seconds))
        self._values: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._inflight: set[Hashable] = set()
        self._condition = threading.Condition()

    def clear(self) -> None:
        with self._condition:
            self._values.clear()

    def get_or_translate(
        self,
        key: Hashable,
        loader: Callable[[], T],
        *,
        now: float | None = None,
    ) -> T:
        clock = time.monotonic if now is None else lambda: now
        while True:
            with self._condition:
                current = clock()
                cached = self._values.get(key)
                if cached is not None:
                    expires_at, value = cached
                    if current < expires_at:
                        self._values.move_to_end(key)
                        return value
                    del self._values[key]
                if key not in self._inflight:
                    self._inflight.add(key)
                    break
                self._condition.wait()
        try:
            value = loader()
        except Exception:
            with self._condition:
                self._inflight.remove(key)
                self._condition.notify_all()
            raise
        with self._condition:
            self._inflight.remove(key)
            if getattr(value, "warning", None) is None:
                self._values[key] = (clock() + self._ttl_seconds, value)
                self._values.move_to_end(key)
                while len(self._values) > self._max_entries:
                    self._values.popitem(last=False)
            self._condition.notify_all()
        return value
