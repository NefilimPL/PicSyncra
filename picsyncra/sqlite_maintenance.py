"""SQLite maintenance and repair workflow helpers."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sqlite_backup import create_backup
from .sqlite_coordination import database_activity
from .sqlite_store import SCHEMA_VERSION, SqliteStore


TIMESTAMP_COLUMNS = (
    ("schema_version", "applied_at"),
    ("app_config_values", "updated_at"),
    ("app_settings", "updated_at"),
    ("sql_available_columns", "detected_at"),
    ("product_entries", "updated_at"),
    ("web_users", "updated_at"),
    ("web_history", "created_at"),
    ("file_index_cache", "updated_at"),
    ("file_index_segments", "updated_at"),
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
)


def integrity_check(database_path: str) -> str:
    with database_activity(database_path):
        with closing(sqlite3.connect(database_path)) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
    return str(row[0] if row else "")


def current_schema_version(database_path: str) -> int:
    try:
        with database_activity(database_path):
            with closing(sqlite3.connect(database_path)) as conn:
                row = conn.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_version"
                ).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _iso_from_legacy_timestamp(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        parsed = datetime.fromtimestamp(number, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_timestamp_columns(conn: sqlite3.Connection) -> int:
    changed = 0
    for table, column in TIMESTAMP_COLUMNS:
        if not _column_exists(conn, table, column):
            continue
        rows = conn.execute(f"SELECT rowid, {column} FROM {table}").fetchall()
        for rowid, raw_value in rows:
            normalized = _iso_from_legacy_timestamp(raw_value)
            if normalized and normalized != raw_value:
                conn.execute(
                    f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                    (normalized, rowid),
                )
                changed += 1
    return changed


def drop_empty_legacy_tables(conn: sqlite3.Connection) -> list[str]:
    removed: list[str] = []
    if _table_exists(conn, "app_settings"):
        row = conn.execute("SELECT COUNT(*) FROM app_settings").fetchone()
        if int(row[0] or 0) == 0:
            conn.execute("DROP TABLE app_settings")
            removed.append("app_settings")
    return removed


def rebuild_file_index_segments(store: SqliteStore) -> int:
    snapshot = store.load_file_index_cache()
    if not snapshot:
        return 0
    return store.save_file_index_segments(snapshot)


def _repair_sqlite_database(database_path: str, backup_dir: str) -> dict[str, Any]:
    db_path = Path(database_path)
    if not db_path.exists():
        raise FileNotFoundError(str(db_path))
    backup = create_backup(str(db_path), backup_dir, reason="pre-repair")
    check = integrity_check(str(db_path))
    before_version = current_schema_version(str(db_path))
    if check.lower() != "ok":
        return {
            "ok": False,
            "backup": backup,
            "integrity_check": check,
            "schema_version": before_version,
            "warnings": ["integrity_check_failed"],
        }
    store = SqliteStore(str(db_path))
    store.initialize()
    segments = rebuild_file_index_segments(store)
    with closing(sqlite3.connect(str(db_path))) as conn:
        with conn:
            timestamps_normalized = normalize_timestamp_columns(conn)
            removed_tables = drop_empty_legacy_tables(conn)
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.execute("ANALYZE")
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.execute("VACUUM")
    from .data_store import invalidate_sqlite_store

    invalidate_sqlite_store(str(db_path))
    return {
        "ok": True,
        "backup": backup,
        "integrity_check": "ok",
        "schema_version": current_schema_version(str(db_path)),
        "previous_schema_version": before_version,
        "target_schema_version": SCHEMA_VERSION,
        "segments_rebuilt": segments,
        "timestamps_normalized": timestamps_normalized,
        "removed_tables": removed_tables,
        "warnings": [],
    }


def repair_sqlite_database(database_path: str, backup_dir: str) -> dict[str, Any]:
    """Repair one database while respecting an ongoing legacy handover."""

    with database_activity(database_path):
        return _repair_sqlite_database(database_path, backup_dir)
