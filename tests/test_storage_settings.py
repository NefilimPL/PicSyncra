"""Tests for bootstrap storage mode and SQLite location settings."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from picsyncra import storage_settings


def test_sqlite_path_in_image_dir(tmp_path: Path) -> None:
    image_dir = tmp_path / "photos"
    image_dir.mkdir()

    with patch.object(storage_settings.settings, "AC", str(image_dir)):
        resolved = storage_settings.resolve_sqlite_path(
            {"database_location_mode": "image_dir"}
        )

    assert resolved == str(image_dir / "picsyncra.sqlite")


def test_sqlite_path_in_custom_location(tmp_path: Path) -> None:
    target = tmp_path / "custom" / "data.sqlite"

    resolved = storage_settings.resolve_sqlite_path(
        {"database_location_mode": "custom", "database_path": str(target)}
    )

    assert resolved == str(target.resolve())


def test_sqlite_path_in_exe_dir(tmp_path: Path) -> None:
    settings_file = tmp_path / "local_settings.json"

    with patch.object(
        storage_settings.settings, "BASE_DIR_SETTINGS_PATH", str(settings_file)
    ):
        resolved = storage_settings.resolve_sqlite_path(
            {"database_location_mode": "exe_dir"}
        )

    assert resolved == str(tmp_path / "picsyncra.sqlite")


def test_explicit_settings_path_helpers_do_not_use_process_global_settings(
    tmp_path: Path,
) -> None:
    settings_file = tmp_path / "application" / "local_settings.json"
    settings_file.parent.mkdir()
    settings_file.write_text(
        json.dumps({"database_location_mode": "exe_dir", "language": "pl"}),
        encoding="utf-8",
    )

    payload = storage_settings.load_bootstrap_settings_file(settings_file)
    resolved = storage_settings.resolve_sqlite_path_for_settings_file(
        settings_file, payload
    )

    assert payload["language"] == "pl"
    assert resolved == str(settings_file.parent / "picsyncra.sqlite")


def test_explicit_settings_path_uses_its_saved_image_directory(
    tmp_path: Path,
) -> None:
    """An offline tool must target the selected application's configured image directory."""

    settings_file = tmp_path / "application" / "local_settings.json"
    image_dir = tmp_path / "profile-images"
    settings_file.parent.mkdir()
    image_dir.mkdir()
    settings_file.write_text(
        json.dumps(
            {
                "database_location_mode": "image_dir",
                "base_dir_override": str(image_dir),
            }
        ),
        encoding="utf-8",
    )

    with patch.object(storage_settings.settings, "AC", str(tmp_path / "wrong-process-dir")):
        resolved = storage_settings.resolve_sqlite_path_for_settings_file(settings_file)

    assert resolved == str(image_dir / "picsyncra.sqlite")


def test_update_explicit_settings_file_preserves_unknown_values(tmp_path: Path) -> None:
    settings_file = tmp_path / "application" / "local_settings.json"
    settings_file.parent.mkdir()
    settings_file.write_text(
        json.dumps({"language": "pl", "custom_previous_key": [1, 2]}),
        encoding="utf-8",
    )

    saved = storage_settings.update_bootstrap_settings_file(
        settings_file,
        {"data_mode": "sqlite", "database_location_mode": "custom"},
    )

    assert saved["custom_previous_key"] == [1, 2]
    assert json.loads(settings_file.read_text(encoding="utf-8"))["data_mode"] == "sqlite"


def test_load_bootstrap_settings_defaults_to_legacy(tmp_path: Path) -> None:
    settings_file = tmp_path / "local_settings.json"

    with patch.object(
        storage_settings.settings, "BASE_DIR_SETTINGS_PATH", str(settings_file)
    ):
        payload = storage_settings.load_bootstrap_settings()

    assert payload["data_mode"] == "legacy"
    assert payload["database_location_mode"] == "image_dir"


def test_save_bootstrap_settings_merges_existing_values(tmp_path: Path) -> None:
    settings_file = tmp_path / "local_settings.json"
    settings_file.write_text(
        json.dumps({"language": "pl", "base_dir_override": "C:/Photos"}),
        encoding="utf-8",
    )

    with patch.object(
        storage_settings.settings, "BASE_DIR_SETTINGS_PATH", str(settings_file)
    ):
        payload = storage_settings.save_bootstrap_settings(
            {"data_mode": "sqlite", "database_location_mode": "exe_dir"}
        )

    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert payload["language"] == "pl"
    assert saved["base_dir_override"] == "C:/Photos"
    assert saved["data_mode"] == "sqlite"
    assert saved["database_location_mode"] == "exe_dir"


def test_save_bootstrap_settings_keeps_the_previous_file_if_publish_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """The activation callback cannot leave a partially written configuration."""

    settings_file = tmp_path / "local_settings.json"
    original = {"language": "pl", "data_mode": "legacy"}
    settings_file.write_text(json.dumps(original), encoding="utf-8")

    def fail_replace(*_args) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(storage_settings.os, "replace", fail_replace)

    with patch.object(
        storage_settings.settings, "BASE_DIR_SETTINGS_PATH", str(settings_file)
    ):
        with pytest.raises(OSError, match="disk full"):
            storage_settings.save_bootstrap_settings({"data_mode": "sqlite"})

    assert json.loads(settings_file.read_text(encoding="utf-8")) == original


def test_restore_bootstrap_settings_restores_the_exact_pre_activation_file(
    tmp_path: Path,
) -> None:
    """A failed profile switch must restore unknown bootstrap fields verbatim."""

    settings_file = tmp_path / "local_settings.json"
    original_bytes = b'{\n  "language": "pl",\n  "custom_previous_key": [1, 2]\n}\n'
    settings_file.write_bytes(original_bytes)

    with patch.object(
        storage_settings.settings, "BASE_DIR_SETTINGS_PATH", str(settings_file)
    ):
        snapshot = storage_settings.capture_bootstrap_settings()
        storage_settings.save_bootstrap_settings(
            {"data_mode": "sqlite", "database_path": "new.sqlite"}
        )
        storage_settings.restore_bootstrap_settings(snapshot)

    assert settings_file.read_bytes() == original_bytes


def test_restore_bootstrap_settings_removes_a_file_that_did_not_previously_exist(
    tmp_path: Path,
) -> None:
    settings_file = tmp_path / "local_settings.json"

    with patch.object(
        storage_settings.settings, "BASE_DIR_SETTINGS_PATH", str(settings_file)
    ):
        snapshot = storage_settings.capture_bootstrap_settings()
        storage_settings.save_bootstrap_settings({"data_mode": "sqlite"})
        storage_settings.restore_bootstrap_settings(snapshot)

    assert not settings_file.exists()
