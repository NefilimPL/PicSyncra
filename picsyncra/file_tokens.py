"""Short-lived, opaque tokens for files already approved by the server."""

from __future__ import annotations

from collections import OrderedDict
import secrets
import threading
import time
from collections.abc import Callable


class FileTokenRegistry:
    """Keep a bounded mapping from browser tokens to trusted file paths."""

    def __init__(
        self,
        *,
        max_age_seconds: float = 30 * 60,
        max_entries: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_age_seconds = max_age_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._lock = threading.Lock()

    def _discard_expired(self, now: float) -> None:
        expired = [token for token, (_path, expiry) in self._entries.items() if expiry <= now]
        for token in expired:
            self._entries.pop(token, None)

    def issue(self, path: str) -> str:
        """Register an already validated path and return an opaque browser token."""
        now = self._clock()
        with self._lock:
            self._discard_expired(now)
            token = secrets.token_urlsafe(32)
            while token in self._entries:
                token = secrets.token_urlsafe(32)
            self._entries[token] = (path, now + self._max_age_seconds)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return token

    def resolve(self, token: str) -> str | None:
        """Return a live registered path, or ``None`` for an unknown/expired token."""
        now = self._clock()
        with self._lock:
            self._discard_expired(now)
            entry = self._entries.get(token)
            if entry is None:
                return None
            self._entries.move_to_end(token)
            return entry[0]
