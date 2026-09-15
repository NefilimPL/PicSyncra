"""Installed backend supervision must never act on an unrelated listener."""

from __future__ import annotations

from pathlib import Path

import pytest

from picsyncra.installation.contracts import InstallContext
from picsyncra.installation.controller import (
    InstallationController,
    InstallationControllerError,
)


class FakeScmAdapter:
    """In-memory SCM boundary; the controller behavior stays real."""

    def __init__(self, *, port_owner: str | None = None) -> None:
        self.port_owner = port_owner
        self.backend_running = False
        self.autostart = False
        self.start_calls = 0
        self.stop_calls: list[bool] = []

    def listener_owner(self, _port: int) -> str | None:
        return self.port_owner

    def start_backend(self) -> None:
        self.start_calls += 1
        self.backend_running = True
        self.port_owner = "primary-installation"

    def stop_backend(self, *, force: bool) -> bool:
        self.stop_calls.append(force)
        self.backend_running = False
        self.port_owner = None
        return True

    def set_autostart(self, enabled: bool) -> bool:
        self.autostart = enabled
        return True

    def snapshot(self) -> dict[str, object]:
        return {
            "backend_running": self.backend_running,
            "autostart": self.autostart,
        }


def _context(tmp_path: Path) -> InstallContext:
    return InstallContext(
        installation_id="primary-installation",
        program_root=tmp_path / "program",
        state_root=tmp_path / "state",
        config_root=tmp_path / "state" / "config",
        database_path=tmp_path / "state" / "data" / "picsyncra.sqlite",
    )


def test_controller_starts_owned_backend_and_reports_confirmed_autostart(
    tmp_path: Path,
) -> None:
    """Catches treating a requested SCM change as a confirmed service state."""

    scm = FakeScmAdapter()
    controller = InstallationController(_context(tmp_path), scm, backend_port=8010)

    controller.start_backend()
    assert controller.set_autostart(True) is True

    assert scm.start_calls == 1
    assert controller.snapshot() == {
        "installation_id": "primary-installation",
        "backend_port": 8010,
        "backend_running": True,
        "autostart": True,
    }


def test_controller_refuses_a_port_owned_by_another_process(tmp_path: Path) -> None:
    """Catches starting a second backend or killing a foreign listener on force."""

    scm = FakeScmAdapter(port_owner="foreign-process")
    controller = InstallationController(_context(tmp_path), scm, backend_port=8010)

    with pytest.raises(InstallationControllerError):
        controller.start_backend()
    assert controller.stop_backend(force=True) is False

    assert scm.start_calls == 0
    assert scm.stop_calls == []
