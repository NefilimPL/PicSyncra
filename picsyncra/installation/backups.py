"""Mandatory, verified backups owned by an installed update operation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Iterator
from uuid import uuid4

from .contracts import BackupReceipt, InstallContext
from .database import DatabaseSnapshotError, create_database_snapshot


class BackupError(RuntimeError):
    """The required pre-operation backup could not be created safely."""


_IDENTIFIER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$")


def _operation_directory(context: InstallContext, operation_id: str) -> tuple[Path, Path]:
    if not isinstance(operation_id, str) or _IDENTIFIER.fullmatch(operation_id) is None:
        raise BackupError("The operation identifier is invalid.")
    return context.state_root / "backups" / "operations", context.state_root / "backups" / "operations" / operation_id


def _configuration_root(context: InstallContext) -> Path:
    root = Path(context.config_root)
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise BackupError("The installed configuration is unavailable.") from exc
    if root.is_symlink() or not resolved.is_dir():
        raise BackupError("The installed configuration is unsafe.")
    return resolved


def _configuration_files(root: Path) -> Iterator[tuple[Path, Path]]:
    for source in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if source.is_symlink():
            raise BackupError("The installed configuration contains a link.")
        if source.is_dir():
            continue
        try:
            mode = source.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise BackupError("Cannot read the installed configuration.") from exc
        if not stat.S_ISREG(mode):
            raise BackupError("The installed configuration contains an unsupported file.")
        yield source, source.relative_to(root)


def _copy_configuration(source_root: Path, target_root: Path) -> str:
    digest = hashlib.sha256()
    target_root.mkdir()
    for source, relative in _configuration_files(source_root):
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        with target.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def _active_release(context: InstallContext) -> int:
    try:
        payload = json.loads((context.program_root / "active.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise BackupError("The active installed release is unavailable.") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema", "installation_id", "release_id"}:
        raise BackupError("The active installed release is invalid.")
    release_id = payload.get("release_id")
    if (
        payload.get("schema") != 1
        or payload.get("installation_id") != context.installation_id
        or isinstance(release_id, bool)
        or not isinstance(release_id, int)
        or release_id < 0
    ):
        raise BackupError("The active installed release is invalid.")
    return release_id


def _write_receipt(path: Path, receipt: BackupReceipt) -> None:
    payload = {
        "schema": 1,
        "backup_id": receipt.backup_id,
        "operation_id": receipt.operation_id,
        "database_sha256": receipt.database_sha256,
        "config_sha256": receipt.config_sha256,
        "schema_version": receipt.schema_version,
        "release_id": receipt.release_id,
        "verified": receipt.verified,
    }
    receipt_path = path / "receipt.json"
    receipt_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with receipt_path.open("rb+") as handle:
        os.fsync(handle.fileno())


def create_operation_backup(context: InstallContext, operation_id: str) -> BackupReceipt:
    """Create a no-overwrite snapshot of both database and managed config.

    The final directory appears only after database integrity and config copying
    have completed.  Temporary directories are never considered backups.
    """
    operations_root, final_root = _operation_directory(context, operation_id)
    config_root = _configuration_root(context)
    release_id = _active_release(context)
    if not Path(context.database_path).is_file():
        raise BackupError("The installed database is unavailable.")
    if final_root.exists() or final_root.is_symlink():
        raise BackupError("The operation backup already exists.")
    operations_root.mkdir(parents=True, exist_ok=True)
    temporary = operations_root / f".{operation_id}.{uuid4().hex}.tmp"
    backup_id = operation_id
    try:
        temporary.mkdir()
        snapshot = create_database_snapshot(context.database_path, temporary / "database.sqlite")
        config_sha256 = _copy_configuration(config_root, temporary / "config")
        receipt = BackupReceipt(
            backup_id=backup_id,
            operation_id=operation_id,
            database_sha256=snapshot.sha256,
            config_sha256=config_sha256,
            schema_version=snapshot.schema_version,
            release_id=release_id,
            verified=snapshot.integrity_ok,
        )
        _write_receipt(temporary, receipt)
        os.replace(temporary, final_root)
        return receipt
    except (OSError, DatabaseSnapshotError) as exc:
        raise BackupError("Cannot create the mandatory operation backup.") from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


__all__ = ["BackupError", "create_operation_backup"]
