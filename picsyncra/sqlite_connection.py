"""SQLite connection policy shared by short-lived store connections."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class SQLiteConnectionSettings:
    busy_timeout_ms: int = 5000
    connect_timeout_seconds: float = 5.0


def configure_connection(
    conn: sqlite3.Connection,
    settings: SQLiteConnectionSettings,
    *,
    wal_active: bool,
) -> None:
    """Apply the store's concurrency policy to one SQLite connection."""

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {settings.busy_timeout_ms:d}")
    if wal_active:
        conn.execute("PRAGMA synchronous = NORMAL")


def try_enable_wal(conn: sqlite3.Connection) -> str:
    """Request WAL mode and return SQLite's normalized response."""

    row = conn.execute("PRAGMA journal_mode = WAL").fetchone()
    return str(row[0] if row else "").strip().lower()
