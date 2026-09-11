"""Canonical path containment helpers for trusted filesystem roots."""

from __future__ import annotations

import ntpath
import os
from collections.abc import Iterable
from pathlib import Path


class PathSecurityError(ValueError):
    """Raised when a path is not safe to use below a trusted root."""


def _canonical_path(path: str | os.PathLike[str]) -> str:
    canonical = os.path.realpath(os.path.abspath(os.fspath(path)))
    if canonical.startswith("\\\\") or (len(canonical) >= 2 and canonical[1] == ":"):
        return ntpath.normcase(canonical)
    return os.path.normcase(canonical)


def resolve_path_within_roots(
    path: str | os.PathLike[str],
    roots: Iterable[str | os.PathLike[str]],
) -> Path:
    """Return a canonical path only when it is contained by a trusted root."""
    target = _canonical_path(path)
    for root in roots:
        trusted_root = _canonical_path(root)
        trusted_prefix = trusted_root if trusted_root.endswith(os.sep) else trusted_root + os.sep
        if target != trusted_root and not target.startswith(trusted_prefix):
            continue
        return Path(target)
    raise PathSecurityError("path is outside trusted roots")


def build_child_path(root: str | os.PathLike[str], *segments: object) -> Path:
    """Build a canonical child path from individual non-path segments only."""
    safe_segments: list[str] = []
    for segment in segments:
        value = str(segment or "")
        part = Path(value)
        if (
            not value
            or part.is_absolute()
            or len(part.parts) != 1
            or part.name in {"", ".", ".."}
        ):
            raise PathSecurityError("unsafe path segment")
        safe_segments.append(part.name)
    if not safe_segments:
        raise PathSecurityError("missing path segment")
    return resolve_path_within_roots(os.path.join(os.fspath(root), *safe_segments), [root])
