from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import threading
import time

import pytest

from picsyncra.resource_monitor import ResourceMonitor


MIB = 1024 * 1024
SETTINGS = {
    "cpu_percent_threshold": 25,
    "memory_percent_threshold": 20,
    "io_mib_per_second_threshold": 8,
}
CONTEXT = {"active_jobs": 0, "queued_jobs": 0, "active_clients": 0}


class _ReaderSequence:
    def __init__(
        self,
        *,
        cpu: list[float],
        memory: list[float] | None = None,
        io: list[float] | None = None,
        host: dict[str, object] | None = None,
    ) -> None:
        count = len(cpu)
        self._cpu = iter(cpu)
        self._memory = iter(memory if memory is not None else [2.0] * count)
        self._io = iter(io if io is not None else [0.0] * count)
        self._host = host or {
            "cpu_percent": 95.0,
            "memory_percent": 95.0,
            "memory_used_bytes": 950,
            "memory_total_bytes": 1000,
            "disk_busy_percent": 95.0,
        }

    def read_host(self) -> dict[str, object]:
        return dict(self._host)

    def read_backend(self, _worker_pid: int | None = None) -> dict[str, object]:
        return {
            "cpu_percent": next(self._cpu),
            "memory_percent": next(self._memory),
            "memory_working_set_bytes": 20,
            "memory_private_bytes": 10,
            "disk_read_bytes_per_second": 0.0,
            "disk_write_bytes_per_second": next(self._io),
            "disk_io_bytes_per_second": 0.0,
        }


class _IoReaderSequence(_ReaderSequence):
    def read_backend(self, _worker_pid: int | None = None) -> dict[str, object]:
        sample = super().read_backend(_worker_pid)
        sample["disk_io_bytes_per_second"] = sample["disk_write_bytes_per_second"]
        return sample


def _record_event(
    events: list[tuple[str, str, dict[str, object]]],
    severity: str,
    event_type: str,
    details: dict[str, object],
) -> bool:
    events.append((severity, event_type, details))
    return True


def _monitor(
    readers: object,
    events: list[tuple[str, str, dict[str, object]]],
    *,
    settings: dict[str, object] | None = None,
) -> ResourceMonitor:
    return ResourceMonitor(
        settings_provider=lambda: dict(settings or SETTINGS),
        context_provider=lambda: dict(CONTEXT),
        event_emitter=lambda severity, event_type, details: _record_event(
            events, severity, event_type, details
        ),
        wall_clock=lambda: 1_700_000_000.0,
        readers=readers,
    )


def test_monitor_registers_external_ocr_worker_pid_for_backend_sampling() -> None:
    class _PidReader(_ReaderSequence):
        def __init__(self) -> None:
            super().__init__(cpu=[1])
            self.worker_pids: list[int | None] = []

        def read_backend(self, worker_pid: int | None = None) -> dict[str, object]:
            self.worker_pids.append(worker_pid)
            return super().read_backend(worker_pid)

    events: list[tuple[str, str, dict[str, object]]] = []
    reader = _PidReader()
    monitor = _monitor(reader, events)

    monitor.register_ocr_worker_pid(4321)
    snapshot = monitor.sample_once()

    assert reader.worker_pids == [4321]
    assert snapshot["backend"]["ocr_worker_registered"] is True
    assert snapshot["backend"]["ocr_worker_pid"] == 4321


def test_monitor_emits_one_alert_after_two_backend_cpu_breaches() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(
        _ReaderSequence(cpu=[24, 28, 31, 5, 6]),
        events,
    )

    monitor.sample_once()
    monitor.sample_once()
    assert events == []
    monitor.sample_once()

    assert events[0][0:2] == ("warning", "backend.resource_high")
    assert events[0][2]["trigger"]["metric"] == "cpu_percent"
    assert json.loads(json.dumps(events[0][2])) == events[0][2]


def test_monitor_preserves_explicit_unavailable_host_disk_metric() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(
        _ReaderSequence(
            cpu=[1],
            host={
                "cpu_percent": 1.0,
                "memory_percent": 2.0,
                "memory_used_bytes": 20,
                "memory_total_bytes": 1000,
                "disk_busy_percent": {"available": False},
            },
        ),
        events,
    )

    snapshot = monitor.sample_once()

    assert snapshot["host"]["disk_busy_percent"] == {"available": False}
    assert events == []


def test_host_only_load_never_triggers_backend_event() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(_ReaderSequence(cpu=[1, 2, 3]), events)

    for _ in range(3):
        monitor.sample_once()

    assert events == []


@pytest.mark.parametrize(
    ("readers", "metric"),
    [
        (_ReaderSequence(cpu=[1, 1], memory=[21, 22]), "memory_percent"),
        (_IoReaderSequence(cpu=[1, 1], io=[9 * MIB, 10 * MIB]), "disk_io_bytes_per_second"),
    ],
)
def test_memory_and_io_thresholds_trigger_independently(
    readers: object, metric: str
) -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(readers, events)

    monitor.sample_once()
    monitor.sample_once()

    assert len(events) == 1
    assert events[0][2]["trigger"]["metric"] == metric


def test_simultaneous_metric_confirmations_emit_one_event_per_metric() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(
        _ReaderSequence(cpu=[30, 31], memory=[21, 22]),
        events,
    )

    monitor.sample_once()
    monitor.sample_once()

    assert {event[2]["trigger"]["metric"] for event in events} == {
        "cpu_percent",
        "memory_percent",
    }


def test_real_test_ack_is_set_only_by_requested_detector_latch_transition() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []

    class AckEvent:
        def __init__(self) -> None:
            self.ready = False

        def is_set(self) -> bool:
            return self.ready

        def set(self) -> None:
            self.ready = True

    monitor = _monitor(_ReaderSequence(cpu=[30, 31]), events)
    ack = AckEvent()
    monitor._worker_process = object()
    monitor._worker_pid = 43210
    monitor._worker_kind = "cpu"
    monitor._worker_generation = object()
    monitor._worker_detection_event = ack

    first = monitor.sample_once()
    assert ack.is_set() is False
    assert events == []
    assert "worker_detection_event" not in json.dumps(first)

    second = monitor.sample_once()
    assert ack.is_set() is True
    assert len(events) == 1
    assert events[0][2]["trigger"]["metric"] == "cpu_percent"
    assert "worker_detection_event" not in json.dumps(second)


def test_unrelated_metric_alert_does_not_ack_registered_real_test() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []

    class AckEvent:
        ready = False

        def is_set(self) -> bool:
            return self.ready

        def set(self) -> None:
            self.ready = True

    monitor = _monitor(_ReaderSequence(cpu=[30, 31]), events)
    ack = AckEvent()
    monitor._worker_process = object()
    monitor._worker_pid = 43211
    monitor._worker_kind = "disk"
    monitor._worker_generation = object()
    monitor._worker_detection_event = ack

    monitor.sample_once()
    monitor.sample_once()

    assert events[0][2]["trigger"]["metric"] == "cpu_percent"
    assert ack.is_set() is False


