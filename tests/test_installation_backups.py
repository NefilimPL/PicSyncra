from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from picsyncra.installation.contracts import InstallContext


def context(tmp_path: Path) -> InstallContext:
    program = tmp_path / "Program Files" / "PicSyncra"
    state = tmp_path / "ProgramData" / "PicSyncra"
    config = state / "config"
    program.mkdir(parents=True)
    config.mkdir(parents=True)
    database = state / "data.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TABLE schema_version(version INTEGER);"
            "INSERT INTO schema_version VALUES (17);"
            "CREATE TABLE app_config_values(key TEXT, value_json TEXT);"
        )
    (program / "active.json").write_text(
        json.dumps({"schema": 1, "installation_id": "site-1", "release_id": 41}),
        encoding="utf-8",
    )
    (config / "settings.json").write_text('{"secret":"kept-private"}', encoding="utf-8")
    return InstallContext("site-1", program, state, config, database)


def test_operation_backup_creates_verified_database_and_independent_config_copy(tmp_path: Path) -> None:
    from picsyncra.installation.backups import create_operation_backup

    value = context(tmp_path)
    receipt = create_operation_backup(value, "operation-1")

    backup_root = value.state_root / "backups" / "operations" / receipt.backup_id
    assert receipt.operation_id == "operation-1"
    assert receipt.release_id == 41
    assert receipt.schema_version == 17
    assert receipt.verified is True
    assert (backup_root / "database.sqlite").is_file()
    assert (backup_root / "config" / "settings.json").read_text(encoding="utf-8") == '{"secret":"kept-private"}'
    assert json.loads((backup_root / "receipt.json").read_text(encoding="utf-8"))["database_sha256"] == receipt.database_sha256

    (value.config_root / "settings.json").write_text('{"secret":"changed"}', encoding="utf-8")
    with sqlite3.connect(value.database_path) as connection:
        connection.execute("INSERT INTO schema_version VALUES (18)")
    assert (backup_root / "config" / "settings.json").read_text(encoding="utf-8") == '{"secret":"kept-private"}'
    assert hashlib.sha256((backup_root / "database.sqlite").read_bytes()).hexdigest() == receipt.database_sha256


def test_operation_backup_rejects_missing_or_unsafe_configuration_before_publishing(tmp_path: Path) -> None:
    from picsyncra.installation.backups import BackupError, create_operation_backup

    value = context(tmp_path)
    (value.config_root / "settings.json").unlink()
    value.config_root.rmdir()

    with pytest.raises(BackupError, match="configuration"):
        create_operation_backup(value, "operation-1")
    assert not (value.state_root / "backups" / "operations").exists()


def test_operation_backup_does_not_overwrite_an_existing_operation_backup(tmp_path: Path) -> None:
    from picsyncra.installation.backups import BackupError, create_operation_backup

    value = context(tmp_path)
    create_operation_backup(value, "operation-1")
    with pytest.raises(BackupError, match="already exists"):
        create_operation_backup(value, "operation-1")


def test_operation_backup_rejects_path_traversal_operation_identifier(tmp_path: Path) -> None:
    from picsyncra.installation.backups import BackupError, create_operation_backup

    with pytest.raises(BackupError, match="operation"):
        create_operation_backup(context(tmp_path), "../outside")
    assert not (tmp_path / "outside").exists()
