"""Short-lived WEB presence used when an installed backend enters maintenance."""

from __future__ import annotations

from collections.abc import Callable
import time


class PresenceRegistry:
    """Track browser heartbeats without treating several tabs as several users."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, ttl_seconds: float = 60.0) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._entries: dict[tuple[str, str], float] = {}

    def heartbeat(self, user_id: str, session_id: str) -> None:
        if not isinstance(user_id, str) or not user_id or not isinstance(session_id, str) or not session_id:
            raise ValueError("user_id and session_id must be non-empty strings")
        self._entries[(user_id, session_id)] = self._clock()

    def remove(self, user_id: str, session_id: str) -> bool:
        self._expire()
        return self._entries.pop((user_id, session_id), None) is not None

    def other_user_count(self, initiator_id: str) -> int:
        self._expire()
        return len({user_id for user_id, _session_id in self._entries if user_id != initiator_id})

    def _expire(self) -> None:
        cutoff = self._clock() - self._ttl_seconds
        for key, observed_at in tuple(self._entries.items()):
            if observed_at <= cutoff:
                self._entries.pop(key, None)
