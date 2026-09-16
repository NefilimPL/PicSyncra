from __future__ import annotations

from pathlib import Path

from picsyncra.installation.contracts import InstallContext, OperationRequest
from picsyncra.installation.journal import OperationJournal


def context(tmp_path: Path) -> InstallContext:
    return InstallContext("site-1", tmp_path / "program", tmp_path / "state", tmp_path / "state" / "config", tmp_path / "state" / "data.sqlite")


def test_interrupted_install_requires_explicit_recovery_and_is_idempotent(tmp_path: Path) -> None:
    from picsyncra.installation.recovery import recover_pending_operation

    value = context(tmp_path)
    journal = OperationJournal(value.state_root / "operations.json")
    operation = journal.submit(OperationRequest("request-1", "update", 42, None, False), actor_id="admin")
    journal.transition(operation.operation_id, "draining")
    journal.transition(operation.operation_id, "backing_up")
    journal.transition(operation.operation_id, "installing")

    recovered = recover_pending_operation(value)

    assert recovered is not None
    assert recovered.state == "recovery_required"
    assert recovered.error_code == "interrupted_operation"
    assert recover_pending_operation(value) is None


def test_service_blocks_new_operations_after_startup_recovery(tmp_path: Path) -> None:
    from picsyncra.installation.operation_service import InstalledOperationService, OperationUnavailable

    class Controller:
        def restart_backend(self): return True
        def snapshot(self): return {"backend_running": True, "autostart": False}
        def set_autostart(self, enabled): return enabled

    value = context(tmp_path)
    journal = OperationJournal(value.state_root / "operations.json")
    operation = journal.submit(OperationRequest("request-1", "update", 42, None, False), actor_id="admin")
    journal.transition(operation.operation_id, "draining")
    journal.transition(operation.operation_id, "backing_up")
    journal.transition(operation.operation_id, "installing")
    service = InstalledOperationService(value, Controller())

    with __import__("pytest").raises(OperationUnavailable):
        service.submit(OperationRequest("restart-1", "restart", None, None, False), actor_id="admin")
