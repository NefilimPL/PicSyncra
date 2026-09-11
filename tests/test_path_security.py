from __future__ import annotations

from pathlib import Path

import pytest

from picsyncra.path_security import (
    PathSecurityError,
    build_child_path,
    resolve_path_within_roots,
)


def test_resolve_path_within_roots_rejects_traversal(tmp_path: Path) -> None:
    """A normalized parent segment must not escape the trusted root."""
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(PathSecurityError):
        resolve_path_within_roots(root / ".." / "outside.txt", [root])


def test_build_child_path_rejects_absolute_and_nested_segments(tmp_path: Path) -> None:
    """Request-derived child names must represent exactly one safe segment."""
    with pytest.raises(PathSecurityError):
        build_child_path(tmp_path, "..", "secret.txt")
    with pytest.raises(PathSecurityError):
        build_child_path(tmp_path, "nested/secret.txt")
    with pytest.raises(PathSecurityError):
        build_child_path(tmp_path, str(tmp_path / "secret.txt"))


def test_resolve_path_within_roots_rejects_symlink_escape(tmp_path: Path) -> None:
    """A path below a trusted root cannot escape through a symbolic link."""
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")

    with pytest.raises(PathSecurityError):
        resolve_path_within_roots(link / "secret.txt", [root])


def test_build_child_path_keeps_valid_child_within_root(tmp_path: Path) -> None:
    """A generated one-segment filename remains usable under its root."""
    root = tmp_path / "root"
    root.mkdir()

    assert build_child_path(root, "upload_123.jpg") == root / "upload_123.jpg"
