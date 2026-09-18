"""Atomic active-version pointer for a trusted installed program root."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from .contracts import InstallContext


class ActiveReleaseError(RuntimeError):
    """The active release marker or selected version bundle is unsafe."""


def _release_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ActiveReleaseError("The active release identifier is invalid.")
    return value


def _root(context: InstallContext) -> Path:
    root = Path(context.program_root)
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise ActiveReleaseError("The installed program root is unavailable.") from exc
    if root.is_symlink() or not resolved.is_dir():
        raise ActiveReleaseError("The installed program root is unsafe.")
    return resolved


def _payload(context: InstallContext, path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ActiveReleaseError("The active release marker is unreadable.") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "installation_id", "release_id"}
        or value.get("schema") != 1
        or value.get("installation_id") != context.installation_id
    ):
        raise ActiveReleaseError("The active release marker is invalid.")
    _release_id(value.get("release_id"))
    return value


def read_active_release(context: InstallContext) -> int:
    """Read the active bundle identifier without accepting a foreign marker."""
    root = _root(context)
    return _release_id(_payload(context, root / "active.json").get("release_id"))


def activate_release(context: InstallContext, release_id: int) -> int:
    """Atomically point one installation at an existing, non-link version bundle."""
    release_id = _release_id(release_id)
    root = _root(context)
    bundle = root / "versions" / str(release_id)
    try:
        resolved_bundle = bundle.resolve(strict=True)
    except OSError as exc:
        raise ActiveReleaseError("The selected version bundle is unavailable.") from exc
    if bundle.is_symlink() or not resolved_bundle.is_dir():
        raise ActiveReleaseError("The selected version bundle is unsafe.")
    try:
        resolved_bundle.relative_to(root / "versions")
    except ValueError as exc:
        raise ActiveReleaseError("The selected version bundle is outside the installation.") from exc
    active = root / "active.json"
    # Validate a pre-existing marker before replacing it, which stops a helper
    # from silently taking ownership of another installation's directory.
    if active.exists():
        _payload(context, active)
    temporary = root / f".active.{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(
                {"schema": 1, "installation_id": context.installation_id, "release_id": release_id},
                handle,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, active)
    except OSError as exc:
        raise ActiveReleaseError("Cannot activate the selected version bundle.") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return release_id


__all__ = ["ActiveReleaseError", "activate_release", "read_active_release"]
