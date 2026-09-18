from __future__ import annotations

import threading

import pytest

from picsyncra.web.process_queue import (
    MaintenanceInProgress,
    OwnerQueueLimit,
    ProcessQueueFull,
    ProcessQueueService,
    QueueLimits,
)
from picsyncra.installation.maintenance import MaintenanceGate


def test_reservations_enforce_global_and_owner_limits() -> None:
    """Catches a queue that admits a third job or duplicate owner reservation."""
    queue = ProcessQueueService(
        QueueLimits(workers=1, max_pending=2, max_per_owner=1),
        start_workers=False,
    )

    first = queue.reserve("owner-a")
    with pytest.raises(OwnerQueueLimit):
        queue.reserve("owner-a")

    second = queue.reserve("owner-b")
    with pytest.raises(ProcessQueueFull) as error:
        queue.reserve("owner-c")

    assert error.value.retry_after_seconds == 2
    first.release()
    second.release()


def test_cancelled_waiting_job_is_skipped_and_positions_are_recomputed() -> None:
    """Catches a worker that runs a cancelled job or leaves its old position."""
    first_started = threading.Event()
    unblock_first = threading.Event()
    third_finished = threading.Event()
    started_jobs: list[str] = []

    def run_first(job_id: str, cancel_event: threading.Event) -> None:
        started_jobs.append(job_id)
        first_started.set()
        assert unblock_first.wait(timeout=5.0)

    def run_second(job_id: str, cancel_event: threading.Event) -> None:
        started_jobs.append(job_id)

    def run_third(job_id: str, cancel_event: threading.Event) -> None:
        started_jobs.append(job_id)
        third_finished.set()

    queue = ProcessQueueService(
        QueueLimits(workers=1, max_pending=3, max_per_owner=3),
    )
    try:
        queue.submit(queue.reserve("owner-a"), "first", run_first)
        assert first_started.wait(timeout=5.0)

        queue.submit(queue.reserve("owner-b"), "second", run_second)
        queue.submit(queue.reserve("owner-c"), "third", run_third)
        assert queue.position("second") == 1
        assert queue.position("third") == 2

        assert queue.cancel("second") is True
        assert queue.position("third") == 1

        unblock_first.set()
        assert third_finished.wait(timeout=5.0)
    finally:
        unblock_first.set()
        shutdown = getattr(queue, "shutdown", None)
        if shutdown is not None:
            shutdown()

    assert started_jobs == ["first", "third"]


def test_maintenance_waits_for_admitted_reservation_and_rejects_new_one() -> None:
    """A drain cannot miss a job admitted immediately before it begins."""
    gate = MaintenanceGate()
    queue = ProcessQueueService(start_workers=False, maintenance_gate=gate)

    admitted = queue.reserve("owner-a")
    gate.begin("update-1", initiator_id="admin")

    assert gate.snapshot()["active_tasks"] == 1
    with pytest.raises(MaintenanceInProgress):
        queue.reserve("owner-b")

    assert gate.wait_for_drain(timeout=0.01) is False
    assert admitted.release() is True
    assert gate.wait_for_drain(timeout=0.01) is True


def test_force_maintenance_cancels_an_admitted_queued_job() -> None:
    gate = MaintenanceGate()
    queue = ProcessQueueService(start_workers=False, maintenance_gate=gate)
    reservation = queue.reserve("owner-a")
    queue.submit(reservation, "job-1", lambda _job_id, _cancel: None)

    gate.begin("update-1", initiator_id="admin")
    assert gate.request_force_cancel() == 1
    assert gate.wait_for_drain(timeout=0.01) is True
    assert queue.position("job-1") is None
