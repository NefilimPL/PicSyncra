from __future__ import annotations

import threading

import pytest

from picsyncra.web.process_queue import (
    OwnerQueueLimit,
    ProcessQueueFull,
    ProcessQueueService,
    QueueLimits,
)


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