def test_sample_for_replaced_worker_cannot_mutate_state_or_ack_new_worker() -> None:
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    class AckEvent:
        def __init__(self) -> None:
            self.ready = False

        def is_set(self) -> bool:
            return self.ready

        def set(self) -> None:
            self.ready = True

    class BlockingReader:
        def read_host(self) -> dict[str, object]:
            return {
                "cpu_percent": 1,
                "memory_percent": 2,
                "memory_used_bytes": 20,
                "memory_total_bytes": 1000,
                "disk_busy_percent": 1,
            }

        def read_backend(self, _worker_pid: int | None = None) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 2:
                entered.set()
                assert release.wait(2.0)
            cpu_values = [0, 30, 31, 32]
            return {
                "cpu_percent": cpu_values[calls - 1],
                "memory_percent": 2,
                "memory_working_set_bytes": 20,
                "memory_private_bytes": 10,
                "disk_read_bytes_per_second": 0,
                "disk_write_bytes_per_second": 0,
                "disk_io_bytes_per_second": 0,
            }

    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(BlockingReader(), events)
    monitor.sample_once()
    ack_a = AckEvent()
    ack_b = AckEvent()
    process_a = object()
    process_b = object()
    with monitor._state_lock:
        monitor._worker_process = process_a
        monitor._worker_pid = 1111
        monitor._worker_kind = "cpu"
        monitor._worker_generation = object()
        monitor._worker_detection_event = ack_a

    sampler = threading.Thread(target=monitor.sample_once)
    sampler.start()
    assert entered.wait(1.0)
    with monitor._state_lock:
        monitor._worker_process = process_b
        monitor._worker_pid = 2222
        monitor._worker_kind = "cpu"
        monitor._worker_generation = object()
        monitor._worker_detection_event = ack_b
        monitor._set_cached_worker_registration_locked(True)
    release.set()
    sampler.join(2.0)

    assert not sampler.is_alive()
    assert ack_a.is_set() is False
    assert ack_b.is_set() is False
    stale_rejected = monitor.latest_public_snapshot()
    assert stale_rejected["backend"]["cpu_percent"] == 0
    assert stale_rejected["backend"]["test_worker_registered"] is True
    assert stale_rejected["detector"]["pending_metrics"] == []
    assert events == []

    monitor.sample_once()
    assert ack_b.is_set() is False
    assert events == []
    monitor.sample_once()

    assert ack_b.is_set() is True
    assert len(events) == 1
    assert events[0][2]["trigger"]["metric"] == "cpu_percent"


def test_latch_resets_only_after_two_consecutive_normal_samples() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(
        _ReaderSequence(cpu=[30, 31, 5, 30, 31, 5, 6, 30, 31]),
        events,
    )

    for _ in range(5):
        monitor.sample_once()
    assert len(events) == 1
    assert monitor.latest_public_snapshot()["detector"]["latched_metrics"] == [
        "cpu_percent"
    ]

    for _ in range(4):
        monitor.sample_once()

    assert len(events) == 2


def test_unavailable_sample_breaks_high_and_recovery_streaks() -> None:
    unavailable = {"available": False}
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(
        _ReaderSequence(cpu=[30, unavailable, 30, 31, 5, unavailable, 5, 6]),
        events,
    )

    for _ in range(3):
        monitor.sample_once()
    assert events == []

    monitor.sample_once()
    assert len(events) == 1
    for _ in range(3):
        monitor.sample_once()
    assert monitor.latest_public_snapshot()["detector"]["latched_metrics"] == [
        "cpu_percent"
    ]

    monitor.sample_once()
    assert monitor.latest_public_snapshot()["detector"]["latched_metrics"] == []


def test_diagnostic_history_is_capped_at_twelve_samples() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(
        _ReaderSequence(cpu=[30, 31] + [5] * 12 + [30, 31]),
        events,
    )

    for _ in range(16):
        monitor.sample_once()

    history = events[-1][2]["history"]
    assert len(history) == ResourceMonitor.HISTORY_SIZE == 12
    assert history[-1]["backend"]["cpu_percent"] == 31


def test_safe_simulation_emits_labelled_serializable_diagnostic() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(_ReaderSequence(cpu=[1]), events)
    monitor.sample_once()

    result = monitor.record_safe_simulation()

    assert result["ok"] is True
    assert result["test_mode"] == "safe"
    assert events[-1][0:2] == ("info", "backend.resource_test")
    assert events[-1][2]["test_mode"] == "safe"
    json.dumps(events[-1][2])


@pytest.mark.parametrize(
    "failure_mode", ["returns_false", "returns_none", "returns_zero", "raises"]
)
def test_safe_simulation_reports_event_persistence_failure(
    failure_mode: str,
) -> None:
    def failing_emitter(
        _severity: str, _event_type: str, _details: dict[str, object]
    ) -> object:
        if failure_mode == "raises":
            raise OSError("observability unavailable")
        if failure_mode == "returns_none":
            return None
        if failure_mode == "returns_zero":
            return 0
        return False

    monitor = ResourceMonitor(
        settings_provider=lambda: dict(SETTINGS),
        context_provider=lambda: dict(CONTEXT),
        event_emitter=failing_emitter,
        readers=_ReaderSequence(cpu=[1]),
    )

    result = monitor.record_safe_simulation()

    assert result == {
        "ok": False,
        "test_mode": "safe",
        "status": "persistence_failed",
        "resources": monitor.latest_public_snapshot(),
    }


@pytest.mark.parametrize("failure_mode", ["returns_false", "raises"])
def test_ordinary_resource_sampling_remains_nonfatal_when_event_emission_fails(
    failure_mode: str,
) -> None:
    def failing_emitter(
        _severity: str, _event_type: str, _details: dict[str, object]
    ) -> bool:
        if failure_mode == "raises":
            raise OSError("observability unavailable")
        return False

    monitor = ResourceMonitor(
        settings_provider=lambda: dict(SETTINGS),
        context_provider=lambda: dict(CONTEXT),
        event_emitter=failing_emitter,
        readers=_ReaderSequence(cpu=[24, 28, 31]),
    )

    monitor.sample_once()
    monitor.sample_once()
    snapshot = monitor.sample_once()

    assert snapshot["detector"]["latched_metrics"] == ["cpu_percent"]


def test_real_cpu_test_uses_temporary_threshold_when_production_threshold_exceeds_cap() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(
        _ReaderSequence(cpu=[0, 0]),
        events,
        settings={**SETTINGS, "cpu_percent_threshold": 26},
    )
    monitor.sample_once()

    assert monitor._effective_real_test_thresholds("cpu") == {
        "cpu_percent": 18.75,
    }
    assert monitor._settings_provider()["cpu_percent_threshold"] == 26


