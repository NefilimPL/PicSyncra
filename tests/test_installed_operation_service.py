from __future__ import annotations

from pathlib import Path
import time

import pytest

from picsyncra.installation.contracts import InstallContext, OperationRequest


class Controller:
    def __init__(self, *, restart_result: bool = True, running: bool = True) -> None:
        self.restart_result = restart_result
        self.running = running
        self.restart_calls = 0
        self.autostart = False

    def restart_backend(self) -> bool:
        self.restart_calls += 1
        return self.restart_result

    def snapshot(self) -> dict[str, bool]:
        return {"backend_running": self.running, "autostart": self.autostart}

    def set_autostart(self, enabled: bool) -> bool:
        self.autostart = enabled
        return enabled


def context(tmp_path: Path) -> InstallContext:
    root = tmp_path / "program"
    state = tmp_path / "state"
    (root / "versions" / "41").mkdir(parents=True, exist_ok=True)
    (state / "config").mkdir(parents=True, exist_ok=True)
    (root / "active.json").write_text(
        '{"schema":1,"installation_id":"site-1","release_id":41}', encoding="utf-8"
    )
    return InstallContext("site-1", root, state, state / "config", state / "data.sqlite")


def restart_request(request_id: str = "restart-1") -> OperationRequest:
    return OperationRequest(request_id, "restart", None, None, False)


def test_remote_restart_uses_only_controller_and_advances_session_epoch(tmp_path: Path) -> None:
    from picsyncra.installation.operation_service import InstalledOperationService

    controller = Controller()
    service = InstalledOperationService(context(tmp_path), controller)
    result = service.submit(restart_request(), actor_id="admin-1")

    assert result["state"] == "committed"
    assert controller.restart_calls == 1
    assert service.status()["session_epoch"] == 1

    repeated = service.submit(restart_request(), actor_id="admin-1")
    assert repeated["state"] == "committed"
    assert controller.restart_calls == 1
    assert service.status()["session_epoch"] == 1


def test_failed_remote_restart_is_recorded_without_advancing_session_epoch(tmp_path: Path) -> None:
    from picsyncra.installation.operation_service import InstalledOperationService

    service = InstalledOperationService(context(tmp_path), Controller(restart_result=False))
    result = service.submit(restart_request(), actor_id="admin-1")

    assert result["state"] == "failed"
    assert result["error_code"] == "apply_failed"
    assert service.status()["session_epoch"] == 0


def test_update_submission_stays_disabled_until_verified_package_executor_is_connected(tmp_path: Path) -> None:
    from picsyncra.installation.operation_service import OperationUnavailable, InstalledOperationService

    service = InstalledOperationService(context(tmp_path), Controller())
    with pytest.raises(OperationUnavailable):
        service.submit(OperationRequest("update-1", "update", 42, None, False), actor_id="admin-1")


def test_verified_release_executor_runs_backup_before_switching_and_invalidates_sessions(tmp_path: Path) -> None:
    from picsyncra.installation.contracts import BackupReceipt
    from picsyncra.installation.operation_service import InstalledOperationService

    calls: list[str] = []

    class Executor:
        def create_backup(self, operation_id: str):
            calls.append("backup")
            return BackupReceipt(operation_id, operation_id, "a" * 64, "b" * 64, 1, 41, True)

        def apply(self, _request):
            calls.append("apply")

        def validate(self, _request):
            calls.append("validate")
            return True

        def rollback(self, _backup):
            calls.append("rollback")

    controller = Controller()
    service = InstalledOperationService(context(tmp_path), controller, release_executor_factory=lambda _request: Executor())
    result = service.submit(OperationRequest("update-1", "update", 42, None, False), actor_id="admin-1")

    assert result["state"] == "committed"
    assert calls == ["backup", "apply", "validate"]
    assert controller.restart_calls == 1
    assert service.status()["session_epoch"] == 1


