"""Tests for asynchronous desktop data loading."""

from dataclasses import FrozenInstanceError
import threading

import pytest

from picsyncra import desktop_data_loader, excel_utils
from picsyncra.desktop_data_loader import (
    DesktopDataLoader,
    DesktopDataSnapshot,
    load_desktop_data,
)


def _capture_schedule(scheduled, *args):
    """Capture both the legacy immediate and desired delayed scheduler shapes."""

    if len(args) == 1:
        delay_ms, callback = 0, args[0]
    else:
        delay_ms, callback = args
    scheduled.append((delay_ms, callback))
    return f"job-{len(scheduled)}"


def test_loader_posts_result_through_scheduler():
    caller_thread = threading.get_ident()
    scheduled = []
    received = []
    errors = []

    def schedule(*args):
        job_id = _capture_schedule(scheduled, *args)
        received.append(("schedule", threading.get_ident()))
        return job_id

    loader = DesktopDataLoader(
        load=lambda: DesktopDataSnapshot(lists={"NAZWY": ["ALFA"]}, entries=()),
        schedule=schedule,
    )

    assert loader.start(
        on_success=lambda snapshot: received.append(
            ("success", threading.get_ident(), snapshot)
        ),
        on_error=errors.append,
    )
    loader.join_for_test(timeout=1.0)

    assert received == [("schedule", caller_thread)]
    assert 0 < scheduled[0][0] <= 250
    scheduled.pop(0)[1]()
    assert received[1][0:2] == ("success", caller_thread)
    assert received[1][2].lists["NAZWY"] == ["ALFA"]


def test_loader_posts_error_through_scheduler():
    caller_thread = threading.get_ident()
    scheduled = []
    received = []
    scheduler_threads = []
    failure = RuntimeError("data unavailable")

    def fail_load():
        raise failure

    def schedule(*args):
        scheduler_threads.append(threading.get_ident())
        return _capture_schedule(scheduled, *args)

    loader = DesktopDataLoader(load=fail_load, schedule=schedule)

    assert loader.start(
        on_success=received.append,
        on_error=lambda error: received.append((threading.get_ident(), error)),
    )
    loader.join_for_test(timeout=1.0)

    assert received == []
    assert scheduler_threads == [caller_thread]
    assert len(scheduled) == 1
    assert 0 < scheduled[0][0] <= 250
    scheduled.pop(0)[1]()
    assert received == [(caller_thread, failure)]


def test_loader_reschedules_empty_poll_only_from_caller_thread():
    caller_thread = threading.get_ident()
    release_load = threading.Event()
    load_started = threading.Event()
    scheduled = []
    scheduler_threads = []
    received = []

    def slow_load():
        load_started.set()
        release_load.wait(timeout=1.0)
        return DesktopDataSnapshot(lists={}, entries=())

    def schedule(*args):
        scheduler_threads.append(threading.get_ident())
        return _capture_schedule(scheduled, *args)

    loader = DesktopDataLoader(load=slow_load, schedule=schedule)

    assert loader.start(on_success=received.append, on_error=received.append)
    assert load_started.wait(timeout=1.0)
    assert 0 < scheduled[0][0] <= 250
    scheduled.pop(0)[1]()

    assert received == []
    assert scheduler_threads == [caller_thread, caller_thread]

    release_load.set()
    loader.join_for_test(timeout=1.0)
    scheduled.pop(0)[1]()
    assert loader.start(on_success=lambda _snapshot: None, on_error=lambda _error: None)
    loader.join_for_test(timeout=1.0)
    scheduled.pop(0)[1]()
    assert len(received) == 1


def test_loader_rejects_second_start_while_load_is_running():
    release_load = threading.Event()
    load_started = threading.Event()
    scheduled = []

    def slow_load():
        load_started.set()
        release_load.wait(timeout=1.0)
        return DesktopDataSnapshot(lists={}, entries=())

    loader = DesktopDataLoader(
        load=slow_load,
        schedule=lambda *args: _capture_schedule(scheduled, *args),
    )

    assert loader.start(on_success=lambda _snapshot: None, on_error=lambda _error: None)
    assert load_started.wait(timeout=1.0)
    assert not loader.start(
        on_success=lambda _snapshot: None,
        on_error=lambda _error: None,
    )

    release_load.set()
    loader.join_for_test(timeout=1.0)


