"""Bounded, owner-aware reservations for process jobs."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
import uuid
from collections.abc import Callable


@dataclass(frozen=True)
class QueueLimits:
    workers: int = 1
    max_pending: int = 8
    max_per_owner: int = 2
    retry_after_seconds: int = 2


class ProcessQueueFull(RuntimeError):
    def __init__(self, retry_after_seconds: int):
        super().__init__("process queue is full")
        self.retry_after_seconds = retry_after_seconds


class OwnerQueueLimit(RuntimeError):
    """Raised when an owner has reached its reservation limit."""


class QueueReservation:
    """A queue slot that may be submitted later or released idempotently."""

    def __init__(self, queue: ProcessQueueService, token: str, owner_id: str):
        self._queue = queue
        self.token = token
        self.owner_id = owner_id
        self.state = "reserved"

    def release(self) -> bool:
        return self._queue._release(self)


@dataclass
class _QueuedJob:
    reservation: QueueReservation
    job_id: str
    run: Callable[[str, threading.Event], None]
    cancel_event: threading.Event
    state: str = "submitted"


class ProcessQueueService:
    """Reserves the bounded capacity shared by process job producers."""

    def __init__(self, limits: QueueLimits | None = None, *, start_workers: bool = True):
        self.limits = limits or QueueLimits()
        self._condition = threading.Condition()
        self._reservations: dict[str, QueueReservation] = {}
        self._owner_counts: dict[str, int] = {}
        self._jobs: deque[_QueuedJob] = deque()
        self._jobs_by_id: dict[str, _QueuedJob] = {}
        self._stopping = False
        self._workers: list[threading.Thread] = []
        self._start_workers = start_workers
        if start_workers:
            self._workers = [
                threading.Thread(
                    target=self._worker_loop,
                    name=f"ProcessQueueService-{index + 1}",
                    daemon=True,
                )
                for index in range(self.limits.workers)
            ]
            for worker in self._workers:
                worker.start()

    def reserve(self, owner_id: str) -> QueueReservation:
        with self._condition:
            if self._owner_counts.get(owner_id, 0) >= self.limits.max_per_owner:
                raise OwnerQueueLimit("owner queue limit reached")
            if len(self._reservations) >= self.limits.max_pending:
                raise ProcessQueueFull(self.limits.retry_after_seconds)

            token = uuid.uuid4().hex
            reservation = QueueReservation(self, token, owner_id)
            self._reservations[token] = reservation
            self._owner_counts[owner_id] = self._owner_counts.get(owner_id, 0) + 1
            return reservation

    def _release(self, reservation: QueueReservation) -> bool:
        with self._condition:
            if reservation.state != "reserved":
                return False
            if not self._discard_reservation_locked(reservation):
                return False

            self._condition.notify_all()
            return True

    def _discard_reservation_locked(self, reservation: QueueReservation) -> bool:
        if self._reservations.pop(reservation.token, None) is None:
            return False

        owner_count = self._owner_counts[reservation.owner_id] - 1
        if owner_count:
            self._owner_counts[reservation.owner_id] = owner_count
        else:
            del self._owner_counts[reservation.owner_id]
        reservation.state = "released"
        return True

    def submit(
        self,
        reservation: QueueReservation,
        job_id: str,
        run: Callable[[str, threading.Event], None],
    ) -> int:
        with self._condition:
            if reservation._queue is not self or reservation.state != "reserved":
                raise RuntimeError("queue reservation is not available")
            if self._reservations.get(reservation.token) is not reservation:
                raise RuntimeError("queue reservation is not available")
            if job_id in self._jobs_by_id:
                raise ValueError(f"process job already exists: {job_id}")

            job = _QueuedJob(reservation, job_id, run, threading.Event())
            reservation.state = "submitted"
            self._jobs.append(job)
            self._jobs_by_id[job_id] = job
            self._condition.notify()
            return len(self._jobs)

    def position(self, job_id: str) -> int | None:
        with self._condition:
            for index, job in enumerate(self._jobs, start=1):
                if job.job_id == job_id:
                    return index
            return None

    def cancel(self, job_id: str) -> bool:
        with self._condition:
            job = self._jobs_by_id.get(job_id)
            if job is None:
                return False
            if job.state == "submitted":
                self._jobs.remove(job)
                self._jobs_by_id.pop(job_id, None)
                job.state = "cancelled"
                job.cancel_event.set()
                self._discard_reservation_locked(job.reservation)
                self._condition.notify_all()
                return True
            if job.state == "running":
                job.cancel_event.set()
                return True
            return False

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        for worker in self._workers:
            worker.join(timeout=timeout)

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._stopping or bool(self._jobs))
                if self._stopping and not self._jobs:
                    return
                job = self._jobs.popleft()
                job.state = "running"

            try:
                job.run(job.job_id, job.cancel_event)
            finally:
                with self._condition:
                    job.state = "cancelled" if job.cancel_event.is_set() else "completed"
                    self._jobs_by_id.pop(job.job_id, None)
                    self._discard_reservation_locked(job.reservation)
                    self._condition.notify_all()