@pytest.mark.parametrize("kind", ["cpu", "memory"])
def test_real_tests_accept_default_production_thresholds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    from picsyncra import resource_monitor

    class FakeEvent:
        def is_set(self) -> bool:
            return False

        def set(self) -> None:
            return None

    class FakeProcess:
        pid = 4242
        exitcode = 0

        def __init__(self, *, target, args, daemon) -> None:
            return None

        def start(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            return None

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            return None

    monitor = _monitor(
        _ReaderSequence(
            cpu=[0],
            host={
                "cpu_percent": 15.0,
                "memory_percent": 84.0,
                "memory_used_bytes": 13_606 * MIB,
                "memory_total_bytes": 16_168 * MIB,
                "disk_busy_percent": 100.0,
            },
        ),
        [],
    )
    monitor.sample_once()
    monkeypatch.setattr(resource_monitor.tempfile, "mkdtemp", lambda **_: str(tmp_path / kind))
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)

    result = monitor.start_real_test(kind)

    assert result == {
        "ok": False,
        "kind": kind,
        "status": "not_detected",
        "timed_out": False,
    }


def test_real_test_threshold_marks_trigger_without_changing_production_setting() -> None:
    from picsyncra.resource_monitor import _ResourceAlertDetector

    detector = _ResourceAlertDetector(confirming_samples=2)
    backend = {"memory_percent": 2.0}
    settings = {"memory_percent_threshold": 20}

    assert detector.observe(
        backend,
        settings,
        "2026-07-23T08:36:50Z",
        effective_thresholds={"memory_percent": 1.5},
    ) == []
    triggers = detector.observe(
        backend,
        settings,
        "2026-07-23T08:36:55Z",
        effective_thresholds={"memory_percent": 1.5},
    )

    assert triggers == [
        {
            "metric": "memory_percent",
            "value": 2.0,
            "threshold": 1.5,
            "configured_threshold": 20.0,
            "effective_threshold": 1.5,
            "test_mode": "real",
        }
    ]


def test_disk_worker_skips_sleep_when_clock_passes_write_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from picsyncra import resource_monitor

    class StopEvent:
        def is_set(self) -> bool:
            return False

    class FakeFile:
        def open(self, *_args, **_kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def write(self, chunk: bytes) -> int:
            return len(chunk)

        def unlink(self, *, missing_ok: bool = False) -> None:
            return None

    class FakeRoot:
        def mkdir(self, **_kwargs) -> None:
            return None

        def __truediv__(self, _name: str) -> FakeFile:
            return FakeFile()

    moments = iter((0.0, 0.0, 0.0, 0.0, 0.11))
    sleeps: list[float] = []
    monkeypatch.setattr(resource_monitor.time, "monotonic", lambda: next(moments, 0.11))
    monkeypatch.setattr(resource_monitor.time, "sleep", sleeps.append)

    resource_monitor._run_disk_test(StopEvent(), 1.0, FakeRoot(), 1, 10.0)

    assert not [value for value in sleeps if value <= 0]


def test_failed_real_worker_reports_redacted_diagnostics_and_keeps_public_result_safe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from picsyncra import resource_monitor

    class FakeEvent:
        def is_set(self) -> bool:
            return False

        def set(self) -> None:
            return None

    class Receiver:
        message: object | None = None

        def poll(self) -> bool:
            return self.message is not None

        def recv(self) -> object:
            assert self.message is not None
            return self.message

        def close(self) -> None:
            return None

    class Sender:
        def __init__(self, receiver: Receiver) -> None:
            self.receiver = receiver

        def send(self, message: object) -> None:
            self.receiver.message = message

        def close(self) -> None:
            return None

    class FakeProcess:
        pid = 4243
        exitcode = 0

        def __init__(self, *, target, args, daemon) -> None:
            self.target = target
            self.args = args

        def start(self) -> None:
            self.target(*self.args)

        def join(self, timeout: float | None = None) -> None:
            return None

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            return None

    receiver = Receiver()
    reported: list[tuple[str, str]] = []
    monitor = ResourceMonitor(
        settings_provider=lambda: dict(SETTINGS),
        context_provider=lambda: dict(CONTEXT),
        event_emitter=lambda *_args: True,
        readers=_ReaderSequence(cpu=[0]),
        real_test_failure_reporter=lambda kind, report: reported.append((kind, report)),
    )
    monitor.sample_once()
    monkeypatch.setattr(resource_monitor.tempfile, "mkdtemp", lambda **_: str(tmp_path))
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(
        resource_monitor.multiprocessing,
        "Pipe",
        lambda **_: (receiver, Sender(receiver)),
    )
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)
    monkeypatch.setattr(
        resource_monitor,
        "_run_cpu_test",
        lambda *_args: (_ for _ in ()).throw(ValueError("password=do-not-leak")),
    )

    result = monitor.start_real_test("cpu")

    assert result == {
        "ok": False,
        "kind": "cpu",
        "status": "failed",
        "timed_out": False,
    }
    assert len(reported) == 1
    assert reported[0][0] == "cpu"
    assert "ValueError" in reported[0][1]
    assert "do-not-leak" not in reported[0][1]
    assert "[REDACTED]" in reported[0][1]


def test_worker_timeout_removes_registration_and_private_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from picsyncra import resource_monitor

    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(
        _ReaderSequence(cpu=[0]),
        events,
        settings={**SETTINGS, "cpu_percent_threshold": 20},
    )
    monitor.sample_once()
    private_dir = tmp_path / "picsyncra_resource_test_timeout"
    process_instances: list[FakeProcess] = []

    class FakeEvent:
        def __init__(self) -> None:
            self.was_set = False

        def set(self) -> None:
            self.was_set = True

        def is_set(self) -> bool:
            return self.was_set

    class FakeProcess:
        def __init__(self, *, target, args, daemon) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon
            self.pid: int | None = None
            self.exitcode: int | None = None
            self._alive = False
            self._join_calls = 0
            self.closed = False
            process_instances.append(self)

        def start(self) -> None:
            self.pid = 4321
            self._alive = True
            worker_dir = Path(self.args[3])
            worker_dir.mkdir(parents=True, exist_ok=True)
            (worker_dir / "left-behind.tmp").write_bytes(b"temporary")

        def join(self, timeout: float | None = None) -> None:
            assert monitor._worker_process is self
            self._join_calls += 1
            if self._join_calls == 1:
                assert monitor.sample_once()["backend"]["test_worker_registered"] is True

        def is_alive(self) -> bool:
            return self._alive

        def terminate(self) -> None:
            self._alive = False
            self.exitcode = -15

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(resource_monitor.tempfile, "mkdtemp", lambda **_kwargs: str(private_dir))
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)
    monkeypatch.setattr(monitor, "REAL_TEST_SECONDS", 0.01)

    result = monitor.start_real_test("cpu")

    assert result == {"ok": False, "kind": "cpu", "status": "timeout", "timed_out": True}
    assert monitor._worker_pid is None
    assert monitor._worker_process is None
    assert process_instances[0].closed is True
    assert not private_dir.exists()
    assert monitor.latest_public_snapshot()["backend"]["test_worker_registered"] is False


