"""Read-only database inspection and verified snapshots for installed operations.

No schema migration, default database creation or raw-file-copy fallback occurs.
The caller is responsible for draining writers before a snapshot is used for a
version switch; an online SQLite snapshot alone is not a maintenance lock.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time


class DatabaseSnapshotError(RuntimeError):
    """A verified database snapshot could not be created."""


@dataclass(frozen=True)
class DatabaseInspection:
    schema_version: int
    integrity_ok: bool
    is_picsyncra: bool


@dataclass(frozen=True)
class DatabaseSnapshot:
    path: Path
    sha256: str
    schema_version: int
    integrity_ok: bool


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError("The selected database does not exist.")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    return connection


def _inspect(connection: sqlite3.Connection) -> DatabaseInspection:
    integrity_ok = connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    is_picsyncra = {"schema_version", "app_config_values"}.issubset(tables)
    schema = 0
    if is_picsyncra:
        schema = int(connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0])
    return DatabaseInspection(schema, integrity_ok, is_picsyncra)


def inspect_database(path: Path) -> DatabaseInspection:
    """Inspect an existing database without instantiating the migrating store."""
    with closing(_read_only_connection(Path(path))) as connection:
        return _inspect(connection)


def create_database_snapshot(
    source_path: Path, target_path: Path, *, timeout_seconds: float = 30.0
) -> DatabaseSnapshot:
    """Back up committed SQLite state, verify it, then publish without overwrite."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Snapshot timeout must be finite and positive.")
    source = Path(source_path).resolve(strict=True)
    target = Path(target_path).absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError("The selected backup already exists.")
    if source == target.resolve():
        raise ValueError("The source cannot be its own backup.")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".database-snapshot-", suffix=".sqlite", dir=target.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    deadline = time.monotonic() + timeout_seconds

    def check_deadline(status: int, remaining: int, total: int) -> None:
        if time.monotonic() > deadline:
            raise DatabaseSnapshotError("Timed out waiting for a consistent database snapshot.")

    try:
        with closing(_read_only_connection(source)) as src, closing(sqlite3.connect(temporary)) as dst:
            src.backup(dst, pages=256, progress=check_deadline, sleep=0.05)
        with closing(_read_only_connection(temporary_path)) as check:
            inspection = _inspect(check)
        if not inspection.integrity_ok:
            raise DatabaseSnapshotError("The database snapshot failed its integrity check.")
        with temporary_path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        with temporary_path.open("rb+") as handle:
            os.fsync(handle.fileno())
        # A same-volume hard link is an atomic no-overwrite publication. An
        # unsupported filesystem fails closed instead of weakening this rule.
        os.link(temporary_path, target)
        return DatabaseSnapshot(target, digest, inspection.schema_version, True)
    except sqlite3.Error as exc:
        raise DatabaseSnapshotError("Cannot create a verified database snapshot.") from exc
    finally:
        temporary_path.unlink(missing_ok=True)