def test_slow_load_never_busy_polls_zero_delay_callbacks():
    release_load = threading.Event()
    load_started = threading.Event()
    scheduled = []

    def slow_load():
        load_started.set()
        release_load.wait(timeout=1.0)
        return DesktopDataSnapshot(lists={}, entries=())

    loader = DesktopDataLoader(
        load=slow_load,
        schedule=lambda *args: _capture_schedule(scheduled, *args),
    )

    assert loader.start(on_success=lambda _value: None, on_error=lambda _error: None)
    assert load_started.wait(timeout=1.0)
    zero_delay_callbacks = 0
    while scheduled and scheduled[0][0] == 0 and zero_delay_callbacks < 50:
        _delay, callback = scheduled.pop(0)
        callback()
        zero_delay_callbacks += 1

    release_load.set()
    loader.join_for_test(timeout=1.0)

    assert zero_delay_callbacks == 0
    assert scheduled
    assert 0 < scheduled[0][0] <= 250


def test_cancel_stops_polling_and_discards_late_worker_result():
    release_load = threading.Event()
    load_started = threading.Event()
    scheduled = []
    cancelled = []
    received = []

    def slow_load():
        load_started.set()
        release_load.wait(timeout=1.0)
        return DesktopDataSnapshot(lists={}, entries=())

    loader = DesktopDataLoader(
        load=slow_load,
        schedule=lambda *args: _capture_schedule(scheduled, *args),
    )
    loader._cancel_schedule = cancelled.append

    assert loader.start(on_success=received.append, on_error=received.append)
    assert load_started.wait(timeout=1.0)
    getattr(loader, "cancel", lambda: None)()
    release_load.set()
    loader.join_for_test(timeout=1.0)

    assert cancelled == ["job-1"]
    assert received == []


def test_first_run_excel_failure_is_delivered_without_worker_ui_calls(
    monkeypatch,
    tmp_path,
):
    workbook_path = tmp_path / "missing" / "lists.xlsx"
    failure = OSError("cannot create workbook")
    ui_calls = []
    errors = []
    scheduled = []

    def fail_save(_workbook, _path):
        raise failure

    def forbidden_ui(*args, **kwargs):
        ui_calls.append((args, kwargs, threading.get_ident()))

    monkeypatch.setattr(excel_utils, "_active_sqlite_store", lambda: None)
    monkeypatch.setattr(
        excel_utils.settings,
        "LISTS_WORKBOOK_PATH",
        str(workbook_path),
    )
    monkeypatch.setattr(excel_utils.Workbook, "save", fail_save)
    monkeypatch.setattr(excel_utils.messagebox, "showerror", forbidden_ui)
    monkeypatch.setattr(excel_utils, "log_error_loc", forbidden_ui)
    excel_utils.clear_excel_snapshot_cache()

    loader = DesktopDataLoader(
        load=load_desktop_data,
        schedule=lambda *args: _capture_schedule(scheduled, *args),
    )
    assert loader.start(on_success=lambda _value: None, on_error=errors.append)
    loader.join_for_test(timeout=1.0)
    scheduled.pop(0)[1]()

    assert ui_calls == []
    assert errors == [failure]


def test_load_desktop_data_returns_frozen_complete_snapshot(monkeypatch):
    payload = {
        "NAZWY": ["ALFA"],
        "ENTRIES": {"590": {"NAZWA": "ALFA"}},
        "__ENTRY_RECORDS__": [{"EAN": "590", "NAZWA": "ALFA"}],
    }
    monkeypatch.setattr(
        desktop_data_loader,
        "prepare_excel_lists",
        lambda **_kwargs: payload,
    )

    snapshot = load_desktop_data()

    assert snapshot.lists is payload
    assert snapshot.entries == ({"EAN": "590", "NAZWA": "ALFA"},)
    with pytest.raises(FrozenInstanceError):
        snapshot.entries = ()