def test_public_snapshot_never_exposes_worker_handles_or_temporary_paths() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(_ReaderSequence(cpu=[1]), events)

    snapshot = monitor.sample_once()

    assert set(snapshot) == {"host", "backend", "detector", "observed_at"}
    serialized = json.dumps(snapshot)
    assert "Process" not in serialized
    assert "picsyncra_resource_test_" not in serialized


@pytest.mark.skipif(os.name != "nt", reason="Windows native reader contract")
def test_native_reader_reports_current_backend_process_memory() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = ResourceMonitor(
        settings_provider=lambda: dict(SETTINGS),
        context_provider=lambda: dict(CONTEXT),
        event_emitter=lambda severity, event_type, details: _record_event(
            events, severity, event_type, details
        ),
    )

    snapshot = monitor.sample_once()

    assert snapshot["backend"]["memory_working_set_bytes"] > 0
    assert snapshot["backend"]["memory_private_bytes"] > 0


def test_public_and_event_payloads_drop_undeclared_provider_values() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []

    class UnsafeReader(_ReaderSequence):
        def read_host(self) -> dict[str, object]:
            return {**super().read_host(), "temporary_path": Path("private.tmp")}

        def read_backend(self, worker_pid: int | None = None) -> dict[str, object]:
            return {**super().read_backend(worker_pid), "process_handle": object()}

    monitor = ResourceMonitor(
        settings_provider=lambda: dict(SETTINGS),
        context_provider=lambda: {**CONTEXT, "secret": object()},
        event_emitter=lambda severity, event_type, details: _record_event(
            events, severity, event_type, details
        ),
        readers=UnsafeReader(cpu=[30, 31]),
    )

    monitor.sample_once()
    snapshot = monitor.sample_once()

    assert "temporary_path" not in snapshot["host"]
    assert "process_handle" not in snapshot["backend"]
    assert "secret" not in snapshot["backend"]
    json.dumps(snapshot)
    json.dumps(events[0][2])


def test_stop_closes_native_reader_resources() -> None:
    class ClosableReader(_ReaderSequence):
        closed = False

        def close(self) -> None:
            self.closed = True

    readers = ClosableReader(cpu=[1])
    monitor = _monitor(readers, [])

    monitor.stop()

    assert readers.closed is True


def test_stop_during_worker_launch_cannot_leave_unregistered_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from picsyncra import resource_monitor

    started = threading.Event()
    allow_start = threading.Event()
    private_dir = tmp_path / "picsyncra_resource_test_race"
    process_instances: list[FakeProcess] = []

    class FakeEvent:
        def __init__(self) -> None:
            self.was_set = False

        def set(self) -> None:
            self.was_set = True

        def is_set(self) -> bool:
            return self.was_set

    class FakeProcess:
        def __init__(self, *, target, args, daemon) -> None:
            self.pid: int | None = None
            self.exitcode: int | None = None
            self._alive = False
            self.closed = False
            process_instances.append(self)

        def start(self) -> None:
            started.set()
            assert allow_start.wait(2.0)
            self.pid = 9876
            self._alive = True
            private_dir.mkdir(parents=True, exist_ok=True)
            (private_dir / "race.tmp").write_bytes(b"temporary")

        def join(self, timeout: float | None = None) -> None:
            return None

        def is_alive(self) -> bool:
            return self._alive

        def terminate(self) -> None:
            self._alive = False
            self.exitcode = -15

        def kill(self) -> None:
            self._alive = False
            self.exitcode = -9

        def close(self) -> None:
            self.closed = True

    monitor = _monitor(
        _ReaderSequence(cpu=[0]),
        [],
        settings={**SETTINGS, "cpu_percent_threshold": 20},
    )
    monitor.sample_once()
    monkeypatch.setattr(resource_monitor.tempfile, "mkdtemp", lambda **_kwargs: str(private_dir))
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)
    monkeypatch.setattr(monitor, "REAL_TEST_SECONDS", 0.01)
    results: list[dict[str, object]] = []
    launch_thread = threading.Thread(target=lambda: results.append(monitor.start_real_test("cpu")))
    launch_thread.start()
    assert started.wait(1.0)
    stop_thread = threading.Thread(target=monitor.stop)
    stop_thread.start()
    allow_start.set()
    launch_thread.join(2.0)
    stop_thread.join(2.0)

    assert not launch_thread.is_alive()
    assert not stop_thread.is_alive()
    assert process_instances and not process_instances[0].is_alive()
    assert process_instances[0].closed is True
    assert monitor._worker_process is None
    assert not private_dir.exists()


@pytest.mark.parametrize("kind", ["cpu", "memory", "disk"])
def test_stop_interruption_reports_cancelled_even_with_zero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    from picsyncra import resource_monitor

    started = threading.Event()
    cancelled = threading.Event()

    class FakeEvent:
        def __init__(self) -> None:
            self.ready = False

        def set(self) -> None:
            self.ready = True
            if self is stop_event:
                cancelled.set()

        def is_set(self) -> bool:
            return self.ready

    stop_event: FakeEvent

    class FakeProcess:
        pid = 9753
        exitcode = 0

        def __init__(self, *, target, args, daemon) -> None:
            nonlocal stop_event
            stop_event = args[1]
            self.alive = False

        def start(self) -> None:
            self.alive = True
            started.set()

        def join(self, timeout: float | None = None) -> None:
            assert cancelled.wait(2.0)
            self.alive = False

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            self.alive = False

        def close(self) -> None:
            return None

    monitor = _monitor(
        _ReaderSequence(cpu=[0]),
        [],
        settings={**SETTINGS, "cpu_percent_threshold": 20},
    )
    monitor.sample_once()
    monkeypatch.setattr(
        resource_monitor.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(tmp_path / f"picsyncra_resource_test_cancel_{kind}"),
    )
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)
    results: list[dict[str, object]] = []
    launch = threading.Thread(
        target=lambda: results.append(monitor.start_real_test(kind))
    )
    launch.start()
    assert started.wait(1.0)

    monitor.stop()
    launch.join(2.0)

    assert not launch.is_alive()
    assert results == [
        {"ok": False, "kind": kind, "status": "cancelled", "timed_out": False}
    ]


