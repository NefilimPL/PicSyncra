from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from picsyncra import data_store, sqlite_backup, storage_settings


def _create_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL)")
            conn.execute("INSERT INTO schema_version VALUES (3, '2026-06-25T13:02:34.300Z')")
            conn.execute("CREATE TABLE app_config_values (path TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL)")
            conn.execute("INSERT INTO app_config_values VALUES ('database.query', '\"secret query\"', '2026-06-25T13:02:34.300Z')")


def test_backup_creates_sqlite_copy_and_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    backup_dir = tmp_path / "BACKUP"
    _create_db(db_path)

    result = sqlite_backup.create_backup(
        str(db_path),
        str(backup_dir),
        reason="manual",
        now=datetime(2026, 6, 25, 13, 2, 34, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    backup_path = Path(result["backup_path"])
    meta_path = backup_path.with_suffix(".json")
    assert backup_path.exists()
    assert meta_path.exists()
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["reason"] == "manual"
    assert metadata["schema_version"] == 3


def test_backup_retention_keeps_newest_manual_and_scheduled(tmp_path: Path) -> None:
    backup_dir = tmp_path / "BACKUP"
    backup_dir.mkdir()
    for index in range(4):
        db = backup_dir / f"picsyncra-20260625-130{index}00-manual.sqlite"
        db.write_text("x", encoding="utf-8")
        db.with_suffix(".json").write_text(
            json.dumps(
                {
                    "created_at": f"2026-06-25T13:0{index}:00.000Z",
                    "reason": "manual",
                }
            ),
            encoding="utf-8",
        )

    removed = sqlite_backup.enforce_retention(str(backup_dir), max_copies=2)

    assert removed["removed"] == 2
    remaining = sorted(path.name for path in backup_dir.glob("*.sqlite"))
    assert remaining == [
        "picsyncra-20260625-130200-manual.sqlite",
        "picsyncra-20260625-130300-manual.sqlite",
    ]


def test_backup_settings_roundtrip(tmp_path: Path) -> None:
    settings_path = tmp_path / "local_settings.json"
    with patch.object(storage_settings.settings, "BASE_DIR_SETTINGS_PATH", str(settings_path)):
        saved = storage_settings.save_backup_settings(
            {
                "enabled": True,
                "slots": ["mon:8", "mon:13"],
                "days": ["mon"],
                "hours": [8, 13],
                "max_copies": 4,
                "archive_dirs": [str(tmp_path / "archive"), str(tmp_path / "archive")],
            }
        )
        loaded = storage_settings.load_backup_settings()

    assert saved["enabled"] is True
    assert loaded["slots"] == ["mon:8", "mon:13"]
    assert loaded["days"] == ["mon"]
    assert loaded["hours"] == [8, 13]
    assert loaded["max_copies"] == 4
    assert loaded["archive_dirs"] == [str((tmp_path / "archive").resolve())]


def test_restore_rejects_backup_outside_trusted_directories(tmp_path: Path) -> None:
    active = tmp_path / "active.sqlite"
    backup_dir = tmp_path / "BACKUP"
    outside = tmp_path / "outside.sqlite"
    backup_dir.mkdir()
    _create_db(active)
    _create_db(outside)

    with pytest.raises(ValueError, match="dozwolonym katalog"):
        sqlite_backup.restore_backup(str(active), str(outside), str(backup_dir))


def test_restore_allows_backup_from_registered_archive_directory(tmp_path: Path) -> None:
    active = tmp_path / "active.sqlite"
    backup_dir = tmp_path / "BACKUP"
    archive_dir = tmp_path / "archive"
    backup = archive_dir / "moved.sqlite"
    backup_dir.mkdir()
    archive_dir.mkdir()
    _create_db(active)
    _create_db(backup)

    result = sqlite_backup.restore_backup(
        str(active),
        str(backup),
        str(backup_dir),
        allowed_backup_dirs=[str(backup_dir), str(archive_dir)],
    )

    assert result["restored_from"] == str(backup.resolve())


def test_list_backups_includes_registered_archive_directory(tmp_path: Path) -> None:
    primary_dir = tmp_path / "BACKUP"
    archive_dir = tmp_path / "archive"
    primary_dir.mkdir()
    archive_dir.mkdir()
    _create_db(primary_dir / "current.sqlite")
    _create_db(archive_dir / "moved.sqlite")

    backups = sqlite_backup.list_backups([str(primary_dir), str(archive_dir)])

    assert {Path(item["backup_path"]).name for item in backups} == {
        "current.sqlite",
        "moved.sqlite",
    }


def test_due_schedule_slots_respects_day_hour_and_last_run() -> None:
    now = datetime(2026, 6, 22, 8, 15, tzinfo=timezone.utc)  # Monday
    settings_payload = {
        "enabled": True,
        "days": ["mon", "tue"],
        "hours": [8, 13],
        "max_copies": 5,
        "last_run_slots": [],
    }

    due = sqlite_backup.due_schedule_slots(settings_payload, now)

    assert due == ["2026-06-22T08"]

    settings_payload["last_run_slots"] = ["2026-06-22T08"]
    assert sqlite_backup.due_schedule_slots(settings_payload, now) == []


def test_due_schedule_slots_respects_explicit_day_hour_slots() -> None:
    monday = datetime(2026, 6, 22, 8, 15, tzinfo=timezone.utc)
    tuesday = datetime(2026, 6, 23, 8, 15, tzinfo=timezone.utc)
    settings_payload = {
        "enabled": True,
        "slots": ["mon:8", "tue:13"],
        "max_copies": 5,
        "last_run_slots": [],
    }

    assert sqlite_backup.due_schedule_slots(settings_payload, monday) == ["2026-06-22T08"]
    assert sqlite_backup.due_schedule_slots(settings_payload, tuesday) == []


@pytest.mark.parametrize(
    ("now", "configured_slot", "expected_run_slot"),
    [
        # Europe/Warsaw is UTC+2 in September (CEST).
        (datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc), "thu:17", "2026-09-10T15"),
        # Europe/Warsaw is UTC+1 in January (CET).
        (datetime(2026, 1, 14, 16, 0, tzinfo=timezone.utc), "wed:17", "2026-01-14T16"),
    ],
)
def test_due_schedule_slots_matches_the_configured_time_zone(
    now: datetime,
    configured_slot: str,
    expected_run_slot: str,
) -> None:
    """Catches backup slots being compared with UTC instead of the configured zone."""

    due = sqlite_backup.due_schedule_slots(
        {
            "enabled": True,
            "slots": [configured_slot],
            "last_run_slots": [],
        },
        now,
        time_zone_name="Europe/Warsaw",
    )

    assert due == [expected_run_slot]


def test_mark_schedule_slots_run_keeps_recent_slots() -> None:
    updated = sqlite_backup.mark_schedule_slots_run(
        {"last_run_slots": ["2026-06-21T08"]},
        ["2026-06-22T08"],
    )

    assert updated["last_run_slots"] == ["2026-06-21T08", "2026-06-22T08"]


def test_restore_backup_creates_pre_restore_backup_and_replaces_database(tmp_path: Path) -> None:
    active = tmp_path / "active.sqlite"
    backup = tmp_path / "BACKUP" / "picsyncra-20260625-130234-manual.sqlite"
    backup.parent.mkdir()
    _create_db(active)
    _create_db(backup)
    with sqlite3.connect(backup) as conn:
        conn.execute("UPDATE app_config_values SET value_json = '\"restored\"' WHERE path = 'database.query'")

    result = sqlite_backup.restore_backup(str(active), str(backup), str(backup.parent))

    assert result["ok"] is True
    assert Path(result["pre_restore_backup"]["backup_path"]).exists()
    with sqlite3.connect(active) as conn:
        value = conn.execute("SELECT value_json FROM app_config_values WHERE path = 'database.query'").fetchone()[0]
    assert value == '"restored"'


def test_restore_backup_invalidates_the_replaced_store(tmp_path: Path) -> None:
    active = tmp_path / "active.sqlite"
    backup = tmp_path / "BACKUP" / "restore.sqlite"
    backup.parent.mkdir()
    _create_db(active)
    _create_db(backup)
    stale_store = data_store.get_sqlite_store(str(active))

    sqlite_backup.restore_backup(str(active), str(backup), str(backup.parent))

    assert data_store.get_sqlite_store(str(active)) is not stale_store


def test_failed_restore_preserves_the_active_store(tmp_path: Path) -> None:
    active = tmp_path / "active.sqlite"
    backup_dir = tmp_path / "BACKUP"
    backup_dir.mkdir()
    _create_db(active)
    active_store = data_store.get_sqlite_store(str(active))

    with pytest.raises(FileNotFoundError):
        sqlite_backup.restore_backup(
            str(active), str(backup_dir / "missing.sqlite"), str(backup_dir)
        )

    assert data_store.get_sqlite_store(str(active)) is active_store


def test_diff_databases_masks_secret_values(tmp_path: Path) -> None:
    left = tmp_path / "left.sqlite"
    right = tmp_path / "right.sqlite"
    _create_db(left)
    _create_db(right)
    with sqlite3.connect(right) as conn:
        conn.execute("INSERT INTO app_config_values VALUES ('ftp.password', '\"secret\"', '2026-06-25T13:02:34.300Z')")

    diff = sqlite_backup.diff_databases(str(left), str(right), [str(tmp_path)])

    assert diff["tables"]["app_config_values"]["added"] >= 1
    assert "secret" not in json.dumps(diff)
    assert "ftp.password" in json.dumps(diff)
    assert "present" in json.dumps(diff)


def test_diff_databases_closes_both_database_files_before_returning(tmp_path: Path) -> None:
    """Database comparison must not leave Windows file handles open."""

    active = tmp_path / "active.sqlite"
    backup = tmp_path / "backup.sqlite"
    _create_db(active)
    _create_db(backup)

    sqlite_backup.diff_databases(str(active), str(backup), [str(tmp_path)])

    active.unlink()
    backup.unlink()
    assert not active.exists()
    assert not backup.exists()


def test_diff_databases_rejects_backup_outside_trusted_directories(tmp_path: Path) -> None:
    active = tmp_path / "active.sqlite"
    outside = tmp_path.parent / "outside.sqlite"
    _create_db(active)
    _create_db(outside)

    with pytest.raises(ValueError, match="dozwolonym katalogu"):
        sqlite_backup.diff_databases(str(active), str(outside), [str(tmp_path)])
