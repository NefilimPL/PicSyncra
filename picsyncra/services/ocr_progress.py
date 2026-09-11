"""Bounded OCR run snapshots for tester and background queue progress."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Literal, Protocol
import threading
import time
import uuid


class OcrProgressStore(Protocol):
    def create_ocr_progress_run(
        self, run_id: str, *, kind: str, job_id: str | None
    ) -> None: ...

    def append_ocr_progress_event(
        self, run_id: str, sequence: int, kind: str, payload: dict[str, object]
    ) -> None: ...

    def finalize_ocr_progress_run(
        self,
        run_id: str,
        *,
        state: str,
        result: dict[str, object] | None,
        error: str | None,
    ) -> None: ...


@dataclass(frozen=True)
class OcrProgressEvent:
    sequence: int
    kind: str
    payload: dict[str, object]


@dataclass(frozen=True)
class OcrRunSnapshot:
    run_id: str
    kind: str
    job_id: str | None
    state: str
    latest_sequence: int
    cancel_requested: bool
    events: list[OcrProgressEvent]
    result: dict[str, object] | None
    error: str | None


@dataclass
class _Run:
    kind: str
    job_id: str | None
    created_at: float
    state: str = "running"
    sequence: int = 0
    cancel_requested: bool = False
    events: list[OcrProgressEvent] = field(default_factory=list)
    result: dict[str, object] | None = None
    error: str | None = None


class OcrProgressRegistry:
    """Publish ordered, bounded OCR progress without retaining image payloads."""

    def __init__(
        self,
        *,
        event_limit: int = 200,
        store: OcrProgressStore | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._event_limit = max(1, int(event_limit))
        self._store = store
        self._clock = clock
        self._runs: dict[str, _Run] = {}
        self._lock = threading.Lock()

    def create_run(self, *, kind: Literal["test", "queue"], job_id: str | None) -> str:
        run_id = f"ocr-run-{uuid.uuid4().hex}"
        with self._lock:
            self._runs[run_id] = _Run(kind=kind, job_id=job_id, created_at=self._clock())
        if kind == "queue" and self._store is not None:
            self._store.create_ocr_progress_run(run_id, kind=kind, job_id=job_id)
        return run_id

    def publish(self, run_id: str, kind: str, **payload: object) -> OcrProgressEvent:
        serialized_payload = {str(key): value for key, value in payload.items()}
        with self._lock:
            run = self._required_run(run_id)
            run.sequence += 1
            event = OcrProgressEvent(run.sequence, str(kind), serialized_payload)
            run.events.append(event)
            del run.events[:-self._event_limit]
            persist = run.kind == "queue" and self._store is not None
        if persist:
            self._store.append_ocr_progress_event(
                run_id, event.sequence, event.kind, event.payload
            )
        return event

    def snapshot(self, run_id: str, *, after_sequence: int = 0) -> OcrRunSnapshot:
        with self._lock:
            run = self._required_run(run_id)
            events = [event for event in run.events if event.sequence > after_sequence]
            return OcrRunSnapshot(
                run_id=run_id,
                kind=run.kind,
                job_id=run.job_id,
                state=run.state,
                latest_sequence=run.sequence,
                cancel_requested=run.cancel_requested,
                events=events,
                result=run.result,
                error=run.error,
            )

    def request_cancel(self, run_id: str) -> None:
        with self._lock:
            self._required_run(run_id).cancel_requested = True

    def is_cancel_requested(self, run_id: str) -> bool:
        with self._lock:
            return self._required_run(run_id).cancel_requested

    def finalize(
        self,
        run_id: str,
        *,
        state: str,
        result: dict[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            run = self._required_run(run_id)
            run.state = str(state)
            run.result = result
            run.error = str(error)[:2048] if error else None
            persist = run.kind == "queue" and self._store is not None
        if persist:
            self._store.finalize_ocr_progress_run(
                run_id, state=str(state), result=result, error=error
            )

    def prune_expired_test_runs(self, *, ttl_seconds: float) -> int:
        """Discard old ephemeral tester runs while retaining queue recovery state."""

        threshold = self._clock() - max(0.0, float(ttl_seconds))
        with self._lock:
            expired = [
                run_id
                for run_id, run in self._runs.items()
                if run.kind == "test" and run.created_at < threshold
            ]
            for run_id in expired:
                del self._runs[run_id]
        return len(expired)

    def _required_run(self, run_id: str) -> _Run:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"Unknown OCR run: {run_id}") from exc
