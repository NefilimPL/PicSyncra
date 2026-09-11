"""Thread-safe delivery control for desktop FTP preview requests."""

from __future__ import annotations

import threading
from collections.abc import Callable
from queue import Empty, SimpleQueue
from typing import Any


class DesktopFtpPreviewController:
    """Publish FTP preview work only while its request remains current."""

    def __init__(
        self,
        *,
        downloader: Callable[[int, str, threading.Event, Callable[[Any], None]], None],
        temp_manager: Any,
        schedule: Callable[[], Any],
    ) -> None:
        self._downloader = downloader
        self._temp_manager = temp_manager
        self._schedule = schedule
        self._lock = threading.Lock()
        self._ui_thread_id = threading.get_ident()
        self._deliveries: SimpleQueue = SimpleQueue()
        self._request_id = 0
        self._cancel_event: threading.Event | None = None
        self._outstanding: dict[int, threading.Event] = {}
        self._pending_deliveries = 0
        self._closed = False

    def request(
        self,
        ean: str,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        on_discard: Callable[[Any], None] | None = None,
    ) -> int:
        """Start one request and make every older request stale.

        The injected downloader may finish on a worker thread. It only enqueues
        delivery; :meth:`drain` must be called by the UI thread.
        """

        if not isinstance(ean, str):
            raise TypeError("ean must be a string")
        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("desktop FTP preview requests require the UI thread")
        with self._lock:
            if self._closed:
                raise RuntimeError("desktop FTP preview controller is closed")
            if self._cancel_event is not None:
                self._cancel_event.set()
            self._request_id += 1
            request_id = self._request_id
            cancel_event = threading.Event()
            self._cancel_event = cancel_event
            self._outstanding[request_id] = cancel_event

        def complete(result: Any) -> None:
            self._enqueue_delivery(
                "success",
                request_id,
                cancel_event,
                result,
                on_success,
                on_error,
                on_discard,
            )

        try:
            self._downloader(request_id, ean, cancel_event, complete)
        except Exception as exc:
            self._enqueue_delivery(
                "error",
                request_id,
                cancel_event,
                exc,
                on_success,
                on_error,
                on_discard,
            )
        self._schedule()
        return request_id

    def drain(self) -> int:
        """Deliver queued completions on the caller's thread."""

        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("desktop FTP preview callbacks require the UI thread")
        delivered = 0
        while True:
            try:
                (
                    kind,
                    request_id,
                    cancel_event,
                    payload,
                    on_success,
                    on_error,
                    on_discard,
                ) = self._deliveries.get_nowait()
            except Empty:
                return delivered
            with self._lock:
                self._pending_deliveries -= 1
                is_closed = self._closed
                is_current = (
                    not is_closed
                    and self._request_id == request_id
                    and self._cancel_event is cancel_event
                    and not cancel_event.is_set()
                )
            if is_current:
                if kind == "success":
                    on_success(payload)
                else:
                    on_error(payload)
            elif not is_closed and kind == "success" and on_discard is not None:
                on_discard(payload)
            delivered += 1

    def has_pending_work(self) -> bool:
        """Return whether UI polling must continue for worker completion."""

        with self._lock:
            return bool(self._outstanding) or self._pending_deliveries > 0

    def create_request_dir(
        self,
        request_id: int,
        cancel_event: threading.Event,
    ) -> str | None:
        """Allocate a temp directory only while the request remains current."""

        with self._lock:
            if (
                self._closed
                or self._request_id != request_id
                or self._cancel_event is not cancel_event
                or cancel_event.is_set()
            ):
                return None
            return self._temp_manager.create_request_dir(request_id)

    def cancel_current(self) -> None:
        """Cancel the outstanding request and invalidate scheduled delivery."""

        with self._lock:
            if self._cancel_event is not None:
                self._cancel_event.set()
            self._request_id += 1
            self._cancel_event = None

    def close(self) -> None:
        """Cancel outstanding work and release manager-owned preview files once."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            for cancel_event in self._outstanding.values():
                cancel_event.set()
            self._request_id += 1
            self._cancel_event = None
            self._temp_manager.close()

    def _enqueue_delivery(
        self,
        kind: str,
        request_id: int,
        cancel_event: threading.Event,
        payload: Any,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        on_discard: Callable[[Any], None] | None,
    ) -> None:
        with self._lock:
            if request_id not in self._outstanding:
                return
            self._outstanding.pop(request_id)
            if self._closed:
                return
            self._pending_deliveries += 1
        self._deliveries.put(
            (
                kind,
                request_id,
                cancel_event,
                payload,
                on_success,
                on_error,
                on_discard,
            )
        )
