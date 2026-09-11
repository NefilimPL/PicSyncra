"""Thread-boundary tests for the standalone migrator GUI."""

from __future__ import annotations

from pathlib import Path

import pytest

from picsyncra.offline_legacy_sqlite_migrator import (
    MigrationPaths,
    MigrationProgress,
    OfflineMigrationReport,
)
from picsyncra.offline_legacy_profile_migrator import (
    OfflineLegacyProfileMigrationError,
    OfflineLegacyProfilePaths,
    OfflineLegacyProfileReport,
)
from picsyncra.offline_migrator_gui import (
    OfflineMigratorController,
    LEGACY_PROFILE_MODE,
    SQLITE_REBRAND_MODE,
    legacy_profile_source_path,
    legacy_profile_confirmation_message,
    migration_confirmation_message,
)


class RecordingScheduler:
    def __init__(self) -> None:
        self.callbacks = []

    def after(self, _delay: int, callback) -> None:
        self.callbacks.append(callback)


def test_controller_schedules_progress_without_updating_tk_from_worker_thread() -> None:
    scheduler = RecordingScheduler()
    events = []
    controller = OfflineMigratorController(scheduler.after, events.append, lambda _text: None)

    controller.receive_progress(MigrationProgress("copy", 10, 100, "Kopia SQLite"))

    assert len(scheduler.callbacks) == 1
    assert events == []
    scheduler.callbacks[0]()
    assert events[0].message == "Kopia SQLite"


def test_confirmation_explains_legacy_sqlite_archiving() -> None:
    paths = MigrationPaths(
        app_root=Path("application"),
        settings_path=Path("application/local_settings.json"),
        source=Path("legacy/picorgftp_sql.sqlite"),
        target=Path("legacy/picsyncra.sqlite"),
    )

    message = migration_confirmation_message(paths)

    assert str(paths.source) in message
    assert str(paths.target) in message
    assert "zostaną przeniesione" in message
    assert str(paths.app_root / "BACKUP" / "legacy-import") in message


def test_legacy_profile_mode_confirmation_names_selected_source_target_and_archive() -> None:
    paths = OfflineLegacyProfilePaths(
        app_root=Path("application"),
        settings_path=Path("application/local_settings.json"),
        source_root=Path("old-configuration"),
        target=Path("application/picsyncra.sqlite"),
        backup_root=Path("application/BACKUP"),
        source_names=("config.json", "web_users.json"),
    )

    message = legacy_profile_confirmation_message(paths)

    assert SQLITE_REBRAND_MODE != LEGACY_PROFILE_MODE
    assert str(paths.source_root) in message
    assert str(paths.target) in message
    assert str(paths.backup_root / "legacy-import") in message


def test_legacy_profile_mode_requires_a_source_folder_choice() -> None:
    """An empty GUI field must not silently become the migrator's current directory."""

    with pytest.raises(OfflineLegacyProfileMigrationError) as error:
        legacy_profile_source_path("   ")

    assert error.value.code == "source_missing"


def test_controller_success_report_includes_archive_without_account_hashes() -> None:
    scheduler = RecordingScheduler()
    status = []
    controller = OfflineMigratorController(scheduler.after, lambda _event: None, status.append)
    archive_dir = Path("BACKUP/legacy-import/20260902-run")

    controller.receive_success(
        OfflineMigrationReport(
            Path("source.sqlite"),
            Path("picsyncra.sqlite"),
            {"web_users": 1},
            2,
            1,
            archive_dir=archive_dir,
            archive_warning="Plik picorgftp_sql.sqlite-wal oczekuje na przeniesienie.",
        )
    )

    scheduler.callbacks[0]()
    assert "picsyncra.sqlite" in status[0]
    assert str(archive_dir) in status[0]
    assert "oczekuje na przeniesienie" in status[0]
    assert "hash" not in status[0].lower()


def test_controller_success_for_profile_mode_reports_component_counts_without_sensitive_data() -> None:
    scheduler = RecordingScheduler()
    status = []
    controller = OfflineMigratorController(scheduler.after, lambda _event: None, status.append)

    controller.receive_success(
        OfflineLegacyProfileReport(
            source_root=Path("old-profile"),
            target=Path("application/picsyncra.sqlite"),
            source_kind="sqlite+files",
            component_counts={"config": 1, "users": 1},
            archive_dir=Path("application/BACKUP/legacy-import/run"),
            archive_warning=None,
        )
    )

    scheduler.callbacks[0]()
    assert "picsyncra.sqlite" in status[0]
    assert "config: 1" in status[0]
    assert "users: 1" in status[0]
    assert "hash" not in status[0].lower()
