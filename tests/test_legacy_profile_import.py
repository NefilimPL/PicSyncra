"""Real-data tests for a staged import of one legacy profile."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from picsyncra import web_data
from picsyncra.excel_utils import ENTRY_RECORDS_KEY
from picsyncra.legacy_profile import load_legacy_profile
from picsyncra.sqlite_store import SqliteStore


def test_staged_import_preserves_admin_from_json_when_old_sqlite_has_no_users(
    tmp_path: Path,
) -> None:
    """Dropping JSON users must fail this: the result would create default admin instead."""

    from picsyncra.legacy_profile_import import stage_legacy_profile_import

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    legacy_database = source_root / "picorgftp_sql.sqlite"
    SqliteStore(str(legacy_database)).save_config({"database_setting": "from-sqlite"})
    old_password = "old-admin-password"
    old_password_hash = web_data._hash_password(old_password)
    (source_root / "web_users.json").write_text(
        json.dumps(
            [
                {
                    "username": "admin",
                    "role": "admin",
                    "enabled": True,
                    "password_hash": old_password_hash,
                }
            ]
        ),
        encoding="utf-8",
    )
    (source_root / "config.json").write_text(
        json.dumps({"json_setting": {"enabled": True}}), encoding="utf-8"
    )
    (source_root / "web_history.json").write_text(
        json.dumps([{"id": "legacy-history", "action": "save"}]), encoding="utf-8"
    )
    (source_root / "file_index.json").write_text(
        json.dumps({"version": 1, "names": ["OLD"]}), encoding="utf-8"
    )
    profile = load_legacy_profile(source_root)
    assert profile is not None
    staged_database = tmp_path / "staging" / "picsyncra.sqlite"

    report = stage_legacy_profile_import(profile, staged_database)

    users = SqliteStore(str(staged_database)).load_users()
    assert report.component_counts == {
        "config": 1,
        "lists": 0,
        "entries": 0,
        "users": 1,
        "history": 1,
        "file_index": 1,
        "bootstrap_settings": 0,
    }
    assert users == [
        {
            "username": "admin",
            "role": "admin",
            "enabled": True,
            "password_hash": old_password_hash,
        }
    ]
    assert web_data.verify_password(old_password, users[0]["password_hash"])
    assert SqliteStore(str(staged_database)).load_config()["json_setting"] == {"enabled": True}
    assert SqliteStore(str(staged_database)).load_history()[0]["id"] == "legacy-history"
    assert SqliteStore(str(staged_database)).load_file_index_cache()["names"] == ["OLD"]


def test_staged_import_rejects_invalid_accounts_before_creating_a_result(tmp_path: Path) -> None:
    """Malformed account data must not be replaced silently with a default admin."""

    from picsyncra.legacy_profile_import import (
        LegacyProfileValidationError,
        stage_legacy_profile_import,
    )

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    (source_root / "web_users.json").write_text("{}", encoding="utf-8")
    profile = load_legacy_profile(source_root)
    assert profile is not None
    staged_database = tmp_path / "staging" / "picsyncra.sqlite"

    with pytest.raises(LegacyProfileValidationError, match="web_users.json"):
        stage_legacy_profile_import(profile, staged_database)

    assert not staged_database.exists()


@pytest.mark.parametrize(
    "users",
    [
        [],
        [
            {
                "username": "admin",
                "role": "owner",
                "enabled": True,
                "password_hash": web_data._hash_password("password"),
            }
        ],
        [
            {
                "username": "admin",
                "role": "admin",
                "enabled": "yes",
                "password_hash": web_data._hash_password("password"),
            }
        ],
        [
            {
                "username": "admin",
                "role": "admin",
                "enabled": True,
                "password_hash": "not-a-supported-password-hash",
            }
        ],
    ],
)
def test_staged_import_rejects_invalid_web_accounts_without_creating_default_admin(
    tmp_path: Path, users: list[dict[str, object]]
) -> None:
    """The importer must fail instead of allowing load_user_records() to invent admin/admin."""

    from picsyncra.legacy_profile_import import (
        LegacyProfileValidationError,
        stage_legacy_profile_import,
    )

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    (source_root / "web_users.json").write_text(json.dumps(users), encoding="utf-8")
    profile = load_legacy_profile(source_root)
    assert profile is not None
    staged_database = tmp_path / "staging" / "picsyncra.sqlite"

    with pytest.raises(LegacyProfileValidationError, match="kont"):
        stage_legacy_profile_import(profile, staged_database)

    assert not staged_database.exists()


def test_staged_import_rejects_sqlite_profile_without_a_usable_admin_account(
    tmp_path: Path,
) -> None:
    """An old SQLite profile with empty users is corrupt for web migration, not a new-admin request."""

    from picsyncra.legacy_profile_import import (
        LegacyProfileValidationError,
        stage_legacy_profile_import,
    )

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    SqliteStore(str(source_root / "picorgftp_sql.sqlite")).save_config({"legacy": True})
    profile = load_legacy_profile(source_root)
    assert profile is not None
    staged_database = tmp_path / "staging" / "picsyncra.sqlite"

    with pytest.raises(LegacyProfileValidationError, match="administratora"):
        stage_legacy_profile_import(profile, staged_database)

    assert not staged_database.exists()


def test_staged_import_preserves_valid_sqlite_only_admin_account(tmp_path: Path) -> None:
    """Accounts stored only in the old SQLite receive the same validation as JSON accounts."""

    from picsyncra.legacy_profile_import import stage_legacy_profile_import

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    password = "sqlite-only-admin-password"
    password_hash = web_data._hash_password(password)
    legacy_store = SqliteStore(str(source_root / "picorgftp_sql.sqlite"))
    legacy_store.save_config({"legacy": True})
    legacy_store.save_users(
        [
            {
                "username": "admin",
                "role": "admin",
                "enabled": True,
                "password_hash": password_hash,
            }
        ]
    )
    profile = load_legacy_profile(source_root)
    assert profile is not None
    staged_database = tmp_path / "staging" / "picsyncra.sqlite"

    report = stage_legacy_profile_import(profile, staged_database)

    users = SqliteStore(str(staged_database)).load_users()
    assert report.component_counts["users"] == 1
    assert users[0]["role"] == "admin"
    assert web_data.verify_password(password, users[0]["password_hash"])


def test_staged_import_rebuilds_pre_rebrand_sqlite_fts_triggers(tmp_path: Path) -> None:
    """A database carrying the old SQLite function names remains importable."""

    from picsyncra.legacy_profile_import import stage_legacy_profile_import

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    legacy_database = source_root / "picorgftp_sql.sqlite"
    legacy_store = SqliteStore(str(legacy_database))
    legacy_store.initialize()
    legacy_store.save_lists(
        {
            ENTRY_RECORDS_KEY: [
                {
                    "PRODUCT_ID": "P-LEGACY-1",
                    "EAN": "5901234567890",
                    "NAZWA": "LEGACY PRODUCT",
                }
            ]
        }
    )
    with sqlite3.connect(legacy_database) as connection:
        connection.executescript(
            """
            DROP TRIGGER trg_product_entries_short_fts_insert;
            DROP TRIGGER trg_product_entries_short_fts_delete;
            DROP TRIGGER trg_product_entries_short_fts_update;

            CREATE TRIGGER trg_product_entries_short_fts_insert
            AFTER INSERT ON product_entries
            BEGIN
                INSERT INTO product_entries_short_fts(rowid, grams)
                VALUES (new.rowid, picorg_product_short_grams(new.search_text_key));
            END;

            CREATE TRIGGER trg_product_entries_short_fts_delete
            AFTER DELETE ON product_entries
            BEGIN
                INSERT INTO product_entries_short_fts(product_entries_short_fts, rowid, grams)
                VALUES ('delete', old.rowid, picorg_product_short_grams(old.search_text_key));
            END;

            CREATE TRIGGER trg_product_entries_short_fts_update
            AFTER UPDATE OF search_text_key ON product_entries
            BEGIN
                INSERT INTO product_entries_short_fts(product_entries_short_fts, rowid, grams)
                VALUES ('delete', old.rowid, picorg_product_short_grams(old.search_text_key));
                INSERT INTO product_entries_short_fts(rowid, grams)
                VALUES (new.rowid, picorg_product_short_grams(new.search_text_key));
            END;
            """
        )
        connection.execute(
            "PRAGMA user_version = 15"
        )
    password = "old-trigger-admin-password"
    (source_root / "web_users.json").write_text(
        json.dumps(
            [
                {
                    "username": "admin",
                    "role": "admin",
                    "enabled": True,
                    "password_hash": web_data._hash_password(password),
                }
            ]
        ),
        encoding="utf-8",
    )
    (source_root / "config.json").write_text(
        json.dumps({"trigger_migration": True}), encoding="utf-8"
    )
    profile = load_legacy_profile(source_root)
    assert profile is not None

    stage_legacy_profile_import(profile, tmp_path / "staging" / "picsyncra.sqlite")

    staged_store = SqliteStore(str(tmp_path / "staging" / "picsyncra.sqlite"))
    assert staged_store.load_config()["trigger_migration"] is True
    assert staged_store.load_lists()[ENTRY_RECORDS_KEY][0]["PRODUCT_ID"] == "P-LEGACY-1"
    assert web_data.verify_password(password, staged_store.load_users()[0]["password_hash"])


def test_staged_import_rejects_history_records_without_stable_ids(tmp_path: Path) -> None:
    """ID-less history can be pruned or regenerated, so it cannot be verified after staging."""

    from picsyncra.legacy_profile_import import (
        LegacyProfileValidationError,
        stage_legacy_profile_import,
    )

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    (source_root / "web_history.json").write_text(
        json.dumps([{"action": "save", "ean": "5901234567890"}]),
        encoding="utf-8",
    )
    profile = load_legacy_profile(source_root)
    assert profile is not None

    with pytest.raises(LegacyProfileValidationError, match="web_history.json"):
        stage_legacy_profile_import(profile, tmp_path / "staging" / "picsyncra.sqlite")


def test_staged_import_rejects_a_result_without_the_selected_excel_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reporting list counts is insufficient: their values must exist in the staged database."""

    from openpyxl import Workbook

    from picsyncra import legacy_profile_import

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "NAZWY"
    worksheet.append(["OLD LIST VALUE"])
    workbook.save(source_root / "lists.xlsx")
    workbook.close()
    profile = load_legacy_profile(source_root)
    assert profile is not None
    staged_database = tmp_path / "staging" / "picsyncra.sqlite"
    monkeypatch.setattr(
        legacy_profile_import,
        "import_legacy_to_sqlite",
        lambda *_args, **_kwargs: {"lists": 1, "entries": 0},
    )

    with pytest.raises(legacy_profile_import.LegacyProfileValidationError, match="list"):
        legacy_profile_import.stage_legacy_profile_import(profile, staged_database)

    assert not staged_database.exists()


