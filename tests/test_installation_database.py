"""Read-only discovery and strict SQLite snapshots for installed operations."""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest


def database_module():
    return importlib.import_module("picsyncra.installation.database")


def make_database(path: Path):
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE schema_version(version INTEGER, applied_at TEXT);
        INSERT INTO schema_version VALUES (17, '2026-01-01');
        CREATE TABLE app_config_values(key TEXT PRIMARY KEY, value_json TEXT);
        CREATE TABLE products(name TEXT);
        INSERT INTO products VALUES ('original');
        PRAGMA user_version=17;
    """)
    connection.commit()
    return connection


def test_inspection_reads_existing_schema_without_migrating(tmp_path):
    module = database_module()
    path = tmp_path / "source.sqlite"
    make_database(path).close()
    before = path.read_bytes()
    result = module.inspect_database(path)
    assert result.schema_version == 17
    assert result.integrity_ok is True
    assert result.is_picsyncra is True
    assert path.read_bytes() == before


def test_discovery_does_not_create_missing_database(tmp_path):
    module = database_module()
    path = tmp_path / "absent.sqlite"
    with pytest.raises(FileNotFoundError):
        module.inspect_database(path)
    assert not path.exists()


def test_snapshot_includes_committed_wal_and_is_independent(tmp_path):
    module = database_module()
    source = tmp_path / "source.sqlite"
    connection = make_database(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("INSERT INTO products VALUES ('in WAL')")
    connection.commit()
    target = tmp_path / "backups" / "before-update.sqlite"
    try:
        result = module.create_database_snapshot(source, target)
        assert result.integrity_ok is True
        assert len(result.sha256) == 64
    finally:
        connection.close()
    source.unlink()
    with sqlite3.connect(target) as backup:
        assert backup.execute("SELECT name FROM products ORDER BY rowid").fetchall() == [
            ("original",), ("in WAL",)
        ]


def test_corrupt_database_cannot_produce_successful_snapshot(tmp_path):
    module = database_module()
    source = tmp_path / "source.sqlite"
    source.write_bytes(b"not a database")
    target = tmp_path / "backups" / "before-update.sqlite"
    with pytest.raises(module.DatabaseSnapshotError):
        module.create_database_snapshot(source, target)
    assert not target.exists()
    assert source.read_bytes() == b"not a database"


def test_snapshot_never_overwrites_previous_backup(tmp_path):
    module = database_module()
    source = tmp_path / "source.sqlite"
    make_database(source).close()
    target = tmp_path / "existing.sqlite"
    target.write_bytes(b"previous backup")
    with pytest.raises(FileExistsError):
        module.create_database_snapshot(source, target)
    assert target.read_bytes() == b"previous backup"


def test_arbitrary_sqlite_is_not_mistaken_for_picsyncra(tmp_path):
    module = database_module()
    path = tmp_path / "other.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE other(value TEXT)")
    assert module.inspect_database(path).is_picsyncra is False
