"""Maintenance state coordinates safe draining before an installed update."""

from __future__ import annotations

import threading

from picsyncra.installation.maintenance import MaintenanceGate


class Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_admitted_work_is_counted_until_its_lease_finishes() -> None:
    gate = MaintenanceGate()
    lease = gate.try_admit("upload")
    assert lease is not None
    assert gate.snapshot()["active_tasks"] == 1
    assert lease.finish() is True
    assert lease.finish() is False
    assert gate.snapshot()["active_tasks"] == 0


def test_begin_draining_blocks_new_work_without_losing_already_admitted_work() -> None:
    gate = MaintenanceGate()
    upload = gate.try_admit("upload")
    assert upload is not None
    gate.begin("operation-1", initiator_id="admin")
    assert gate.try_admit("ftp") is None
    assert gate.snapshot()["state"] == "draining"
    assert gate.snapshot()["active_by_kind"] == {"upload": 1}
    upload.finish()
    assert gate.snapshot()["active_tasks"] == 0


def test_only_one_operation_can_own_the_maintenance_gate() -> None:
    gate = MaintenanceGate()
    gate.begin("operation-1", initiator_id="admin")
    gate.begin("operation-1", initiator_id="someone-else")
    try:
        gate.begin("operation-2", initiator_id="admin")
    except RuntimeError as exc:
        assert "operation" in str(exc)
    else:
        raise AssertionError("A second operation acquired maintenance")


def test_force_requests_registered_cancellation_once_and_never_reopens_admission() -> None:
    gate = MaintenanceGate()
    cancelled: list[str] = []
    lease = gate.try_admit("ocr", on_cancel=lambda: cancelled.append("ocr"))
    assert lease is not None
    gate.begin("operation-1", initiator_id="admin")
    assert gate.request_force_cancel() == 1
    assert gate.request_force_cancel() == 0
    assert cancelled == ["ocr"]
    assert gate.try_admit("upload") is None
    assert gate.snapshot()["force_requested"] is True


def test_wait_for_drain_wakes_when_last_task_finishes() -> None:
    gate = MaintenanceGate()
    lease = gate.try_admit("ftp")
    assert lease is not None
    gate.begin("operation-1", initiator_id="admin")
    finished = threading.Event()

    def wait() -> None:
        assert gate.wait_for_drain(timeout=1.0) is True
        finished.set()

    thread = threading.Thread(target=wait)
    thread.start()
    lease.finish()
    thread.join(timeout=1.0)
    assert finished.is_set()


def test_complete_restores_admission_only_for_the_owning_operation() -> None:
    gate = MaintenanceGate()
    gate.begin("operation-1", initiator_id="admin")
    try:
        gate.complete("other-operation")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Wrong operation completed maintenance")
    gate.complete("operation-1")
    assert gate.try_admit("upload") is not None
