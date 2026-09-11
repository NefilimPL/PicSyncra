"""Lifetime management for desktop FTP preview files."""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from pathlib import Path


class FtpTempManager:
    """Create and safely remove request-scoped FTP preview directories."""

    DIRECTORY_PREFIX = "picsyncra_ftp_"

    def __init__(self, root: str, *, stale_after_seconds: float = 24 * 60 * 60):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.stale_after_seconds = float(stale_after_seconds)
        self._active_paths: set[Path] = set()
        self._lock = threading.Lock()

    def create_request_dir(self, request_id: object) -> str:
        """Create and register a unique preview directory for one lookup."""

        request_text = "".join(
            character if character.isascii() and character.isalnum() else "_"
            for character in str(request_id)
        ).strip("_")
        if not request_text:
            request_text = "request"
        candidate = self.root / (
            f"{self.DIRECTORY_PREFIX}{request_text}_{uuid.uuid4().hex}"
        )
        candidate.mkdir()
        resolved = candidate.resolve()
        with self._lock:
            self._active_paths.add(resolved)
        return str(resolved)

    def release(self, path: str) -> bool:
        """Remove one managed directory; reject arbitrary caller-provided paths."""

        candidate = Path(path).resolve()
        if not self._is_managed_directory(candidate):
            return False
        with self._lock:
            self._active_paths.discard(candidate)
        try:
            shutil.rmtree(candidate)
        except OSError:
            return False
        return True

    def cleanup_stale(self, *, now: float | None = None) -> int:
        """Remove inactive managed directories whose TTL has elapsed."""

        checked_at = time.time() if now is None else float(now)
        with self._lock:
            active_paths = set(self._active_paths)
        removed = 0
        try:
            candidates = list(self.root.iterdir())
        except OSError:
            return removed
        for candidate in candidates:
            resolved = candidate.resolve()
            if (
                resolved in active_paths
                or not self._is_managed_directory(resolved)
                or candidate.is_symlink()
            ):
                continue
            try:
                is_stale = (
                    checked_at - candidate.stat().st_mtime
                    > self.stale_after_seconds
                )
            except OSError:
                continue
            if is_stale and self.release(str(resolved)):
                removed += 1
        return removed

    def close(self) -> None:
        """Release every currently registered request directory."""

        with self._lock:
            active_paths = tuple(self._active_paths)
        for path in active_paths:
            self.release(str(path))

    def _is_managed_directory(self, candidate: Path) -> bool:
        return (
            candidate.parent == self.root
            and candidate.name.startswith(self.DIRECTORY_PREFIX)
            and candidate.is_dir()
            and not candidate.is_symlink()
        )
