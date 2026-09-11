"""Tests for importing one selected PicOrgFTP-SQL profile outside the web app."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from picsyncra import web_data
from picsyncra.offline_legacy_profile_migrator import (
    OfflineLegacyProfileMigrationError,
    resolve_offline_legacy_profile_paths,
    run_offline_legacy_profile_migration,
)
from picsyncra.sqlite_store import SqliteStore


def _create_source_profile(root: Path) -> Path:
    root.mkdir()
    (root / "config.json").write_text(
        json.dumps({"legacy_setting": {"enabled": True}}), encoding="utf-8"
    )
    (root / "web_users.json").write_text(
        json.dumps(
            [
                {
                    "username": "admin",
                    "role": "admin",
                    "enabled": True,
                    "password_hash": web_data._hash_password("old-password"),
                }
            ]
        ),
        encoding="utf-8",
    )
    return root


def _configure_target_application(tmp_path: Path) -> tuple[Path, Path]:
    app_root = tmp_path / "application"
    app_root.mkdir()
    settings_path = app_root / "local_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "data_mode": "legacy",
                "database_location_mode": "exe_dir",
                "database_path": "",
                "unrelated_setting": "must survive",
            }
        ),
        encoding="utf-8",
    )
    return app_root, settings_path


def test_resolve_paths_requires_explicit_profile_and_uses_target_configuration(
    tmp_path: Path,
) -> None:
    """The standalone tool must not scan sibling folders or inherit their target."""

    app_root, settings_path = _configure_target_application(tmp_path)
    source_root = _create_source_profile(tmp_path / "legacy-profile")
    _create_source_profile(tmp_path / "stale-profile")

    paths = resolve_offline_legacy_profile_paths(app_root, source_root)

    assert paths.app_root == app_root.resolve()
    assert paths.settings_path == settings_path.resolve()
    assert paths.source_root == source_root.resolve()
    assert paths.target == (app_root / "picsyncra.sqlite").resolve()
    assert paths.backup_root == (app_root / "BACKUP").resolve()


def test_legacy_profile_migration_imports_and_activates_picsyncra_sqlite(
    tmp_path: Path,
) -> None:
    """The selected LEGACY profile becomes the configured SQLite PicSyncra store."""

    app_root, settings_path = _configure_target_application(tmp_path)
    source_root = _create_source_profile(tmp_path / "legacy-profile")
    progress_events = []

    report = run_offline_legacy_profile_migration(
        app_root, source_root, progress=progress_events.append
    )

    assert report.source_root == source_root.resolve()
    assert report.target == (app_root / "picsyncra.sqlite").resolve()
    assert report.source_kind == "files"
    assert report.component_counts["config"] == 1
    assert report.component_counts["users"] == 1
    assert report.archive_dir is not None
    assert report.archive_dir.is_dir()
    assert not any(source_root.iterdir())
    settings_payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings_payload["data_mode"] == "sqlite"
    assert settings_payload["database_location_mode"] == "custom"
    assert settings_payload["database_path"] == str(report.target)
    assert settings_payload["unrelated_setting"] == "must survive"
    assert SqliteStore(str(report.target)).load_config()["legacy_setting"] == {"enabled": True}
    assert {event.stage for event in progress_events} >= {"process", "import", "activation", "cleanup"}


def test_resolve_paths_rejects_any_existing_target_even_when_empty(tmp_path: Path) -> None:
    """The offline adapter must be stricter than the reusable adoption primitive."""

    app_root, _settings_path = _configure_target_application(tmp_path)
    source_root = _create_source_profile(tmp_path / "legacy-profile")
    (app_root / "picsyncra.sqlite").touch()

    with pytest.raises(OfflineLegacyProfileMigrationError) as error:
        resolve_offline_legacy_profile_paths(app_root, source_root)

    assert error.value.code == "target_exists"


def test_target_created_after_preflight_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A race-created empty target must be preserved instead of imported over."""

    from picsyncra import offline_legacy_profile_migrator

    app_root, _settings_path = _configure_target_application(tmp_path)
    source_root = _create_source_profile(tmp_path / "legacy-profile")
    original_adopter = offline_legacy_profile_migrator.adopt_legacy_profile

    def create_target_before_adoption(**kwargs):
        Path(kwargs["database_path"]).touch()
        return original_adopter(**kwargs)

    monkeypatch.setattr(
        offline_legacy_profile_migrator,
        "adopt_legacy_profile",
        create_target_before_adoption,
    )

    with pytest.raises(OfflineLegacyProfileMigrationError) as error:
        run_offline_legacy_profile_migration(
            app_root, source_root, progress=lambda _event: None
        )

    assert error.value.code == "target_exists"
    assert (app_root / "picsyncra.sqlite").is_file()
    assert (app_root / "picsyncra.sqlite").stat().st_size == 0
    assert (source_root / "config.json").is_file()


def test_failed_settings_activation_removes_target_and_restores_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed final activation cannot leave migrated data as the active configuration."""

    from picsyncra import storage_settings

    app_root, settings_path = _configure_target_application(tmp_path)
    source_root = _create_source_profile(tmp_path / "legacy-profile")
    snapshot = settings_path.read_bytes()

    def fail_update(_path: Path, _updates: dict[str, object]) -> dict[str, object]:
        raise OSError("simulated settings write failure")

    monkeypatch.setattr(storage_settings, "update_bootstrap_settings_file", fail_update)

    with pytest.raises(OfflineLegacyProfileMigrationError) as error:
        run_offline_legacy_profile_migration(app_root, source_root, progress=lambda _event: None)

    assert error.value.code == "settings_update"
    assert not (app_root / "picsyncra.sqlite").exists()
    assert settings_path.read_bytes() == snapshot