def test_worker_exit_without_detector_ack_is_not_detected_and_uses_grace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from picsyncra import resource_monitor

    joins: list[float | None] = []

    class FakeEvent:
        def set(self) -> None:
            return None

        def is_set(self) -> bool:
            return False

    class FakeProcess:
        pid = 2468
        exitcode = 0

        def __init__(self, *, target, args, daemon) -> None:
            self.closed = False

        def start(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            joins.append(timeout)

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            self.closed = True

    monitor = _monitor(
        _ReaderSequence(cpu=[0]),
        [],
        settings={**SETTINGS, "cpu_percent_threshold": 20},
    )
    monitor.sample_once()
    monkeypatch.setattr(
        resource_monitor.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(tmp_path / "picsyncra_resource_test_complete"),
    )
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)
    monkeypatch.setattr(monitor, "REAL_TEST_SECONDS", 0.25)
    monkeypatch.setattr(monitor, "REAL_TEST_GRACE_SECONDS", 0.5)

    result = monitor.start_real_test("cpu")

    assert result == {
        "ok": False,
        "kind": "cpu",
        "status": "not_detected",
        "timed_out": False,
    }
    assert joins[0] == pytest.approx(0.75)


def test_real_test_succeeds_only_after_normal_detector_ack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from picsyncra import resource_monitor

    class FakeEvent:
        def __init__(self) -> None:
            self.ready = False

        def set(self) -> None:
            self.ready = True

        def is_set(self) -> bool:
            return self.ready

    class FakeProcess:
        pid = 2469
        exitcode = 0

        def __init__(self, *, target, args, daemon) -> None:
            return None

        def start(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            monitor.sample_once()
            monitor.sample_once()

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            return None

    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = _monitor(
        _ReaderSequence(cpu=[0, 30, 31]),
        events,
        settings={**SETTINGS, "cpu_percent_threshold": 20},
    )
    monitor.sample_once()
    monkeypatch.setattr(
        resource_monitor.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(tmp_path / "picsyncra_resource_test_detected"),
    )
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)

    result = monitor.start_real_test("cpu")

    assert result == {
        "ok": True,
        "kind": "cpu",
        "status": "detected",
        "timed_out": False,
    }
    assert len(events) == 1
    assert events[0][2]["trigger"]["metric"] == "cpu_percent"


@pytest.mark.parametrize("failure_mode", ["returns_false", "raises"])
def test_real_test_is_not_detected_when_trigger_event_is_not_persisted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure_mode: str
) -> None:
    from picsyncra import resource_monitor

    class FakeEvent:
        def __init__(self) -> None:
            self.ready = False

        def set(self) -> None:
            self.ready = True

        def is_set(self) -> bool:
            return self.ready

    class FakeProcess:
        pid = 2470
        exitcode = 0

        def __init__(self, *, target, args, daemon) -> None:
            return None

        def start(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            monitor.sample_once()
            monitor.sample_once()

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            return None

    attempted_events: list[tuple[str, str, dict[str, object]]] = []

    def failing_emitter(
        severity: str, event_type: str, details: dict[str, object]
    ) -> bool:
        attempted_events.append((severity, event_type, details))
        if failure_mode == "raises":
            raise OSError("observability unavailable")
        return False

    monitor = ResourceMonitor(
        settings_provider=lambda: {**SETTINGS, "cpu_percent_threshold": 20},
        context_provider=lambda: dict(CONTEXT),
        event_emitter=failing_emitter,
        readers=_ReaderSequence(cpu=[0, 30, 31]),
    )
    monitor.sample_once()
    monkeypatch.setattr(
        resource_monitor.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(tmp_path / "picsyncra_resource_test_persistence_failure"),
    )
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)

    result = monitor.start_real_test("cpu")

    assert result == {
        "ok": False,
        "kind": "cpu",
        "status": "persistence_failed",
        "timed_out": False,
    }
    assert len(attempted_events) == 1
    assert attempted_events[0][0:2] == ("warning", "backend.resource_high")


def test_real_test_constructor_failure_removes_private_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from picsyncra import resource_monitor

    private_dir = tmp_path / "picsyncra_resource_test_constructor_failure"
    monitor = _monitor(
        _ReaderSequence(cpu=[0]),
        [],
        settings={**SETTINGS, "cpu_percent_threshold": 20},
    )
    monitor.sample_once()

    def make_directory(**_kwargs) -> str:
        private_dir.mkdir()
        return str(private_dir)

    monkeypatch.setattr(resource_monitor.tempfile, "mkdtemp", make_directory)
    monkeypatch.setattr(
        resource_monitor.multiprocessing,
        "Event",
        lambda: (_ for _ in ()).throw(OSError("event construction failed")),
    )

    result = monitor.start_real_test("cpu")

    assert result == {
        "ok": False,
        "kind": "cpu",
        "status": "launch_failed",
        "timed_out": False,
    }
    assert monitor._worker_process is None
    assert not private_dir.exists()


def test_cpu_worker_uses_parallel_gil_releasing_hash_rounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from picsyncra import resource_monitor

    calls = 0

    class StopAfterHash:
        def is_set(self) -> bool:
            return calls > 0

    class HashResult:
        def digest(self) -> bytes:
            return b"digest"

    def fake_sha256(payload: bytes) -> HashResult:
        nonlocal calls
        assert len(payload) > 2047
        calls += 1
        return HashResult()

    monkeypatch.setattr(resource_monitor.hashlib, "sha256", fake_sha256)

    resource_monitor._run_cpu_test(StopAfterHash(), time.monotonic() + 1.0, 8)

    assert calls >= 1


def test_cleanup_uses_kill_fallback_before_deregistering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from picsyncra import resource_monitor

    private_dir = tmp_path / "picsyncra_resource_test_kill"
    process_instances: list[FakeProcess] = []

    class FakeEvent:
        def set(self) -> None:
            return None

        def is_set(self) -> bool:
            return False

    class FakeProcess:
        pid = 1357
        exitcode = None

        def __init__(self, *, target, args, daemon) -> None:
            self.alive = False
            self.killed = False
            self.closed = False
            process_instances.append(self)

        def start(self) -> None:
            self.alive = True
            private_dir.mkdir(parents=True, exist_ok=True)

        def join(self, timeout: float | None = None) -> None:
            assert monitor._worker_process is self

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            self.killed = True
            self.alive = False
            self.exitcode = -9

        def close(self) -> None:
            self.closed = True

    monitor = _monitor(
        _ReaderSequence(cpu=[0]),
        [],
        settings={**SETTINGS, "cpu_percent_threshold": 20},
    )
    monitor.sample_once()
    monkeypatch.setattr(resource_monitor.tempfile, "mkdtemp", lambda **_kwargs: str(private_dir))
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)
    monkeypatch.setattr(monitor, "REAL_TEST_SECONDS", 0.01)

    result = monitor.start_real_test("cpu")

    assert result["status"] == "timeout"
    assert process_instances[0].killed is True
    assert process_instances[0].closed is True
    assert monitor._worker_process is None
    assert not private_dir.exists()


