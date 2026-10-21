"""Durable context for a restart that is completed by the controller."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from pathlib import Path
from uuid import uuid4

from .contracts import InstallContext
from .update_helper import activate_release


class RestartHandoffError(RuntimeError):
    """The controller cannot safely complete the pending restart."""


@dataclass(frozen=True)
class RestartHandoff:
    operation_id: str
    previous_release: int
    target_release: int
    previous_ocr_marker: bytes | None


def _path(context: InstallContext) -> Path:
    return context.state_root / "restart-handoff.json"


def _validate_release(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RestartHandoffError("Restart handoff has an invalid release.")
    return value


def _validate_operation(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 128 or any(part in value for part in "\\/\x00"):
        raise RestartHandoffError("Restart handoff has an invalid operation.")
    return value


def create_restart_handoff(
    context: InstallContext,
    *,
    operation_id: str,
    previous_release: int,
    target_release: int,
    previous_ocr_marker: bytes | None,
) -> RestartHandoff:
    """Persist rollback data before asking the controller to stop WEB."""

    handoff = RestartHandoff(
        operation_id=_validate_operation(operation_id),
        previous_release=_validate_release(previous_release),
        target_release=_validate_release(target_release),
        previous_ocr_marker=previous_ocr_marker,
    )
    if previous_ocr_marker is not None and not isinstance(previous_ocr_marker, bytes):
        raise RestartHandoffError("Restart handoff has an invalid OCR marker.")
    target = _path(context)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    payload = {
        "schema": 1,
        "operation_id": handoff.operation_id,
        "previous_release": handoff.previous_release,
        "target_release": handoff.target_release,
        "previous_ocr_marker": (
            None
            if handoff.previous_ocr_marker is None
            else base64.b64encode(handoff.previous_ocr_marker).decode("ascii")
        ),
    }
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return handoff


def read_restart_handoff(context: InstallContext) -> RestartHandoff | None:
    target = _path(context)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != {
            "schema", "operation_id", "previous_release", "target_release", "previous_ocr_marker"
        } or payload["schema"] != 1:
            raise ValueError
        encoded_marker = payload["previous_ocr_marker"]
        if encoded_marker is not None and not isinstance(encoded_marker, str):
            raise ValueError
        marker = None if encoded_marker is None else base64.b64decode(encoded_marker, validate=True)
        return RestartHandoff(
            operation_id=_validate_operation(payload["operation_id"]),
            previous_release=_validate_release(payload["previous_release"]),
            target_release=_validate_release(payload["target_release"]),
            previous_ocr_marker=marker,
        )
    except (OSError, ValueError, TypeError) as exc:
        raise RestartHandoffError("Restart handoff is unreadable.") from exc


def clear_restart_handoff(context: InstallContext, operation_id: str) -> None:
    handoff = read_restart_handoff(context)
    if handoff is None:
        return
    if handoff.operation_id != operation_id:
        raise RestartHandoffError("Restart handoff belongs to another operation.")
    _path(context).unlink(missing_ok=True)


def restore_restart_handoff(context: InstallContext, handoff: RestartHandoff) -> None:
    """Restore the active release and OCR selection without touching backups."""

    activate_release(context, handoff.previous_release)
    marker = context.program_root / "components" / "ocr" / "active.json"
    if marker.is_symlink():
        raise RestartHandoffError("The OCR active marker is unsafe.")
    if handoff.previous_ocr_marker is None:
        marker.unlink(missing_ok=True)
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_name(f".{marker.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(handoff.previous_ocr_marker)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "RestartHandoff",
    "RestartHandoffError",
    "clear_restart_handoff",
    "create_restart_handoff",
    "read_restart_handoff",
    "restore_restart_handoff",
]
