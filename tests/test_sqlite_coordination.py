"""Tests for cross-process handover markers and in-process coordination."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import subprocess
import sys

import picsyncra.sqlite_coordination as sqlite_coordination
import pytest

from picsyncra.sqlite_coordination import (
    RetiredDatabaseError,
    _marker_path,
    _database_file_lock,
    database_activity,
    database_maintenance,
    clear_retired_database_marker,
    retire_database,
)


def test_maintenance_marker_blocks_another_process_style_activity(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite"

    with database_maintenance(database_path):
        assert _marker_path(database_path).is_file()
        with pytest.raises(RetiredDatabaseError):
            with database_activity(database_path):
                pass

    assert not _marker_path(database_path).exists()


def test_retired_database_keeps_its_marker(tmp_path: Path) -> None:
    database_path = tmp_path / "retired.sqlite"

    with database_maintenance(database_path):
        retire_database(database_path)

    assert _marker_path(database_path).is_file()
    with pytest.raises(RetiredDatabaseError):
        with database_activity(database_path):
            pass


def test_completed_handover_marker_can_be_removed_after_source_is_gone(tmp_path: Path) -> None:
    database_path = tmp_path / "retired.sqlite"
    _marker_path(database_path).write_text("retired", encoding="ascii")

    clear_retired_database_marker(database_path)

    assert not _marker_path(database_path).exists()


def test_failed_marker_update_preserves_the_previous_handover_state(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "legacy.sqlite"
    _marker_path(database_path).write_text("active", encoding="ascii")

    def fail_replace(_source, _target):
        raise OSError("marker volume unavailable")

    monkeypatch.setattr(sqlite_coordination.os, "replace", fail_replace)

    with pytest.raises(OSError, match="marker volume unavailable"):
        sqlite_coordination._set_marker(database_path, "retired")

    assert _marker_path(database_path).read_text(encoding="ascii") == "active"


def test_failed_exclusive_lock_does_not_leave_an_active_marker(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "legacy.sqlite"

    def fail_lock(_path, *, exclusive: bool):
        assert exclusive is True
        raise OSError("database still busy")

    monkeypatch.setattr(sqlite_coordination, "_database_file_lock", fail_lock)

    with pytest.raises(OSError, match="database still busy"):
        with database_maintenance(database_path):
            pass

    assert not _marker_path(database_path).exists()


def test_external_process_cannot_start_activity_while_database_is_handed_over(
    tmp_path: Path,
) -> None:
    """The OS-level lock also protects against the separate web/desktop process."""

    database_path = tmp_path / "legacy.sqlite"
    sqlite3.connect(database_path).close()
    project_root = Path(__file__).resolve().parents[1]
    program = """
from pathlib import Path
import sys
from picsyncra.sqlite_coordination import RetiredDatabaseError, database_activity

try:
    with database_activity(Path(sys.argv[1])):
        pass
except RetiredDatabaseError:
    raise SystemExit(0)
raise SystemExit(1)
"""

    with _database_file_lock(database_path, exclusive=True):
        completed = subprocess.run(
            [sys.executable, "-c", program, str(database_path)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr


def test_external_process_can_join_normal_database_activity(tmp_path: Path) -> None:
    """The handover lock must not turn normal desktop/web reads into a conflict."""

    database_path = tmp_path / "legacy.sqlite"
    sqlite3.connect(database_path).close()
    project_root = Path(__file__).resolve().parents[1]
    program = """
from pathlib import Path
import sys
from picsyncra.sqlite_coordination import RetiredDatabaseError, database_activity

try:
    with database_activity(Path(sys.argv[1])):
        pass
except RetiredDatabaseError:
    raise SystemExit(1)
raise SystemExit(0)
"""

    with _database_file_lock(database_path, exclusive=False):
        completed = subprocess.run(
            [sys.executable, "-c", program, str(database_path)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr
