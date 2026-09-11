"""Load desktop product data outside the Tk event thread."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
from typing import Callable

from .excel_utils import ENTRY_RECORDS_KEY, prepare_excel_lists


DESKTOP_DATA_POLL_MS = 25
_MIN_POLL_MS = 10
_MAX_POLL_MS = 250


@dataclass(frozen=True)
class DesktopDataSnapshot:
    """Complete product data published to the desktop UI."""

    lists: dict
    entries: tuple


def load_desktop_data() -> DesktopDataSnapshot:
    """Build a complete desktop snapshot without accessing Tk state."""

    lists = prepare_excel_lists(ui_errors=False)
    if not isinstance(lists, dict):
        lists = {}
    records = lists.get(ENTRY_RECORDS_KEY, [])
    if not isinstance(records, list):
        records = []
    return DesktopDataSnapshot(
        lists=lists,
        entries=tuple(record for record in records if isinstance(record, dict)),
    )


class DesktopDataLoader:
    """Run one desktop data load and publish its result through a scheduler."""

    def __init__(
        self,
        *,
        load: Callable,
        schedule: Callable,
        cancel_schedule: Callable | None = None,
        poll_interval_ms: int = DESKTOP_DATA_POLL_MS,
    ) -> None:
        self._load = load
        self._schedule = schedule
        self._cancel_schedule = cancel_schedule
        try:
            requested_poll_ms = int(poll_interval_ms)
        except (TypeError, ValueError):
            requested_poll_ms = DESKTOP_DATA_POLL_MS
        self._poll_interval_ms = max(
            _MIN_POLL_MS,
            min(_MAX_POLL_MS, requested_poll_ms),
        )
        self._thread = None
        self._lock = threading.Lock()
        self._running = False
        self._closed = False
        self._poll_handle = None
        self._on_success = None
        self._on_error = None
        self._results = queue.Queue()

    def start(self, on_success: Callable, on_error: Callable) -> bool:
        with self._lock:
            if self._running or self._closed:
                return False
            self._running = True
            self._on_success = on_success
            self._on_error = on_error

        def worker() -> None:
            try:
                snapshot = self._load()
            except Exception as error:
                result = (False, error)
            else:
                result = (True, snapshot)
            with self._lock:
                if self._closed:
                    return
                self._results.put(result)

        thread = threading.Thread(
            target=worker,
            name="DesktopDataLoader",
            daemon=True,
        )
        self._thread = thread
        try:
            self._schedule_poll()
        except Exception:
            with self._lock:
                self._running = False
                self._on_success = None
                self._on_error = None
            raise
        try:
            thread.start()
        except Exception:
            self.cancel()
            raise
        return True

    def _schedule_poll(self) -> None:
        with self._lock:
            if self._closed:
                return
        handle = self._schedule(
            self._poll_interval_ms,
            self._deliver_pending_result,
        )
        cancel_handle = None
        with self._lock:
            if self._closed:
                cancel_handle = handle
            else:
                self._poll_handle = handle
        if cancel_handle is not None and self._cancel_schedule is not None:
            self._cancel_schedule(cancel_handle)

    def _deliver_pending_result(self) -> None:
        with self._lock:
            self._poll_handle = None
            if self._closed:
                return
        try:
            succeeded, value = self._results.get_nowait()
        except queue.Empty:
            with self._lock:
                running = self._running
            if running or not self._results.empty():
                self._schedule_poll()
            return

        with self._lock:
            callback = self._on_success if succeeded else self._on_error
            self._on_success = None
            self._on_error = None
            self._running = False
            closed = self._closed
        if closed or callback is None:
            return
        callback(value)

    def cancel(self) -> None:
        """Cancel UI delivery and discard results after the owning UI closes."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._running = False
            self._on_success = None
            self._on_error = None
            poll_handle = self._poll_handle
            self._poll_handle = None
            while True:
                try:
                    self._results.get_nowait()
                except queue.Empty:
                    break
        if poll_handle is not None and self._cancel_schedule is not None:
            try:
                self._cancel_schedule(poll_handle)
            except Exception:
                pass

    def join_for_test(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
