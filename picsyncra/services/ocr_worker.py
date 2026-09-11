"""Small cooperative runner for the persisted OCR crop queue."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class StopEvent(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, seconds: float) -> bool: ...


class OcrQueueWorker:
    """Run one scheduled OCR crop at a time until the application stops."""

    def __init__(
        self,
        *,
        run_once: Callable[[], str],
        poll_seconds: float,
        stop_event: StopEvent,
    ) -> None:
        self._run_once = run_once
        self._poll_seconds = max(0.05, float(poll_seconds))
        self._stop_event = stop_event

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._run_once()
            self._stop_event.wait(self._poll_seconds)
