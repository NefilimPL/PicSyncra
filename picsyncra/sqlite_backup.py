"""SQLite backup, history, and retention helpers."""

from __future__ import annotations

import json
import gc
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .sqlite_coordination import database_activity

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SECRET_KEYWORDS = ("password", "pass", "secret", "token", "hash", "api_key")


def _utc_datetime(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _schedule_datetime(
    value: datetime | None = None,
    *,
    time_zone_name: object = "UTC",
) -> datetime:
    """Return the instant represented by ``value`` in the configured schedule zone."""

    try:
        target_zone = ZoneInfo(str(time_zone_name or "UTC"))
    except Exception:
        target_zone = timezone.utc
    return _utc_datetime(value).astimezone(target_zone)


def now_iso(now: datetime | None = None) -> str:
    return _utc_datetime(now).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _backup_name(now: datetime, reason: str) -> str:
    safe_reason = (
        "".join(
            ch
            for ch in str(reason or "manual").lower()
            if ch.isalnum() or ch in {"-", "_"}
        )
        or "manual"
    )
    return (
        f"picsyncra-{_utc_datetime(now).strftime('%Y%m%d-%H%M%S')}-"
        f"{safe_reason}.sqlite"
    )


def _backup_roots(backup_dirs: Iterable[str] | str) -> list[Path]:
    values = [backup_dirs] if isinstance(backup_dirs, str) else backup_dirs
    roots = []
    seen = set()
    for value in values:
        try:
            root = Path(value).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if not root.is_dir():
            continue
        key = os.path.normcase(str(root))
        if key not in seen:
            roots.append(root)
            seen.add(key)
    return roots


def resolve_backup_path(backup_path: str, backup_dirs: Iterable[str] | str) -> Path:
    """Resolve an existing SQLite backup only when it is under a trusted root."""

    try:
        candidate = Path(str(backup_path or "")).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise FileNotFoundError(str(backup_path or "")) from exc
    if candidate.suffix.lower() != ".sqlite" or not candidate.is_file():
        raise ValueError("Wybrana kopia musi byc plikiem SQLite.")
    for root in _backup_roots(backup_dirs):
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        return candidate
    raise ValueError("Wybrana kopia nie znajduje sie w dozwolonym katalogu.")


def _schema_version(path: str) -> int:
    conn = None
    try:
        with database_activity(path):
            conn = sqlite3.connect(path)
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_version"
            ).fetchone()
            return int(row[0] or 0) if row else 0
    except Exception:
        return 0
    finally:
        if conn is not None:
            conn.close()


def _integrity_check(path: str) -> str:
    conn = None
    try:
        with database_activity(path):
            conn = sqlite3.connect(path)
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return str(row[0] if row else "")
    except Exception as exc:
        return str(exc)
    finally:
        if conn is not None:
            conn.close()


