"""Tests for process safety boundaries of the offline migrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from picsyncra.offline_legacy_sqlite_migrator import OfflineMigrationError
from picsyncra import offline_migrator_processes
from picsyncra.offline_migrator_processes import ManagedProcess, stop_managed_processes


def test_stop_refuses_matching_name_outside_selected_application_root(
    tmp_path: Path,
) -> None:
    """A same-named EXE in a different folder is never a migration target."""

    app_root = tmp_path / "application"
    foreign = tmp_path / "other" / "PicSyncra-WEB.exe"
    app_root.mkdir()
    foreign.parent.mkdir()
    terminated: list[tuple[int, bool]] = []

    stop_managed_processes(
        app_root,
        notify=lambda _event: None,
        list_processes=lambda: (ManagedProcess(123, foreign),),
        terminate_process=lambda process, force: terminated.append((process.pid, force)) or True,
        process_is_running=lambda _pid: False,
        sleep=lambda _seconds: None,
    )

    assert terminated == []


def test_stop_ends_only_verified_executable_inside_selected_root(tmp_path: Path) -> None:
    """The stop action reaches a positively identified application executable."""

    app_root = tmp_path / "application"
    executable = app_root / "PicSyncra-WEB.exe"
    app_root.mkdir()
    terminated: list[tuple[int, bool]] = []

    stop_managed_processes(
        app_root,
        notify=lambda _event: None,
        list_processes=lambda: (ManagedProcess(456, executable),),
        terminate_process=lambda process, force: terminated.append((process.pid, force)) or True,
        process_is_running=lambda _pid: False,
        sleep=lambda _seconds: None,
    )

    assert terminated == [(456, False)]


def test_stop_discovers_recorded_process_when_no_test_list_is_supplied(
    tmp_path: Path, monkeypatch
) -> None:
    """The normal migrator path uses recorded PIDs rather than an empty list."""

    app_root = tmp_path / "application"
    executable = app_root / "PicSyncra-WEB.exe"
    app_root.mkdir()
    terminated: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        offline_migrator_processes,
        "find_managed_processes",
        lambda _root: (ManagedProcess(457, executable),),
    )

    stop_managed_processes(
        app_root,
        notify=lambda _event: None,
        terminate_process=lambda process, force: terminated.append((process.pid, force)) or True,
        process_is_running=lambda _pid: False,
        sleep=lambda _seconds: None,
    )

    assert terminated == [(457, False)]


def test_stop_blocks_when_candidate_process_cannot_be_verified(tmp_path: Path) -> None:
    """An unknown candidate must stop migration rather than risking a kill."""

    app_root = tmp_path / "application"
    app_root.mkdir()

    with pytest.raises(OfflineMigrationError) as error:
        stop_managed_processes(
            app_root,
            notify=lambda _event: None,
            list_processes=lambda: (ManagedProcess(789, None),),
            terminate_process=lambda _process, _force: True,
            process_is_running=lambda _pid: True,
            sleep=lambda _seconds: None,
        )

    assert error.value.code == "process_unverified"


def test_stop_escalates_only_same_verified_pid_when_first_stop_does_not_exit(
    tmp_path: Path,
) -> None:
    """Forced termination cannot expand from the verified PID to another process."""

    app_root = tmp_path / "application"
    executable = app_root / "PicOrgFTP-WEB.exe"
    app_root.mkdir()
    terminated: list[tuple[int, bool]] = []
    running = iter((True, False))

    stop_managed_processes(
        app_root,
        notify=lambda _event: None,
        list_processes=lambda: (ManagedProcess(999, executable),),
        terminate_process=lambda process, force: terminated.append((process.pid, force)) or True,
        process_is_running=lambda _pid: next(running),
        sleep=lambda _seconds: None,
        wait_timeout=0,
    )

    assert terminated == [(999, False), (999, True)]