def test_staged_import_copies_selected_excel_list_values(tmp_path: Path) -> None:
    """The profile importer retains lists from the same old directory as the accounts."""

    from openpyxl import Workbook

    from picsyncra.legacy_profile_import import stage_legacy_profile_import
    from picsyncra.sqlite_store import LIST_SHEETS

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = LIST_SHEETS[0]
    worksheet.append(["OLD LIST VALUE"])
    workbook.save(source_root / "lists.xlsx")
    workbook.close()
    profile = load_legacy_profile(source_root)
    assert profile is not None
    staged_database = tmp_path / "staging" / "picsyncra.sqlite"

    report = stage_legacy_profile_import(profile, staged_database)

    assert report.component_counts["lists"] == 1
    assert SqliteStore(str(staged_database)).load_lists()[LIST_SHEETS[0]] == ["OLD LIST VALUE"]


def test_profile_transaction_activates_validated_database_then_archives_all_sources(
    tmp_path: Path,
) -> None:
    """Removing any phase must fail this: no account may be lost before activation."""

    from picsyncra.legacy_migration import adopt_legacy_profile

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    SqliteStore(str(source_root / "picorgftp_sql.sqlite")).save_config({"old_db": True})
    old_password = "transaction-admin-password"
    old_password_hash = web_data._hash_password(old_password)
    (source_root / "web_users.json").write_text(
        json.dumps(
            [
                {
                    "username": "admin",
                    "role": "admin",
                    "enabled": True,
                    "password_hash": old_password_hash,
                }
            ]
        ),
        encoding="utf-8",
    )
    (source_root / "config.json").write_text(json.dumps({"old_json": True}), encoding="utf-8")
    (source_root / "local_settings.json").write_text(
        json.dumps(
            {
                "base_dir_override": "C:/old-profile",
                "database_path": "C:/old-profile/picorgftp_sql.sqlite",
                "language": "pl",
                "app_secret": "legacy-secret",
                "custom_bootstrap_setting": {"enabled": True},
            }
        ),
        encoding="utf-8",
    )
    activated: list[tuple[Path, dict[str, object]]] = []
    target = tmp_path / "current" / "picsyncra.sqlite"

    result = adopt_legacy_profile(
        source_root=source_root,
        database_path=target,
        backup_root=tmp_path / "BACKUP",
        finalize=lambda database, bootstrap: activated.append((database, bootstrap)),
    )

    assert result.migrated is True
    assert result.copied_paths == (target,)
    assert activated == [
        (
            target,
            {
                "language": "pl",
                "app_secret": "legacy-secret",
            },
        )
    ]
    imported_user = SqliteStore(str(target)).load_users()[0]
    assert imported_user["role"] == "admin"
    assert web_data.verify_password(old_password, imported_user["password_hash"])
    assert result.report["component_counts"]["users"] == 1
    assert not any(
        (source_root / name).exists()
        for name in (
            "picorgftp_sql.sqlite",
            "config.json",
            "web_users.json",
            "local_settings.json",
            ".picorgftp_sql.sqlite.picsyncra-adoption",
        )
    )
    assert all(
        (result.archive_dir / name).is_file()
        for name in (
            "picorgftp_sql.sqlite",
            "config.json",
            "web_users.json",
            "local_settings.json",
            "import-report.json",
        )
    )


