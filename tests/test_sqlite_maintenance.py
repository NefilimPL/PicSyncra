from __future__ import annotations

import sqlite3
from pathlib import Path

from picsyncra import data_store, sqlite_maintenance
from picsyncra.sqlite_maintenance import (
    TIMESTAMP_COLUMNS,
    normalize_timestamp_columns,
    repair_sqlite_database,
)
from picsyncra.sqlite_store import SqliteStore


def test_integrity_check_closes_database_before_returning(tmp_path: Path) -> None:
    """Maintenance reads must not leave a Windows-locked SQLite file behind."""

    db_path = tmp_path / "data.sqlite"
    SqliteStore(str(db_path)).initialize()

    assert sqlite_maintenance.integrity_check(str(db_path)) == "ok"

    db_path.unlink()
    assert not db_path.exists()


def test_repair_creates_backup_and_migrates_legacy_history(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    backup_dir = tmp_path / "BACKUP"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL);
            INSERT INTO schema_version VALUES (2, '2026-06-25T12:00:00.000Z');
            CREATE TABLE web_history (id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, ts REAL NOT NULL);
            INSERT INTO web_history VALUES ('hist-1', '{"id":"hist-1","ts":1782392554.3,"user":"admin"}', 1782392554.3);
            """
        )

    result = repair_sqlite_database(str(db_path), str(backup_dir))

    assert result["ok"] is True
    assert Path(result["backup"]["backup_path"]).exists()
    assert result["integrity_check"] == "ok"
    assert result["schema_version"] >= 3
    payload = SqliteStore(str(db_path)).load_history()[0]
    assert payload["created_at"].endswith("Z")


def test_repair_preserves_config_and_user_data(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(db_path))
    store.initialize()
    store.save_config({"sql_query": "UPDATE product SET img = {filename}", "db_type": "mysql"})
    store.save_users([{"username": "admin", "password_hash": "hash", "role": "admin"}])

    result = repair_sqlite_database(str(db_path), str(tmp_path / "BACKUP"))

    repaired = SqliteStore(str(db_path))
    assert result["ok"] is True
    assert repaired.load_config()["sql_query"] == "UPDATE product SET img = {filename}"
    assert repaired.load_users()[0]["username"] == "admin"


def test_repair_invalidates_the_mutated_store(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(db_path))
    store.initialize()
    stale_store = data_store.get_sqlite_store(str(db_path))

    result = repair_sqlite_database(str(db_path), str(tmp_path / "BACKUP"))

    assert result["ok"] is True
    assert data_store.get_sqlite_store(str(db_path)) is not stale_store


def test_failed_repair_preserves_the_active_store(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(db_path))
    store.initialize()
    active_store = data_store.get_sqlite_store(str(db_path))
    monkeypatch.setattr(sqlite_maintenance, "integrity_check", lambda _path: "corrupt")

    result = repair_sqlite_database(str(db_path), str(tmp_path / "BACKUP"))

    assert result["ok"] is False
    assert data_store.get_sqlite_store(str(db_path)) is active_store


def test_repair_converts_legacy_numeric_updated_at_and_drops_empty_app_settings(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL);
            INSERT INTO schema_version VALUES (3, '1782390670.4675686');
            CREATE TABLE app_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE app_config_values (path TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
            INSERT INTO app_config_values VALUES ('database.query', '""', '1782390670.4675686');
            CREATE TABLE product_entries (
                product_id TEXT PRIMARY KEY,
                ean TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                type_name TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                color1 TEXT NOT NULL DEFAULT '',
                color2 TEXT NOT NULL DEFAULT '',
                color3 TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            INSERT INTO product_entries VALUES (
                'PRD-1', '5901234567890', 'MAGGIORE', 'KOMODA',
                'MA03', 'BIALY', '', '', 'NO-LED', '1782390670.4675686'
            );
            """
        )

    result = repair_sqlite_database(str(db_path), str(tmp_path / "BACKUP"))

    assert result["ok"] is True
    with sqlite3.connect(db_path) as conn:
        product_updated_at = conn.execute(
            "SELECT updated_at FROM product_entries WHERE product_id = 'PRD-1'"
        ).fetchone()[0]
        config_updated_at = conn.execute(
            "SELECT updated_at FROM app_config_values WHERE path = 'database.query'"
        ).fetchone()[0]
        schema_applied_at = conn.execute(
            "SELECT applied_at FROM schema_version ORDER BY rowid LIMIT 1"
        ).fetchone()[0]
        app_settings_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_settings'"
        ).fetchone()

    for value in (product_updated_at, config_updated_at, schema_applied_at):
        assert isinstance(value, str)
        assert value.endswith("Z")
        assert "T" in value
    assert app_settings_exists is None


def test_normalize_timestamp_columns_covers_observability_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(db_path))
    store.initialize()
    expected = {
        ("operational_events", "created_at"),
        ("job_runs", "started_at"),
        ("job_runs", "finished_at"),
        ("incidents", "first_seen_at"),
        ("incidents", "last_seen_at"),
        ("incidents", "notification_window_at"),
        ("alert_reads", "created_at"),
        ("notification_deliveries", "created_at"),
        ("notification_deliveries", "updated_at"),
        ("notification_deliveries", "next_attempt_at"),
    }
    assert expected <= set(TIMESTAMP_COLUMNS)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO job_runs (id, status, started_at, finished_at)
            VALUES ('job-1', 'completed', '1784196000', '1784196060')
            """
        )
        conn.execute(
            """
            INSERT INTO incidents (
                id, fingerprint, severity, event_type, first_seen_at,
                last_seen_at, first_event_id, latest_event_id,
                notification_window_at
            ) VALUES (
                'inc-1', 'fingerprint', 'error', 'ftp.failed',
                '1784196000', '1784196060', 'evt-1', 'evt-2', '1784196060'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO notification_deliveries (
                id, severity, status, primary_channel, message_json,
                created_at, updated_at, next_attempt_at
            ) VALUES (
                'delivery-1', 'error', 'pending', 'entra', '{}',
                '1784196000', '1784196060', '1784196120'
            )
            """
        )
        changed = normalize_timestamp_columns(conn)
        job = conn.execute(
            "SELECT started_at, finished_at FROM job_runs WHERE id = 'job-1'"
        ).fetchone()
        incident = conn.execute(
            """
            SELECT first_seen_at, last_seen_at, notification_window_at
            FROM incidents WHERE id = 'inc-1'
            """
        ).fetchone()
        delivery = conn.execute(
            """
            SELECT created_at, updated_at, next_attempt_at
            FROM notification_deliveries WHERE id = 'delivery-1'
            """
        ).fetchone()

    assert changed == 8
    assert all(value.endswith("Z") for value in (*job, *incident, *delivery))


def test_normalize_timestamp_columns_canonicalizes_valid_iso_text(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(db_path))
    store.initialize()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO operational_events (
                id, created_at, severity, event_type, summary
            ) VALUES (
                'evt-1', '2026-07-16T10:00:00Z', 'info', 'job.started', 'Start'
            )
            """
        )
        changed = normalize_timestamp_columns(conn)
        created_at = conn.execute(
            "SELECT created_at FROM operational_events WHERE id = 'evt-1'"
        ).fetchone()[0]

    assert changed == 1
    assert created_at == "2026-07-16T10:00:00.000Z"
