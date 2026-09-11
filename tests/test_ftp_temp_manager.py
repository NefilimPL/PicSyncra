from __future__ import annotations

import os
from pathlib import Path

from picsyncra.services.ftp_temp_manager import FtpTempManager


def test_release_refuses_path_outside_temp_root(tmp_path: Path) -> None:
    manager = FtpTempManager(str(tmp_path / "managed"))
    outside = tmp_path / "outside"
    outside.mkdir()

    assert manager.release(str(outside)) is False
    assert outside.exists()


def test_cleanup_stale_removes_only_inactive_managed_directories(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    manager = FtpTempManager(str(managed_root), stale_after_seconds=24 * 60 * 60)
    inactive = managed_root / "picsyncra_ftp_orphan"
    inactive.mkdir()
    active = Path(manager.create_request_dir("active"))
    similar_prefix = managed_root / "picsyncra_ftpish_orphan"
    similar_prefix.mkdir()
    old_time = 1_000_000.0
    for path in (inactive, active, similar_prefix):
        os.utime(path, (old_time, old_time))

    removed = manager.cleanup_stale(now=old_time + 24 * 60 * 60 + 1)

    assert removed == 1
    assert inactive.exists() is False
    assert active.exists() is True
    assert similar_prefix.exists() is True