def test_pdh_invalid_status_is_unavailable_and_query_is_closed() -> None:
    from picsyncra import resource_monitor

    reader = resource_monitor._WindowsResourceReaders()
    close_calls = 0

    class FakePdh:
        def PdhCollectQueryData(self, _query) -> int:
            return 0

        def PdhGetFormattedCounterValue(self, _counter, _format, _kind, value) -> int:
            formatted = ctypes.cast(
                value, ctypes.POINTER(resource_monitor._PDH_FMT_COUNTERVALUE)
            ).contents
            formatted.CStatus = 0xC0000BC6
            formatted.doubleValue = 99.0
            return 0

        def PdhCloseQuery(self, _query) -> int:
            nonlocal close_calls
            close_calls += 1
            return 0

    reader._pdh = FakePdh()
    reader._pdh_query = resource_monitor.wintypes.HANDLE(1)
    reader._pdh_counter = resource_monitor.wintypes.HANDLE(2)
    reader._pdh_ready = True

    assert reader._read_disk_busy() == {"available": False}
    reader.close()

    assert close_calls == 1
    assert reader._pdh_ready is False


def test_pdh_setup_failure_closes_and_resets_query() -> None:
    from picsyncra import resource_monitor

    reader = resource_monitor._WindowsResourceReaders()
    close_calls = 0

    class FakePdh:
        def PdhOpenQueryW(self, _source, _data, query) -> int:
            ctypes.cast(query, ctypes.POINTER(resource_monitor.wintypes.HANDLE)).contents.value = 1
            return 0

        def PdhAddEnglishCounterW(self, _query, _path, _data, counter) -> int:
            ctypes.cast(counter, ctypes.POINTER(resource_monitor.wintypes.HANDLE)).contents.value = 2
            return 0

        def PdhCollectQueryData(self, _query) -> int:
            return 1

        def PdhCloseQuery(self, _query) -> int:
            nonlocal close_calls
            close_calls += 1
            return 0

    reader._pdh = FakePdh()

    assert reader._read_disk_busy() == {"available": False}
    assert close_calls == 1
    assert not reader._pdh_query
    assert not reader._pdh_counter
    assert reader._pdh_ready is False


def test_stop_and_concurrent_restart_are_serialized_until_reader_close() -> None:
    from picsyncra import resource_monitor

    real_thread = threading.Thread
    join_entered = threading.Event()
    allow_join = threading.Event()
    restart_finished = threading.Event()

    class ClosableReader:
        def __init__(self) -> None:
            self.closed = False

        def read_host(self) -> dict[str, object]:
            return {"cpu_percent": 1, "memory_percent": 1, "disk_busy_percent": 1}

        def read_backend(self, _worker_pid=None) -> dict[str, object]:
            return {
                "cpu_percent": 1,
                "memory_percent": 1,
                "disk_io_bytes_per_second": 0,
            }

        def close(self) -> None:
            self.closed = True

    class FinishingThread:
        def join(self, timeout: float | None = None) -> None:
            join_entered.set()
            assert allow_join.wait(2.0)

        def is_alive(self) -> bool:
            return not allow_join.is_set()

    readers = ClosableReader()
    monitor = _monitor(readers, [])
    monitor._thread = FinishingThread()
    stop_thread = real_thread(target=monitor.stop)
    stop_thread.start()
    assert join_entered.wait(1.0)

    restart_thread = real_thread(
        target=lambda: (monitor.start(), restart_finished.set())
    )
    restart_thread.start()

    restart_finished_early = restart_finished.wait(0.1)
    allow_join.set()
    stop_thread.join(2.0)
    restart_thread.join(2.0)

    assert readers.closed is True
    assert restart_finished_early is False
    assert not stop_thread.is_alive()
    assert not restart_thread.is_alive()
    monitor.stop()


def test_concurrent_samples_serialize_reader_access() -> None:
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    class BlockingReader:
        def __init__(self) -> None:
            self.calls = 0
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def read_host(self) -> dict[str, object]:
            with self.lock:
                self.calls += 1
                call = self.calls
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            if call == 1:
                first_entered.set()
                assert release_first.wait(2.0)
            else:
                second_entered.set()
            with self.lock:
                self.active -= 1
            return {"cpu_percent": 1, "memory_percent": 1, "disk_busy_percent": 1}

        def read_backend(self, _worker_pid=None) -> dict[str, object]:
            return {
                "cpu_percent": 1,
                "memory_percent": 1,
                "disk_io_bytes_per_second": 0,
            }

    readers = BlockingReader()
    monitor = _monitor(readers, [])
    first = threading.Thread(target=monitor.sample_once)
    second = threading.Thread(target=monitor.sample_once)
    first.start()
    assert first_entered.wait(1.0)
    second.start()

    second_entered_early = second_entered.wait(0.1)
    release_first.set()
    first.join(2.0)
    second.join(2.0)

    assert readers.max_active == 1
    assert second_entered_early is False
    assert not first.is_alive()
    assert not second.is_alive()


def test_supervision_exception_still_cleans_and_deregisters_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from picsyncra import resource_monitor

    private_dir = tmp_path / "picsyncra_resource_test_supervision"
    instances: list[FakeProcess] = []

    class FakeEvent:
        def set(self) -> None:
            return None

    class FakeProcess:
        pid = 7788
        exitcode = None

        def __init__(self, *, target, args, daemon) -> None:
            self.alive = False
            self.join_calls = 0
            self.closed = False
            instances.append(self)

        def start(self) -> None:
            self.alive = True
            private_dir.mkdir()

        def join(self, timeout: float | None = None) -> None:
            self.join_calls += 1
            if self.join_calls == 1:
                raise RuntimeError("injected supervision failure")

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            self.alive = False

        def close(self) -> None:
            self.closed = True

    monitor = _monitor(
        _ReaderSequence(cpu=[0]),
        [],
        settings={**SETTINGS, "cpu_percent_threshold": 20},
    )
    monitor.sample_once()
    monkeypatch.setattr(resource_monitor.tempfile, "mkdtemp", lambda **_kwargs: str(private_dir))
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)

    result = monitor.start_real_test("cpu")

    assert result["status"] == "supervision_failed"
    assert instances[0].closed is True
    assert monitor._worker_process is None
    assert not private_dir.exists()


