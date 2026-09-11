"""Compatibility and runtime checks for the profile-based legacy importer."""

from __future__ import annotations

from pathlib import Path

import pytest

from picsyncra import bootstrap
import picsyncra.legacy_migration as legacy_migration
from picsyncra.sqlite_store import SqliteStore


def test_automatic_legacy_migration_is_retired(tmp_path: Path) -> None:
    """Startup compatibility code must not copy an old database by itself."""

    source = tmp_path / "picorgftp_sql.sqlite"
    SqliteStore(str(source)).save_config({"migration_marker": "manual-only"})

    result = legacy_migration.migrate_legacy_data(tmp_path, tmp_path)

    assert result.migrated is False
    assert result.skipped is True
    assert source.exists()
    assert not (tmp_path / "picsyncra.sqlite").exists()


def test_runtime_does_not_migrate_legacy_data_before_the_user_chooses_the_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opening the application leaves profile adoption to the settings action."""

    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "picorgftp_sql.sqlite"
    SqliteStore(str(source)).save_config({"migration_marker": "manual-only"})

    monkeypatch.setattr(bootstrap.settings, "initialize_runtime", lambda **_kwargs: None)
    monkeypatch.setattr(
        bootstrap.settings, "BASE_DIR_SETTINGS_PATH", str(tmp_path / "local_settings.json")
    )
    monkeypatch.setattr(bootstrap.settings, "AC", str(data_root))
    monkeypatch.setattr(bootstrap.config, "initialize_config", lambda **_kwargs: {})

    result = bootstrap.initialize_application_runtime(interactive=False)

    assert source.exists()
    assert not (data_root / "picsyncra.sqlite").exists()
    assert "migration" not in result


def test_runtime_cleans_a_completed_marker_next_to_a_custom_active_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed handover leaves no root-level marker next to the old file."""

    data_root = tmp_path / "data"
    custom_root = tmp_path / "custom-sqlite"
    data_root.mkdir()
    custom_root.mkdir()
    active_database = custom_root / "picsyncra-import-active.sqlite"
    SqliteStore(str(active_database)).initialize()
    legacy_database = custom_root / "picorgftp_sql.sqlite"
    marker = legacy_database.with_name(f".{legacy_database.name}.picsyncra-adoption")
    marker.write_text("retired", encoding="ascii")

    monkeypatch.setattr(bootstrap.settings, "initialize_runtime", lambda **_kwargs: None)
    monkeypatch.setattr(
        bootstrap.settings, "BASE_DIR_SETTINGS_PATH", str(tmp_path / "local_settings.json")
    )
    monkeypatch.setattr(bootstrap.settings, "AC", str(data_root))
    monkeypatch.setattr(bootstrap, "resolve_sqlite_path", lambda: str(active_database))
    monkeypatch.setattr(bootstrap.config, "initialize_config", lambda **_kwargs: {})

    bootstrap.initialize_application_runtime(interactive=False)

    assert not marker.exists()