def test_verified_ocr_executor_runs_as_a_backed_up_maintenance_operation(tmp_path: Path) -> None:
    from picsyncra.installation.contracts import BackupReceipt
    from picsyncra.installation.operation_service import InstalledOperationService

    calls: list[str] = []

    class Executor:
        def create_backup(self, operation_id: str):
            calls.append("backup")
            return BackupReceipt(operation_id, operation_id, "a" * 64, "b" * 64, 1, 41, True)

        def apply(self, _request):
            calls.append("apply")

        def validate(self, _request):
            calls.append("validate")
            return True

        def rollback(self, _backup):
            calls.append("rollback")

    service = InstalledOperationService(context(tmp_path), Controller(), ocr_executor_factory=lambda _request: Executor())
    result = service.submit(OperationRequest("ocr-1", "install_ocr", None, None, False), actor_id="admin-1")

    assert result["state"] == "committed"
    assert calls == ["backup", "apply", "validate"]
    assert service.status()["session_epoch"] == 1


def test_failed_updated_backend_restores_the_previous_release_and_restarts_it(tmp_path: Path) -> None:
    from picsyncra.installation.contracts import BackupReceipt
    from picsyncra.installation.operation_service import InstalledOperationService

    calls: list[str] = []

    class Executor:
        def create_backup(self, operation_id: str):
            calls.append("backup")
            return BackupReceipt(operation_id, operation_id, "a" * 64, "b" * 64, 1, 41, True)

        def apply(self, _request):
            calls.append("apply")

        def validate(self, _request):
            calls.append("validate")
            return True

        def rollback(self, _backup):
            calls.append("rollback")

    class ControllerWithRetry(Controller):
        def __init__(self):
            super().__init__()
            self._results = [False, True]

        def restart_backend(self) -> bool:
            self.restart_calls += 1
            return self._results.pop(0)

    controller = ControllerWithRetry()
    service = InstalledOperationService(context(tmp_path), controller, release_executor_factory=lambda _request: Executor())
    result = service.submit(OperationRequest("update-1", "update", 42, None, False), actor_id="admin-1")

    assert result["state"] == "rolled_back"
    assert calls == ["backup", "apply", "validate", "rollback"]
    assert controller.restart_calls == 2
    assert service.status()["session_epoch"] == 0


def test_update_rolls_back_when_session_invalidation_cannot_be_saved(tmp_path: Path, monkeypatch) -> None:
    from picsyncra.installation.contracts import BackupReceipt
    from picsyncra.installation import operation_service as module

    calls: list[str] = []

    class Executor:
        def create_backup(self, operation_id: str):
            return BackupReceipt(operation_id, operation_id, "a" * 64, "b" * 64, 1, 41, True)

        def apply(self, _request):
            calls.append("apply")

        def validate(self, _request):
            calls.append("validate")
            return True

        def rollback(self, _backup):
            calls.append("rollback")

    monkeypatch.setattr(module, "advance_session_epoch", lambda _context: (_ for _ in ()).throw(OSError("disk full")))
    controller = Controller()
    service = module.InstalledOperationService(context(tmp_path), controller, release_executor_factory=lambda _request: Executor())

    result = service.submit(OperationRequest("update-1", "update", 42, None, False), actor_id="admin-1")

    assert result["state"] == "rolled_back"
    assert calls == ["apply", "validate", "rollback"]
    assert controller.restart_calls == 2
    assert service.maintenance_gate.snapshot()["state"] == "idle"


def test_channel_and_autostart_are_persisted_by_installed_service(tmp_path: Path) -> None:
    from picsyncra.installation.operation_service import InstalledOperationService

    service = InstalledOperationService(context(tmp_path), Controller())
    assert service.change_channel("dev") == {"channel": "dev"}
    assert service.set_autostart(True) == {"autostart": True}
    reloaded = InstalledOperationService(context(tmp_path), Controller())
    assert reloaded.status()["channel"] == "dev"


def test_restart_waits_for_admitted_work_and_force_exposes_drain_status(tmp_path: Path) -> None:
    from picsyncra.installation.operation_service import InstalledOperationService

    controller = Controller()
    service = InstalledOperationService(context(tmp_path), controller)
    admitted = service.maintenance_gate.try_admit("upload")
    assert admitted is not None

    submitted = service.submit(restart_request(), actor_id="admin-1")
    assert submitted["state"] == "draining"
    assert submitted["active_tasks"] == 1
    assert controller.restart_calls == 0
    assert service.force_operation(str(submitted["operation_id"])) is not None

    admitted.finish()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        result = service.read_operation(str(submitted["operation_id"]))
        if result is not None and result["state"] == "committed":
            break
        time.sleep(0.02)
    assert result is not None
    assert result["state"] == "committed"
    assert controller.restart_calls == 1
