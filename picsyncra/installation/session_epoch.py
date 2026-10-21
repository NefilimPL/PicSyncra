"""Installed-session epoch kept outside the restorable application database."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from .contracts import InstallContext


class SessionEpochError(RuntimeError):
    """The durable session epoch cannot be read or advanced safely."""


def _path(context: InstallContext) -> Path:
    return Path(context.state_root) / "session-epoch.json"


def _read(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise SessionEpochError("The installed session epoch is unreadable.") from exc
    value = payload.get("epoch") if isinstance(payload, dict) and set(payload) == {"schema", "epoch"} and payload.get("schema") == 1 else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SessionEpochError("The installed session epoch is invalid.")
    return value


def read_session_epoch(context: InstallContext) -> int:
    """Return the epoch which installed WEB sessions must carry."""
    return _read(_path(context))


def advance_session_epoch(context: InstallContext) -> int:
    """Durably invalidate existing installed WEB sessions after maintenance."""
    path = _path(context)
    current = _read(path)
    next_epoch = current + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump({"schema": 1, "epoch": next_epoch}, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise SessionEpochError("The installed session epoch cannot be saved.") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return next_epoch


__all__ = ["SessionEpochError", "advance_session_epoch", "read_session_epoch"]
