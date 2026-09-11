"""Wakeable, bounded waits for notification polling workers."""

import threading


class WakeableDeadlineScheduler:
    """Wait until work arrives, a bounded deadline passes, or shutdown begins."""

    def __init__(self, max_idle_seconds: float = 60.0, condition=None):
        self._condition = condition or threading.Condition()
        self._generation = 0
        self._max_idle = max_idle_seconds
        self._waiting = threading.Event()

    def wake(self) -> None:
        """Interrupt current waiters so they can re-evaluate their deadlines."""
        with self._condition:
            self._generation += 1
            self._condition.notify_all()

    def capture_generation(self) -> int:
        """Capture a token before reading state used to calculate a deadline."""
        with self._condition:
            return self._generation

    def wait(
        self,
        stop_event,
        delay_seconds: float | None,
        *,
        since_generation: int | None = None,
    ) -> str:
        """Wait for a wake, stop signal, or deadline, returning its cause."""
        timeout = self._max_idle
        if delay_seconds is not None:
            timeout = max(0.0, min(timeout, float(delay_seconds)))

        with self._condition:
            generation = (
                self._generation
                if since_generation is None
                else since_generation
            )
            if stop_event.is_set():
                return "stop"
            if self._generation != generation:
                return "wake"
            self._waiting.set()
            try:
                self._condition.wait_for(
                    lambda: stop_event.is_set() or self._generation != generation,
                    timeout=timeout,
                )
            finally:
                self._waiting.clear()
            if stop_event.is_set():
                return "stop"
            return "wake" if self._generation != generation else "deadline"

    def wait_until_waiting(self, timeout: float) -> bool:
        """Wait for a waiter to reach the scheduler wait point."""
        return self._waiting.wait(timeout)