def test_profile_publish_moves_staging_database_before_the_finalizer_opens_it(
    tmp_path: Path,
) -> None:
    """Windows cleanup must not retain a staging hard link after activation."""

    from picsyncra import legacy_migration

    staging = tmp_path / ".picsyncra-profile" / "picsyncra-import.sqlite"
    destination = tmp_path / "current" / "picsyncra-import.sqlite"
    SqliteStore(str(staging)).save_config({"legacy": True})
    destination.parent.mkdir()

    legacy_migration._publish_profile_staging(staging, destination)

    with sqlite3.connect(destination) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not staging.exists()


def test_profile_transaction_keeps_sources_and_target_when_validation_fails(
    tmp_path: Path,
) -> None:
    """Publishing before account validation would overwrite the current database here."""

    from picsyncra.legacy_migration import adopt_legacy_profile

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    (source_root / "web_users.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "current" / "picsyncra.sqlite"
    SqliteStore(str(target)).save_config({"current": True})
    finalized: list[Path] = []

    result = adopt_legacy_profile(
        source_root=source_root,
        database_path=target,
        backup_root=tmp_path / "BACKUP",
        finalize=lambda database, _bootstrap: finalized.append(database),
        replace_existing_target=True,
    )

    assert result.migrated is False
    assert result.error_code == "adoption_failed"
    assert finalized == []
    assert (source_root / "web_users.json").is_file()
    assert SqliteStore(str(target)).load_config() == {"current": True}


def test_legacy_adoption_compatibility_api_delegates_to_one_profile_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old public API must not reintroduce independent root discovery."""

    from picsyncra import legacy_migration

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    (source_root / "config.json").write_text(json.dumps({"legacy": True}), encoding="utf-8")
    adopted = legacy_migration.MigrationResult(migrated=True, skipped=False)
    captured: dict[str, object] = {}

    def adopt_one_profile(**kwargs):
        captured.update(kwargs)
        return adopted

    monkeypatch.setattr(legacy_migration, "adopt_legacy_profile", adopt_one_profile)

    result = legacy_migration.adopt_legacy_data(
        application_root=tmp_path / "application",
        data_root=source_root,
        database_path=tmp_path / "current" / "picsyncra.sqlite",
        backup_root=tmp_path / "BACKUP",
    )

    assert result is adopted
    assert captured["source_root"] == source_root
    assert captured["database_path"] == tmp_path / "current" / "picsyncra.sqlite"
    assert captured["backup_root"] == tmp_path / "BACKUP"


def test_profile_transaction_rolls_back_activation_when_retiring_the_old_source_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finalizer cannot leave bootstrap settings pointing at a deleted staged database."""

    from picsyncra import legacy_migration

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    password_hash = web_data._hash_password("old-password")
    source_store = SqliteStore(str(source_root / "picorgftp_sql.sqlite"))
    source_store.save_config({"legacy": True})
    source_store.save_users(
        [
            {
                "username": "admin",
                "role": "admin",
                "enabled": True,
                "password_hash": password_hash,
            }
        ]
    )
    target = tmp_path / "current" / "picsyncra.sqlite"
    SqliteStore(str(target)).save_config({"current": True})
    active_database = {"path": target}

    def finalize(database: Path, _bootstrap: dict[str, object]):
        active_database["path"] = database

        def rollback() -> None:
            active_database["path"] = target

        return rollback

    monkeypatch.setattr(
        legacy_migration,
        "retire_database",
        lambda _path: (_ for _ in ()).throw(OSError("retirement failed")),
    )

    result = legacy_migration.adopt_legacy_profile(
        source_root=source_root,
        database_path=target,
        backup_root=tmp_path / "BACKUP",
        finalize=finalize,
        replace_existing_target=True,
    )

    assert result.migrated is False
    assert result.error_code == "adoption_failed"
    assert active_database["path"] == target
    assert SqliteStore(str(target)).load_config() == {"current": True}
    assert not list(target.parent.glob("picsyncra-import-*.sqlite"))


def test_profile_transaction_keeps_the_new_bootstrap_file_when_it_shares_the_old_root(
    tmp_path: Path,
) -> None:
    """The cleanup must not move local_settings.json written by the activation itself."""

    from picsyncra.legacy_migration import adopt_legacy_profile

    source_root = tmp_path / "application"
    source_root.mkdir()
    (source_root / "config.json").write_text(json.dumps({"legacy": True}), encoding="utf-8")
    old_settings = source_root / "local_settings.json"
    old_settings.write_text(json.dumps({"language": "pl", "database_path": "old.sqlite"}), encoding="utf-8")
    target = tmp_path / "current" / "picsyncra.sqlite"

    def finalize(database: Path, _bootstrap: dict[str, object]) -> None:
        old_settings.write_text(
            json.dumps({"data_mode": "sqlite", "database_path": str(database)}),
            encoding="utf-8",
        )

    result = adopt_legacy_profile(
        source_root=source_root,
        database_path=target,
        backup_root=tmp_path / "BACKUP",
        finalize=finalize,
        preserve_source_paths=(old_settings,),
    )

    assert result.migrated is True
    assert json.loads(old_settings.read_text(encoding="utf-8"))["database_path"] == str(target)
    assert json.loads((result.archive_dir / "local_settings.json").read_text(encoding="utf-8")) == {
        "language": "pl",
        "database_path": "old.sqlite",
    }


def test_profile_transaction_retires_the_replaced_active_database_after_switching(
    tmp_path: Path,
) -> None:
    """A successful replacement may not leave the former active SQLite in the root."""

    from picsyncra.legacy_migration import adopt_legacy_profile

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    (source_root / "config.json").write_text(json.dumps({"legacy": True}), encoding="utf-8")
    target = tmp_path / "current" / "picsyncra.sqlite"
    SqliteStore(str(target)).save_config({"current": True})
    activated: list[Path] = []

    result = adopt_legacy_profile(
        source_root=source_root,
        database_path=target,
        backup_root=tmp_path / "BACKUP",
        finalize=lambda database, _bootstrap: activated.append(database),
        replace_existing_target=True,
    )

    assert result.migrated is True
    assert result.copied_paths[0] != target
    assert activated == [result.copied_paths[0]]
    assert not target.exists()
    assert SqliteStore(str(result.copied_paths[0])).load_config()["legacy"] is True
    assert SqliteStore(str(result.archive_dir / "previous-picsyncra.sqlite")).load_config() == {
        "current": True
    }
    assert (result.archive_dir / "legacy-source-files" / "picsyncra.sqlite").is_file()


def test_profile_transaction_switches_to_a_fresh_database_when_old_target_is_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WinError 32 for the current database must leave a working imported target."""

    from picsyncra import legacy_migration

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    (source_root / "config.json").write_text(json.dumps({"legacy": True}), encoding="utf-8")
    target = tmp_path / "current" / "picsyncra.sqlite"
    SqliteStore(str(target)).save_config({"current": True})
    original_replace = legacy_migration.os.replace

    def deny_active_target_move(source_path: object, destination_path: object) -> None:
        if Path(source_path) == target:
            error = PermissionError("target database is open")
            error.winerror = 32  # type: ignore[attr-defined]
            raise error
        original_replace(source_path, destination_path)

    monkeypatch.setattr(legacy_migration.os, "replace", deny_active_target_move)
    monkeypatch.setattr(legacy_migration, "_schedule_pending_target_cleanup", lambda *_args, **_kwargs: None)

    result = legacy_migration.adopt_legacy_profile(
        source_root=source_root,
        database_path=target,
        backup_root=tmp_path / "BACKUP",
        replace_existing_target=True,
    )

    assert result.migrated is True
    assert result.copied_paths[0] != target
    assert SqliteStore(str(result.copied_paths[0])).load_config()["legacy"] is True
    assert target.exists()
    assert result.error is not None
    assert "automatycznie przeniesiona" in result.error
    pending = tmp_path / "BACKUP" / "legacy-import" / ".pending-target-cleanup"
    assert list(pending.glob("*.json"))


def test_pending_profile_cleanup_accepts_local_settings_file(tmp_path: Path) -> None:
    """A locked old local_settings.json must be retried after the program restarts."""

    from picsyncra import legacy_migration

    source = tmp_path / "old-profile" / "local_settings.json"
    source.parent.mkdir()
    source.write_text(json.dumps({"language": "pl"}), encoding="utf-8")
    backup_root = tmp_path / "BACKUP"
    archive_dir = backup_root / "legacy-import" / "20260901-120000"
    manifest = legacy_migration._write_pending_source_cleanup(
        sources=(source,),
        archive_dir=archive_dir,
        backup_root=backup_root,
        sqlite_source=False,
    )

    legacy_migration.process_pending_legacy_target_cleanups(backup_root)

    assert not source.exists()
    assert not manifest.exists()
    assert (archive_dir / "local_settings.json").is_file()


def test_strict_profile_publish_defers_staging_cleanup_until_after_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishing must not depend on deleting staging during the atomic handoff."""

    from picsyncra import legacy_migration

    staging = tmp_path / "staging.sqlite"
    target = tmp_path / "picsyncra.sqlite"
    staging.write_bytes(b"staged-data")
    monkeypatch.setattr(
        legacy_migration.Path,
        "unlink",
        lambda _path, *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("simulated staging cleanup failure")
        ),
    )

    legacy_migration._publish_profile_staging(
        staging, target, reject_existing_target=True
    )

    assert target.read_bytes() == b"staged-data"
    assert staging.is_file()


def test_profile_adoption_keeps_published_target_when_temp_cleanup_is_delayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An undeletable temporary hard link is a cleanup warning, not a failed import."""

    from tempfile import TemporaryDirectory as StandardTemporaryDirectory

    from picsyncra import legacy_migration

    class DelayedCleanupTemporaryDirectory(StandardTemporaryDirectory):
        def cleanup(self) -> None:
            super().cleanup()
            raise OSError("simulated temporary cleanup delay")

    source_root = tmp_path / "old-profile"
    source_root.mkdir()
    (source_root / "config.json").write_text(
        json.dumps({"legacy": True}), encoding="utf-8"
    )
    target = tmp_path / "current" / "picsyncra.sqlite"
    monkeypatch.setattr(
        legacy_migration,
        "TemporaryDirectory",
        DelayedCleanupTemporaryDirectory,
    )

    result = legacy_migration.adopt_legacy_profile(
        source_root=source_root,
        database_path=target,
        backup_root=tmp_path / "BACKUP",
        reject_existing_target=True,
    )

    assert result.migrated is True
    assert target.is_file()
    assert result.error is not None
    assert "roboczego" in result.error
