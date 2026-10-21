"""Registry operations for an installed runtime use only the fixed resolver schema."""

from __future__ import annotations

from pathlib import Path
import json

from picsyncra.installation.setup_cli import (
    InstallationRegistration,
    register_installation,
    unregister_installation,
)


class FakeRegistry:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_value(self, key_path: str, name: str, value: str) -> None:
        self.values[(key_path, name)] = value

    def delete_key(self, key_path: str) -> None:
        self.deleted_key = key_path


def test_register_writes_exactly_the_machine_registration_used_by_the_resolver(
    tmp_path: Path,
) -> None:
    """Catches writing installation state to arbitrary registry paths or values."""

    program_root = tmp_path / "program"
    state_root = tmp_path / "state"
    program_root.mkdir()
    state_root.mkdir()
    registration = InstallationRegistration(
        installation_id="primary-installation",
        program_root=program_root,
        state_root=state_root,
        database_path=state_root / "data" / "picsyncra.sqlite",
    )
    registry = FakeRegistry()

    register_installation(registration, registry=registry)

    assert registry.values == {
        (r"SOFTWARE\PicSyncra\Installations\primary-installation", "InstallationId"): "primary-installation",
        (r"SOFTWARE\PicSyncra\Installations\primary-installation", "ProgramRoot"): str(program_root.resolve()),
        (r"SOFTWARE\PicSyncra\Installations\primary-installation", "StateRoot"): str(state_root.resolve()),
        (r"SOFTWARE\PicSyncra\Installations\primary-installation", "DatabasePath"): str(
            (state_root / "data" / "picsyncra.sqlite").resolve()
        ),
    }


def test_register_cli_loads_the_resolver_registration_from_a_request_file(
    tmp_path: Path,
) -> None:
    """Catches register accepting machine paths directly in its process arguments."""

    program_root = tmp_path / "program"
    state_root = tmp_path / "state"
    program_root.mkdir()
    state_root.mkdir()
    request = tmp_path / "register-request.json"
    request.write_text(
        json.dumps(
            {
                "installation_id": "primary-installation",
                "program_root": str(program_root),
                "state_root": str(state_root),
                "database_path": str(state_root / "data" / "picsyncra.sqlite"),
            }
        ),
        encoding="utf-8",
    )
    registry = FakeRegistry()

    from picsyncra.installation.setup_cli import main

    assert main(["register", "--request", str(request)], registry=registry) == 0
    assert registry.values[(r"SOFTWARE\PicSyncra\Installations\primary-installation", "InstallationId")] == "primary-installation"


def test_unregister_removes_only_the_selected_installation_key() -> None:
    """Catches an uninstaller deleting registrations belonging to another install."""

    registry = FakeRegistry()

    unregister_installation("primary-installation", registry=registry)

    assert registry.deleted_key == r"SOFTWARE\PicSyncra\Installations\primary-installation"


def test_unregister_cli_reads_only_the_installation_id_from_its_request_file(
    tmp_path: Path,
) -> None:
    """Catches the uninstaller accepting a registry target in command-line text."""

    request = tmp_path / "unregister-request.json"
    request.write_text(json.dumps({"installation_id": "primary-installation"}), encoding="utf-8")
    registry = FakeRegistry()

    from picsyncra.installation.setup_cli import main

    assert main(["unregister", "--request", str(request)], registry=registry) == 0
    assert registry.deleted_key == r"SOFTWARE\PicSyncra\Installations\primary-installation"


def test_verify_access_cli_checks_a_directory_without_echoing_its_path(
    tmp_path: Path, capsys
) -> None:
    """Catches setup accepting a resource path directly in its command line."""

    resource = tmp_path / "network-like-resource"
    resource.mkdir()
    request = tmp_path / "verify-access-request.json"
    request.write_text(json.dumps({"path": str(resource)}), encoding="utf-8")

    from picsyncra.installation.setup_cli import main

    assert main(["verify-access", "--request", str(request)]) == 0

    response_text = capsys.readouterr().out
    assert json.loads(response_text) == {
        "ok": True,
        "access": {"exists": True, "is_directory": True, "is_unc": False},
    }
    assert str(resource) not in response_text