def create_backup(
    source_path: str,
    backup_dir: str,
    *,
    reason: str = "manual",
    now: datetime | None = None,
) -> dict[str, Any]:
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(str(source))
    timestamp = _utc_datetime(now)
    target_dir = Path(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _backup_name(timestamp, reason)
    method = "sqlite_backup"
    src = None
    dst = None
    try:
        with database_activity(source):
            src = sqlite3.connect(str(source))
            dst = sqlite3.connect(str(target))
            src.backup(dst)
    except sqlite3.Error:
        method = "raw_copy"
        target.write_bytes(source.read_bytes())
    finally:
        if dst is not None:
            dst.close()
        if src is not None:
            src.close()
    metadata = {
        "source_path": str(source),
        "backup_path": str(target),
        "created_at": now_iso(timestamp),
        "reason": reason,
        "size_bytes": target.stat().st_size,
        "schema_version": _schema_version(str(target)),
        "integrity_check": _integrity_check(str(target)),
        "method": method,
    }
    target.with_suffix(".json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"ok": True, **metadata}


def list_backups(backup_dirs: Iterable[str] | str) -> list[dict[str, Any]]:
    items = []
    for backup_dir in _backup_roots(backup_dirs):
        for db_path in backup_dir.glob("*.sqlite"):
            try:
                safe_path = resolve_backup_path(str(db_path), [str(backup_dir)])
            except (ValueError, FileNotFoundError):
                continue
            meta_path = safe_path.with_suffix(".json")
            metadata: dict[str, Any] = {}
            if meta_path.is_file():
                try:
                    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    metadata = {}
            metadata["backup_path"] = str(safe_path)
            metadata.setdefault("created_at", "")
            metadata.setdefault("reason", "")
            metadata.setdefault("size_bytes", safe_path.stat().st_size)
            items.append(metadata)
    return sorted(items, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def enforce_retention(backup_dir: str, max_copies: int) -> dict[str, Any]:
    keep = max(1, int(max_copies or 1))
    candidates = [
        item
        for item in list_backups(backup_dir)
        if item.get("reason") in {"manual", "scheduled"}
    ]
    remove = candidates[keep:]
    removed = 0
    for item in remove:
        try:
            db_path = resolve_backup_path(str(item["backup_path"]), backup_dir)
        except (ValueError, FileNotFoundError):
            continue
        for path in (db_path, db_path.with_suffix(".json")):
            try:
                path.unlink()
                if path.suffix == ".sqlite":
                    removed += 1
            except FileNotFoundError:
                pass
    return {"removed": removed}


def schedule_slot(now: datetime) -> str:
    return _utc_datetime(now).strftime("%Y-%m-%dT%H")


def due_schedule_slots(
    settings_payload: dict[str, Any],
    now: datetime | None = None,
    *,
    time_zone_name: object = "UTC",
) -> list[str]:
    value = _schedule_datetime(now, time_zone_name=time_zone_name)
    if not settings_payload.get("enabled"):
        return []
    day = WEEKDAY_KEYS[value.weekday()]
    hour = value.hour
    explicit_slots = {str(item).lower() for item in settings_payload.get("slots") or []}
    if explicit_slots:
        if f"{day}:{hour}" not in explicit_slots:
            return []
        slot = schedule_slot(value)
        if slot in set(settings_payload.get("last_run_slots") or []):
            return []
        return [slot]
    if day not in set(settings_payload.get("days") or []):
        return []
    try:
        hours = {int(item) for item in settings_payload.get("hours") or []}
    except (TypeError, ValueError):
        hours = set()
    if hour not in hours:
        return []
    slot = schedule_slot(value)
    if slot in set(settings_payload.get("last_run_slots") or []):
        return []
    return [slot]


def mark_schedule_slots_run(
    settings_payload: dict[str, Any],
    slots: list[str],
) -> dict[str, Any]:
    updated = dict(settings_payload or {})
    existing = [str(item) for item in updated.get("last_run_slots", [])]
    merged = existing + [slot for slot in slots if slot not in existing]
    updated["last_run_slots"] = merged[-500:]
    return updated


def restore_backup(
    active_path: str,
    backup_path: str,
    backup_dir: str,
    allowed_backup_dirs: Iterable[str] | None = None,
) -> dict[str, Any]:
    pre_restore = create_backup(active_path, backup_dir, reason="pre-restore")
    active = Path(active_path)
    source = resolve_backup_path(backup_path, allowed_backup_dirs or [backup_dir])
    fd, temp_path = tempfile.mkstemp(
        prefix="restore_",
        suffix=".sqlite.tmp",
        dir=str(active.parent),
    )
    os.close(fd)
    temp = Path(temp_path)
    try:
        temp.write_bytes(source.read_bytes())
        gc.collect()
        os.replace(str(temp), str(active))
        from .data_store import invalidate_sqlite_store

        invalidate_sqlite_store(str(active))
    finally:
        if temp.exists():
            temp.unlink()
    return {
        "ok": True,
        "pre_restore_backup": pre_restore,
        "restored_from": str(source),
        "active_path": str(active),
    }


def _mask_value(key: str, value: object) -> object:
    lowered = str(key or "").lower()
    if any(keyword in lowered for keyword in SECRET_KEYWORDS):
        return "present" if str(value or "") else "empty"
    return value


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
    except sqlite3.Error:
        return 0


def _config_rows(conn: sqlite3.Connection) -> dict[str, object]:
    try:
        rows = conn.execute(
            "SELECT path, value_json FROM app_config_values ORDER BY path"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(path): _mask_value(str(path), value) for path, value in rows}


def diff_databases(
    active_path: str,
    backup_path: str,
    allowed_backup_dirs: Iterable[str] | str,
) -> dict[str, Any]:
    tables = [
        "app_config_values",
        "list_values",
        "slot_definitions",
        "sql_column_map",
        "sql_available_columns",
        "web_users",
        "product_entries",
        "file_index_segments",
        "web_history",
    ]
    safe_backup_path = resolve_backup_path(backup_path, allowed_backup_dirs)
    with database_activity(active_path):
        with (
            closing(sqlite3.connect(active_path)) as active,
            closing(sqlite3.connect(str(safe_backup_path))) as backup,
        ):
            active_counts = {table: _table_count(active, table) for table in tables}
            backup_counts = {table: _table_count(backup, table) for table in tables}
            active_config = _config_rows(active)
            backup_config = _config_rows(backup)
    config_added = sorted(set(backup_config) - set(active_config))
    config_removed = sorted(set(active_config) - set(backup_config))
    config_changed = sorted(
        key
        for key in set(active_config) & set(backup_config)
        if active_config[key] != backup_config[key]
    )
    return {
        "tables": {
            table: {
                "active": active_counts[table],
                "backup": backup_counts[table],
                "added": max(0, backup_counts[table] - active_counts[table]),
                "removed": max(0, active_counts[table] - backup_counts[table]),
            }
            for table in tables
        },
        "config": {
            "added": [
                {"key": key, "value": backup_config[key]} for key in config_added
            ],
            "removed": [
                {"key": key, "value": active_config[key]} for key in config_removed
            ],
            "changed": [
                {
                    "key": key,
                    "active": active_config[key],
                    "backup": backup_config[key],
                }
                for key in config_changed
            ],
        },
    }
