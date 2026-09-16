from __future__ import annotations

from pathlib import Path

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


def test_channel_and_autostart_are_persisted_by_installed_service(tmp_path: Path) -> None:
    from picsyncra.installation.operation_service import InstalledOperationService

    service = InstalledOperationService(context(tmp_path), Controller())
    assert service.change_channel("dev") == {"channel": "dev"}
    assert service.set_autostart(True) == {"autostart": True}
    reloaded = InstalledOperationService(context(tmp_path), Controller())
    assert reloaded.status()["channel"] == "dev"