def test_cleanup_failure_retains_worker_reservation_for_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from picsyncra import resource_monitor

    private_dir = tmp_path / "picsyncra_resource_test_cleanup_retry"
    real_rmtree = resource_monitor.shutil.rmtree
    instances: list[FakeProcess] = []

    class FakeEvent:
        def set(self) -> None:
            return None

    class FakeProcess:
        pid = 8899
        exitcode = 0

        def __init__(self, *, target, args, daemon) -> None:
            self.closed = False
            instances.append(self)

        def start(self) -> None:
            private_dir.mkdir()
            (private_dir / "retained.tmp").write_bytes(b"data")

        def join(self, timeout: float | None = None) -> None:
            return None

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            self.closed = True

    def failing_rmtree(_path, *args, **kwargs) -> None:
        raise OSError("injected cleanup failure")

    monitor = _monitor(
        _ReaderSequence(cpu=[0]),
        [],
        settings={**SETTINGS, "cpu_percent_threshold": 20},
    )
    monitor.sample_once()
    monkeypatch.setattr(resource_monitor.tempfile, "mkdtemp", lambda **_kwargs: str(private_dir))
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)
    monkeypatch.setattr(resource_monitor.shutil, "rmtree", failing_rmtree)

    result = monitor.start_real_test("cpu")

    assert result["status"] == "cleanup_failed"
    assert monitor._worker_process is instances[0]
    assert monitor._worker_temp_dir == str(private_dir)
    assert private_dir.exists()
    assert monitor.latest_public_snapshot()["backend"]["test_worker_registered"] is True

    monkeypatch.setattr(resource_monitor.shutil, "rmtree", real_rmtree)
    monitor.stop()
    assert monitor._worker_process is None
    assert monitor._worker_temp_dir is None
    assert not private_dir.exists()


@pytest.mark.parametrize("worker_pid", [None, 998877])
def test_native_backend_reader_marks_any_requested_process_failure_unavailable(
    monkeypatch: pytest.MonkeyPatch, worker_pid: int | None
) -> None:
    from picsyncra import resource_monitor

    reader = resource_monitor._WindowsResourceReaders()
    current = os.getpid()

    def process_values(pid: int):
        if worker_pid is not None and pid == current:
            return (100, 10, 10, 10, 10)
        return None

    monkeypatch.setattr(reader, "_read_process", process_values)

    assert reader.read_backend(worker_pid) == {"available": False}


