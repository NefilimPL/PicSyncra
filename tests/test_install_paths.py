"""Tests for trusted installed-runtime path discovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from picsyncra import common, config, install_paths, settings, storage_settings
from picsyncra.installation.contracts import InstallContext


def _registered_layout(tmp_path: Path, *, installation_id: str = "primary"):
    program_root = tmp_path / "program"
    state_root = tmp_path / "state" / installation_id
    database_path = state_root / "data" / "picsyncra.sqlite"
    executable = program_root / "versions" / "42" / "PicSyncra-WEB.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"test executable")
    state_root.mkdir(parents=True)
    (program_root / "active.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "installation_id": installation_id,
                "release_id": 42,
            }
        ),
        encoding="utf-8",
    )
    registration = {
        "installation_id": installation_id,
        "program_root": str(program_root),
        "state_root": str(state_root),
        "database_path": str(database_path),
    }
    return registration, executable, program_root, state_root, database_path


def test_registered_active_executable_resolves_install_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration, executable, program_root, state_root, database_path = (
        _registered_layout(tmp_path)
    )
    monkeypatch.setattr(
        install_paths, "_read_hklm_registrations", lambda: (registration,)
    )

    context = install_paths.resolve_install_context(executable)

    assert context is not None
    assert context.installation_id == "primary"
    assert context.program_root == program_root.resolve()
    assert context.state_root == state_root.resolve()
    assert context.config_root == (state_root / "config").resolve()
    assert context.database_path == database_path.resolve()
    assert install_paths.resolve_config_root(executable) == (
        state_root / "config"
    ).resolve()


def test_missing_registration_keeps_portable_or_development_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "portable" / "PicSyncra-WEB.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"portable")
    monkeypatch.setattr(install_paths, "_read_hklm_registrations", lambda: ())

    assert install_paths.resolve_install_context(executable) is None
    assert install_paths.resolve_config_root(executable) is None


def test_environment_variable_cannot_impersonate_an_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "portable" / "PicSyncra-WEB.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"portable")
    monkeypatch.setenv("PICSYNCRA_INSTALLATION_ID", "spoofed")
    monkeypatch.setenv("PICSYNCRA_PROGRAM_ROOT", str(executable.parent))
    monkeypatch.setenv("PICSYNCRA_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(install_paths, "_read_hklm_registrations", lambda: ())

    assert install_paths.resolve_install_context(executable) is None


def test_environment_variable_is_not_expanded_inside_registered_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration, executable, _, _, _ = _registered_layout(tmp_path)
    monkeypatch.setenv("PICSYNCRA_REGISTERED_ROOT", str(executable.parents[2]))
    registration["program_root"] = "%PICSYNCRA_REGISTERED_ROOT%"
    monkeypatch.setattr(
        install_paths, "_read_hklm_registrations", lambda: (registration,)
    )

    assert install_paths.resolve_install_context(executable) is None


def test_executable_outside_registered_active_bundle_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration, _, _, _, _ = _registered_layout(tmp_path)
    foreign_executable = tmp_path / "foreign" / "PicSyncra-WEB.exe"
    foreign_executable.parent.mkdir()
    foreign_executable.write_bytes(b"foreign")
    monkeypatch.setattr(
        install_paths, "_read_hklm_registrations", lambda: (registration,)
    )

    assert install_paths.resolve_install_context(foreign_executable) is None


def test_registration_with_missing_state_root_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration, executable, _, state_root, _ = _registered_layout(tmp_path)
    state_root.rmdir()
    monkeypatch.setattr(
        install_paths, "_read_hklm_registrations", lambda: (registration,)
    )

    assert install_paths.resolve_install_context(executable) is None


@pytest.mark.parametrize(
    "active_payload",
    [
        {"schema": 1, "installation_id": "other", "release_id": 42},
        {"schema": 2, "installation_id": "primary", "release_id": 42},
        {"schema": 1, "installation_id": "primary", "release_id": "../escape"},
        {"schema": 1, "installation_id": "primary", "release_id": 0},
    ],
)
def test_invalid_active_marker_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    active_payload: dict[str, object],
) -> None:
    registration, executable, program_root, _, _ = _registered_layout(tmp_path)
    (program_root / "active.json").write_text(
        json.dumps(active_payload), encoding="utf-8"
    )
    monkeypatch.setattr(
        install_paths, "_read_hklm_registrations", lambda: (registration,)
    )

    assert install_paths.resolve_install_context(executable) is None


@pytest.mark.parametrize("installation_id", ["", "../escape", "bad\\id", "bad/id"])
def test_invalid_registered_installation_id_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    installation_id: str,
) -> None:
    registration, executable, _, _, _ = _registered_layout(tmp_path)
    registration["installation_id"] = installation_id
    monkeypatch.setattr(
        install_paths, "_read_hklm_registrations", lambda: (registration,)
    )

    assert install_paths.resolve_install_context(executable) is None


def test_active_bundle_reparse_escape_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration, executable, program_root, _, _ = _registered_layout(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped_executable = outside / executable.name
    escaped_executable.write_bytes(b"escaped")
    executable.unlink()
    executable.parent.rmdir()
    try:
        executable.parent.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    monkeypatch.setattr(
        install_paths, "_read_hklm_registrations", lambda: (registration,)
    )

    assert (program_root / "versions" / "42").resolve() == outside.resolve()
    assert install_paths.resolve_install_context(executable) is None


def test_ambiguous_matching_registrations_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration, executable, _, _, _ = _registered_layout(tmp_path)
    conflicting = dict(registration)
    other_state = tmp_path / "other-state"
    other_state.mkdir()
    conflicting["state_root"] = str(other_state)
    monkeypatch.setattr(
        install_paths,
        "_read_hklm_registrations",
        lambda: (registration, conflicting),
    )

    assert install_paths.resolve_install_context(executable) is None


def _install_context(tmp_path: Path) -> InstallContext:
    state_root = (tmp_path / "state").resolve()
    return InstallContext(
        installation_id="primary",
        program_root=(tmp_path / "program").resolve(),
        state_root=state_root,
        config_root=state_root / "config",
        database_path=state_root / "data" / "registered.sqlite",
    )


def test_common_reads_bootstrap_secret_from_installed_config_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _install_context(tmp_path)
    monkeypatch.setattr(
        common, "resolve_config_root", lambda _executable: context.config_root
    )

    assert Path(common._resolve_settings_root_for_common()) == context.config_root


def test_settings_separates_installed_config_logs_and_photo_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _install_context(tmp_path)
    monkeypatch.setattr(settings, "_INSTALL_CONTEXT", context)
    for name in (
        "AC",
        "l",
        "LISTS_WORKBOOK_PATH",
        "AD",
        "AM",
        "BM",
        "AN",
        "BASE_DIR_OVERRIDE",
        "LOG_DIR",
    ):
        monkeypatch.setattr(settings, name, getattr(settings, name))

    assert Path(settings._resolve_settings_root()) == context.config_root
    assert Path(settings._default_base_dir()) == context.state_root / "data"
    assert Path(settings._default_log_dir()) == context.state_root / "logs"

    settings._apply_base_dir(str(tmp_path / "photos"))
    assert Path(settings.AD) == context.config_root / "config.json"
    assert Path(settings.AC) == tmp_path / "photos"


def test_config_json_uses_installed_config_root_instead_of_photo_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _install_context(tmp_path)
    monkeypatch.setattr(settings, "_INSTALL_CONTEXT", context)
    monkeypatch.setattr(settings, "AC", str(tmp_path / "photos"))

    assert Path(config._get_config_path()) == context.config_root / "config.json"


def test_registered_database_is_only_the_missing_bootstrap_file_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _install_context(tmp_path)
    settings_file = context.config_root / "local_settings.json"
    monkeypatch.setattr(settings, "_INSTALL_CONTEXT", context)
    monkeypatch.setattr(settings, "BASE_DIR_SETTINGS_PATH", str(settings_file))

    initial = storage_settings.load_bootstrap_settings()
    assert initial[storage_settings.DATABASE_LOCATION_MODE_KEY] == "custom"
    assert Path(initial[storage_settings.DATABASE_PATH_KEY]) == context.database_path

    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        json.dumps(
            {
                "database_location_mode": "image_dir",
                "database_path": str(tmp_path / "stale.sqlite"),
                "base_dir_override": str(tmp_path / "photos"),
            }
        ),
        encoding="utf-8",
    )
    saved = storage_settings.load_bootstrap_settings()
    assert saved[storage_settings.DATABASE_LOCATION_MODE_KEY] == "image_dir"
    assert storage_settings.resolve_sqlite_path(saved) == str(
        tmp_path / "photos" / storage_settings.DEFAULT_SQLITE_FILENAME
    )