@pytest.mark.parametrize("kind", ["memory", "disk"])
def test_memory_and_disk_real_tests_accept_reachable_thresholds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    from picsyncra import resource_monitor

    class FakeEvent:
        def set(self) -> None:
            return None

    class FakeProcess:
        pid = 9090
        exitcode = 0

        def __init__(self, *, target, args, daemon) -> None:
            return None

        def start(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            return None

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            return None

    monitor = _monitor(_ReaderSequence(cpu=[0]), [])
    monitor.sample_once()
    monkeypatch.setattr(
        resource_monitor.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(tmp_path / f"picsyncra_resource_test_{kind}"),
    )
    monkeypatch.setattr(resource_monitor.multiprocessing, "Event", FakeEvent)
    monkeypatch.setattr(resource_monitor.multiprocessing, "Process", FakeProcess)

    result = monitor.start_real_test(kind)

    assert result["ok"] is False
    assert result["kind"] == kind
    assert result["status"] == "not_detected"


def test_start_reports_stopping_until_slow_sampler_exits_and_closes_reader() -> None:
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    class SlowReader:
        def __init__(self) -> None:
            self.calls = 0

        def read_host(self) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                entered.set()
                assert release.wait(2.0)
            return {"cpu_percent": 1, "memory_percent": 1, "disk_busy_percent": 1}

        def read_backend(self, _worker_pid=None) -> dict[str, object]:
            return {
                "cpu_percent": 1,
                "memory_percent": 1,
                "disk_io_bytes_per_second": 0,
            }

        def close(self) -> None:
            closed.set()

    monitor = _monitor(SlowReader(), [])
    monitor.STOP_JOIN_SECONDS = 0.01
    assert monitor.start() is True
    assert entered.wait(1.0)

    monitor.stop()

    assert monitor.start() is False
    assert closed.is_set() is False
    release.set()
    assert closed.wait(1.0)
    assert monitor.start() is True
    monitor.stop()


def test_disk_worker_never_exceeds_total_byte_budget_over_long_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from picsyncra import resource_monitor

    now = 0.0
    written = 0
    open_calls = 0
    unlinks = 0

    class StopEvent:
        def is_set(self) -> bool:
            return False

    class FakeFile:
        def open(self, *_args, **_kwargs):
            nonlocal open_calls
            open_calls += 1
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def write(self, chunk: bytes) -> int:
            nonlocal written
            written += len(chunk)
            return len(chunk)

        def unlink(self, *, missing_ok: bool = False) -> None:
            nonlocal unlinks
            unlinks += 1

    class FakeRoot:
        def __init__(self) -> None:
            self.file = FakeFile()

        def mkdir(self, **_kwargs) -> None:
            return None

        def __truediv__(self, _name: str) -> FakeFile:
            return self.file

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += max(0.0001, seconds)

    monkeypatch.setattr(resource_monitor.time, "monotonic", monotonic)
    monkeypatch.setattr(resource_monitor.time, "sleep", sleep)

    resource_monitor._run_disk_test(
        StopEvent(),
        100.0,
        FakeRoot(),
        10,
        100.0,
    )

    assert written == 10
    assert open_calls == 1
    assert unlinks >= 1


@pytest.mark.parametrize("baseline_at", [0.0, 0.4, 2.5, 5.0, 6.9])
def test_disk_worker_waits_for_baseline_then_covers_two_high_samples(
    monkeypatch: pytest.MonkeyPatch, baseline_at: float
) -> None:
    from picsyncra import resource_monitor

    now = 0.0
    writes: list[tuple[float, int]] = []

    class StopEvent:
        def is_set(self) -> bool:
            return False

    class BaselineEvent:
        def is_set(self) -> bool:
            return now >= baseline_at

    class DetectionEvent:
        def is_set(self) -> bool:
            return now >= baseline_at + 10.0

    class FakeFile:
        def open(self, *_args, **_kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def write(self, chunk: bytes) -> int:
            writes.append((now, len(chunk)))
            return len(chunk)

        def unlink(self, *, missing_ok: bool = False) -> None:
            return None

    class FakeRoot:
        def __init__(self) -> None:
            self.file = FakeFile()

        def mkdir(self, **_kwargs) -> None:
            return None

        def __truediv__(self, _name: str) -> FakeFile:
            return self.file

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += max(0.0001, seconds)

    monkeypatch.setattr(resource_monitor.time, "monotonic", monotonic)
    monkeypatch.setattr(resource_monitor.time, "sleep", sleep)
    budget = ResourceMonitor.MAX_TEST_DISK_BYTES
    rate = ResourceMonitor.MAX_TEST_DISK_RATE_BYTES_PER_SECOND

    detected = resource_monitor._run_disk_test(
        StopEvent(),
        ResourceMonitor.REAL_TEST_SECONDS,
        FakeRoot(),
        budget,
        rate,
        BaselineEvent(),
        DetectionEvent(),
        ResourceMonitor.DISK_BASELINE_WAIT_SECONDS,
    )

    def sampled_rate(start: float, end: float) -> float:
        return sum(size for at, size in writes if start < at <= end) / (end - start)

    assert detected is True
    assert sum(size for _at, size in writes) <= budget
    assert not [at for at, _size in writes if at <= baseline_at]
    assert sampled_rate(baseline_at, baseline_at + 5.0) > 8 * MIB
    assert sampled_rate(baseline_at + 5.0, baseline_at + 10.0) > 8 * MIB
    assert writes[-1][0] < ResourceMonitor.REAL_TEST_SECONDS


def test_disk_worker_baseline_timeout_writes_nothing_and_returns_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from picsyncra import resource_monitor

    now = 0.0
    writes = 0

    class StopEvent:
        def is_set(self) -> bool:
            return False

    class BaselineEvent:
        def is_set(self) -> bool:
            return False

    class FakeFile:
        def open(self, *_args, **_kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def write(self, chunk: bytes) -> int:
            nonlocal writes
            writes += len(chunk)
            return len(chunk)

        def unlink(self, *, missing_ok: bool = False) -> None:
            return None

    class FakeRoot:
        def mkdir(self, **_kwargs) -> None:
            return None

        def __truediv__(self, _name: str) -> FakeFile:
            return FakeFile()

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += max(0.0001, seconds)

    monkeypatch.setattr(resource_monitor.time, "monotonic", monotonic)
    monkeypatch.setattr(resource_monitor.time, "sleep", sleep)

    completed = resource_monitor._run_disk_test(
        StopEvent(),
        ResourceMonitor.REAL_TEST_SECONDS,
        FakeRoot(),
        ResourceMonitor.MAX_TEST_DISK_BYTES,
        ResourceMonitor.MAX_TEST_DISK_RATE_BYTES_PER_SECOND,
        BaselineEvent(),
        BaselineEvent(),
        ResourceMonitor.DISK_BASELINE_WAIT_SECONDS,
    )

    assert completed is False
    assert writes == 0
    assert (
        ResourceMonitor.DISK_BASELINE_WAIT_SECONDS
        <= now
        < ResourceMonitor.REAL_TEST_SECONDS
    )


def test_disk_worker_without_detector_ack_stops_at_cap_and_is_not_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from picsyncra import resource_monitor

    now = 0.0
    written = 0

    class NeverStop:
        def is_set(self) -> bool:
            return False

    class Ready:
        def is_set(self) -> bool:
            return True

    class FakeFile:
        def open(self, *_args, **_kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def write(self, chunk: bytes) -> int:
            nonlocal written
            written += len(chunk)
            return len(chunk)

        def unlink(self, *, missing_ok: bool = False) -> None:
            return None

    class FakeRoot:
        def mkdir(self, **_kwargs) -> None:
            return None

        def __truediv__(self, _name: str) -> FakeFile:
            return FakeFile()

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += max(0.0001, seconds)

    monkeypatch.setattr(resource_monitor.time, "monotonic", monotonic)
    monkeypatch.setattr(resource_monitor.time, "sleep", sleep)

    detected = resource_monitor._run_disk_test(
        NeverStop(),
        ResourceMonitor.REAL_TEST_SECONDS,
        FakeRoot(),
        ResourceMonitor.MAX_TEST_DISK_BYTES,
        ResourceMonitor.MAX_TEST_DISK_RATE_BYTES_PER_SECOND,
        Ready(),
        NeverStop(),
        ResourceMonitor.DISK_BASELINE_WAIT_SECONDS,
    )

    assert detected is False
    assert written == ResourceMonitor.MAX_TEST_DISK_BYTES
    assert now >= ResourceMonitor.REAL_TEST_SECONDS


@pytest.mark.skipif(os.name != "nt", reason="Windows native baseline contract")
def test_native_reader_signals_only_after_successful_worker_io_baseline() -> None:
    from picsyncra import resource_monitor

    worker_pid = 87654
    parent_pid = os.getpid()
    fail_worker = True

    class BaselineEvent:
        def __init__(self) -> None:
            self.ready = False

        def is_set(self) -> bool:
            return self.ready

        def set(self) -> None:
            self.ready = True

    reader = object.__new__(resource_monitor._WindowsResourceReaders)
    reader._clock = lambda: 100.0
    reader._logical_cpus = 1
    reader._process_previous = {}
    reader._read_memory = lambda: {"memory_total_bytes": 1_000_000_000}

    def read_process(pid: int) -> tuple[int, int, int, int, int] | None:
        if pid == worker_pid and fail_worker:
            return None
        assert pid in {parent_pid, worker_pid}
        return (10_000_000, 1000, 900, 2000, 3000)

    reader._read_process = read_process
    baseline = BaselineEvent()

    failed = reader.read_backend_with_worker_baseline(worker_pid, baseline)
    assert failed == {"available": False}
    assert baseline.is_set() is False

    fail_worker = False
    succeeded = reader.read_backend_with_worker_baseline(worker_pid, baseline)
    assert succeeded["memory_working_set_bytes"] == 2000
    assert baseline.is_set() is True
    assert worker_pid in reader._process_previous


@pytest.mark.skipif(os.name != "nt", reason="Windows native binding contract")
def test_missing_pdh_binding_keeps_core_metrics_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from picsyncra import resource_monitor

    def fail_pdh(_self) -> None:
        raise OSError("PDH unavailable")

    monkeypatch.setattr(resource_monitor._WindowsResourceReaders, "_bind_pdh_api", fail_pdh)

    reader = resource_monitor._WindowsResourceReaders()
    host = reader.read_host()
    backend = reader.read_backend()

    assert host["memory_total_bytes"] > 0
    assert host["disk_busy_percent"] == {"available": False}
    assert backend["memory_working_set_bytes"] > 0


@pytest.mark.skipif(os.name != "nt", reason="Windows native binding contract")
def test_missing_core_binding_keeps_monitor_constructible_with_unavailable_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from picsyncra import resource_monitor

    def fail_core(_self) -> None:
        raise OSError("core counters unavailable")

    monkeypatch.setattr(
        resource_monitor._WindowsResourceReaders, "_bind_core_windows_apis", fail_core
    )

    monitor = ResourceMonitor(
        settings_provider=lambda: dict(SETTINGS),
        context_provider=lambda: dict(CONTEXT),
        event_emitter=lambda *_args: None,
    )
    snapshot = monitor.sample_once()
    monitor.stop()

    assert snapshot["host"]["cpu_percent"] == {"available": False}
    assert snapshot["host"]["memory_total_bytes"] == {"available": False}
    assert snapshot["backend"]["available"] is False
