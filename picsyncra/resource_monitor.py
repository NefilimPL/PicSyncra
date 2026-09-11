from __future__ import annotations

import copy
import ctypes
from ctypes import wintypes
from collections import deque
from datetime import datetime, timezone
import hashlib
import math
import multiprocessing
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import traceback
from typing import Callable, Mapping

from .redaction import sanitize_free_text


MIB = 1024 * 1024
_METRICS = (
    ("cpu_percent", "cpu_percent_threshold", 1.0),
    ("memory_percent", "memory_percent_threshold", 1.0),
    ("disk_io_bytes_per_second", "io_mib_per_second_threshold", float(MIB)),
)
_HOST_PUBLIC_KEYS = {
    "available",
    "cpu_percent",
    "memory_percent",
    "memory_used_bytes",
    "memory_total_bytes",
    "disk_busy_percent",
}
_BACKEND_PUBLIC_KEYS = {
    "available",
    "cpu_percent",
    "memory_percent",
    "memory_working_set_bytes",
    "memory_private_bytes",
    "disk_read_bytes_per_second",
    "disk_write_bytes_per_second",
    "disk_io_bytes_per_second",
}
_CONTEXT_PUBLIC_KEYS = {"active_jobs", "queued_jobs", "active_clients"}
_REAL_TEST_TRIGGER_METRICS = {
    "cpu": "cpu_percent",
    "memory": "memory_percent",
    "disk": "disk_io_bytes_per_second",
}


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _safe_metric_value(value: object) -> object | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, Mapping) and isinstance(value.get("available"), bool):
        result: dict[str, object] = {"available": value["available"]}
        reason = value.get("reason")
        if isinstance(reason, str):
            result["reason"] = reason[:80]
        return result
    return None


def _safe_metrics(value: object, allowed_keys: set[str]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {"available": False}
    result: dict[str, object] = {}
    for key in allowed_keys:
        if key not in value:
            continue
        safe_value = _safe_metric_value(value[key])
        if safe_value is not None:
            result[key] = safe_value
    return result or {"available": False}


class _ResourceAlertDetector:
    def __init__(self, confirming_samples: int) -> None:
        self._confirming_samples = confirming_samples
        self._high = {metric: 0 for metric, _setting, _scale in _METRICS}
        self._normal = {metric: 0 for metric, _setting, _scale in _METRICS}
        self._latched: set[str] = set()
        self._last_trigger_at: str | None = None

    def observe(
        self,
        backend: Mapping[str, object],
        settings: Mapping[str, object],
        observed_at: str,
        *,
        effective_thresholds: Mapping[str, object] | None = None,
    ) -> list[dict[str, object]]:
        triggers: list[dict[str, object]] = []
        for metric, setting, scale in _METRICS:
            value = _number(backend.get(metric))
            configured = _number(settings.get(setting))
            if value is None or configured is None:
                self._high[metric] = 0
                self._normal[metric] = 0
                continue
            configured_threshold = configured * scale
            effective_threshold = (
                _number(effective_thresholds.get(metric))
                if effective_thresholds is not None
                else None
            )
            threshold = (
                effective_threshold
                if effective_threshold is not None
                else configured_threshold
            )
            if value > threshold:
                self._normal[metric] = 0
                self._high[metric] += 1
                if (
                    metric not in self._latched
                    and self._high[metric] >= self._confirming_samples
                ):
                    self._latched.add(metric)
                    self._last_trigger_at = observed_at
                    trigger: dict[str, object] = {
                        "metric": metric,
                        "value": value,
                        "threshold": threshold,
                        "configured_threshold": configured,
                    }
                    if effective_threshold is not None:
                        trigger.update(
                            effective_threshold=effective_threshold,
                            test_mode="real",
                        )
                    triggers.append(trigger)
            else:
                self._high[metric] = 0
                if metric in self._latched:
                    self._normal[metric] += 1
                    if self._normal[metric] >= self._confirming_samples:
                        self._latched.remove(metric)
                        self._normal[metric] = 0
                else:
                    self._normal[metric] = 0
        return triggers

    def public_state(self) -> dict[str, object]:
        pending = [
            metric
            for metric, _setting, _scale in _METRICS
            if 0 < self._high[metric] < self._confirming_samples
            and metric not in self._latched
        ]
        return {
            "latched_metrics": sorted(self._latched),
            "pending_metrics": pending,
            "last_trigger_at": self._last_trigger_at,
        }


class ResourceMonitor:
    SAMPLE_SECONDS = 5.0
    STOP_JOIN_SECONDS = 6.0
    HISTORY_SIZE = 12
    CONFIRMING_SAMPLES = 2
    REAL_TEST_SECONDS = 20.0
    REAL_TEST_GRACE_SECONDS = 2.0
    MAX_TEST_CPU_PERCENT = 25.0
    MAX_TEST_MEMORY_BYTES = 256 * MIB
    MAX_TEST_DISK_BYTES = 128 * MIB
    DISK_BASELINE_WAIT_SECONDS = SAMPLE_SECONDS + REAL_TEST_GRACE_SECONDS
    DISK_TEST_WRITE_SECONDS = (
        REAL_TEST_SECONDS - DISK_BASELINE_WAIT_SECONDS - REAL_TEST_GRACE_SECONDS
    )
    MAX_TEST_DISK_RATE_BYTES_PER_SECOND = MAX_TEST_DISK_BYTES / (
        DISK_TEST_WRITE_SECONDS
    )
    REAL_TEST_TARGET_FRACTION = 0.75

    def __init__(
        self,
        settings_provider: Callable[[], Mapping[str, object]],
        context_provider: Callable[[], Mapping[str, object]],
        event_emitter: Callable[[str, str, dict[str, object]], bool],
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        readers: object | None = None,
        real_test_failure_reporter: Callable[[str, str], None] | None = None,
    ) -> None:
        self._settings_provider = settings_provider
        self._context_provider = context_provider
        self._event_emitter = event_emitter
        self._clock = clock
        self._wall_clock = wall_clock
        self._readers = readers or _WindowsResourceReaders(clock=clock)
        self._real_test_failure_reporter = real_test_failure_reporter
        self._detector = _ResourceAlertDetector(self.CONFIRMING_SAMPLES)
        self._history: deque[dict[str, object]] = deque(maxlen=self.HISTORY_SIZE)
        self._latest: dict[str, object] = {
            "host": {},
            "backend": {
                "test_worker_registered": False,
                "ocr_worker_registered": False,
            },
            "detector": self._detector.public_state(),
            "observed_at": self._utc_now(),
        }
        self._state_lock = threading.RLock()
        self._lifecycle_lock = threading.Lock()
        self._sampling_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._sampler_manages_reader_cleanup = False
        self._worker_process: object | None = None
        self._worker_stop_event: object | None = None
        self._worker_baseline_event: object | None = None
        self._worker_detection_event: object | None = None
        self._worker_persistence_failed_event: object | None = None
        self._worker_cancel_event: object | None = None
        self._worker_generation: object | None = None
        self._worker_pid: int | None = None
        self._worker_kind: str | None = None
        self._worker_temp_dir: str | None = None
        self._worker_effective_thresholds: dict[str, float] = {}
        self._worker_failure_receiver: object | None = None
        self._ocr_worker_pid: int | None = None

    def start(self) -> bool:
        with self._lifecycle_lock:
            with self._state_lock:
                if self._thread is not None and self._thread.is_alive():
                    return not self._stop_event.is_set()
                self._stop_event.clear()
                self._thread = threading.Thread(
                    target=self._sampling_loop,
                    name="ResourceMonitor",
                    daemon=True,
                )
                self._sampler_manages_reader_cleanup = True
                try:
                    self._thread.start()
                except Exception:
                    self._thread = None
                    self._sampler_manages_reader_cleanup = False
                    self._stop_event.set()
                    raise
                return True

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop_event.set()
            with self._state_lock:
                thread = self._thread
                sampler_manages_cleanup = self._sampler_manages_reader_cleanup
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=self.STOP_JOIN_SECONDS)
            with self._state_lock:
                if self._thread is thread and (thread is None or not thread.is_alive()):
                    self._thread = None
                    self._sampler_manages_reader_cleanup = False
                sampling_stopped = self._thread is None
            self._cleanup_registered_worker(cancelled=True)
            if sampling_stopped and not sampler_manages_cleanup:
                self._close_readers()

    def latest_public_snapshot(self) -> dict[str, object]:
        with self._state_lock:
            return copy.deepcopy(self._latest)

    def register_ocr_worker_pid(self, pid: int | None) -> None:
        """Include the long-lived OCR child in ordinary backend telemetry."""

        normalized = int(pid) if pid is not None and int(pid) > 0 else None
        with self._state_lock:
            self._ocr_worker_pid = normalized

    def sample_once(self) -> dict[str, object]:
        with self._sampling_lock:
            return self._sample_once_locked()

    def _sample_once_locked(self) -> dict[str, object]:
        host = self._read_host()
        backend, sampled_worker = self._read_backend_with_registered_worker()
        try:
            raw_context = self._context_provider()
        except Exception:
            raw_context = {}
        context: dict[str, int] = {}
        if isinstance(raw_context, Mapping):
            for key in _CONTEXT_PUBLIC_KEYS:
                try:
                    context[key] = max(0, int(raw_context.get(key, 0)))
                except (TypeError, ValueError, OverflowError):
                    context[key] = 0
        backend.update(context)
        observed_at = self._utc_now()
        sample = {
            "host": host,
            "backend": backend,
            "observed_at": observed_at,
        }
        with self._state_lock:
            (
                sampled_process,
                sampled_pid,
                sampled_kind,
                sampled_generation,
                detection_event,
                persistence_failed_event,
                effective_thresholds,
            ) = sampled_worker
            current_worker_matches_sample = (
                self._worker_process is sampled_process
                and self._worker_pid == sampled_pid
                and self._worker_kind == sampled_kind
                and self._worker_generation is sampled_generation
                and self._worker_detection_event is detection_event
                and self._worker_persistence_failed_event is persistence_failed_event
            )
            if not current_worker_matches_sample:
                return copy.deepcopy(self._latest)
            self._history.append(copy.deepcopy(sample))
            try:
                settings = dict(self._settings_provider())
            except Exception:
                settings = {}
            expected_metric = _REAL_TEST_TRIGGER_METRICS.get(sampled_kind or "")
            same_worker = (
                sampled_process is not None
                and sampled_pid is not None
                and sampled_generation is not None
                and detection_event is not None
            )
            triggers = self._detector.observe(
                backend,
                settings,
                observed_at,
                effective_thresholds=effective_thresholds if same_worker else None,
            )
            details = [
                (
                    self._diagnostic_details(sample, trigger),
                    same_worker and trigger.get("metric") == expected_metric,
                )
                for trigger in triggers
            ]
            self._latest = {
                **copy.deepcopy(sample),
                "detector": self._detector.public_state(),
            }
            public = copy.deepcopy(self._latest)
        for diagnostic, confirms_real_test in details:
            persisted = self._emit("warning", "backend.resource_high", diagnostic)
            if confirms_real_test:
                self._record_real_test_trigger_persistence(
                    sampled_process,
                    sampled_pid,
                    sampled_kind,
                    sampled_generation,
                    detection_event,
                    persistence_failed_event,
                    persisted,
                )
        return public

    def record_safe_simulation(self) -> dict[str, object]:
        snapshot = self.latest_public_snapshot()
        details = {
            "test_mode": "safe",
            "simulated": True,
            "observed_at": self._utc_now(),
            "snapshot": snapshot,
        }
        if not self._emit("info", "backend.resource_test", details):
            return {
                "ok": False,
                "test_mode": "safe",
                "status": "persistence_failed",
                "resources": snapshot,
            }
        return {"ok": True, "test_mode": "safe", "resources": snapshot}

    def start_real_test(self, kind: str) -> dict[str, object]:
        normalized_kind = str(kind).strip().lower()
        if normalized_kind not in {"cpu", "memory", "disk"}:
            raise ValueError("unsupported real-test kind")

        process: object
        temp_dir: str
        launch_failed = False
        failure_receiver: object | None = None
        failure_sender: object | None = None
        with self._state_lock:
            if self._worker_process is not None or self._worker_temp_dir is not None:
                raise RuntimeError("a real resource test is already running")
            effective_thresholds = self._effective_real_test_thresholds(
                normalized_kind
            )
            temp_dir = ""
            try:
                temp_dir = tempfile.mkdtemp(prefix="picsyncra_resource_test_")
                stop_event = multiprocessing.Event()
                baseline_event = multiprocessing.Event()
                detection_event = multiprocessing.Event()
                persistence_failed_event = multiprocessing.Event()
                cancel_event = multiprocessing.Event()
                failure_receiver, failure_sender = multiprocessing.Pipe(duplex=False)
                process = multiprocessing.Process(
                    target=_resource_test_worker,
                    args=(
                        normalized_kind,
                        stop_event,
                        self.REAL_TEST_SECONDS,
                        temp_dir,
                        self.MAX_TEST_MEMORY_BYTES,
                        self.MAX_TEST_DISK_BYTES,
                        self.MAX_TEST_DISK_RATE_BYTES_PER_SECOND,
                        baseline_event,
                        detection_event,
                        self.DISK_BASELINE_WAIT_SECONDS,
                        max(1, os.cpu_count() or 1),
                        failure_sender,
                    ),
                    daemon=True,
                )
            except Exception:
                _close_worker_connection(failure_receiver)
                _close_worker_connection(failure_sender)
                cleanup_ok = self._remove_worker_temp_dir(temp_dir)
                if not cleanup_ok:
                    self._worker_kind = normalized_kind
                    self._worker_temp_dir = temp_dir
                    self._set_cached_worker_registration_locked(True)
                return {
                    "ok": False,
                    "kind": normalized_kind,
                    "status": "launch_failed" if cleanup_ok else "cleanup_failed",
                    "timed_out": False,
                }
            self._worker_process = process
            self._worker_stop_event = stop_event
            self._worker_baseline_event = baseline_event
            self._worker_detection_event = detection_event
            self._worker_persistence_failed_event = persistence_failed_event
            self._worker_cancel_event = cancel_event
            self._worker_generation = object()
            self._worker_pid = None
            self._worker_kind = normalized_kind
            self._worker_temp_dir = temp_dir
            self._worker_effective_thresholds = effective_thresholds
            self._worker_failure_receiver = failure_receiver
            self._set_cached_worker_registration_locked(True)
            try:
                process.start()
            except Exception:
                launch_failed = True
            else:
                self._worker_pid = getattr(process, "pid", None)
            _close_worker_connection(failure_sender)

        result: dict[str, object] = {
            "ok": False,
            "kind": normalized_kind,
            "status": "supervision_failed",
            "timed_out": False,
        }
        cleanup_ok = False
        try:
            if launch_failed:
                result = {
                    "ok": False,
                    "kind": normalized_kind,
                    "status": "launch_failed",
                    "timed_out": False,
                }
            else:
                process.join(
                    timeout=self.REAL_TEST_SECONDS + self.REAL_TEST_GRACE_SECONDS
                )
                timed_out = bool(process.is_alive())
                if timed_out:
                    result = {
                        "ok": False,
                        "kind": normalized_kind,
                        "status": "timeout",
                        "timed_out": True,
                    }
                else:
                    exit_code = getattr(process, "exitcode", None)
                    detected = _event_is_set(detection_event)
                    persistence_failed = _event_is_set(persistence_failed_event)
                    failure_report = self._take_worker_failure(process)
                    if failure_report:
                        self._report_real_test_worker_failure(
                            normalized_kind, failure_report
                        )
                        result = {
                            "ok": False,
                            "kind": normalized_kind,
                            "status": "failed",
                            "timed_out": False,
                        }
                    elif exit_code == 0 and persistence_failed:
                        result = {
                            "ok": False,
                            "kind": normalized_kind,
                            "status": "persistence_failed",
                            "timed_out": False,
                        }
                    elif exit_code == 0 and detected:
                        result = {
                            "ok": True,
                            "kind": normalized_kind,
                            "status": "detected",
                            "timed_out": False,
                        }
                    elif exit_code == 0:
                        result = {
                            "ok": False,
                            "kind": normalized_kind,
                            "status": "not_detected",
                            "timed_out": False,
                        }
                    else:
                        result = {
                            "ok": False,
                            "kind": normalized_kind,
                            "status": "failed",
                            "timed_out": False,
                        }
        except Exception:
            result = {
                "ok": False,
                "kind": normalized_kind,
                "status": "supervision_failed",
                "timed_out": False,
            }
        finally:
            cleanup_ok = self._cleanup_registered_worker(expected_process=process)
            if _event_is_set(cancel_event):
                result = {
                    "ok": False,
                    "kind": normalized_kind,
                    "status": "cancelled",
                    "timed_out": False,
                }
        if not cleanup_ok:
            result.update(ok=False, status="cleanup_failed")
        return result

    def _sampling_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    self.sample_once()
                except Exception:
                    pass
                self._stop_event.wait(self.SAMPLE_SECONDS)
        finally:
            self._close_readers()
            current = threading.current_thread()
            with self._state_lock:
                if self._thread is current:
                    self._thread = None
                    self._sampler_manages_reader_cleanup = False

    def _close_readers(self) -> None:
        close = getattr(self._readers, "close", None)
        if callable(close):
            with self._sampling_lock:
                try:
                    close()
                except Exception:
                    pass

    def _read_host(self) -> dict[str, object]:
        try:
            return _safe_metrics(self._readers.read_host(), _HOST_PUBLIC_KEYS)
        except Exception:
            return {"available": False}

    def _read_backend_with_registered_worker(
        self,
    ) -> tuple[
        dict[str, object],
        tuple[
            object | None,
            int | None,
            str | None,
            object | None,
            object | None,
            object | None,
            dict[str, float],
        ],
    ]:
        with self._state_lock:
            worker_process = self._worker_process
            worker_pid = self._worker_pid
            worker_kind = self._worker_kind
            worker_generation = self._worker_generation
            baseline_event = self._worker_baseline_event
            detection_event = self._worker_detection_event
            persistence_failed_event = self._worker_persistence_failed_event
            effective_thresholds = dict(self._worker_effective_thresholds)
            ocr_worker_pid = self._ocr_worker_pid
            registered = (
                worker_process is not None or self._worker_temp_dir is not None
            )
            sampled_worker = (
                worker_process,
                worker_pid,
                worker_kind,
                worker_generation,
                detection_event,
                persistence_failed_event,
                effective_thresholds,
            )
        try:
            read_with_baseline = getattr(
                self._readers, "read_backend_with_worker_baseline", None
            )
            if (
                worker_kind == "disk"
                and worker_pid is not None
                and baseline_event is not None
                and callable(read_with_baseline)
            ):
                raw_backend = read_with_baseline(worker_pid, baseline_event)
            else:
                raw_backend = self._readers.read_backend(worker_pid or ocr_worker_pid)
            backend = _safe_metrics(
                raw_backend, _BACKEND_PUBLIC_KEYS
            )
        except Exception:
            backend = {"available": False}
        backend["test_worker_registered"] = registered
        if registered:
            backend["test_worker_kind"] = worker_kind
        backend["ocr_worker_registered"] = ocr_worker_pid is not None
        if ocr_worker_pid is not None:
            backend["ocr_worker_pid"] = ocr_worker_pid
        return backend, sampled_worker

    def _record_real_test_trigger_persistence(
        self,
        sampled_process: object | None,
        sampled_pid: int | None,
        sampled_kind: str | None,
        sampled_generation: object | None,
        detection_event: object | None,
        persistence_failed_event: object | None,
        persisted: bool,
    ) -> None:
        with self._state_lock:
            current_worker_matches_sample = (
                self._worker_process is sampled_process
                and self._worker_pid == sampled_pid
                and self._worker_kind == sampled_kind
                and self._worker_generation is sampled_generation
                and self._worker_detection_event is detection_event
                and self._worker_persistence_failed_event is persistence_failed_event
            )
            if not current_worker_matches_sample:
                return
            outcome_event = detection_event if persisted else persistence_failed_event
            if outcome_event is None:
                return
            try:
                outcome_event.set()
            except Exception:
                pass

    def _diagnostic_details(
        self, sample: Mapping[str, object], trigger: Mapping[str, object]
    ) -> dict[str, object]:
        with self._state_lock:
            worker_state = {
                "registered": (
                    self._worker_process is not None
                    or self._worker_temp_dir is not None
                ),
                "kind": self._worker_kind,
                "pid": self._worker_pid,
            }
            history = copy.deepcopy(list(self._history))
        return {
            "trigger": dict(trigger),
            "sample": copy.deepcopy(dict(sample)),
            "history": history,
            "test_worker": worker_state,
        }

    def _effective_real_test_thresholds(self, kind: str) -> dict[str, float]:
        latest = self._latest
        backend = latest.get("backend", {})
        if not isinstance(backend, Mapping):
            backend = {}
        host = latest.get("host", {})
        if not isinstance(host, Mapping):
            host = {}
        metric = _REAL_TEST_TRIGGER_METRICS[kind]
        baseline = max(0.0, _number(backend.get(metric)) or 0.0)
        if kind == "cpu":
            capacity = max(0.0, self.MAX_TEST_CPU_PERCENT - baseline)
        elif kind == "memory":
            total = _number(host.get("memory_total_bytes"))
            if total is None or total <= 0:
                raise RuntimeError(
                    "cannot determine system memory for the real memory test"
                )
            capacity = self.MAX_TEST_MEMORY_BYTES / total * 100.0
        else:
            capacity = self.MAX_TEST_DISK_RATE_BYTES_PER_SECOND
        return {
            metric: baseline + capacity * self.REAL_TEST_TARGET_FRACTION,
        }

    def _take_worker_failure(self, expected_process: object) -> str:
        with self._state_lock:
            if self._worker_process is not expected_process:
                return ""
            receiver = self._worker_failure_receiver
        if receiver is None:
            return ""
        try:
            if not bool(receiver.poll()):
                return ""
            report = receiver.recv()
        except Exception:
            return ""
        if isinstance(report, Mapping):
            report = report.get("traceback", "")
        return sanitize_free_text(report, limit=32 * 1024)

    def _report_real_test_worker_failure(self, kind: str, report: str) -> None:
        reporter = self._real_test_failure_reporter
        if reporter is None:
            return
        try:
            reporter(kind, report)
        except Exception:
            pass

    def _cleanup_registered_worker(
        self,
        expected_process: object | None = None,
        *,
        cancelled: bool = False,
    ) -> bool:
        with self._state_lock:
            process = self._worker_process
            if expected_process is not None and process is not expected_process:
                return True
            stop_event = self._worker_stop_event
            cancel_event = self._worker_cancel_event
            failure_receiver = self._worker_failure_receiver
            temp_dir = self._worker_temp_dir
            if cancelled and cancel_event is not None:
                try:
                    cancel_event.set()
                except Exception:
                    pass
            if stop_event is not None:
                try:
                    stop_event.set()
                except Exception:
                    pass
            alive: bool | None = False
            if process is not None:
                alive = self._worker_is_alive(process)
                if alive is not False:
                    self._worker_join(process)
                    alive = self._worker_is_alive(process)
                if alive is not False:
                    try:
                        process.terminate()
                    except Exception:
                        pass
                    self._worker_join(process)
                    alive = self._worker_is_alive(process)
                if alive is not False:
                    kill = getattr(process, "kill", None)
                    kill_succeeded = False
                    if callable(kill):
                        try:
                            kill()
                            kill_succeeded = True
                        except Exception:
                            pass
                    join_succeeded = self._worker_join(process)
                    alive = self._worker_is_alive(process)
                    if alive is None and kill_succeeded and join_succeeded:
                        alive = False
            if alive is not False:
                return False
            if process is not None:
                close = getattr(process, "close", None)
                if callable(close):
                    try:
                        close()
                    except (AssertionError, ValueError):
                        pass
                    except Exception:
                        return False
            if not self._remove_worker_temp_dir(temp_dir):
                return False
            _close_worker_connection(failure_receiver)
            self._worker_process = None
            self._worker_stop_event = None
            self._worker_baseline_event = None
            self._worker_detection_event = None
            self._worker_persistence_failed_event = None
            self._worker_cancel_event = None
            self._worker_generation = None
            self._worker_pid = None
            self._worker_kind = None
            self._worker_temp_dir = None
            self._worker_effective_thresholds = {}
            self._worker_failure_receiver = None
            self._set_cached_worker_registration_locked(False)
            return True

    def _set_cached_worker_registration_locked(self, registered: bool) -> None:
        latest_backend = self._latest.get("backend")
        if not isinstance(latest_backend, Mapping):
            return
        public_backend = copy.deepcopy(dict(latest_backend))
        public_backend["test_worker_registered"] = registered
        if registered:
            public_backend["test_worker_kind"] = self._worker_kind
        else:
            public_backend.pop("test_worker_kind", None)
        self._latest = {**self._latest, "backend": public_backend}

    @staticmethod
    def _worker_is_alive(process: object) -> bool | None:
        try:
            return bool(process.is_alive())
        except (AssertionError, ValueError):
            return False
        except Exception:
            return None

    @staticmethod
    def _worker_join(process: object) -> bool:
        try:
            process.join(timeout=1.0)
            return True
        except (AssertionError, ValueError):
            return True
        except Exception:
            return False

    @staticmethod
    def _remove_worker_temp_dir(temp_dir: str | None) -> bool:
        if not temp_dir:
            return True
        try:
            shutil.rmtree(temp_dir)
            return not Path(temp_dir).exists()
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def _emit(self, severity: str, event_type: str, details: dict[str, object]) -> bool:
        try:
            return self._event_emitter(
                severity, event_type, copy.deepcopy(details)
            ) is True
        except Exception:
            return False

    def _utc_now(self) -> str:
        return datetime.fromtimestamp(self._wall_clock(), timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )


def _resource_test_worker(
    kind: str,
    stop_event: object,
    seconds: float,
    temp_dir: str,
    memory_bytes: int,
    disk_bytes: int,
    disk_rate_bytes_per_second: float,
    disk_baseline_event: object,
    detection_event: object,
    disk_baseline_wait_seconds: float,
    logical_cpus: int,
    failure_sender: object | None = None,
) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    try:
        if kind == "cpu":
            _run_cpu_test(stop_event, deadline, logical_cpus, detection_event)
        elif kind == "memory":
            _run_memory_test(stop_event, deadline, memory_bytes, detection_event)
        elif kind == "disk":
            _run_disk_test(
                stop_event,
                deadline,
                Path(temp_dir),
                disk_bytes,
                disk_rate_bytes_per_second,
                disk_baseline_event,
                detection_event,
                disk_baseline_wait_seconds,
            )
    except Exception as exc:
        _send_worker_failure(failure_sender, kind, exc)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        _close_worker_connection(failure_sender)


def _send_worker_failure(
    sender: object | None, kind: str, exc: BaseException
) -> None:
    if sender is None:
        return
    report = sanitize_free_text(
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        limit=32 * 1024,
    )
    try:
        sender.send(
            {
                "kind": str(kind),
                "exception_type": type(exc).__name__,
                "traceback": report,
            }
        )
    except Exception:
        pass


def _close_worker_connection(connection: object | None) -> None:
    if connection is None:
        return
    close = getattr(connection, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _event_is_set(event: object) -> bool:
    try:
        return bool(event.is_set())
    except Exception:
        return False


def _should_stop(stop_event: object, deadline: float) -> bool:
    return _event_is_set(stop_event) or time.monotonic() >= deadline


def _should_finish(
    stop_event: object, detection_event: object | None, deadline: float
) -> bool:
    return _should_stop(stop_event, deadline) or (
        detection_event is not None and _event_is_set(detection_event)
    )


def _run_cpu_test(
    stop_event: object,
    deadline: float,
    logical_cpus: int,
    detection_event: object | None = None,
) -> None:
    target_cores = max(1, math.ceil(logical_cpus * 0.25))
    duty_cycle = min(1.0, logical_cpus * 0.25 / target_cores)

    def load() -> None:
        payload = bytes(256 * 1024)
        while not _should_finish(stop_event, detection_event, deadline):
            cycle_start = time.monotonic()
            busy_until = cycle_start + 0.05 * duty_cycle
            while time.monotonic() < busy_until and not _should_finish(
                stop_event, detection_event, deadline
            ):
                hashlib.sha256(payload).digest()
            remaining = 0.05 - (time.monotonic() - cycle_start)
            if remaining > 0:
                time.sleep(min(remaining, 0.05))

    threads = [threading.Thread(target=load, daemon=True) for _ in range(target_cores)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()) + 0.1)


def _run_memory_test(
    stop_event: object,
    deadline: float,
    memory_bytes: int,
    detection_event: object | None = None,
) -> None:
    allocations: list[bytearray] = []
    remaining = max(0, memory_bytes)
    chunk_size = 8 * MIB
    while remaining and not _should_finish(stop_event, detection_event, deadline):
        size = min(chunk_size, remaining)
        allocations.append(bytearray(size))
        remaining -= size
    while allocations and not _should_finish(stop_event, detection_event, deadline):
        time.sleep(0.05)
    allocations.clear()


def _run_disk_test(
    stop_event: object,
    deadline: float,
    temp_dir: Path,
    disk_bytes: int,
    rate_bytes_per_second: float,
    baseline_ready_event: object | None = None,
    detection_event: object | None = None,
    baseline_wait_seconds: float = 0.0,
) -> bool:
    temp_dir.mkdir(parents=True, exist_ok=True)
    path = temp_dir / "resource-test.bin"
    chunk = bytes(64 * 1024)
    remaining = max(0, disk_bytes)
    written = 0
    bounded_rate = max(1.0, float(rate_bytes_per_second))
    try:
        baseline_deadline = min(
            deadline, time.monotonic() + max(0.0, baseline_wait_seconds)
        )
        while baseline_ready_event is not None and not _event_is_set(
            baseline_ready_event
        ):
            if _should_stop(stop_event, deadline):
                return False
            remaining_wait = baseline_deadline - time.monotonic()
            if remaining_wait <= 0:
                return False
            time.sleep(min(0.05, remaining_wait))
        started_at = time.monotonic()
        with path.open("wb", buffering=0) as handle:
            while remaining and not _should_stop(stop_event, deadline):
                if detection_event is not None and _event_is_set(detection_event):
                    return True
                piece = chunk if remaining >= len(chunk) else chunk[:remaining]
                write_at = started_at + (written + len(piece)) / bounded_rate
                while True:
                    remaining_wait = write_at - time.monotonic()
                    if remaining_wait <= 0:
                        break
                    if _should_stop(stop_event, deadline):
                        return False
                    if detection_event is not None and _event_is_set(detection_event):
                        return True
                    time.sleep(min(0.05, remaining_wait))
                handle.write(piece)
                written += len(piece)
                remaining -= len(piece)
            if detection_event is None:
                return remaining == 0
            while not _event_is_set(detection_event):
                if _should_stop(stop_event, deadline):
                    return False
                time.sleep(0.05)
            return True
    finally:
        path.unlink(missing_ok=True)


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


def _filetime_value(value: _FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


class _WindowsResourceReaders:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._logical_cpus = max(1, os.cpu_count() or 1)
        self._system_previous: tuple[int, int, int] | None = None
        self._process_previous: dict[int, tuple[float, int, int, int]] = {}
        self._pdh_query = wintypes.HANDLE()
        self._pdh_counter = wintypes.HANDLE()
        self._pdh_ready = False
        self._kernel32 = None
        self._psapi = None
        self._pdh = None
        if os.name == "nt":
            try:
                self._bind_core_windows_apis()
            except Exception:
                self._kernel32 = None
                self._psapi = None
            try:
                self._bind_pdh_api()
            except Exception:
                self._pdh = None
                self._pdh_query = wintypes.HANDLE()
                self._pdh_counter = wintypes.HANDLE()
                self._pdh_ready = False

    def _bind_core_windows_apis(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)

        kernel32.GetSystemTimes.argtypes = [
            ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME),
        ]
        kernel32.GetSystemTimes.restype = wintypes.BOOL
        kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]
        kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.GetProcessIoCounters.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_IO_COUNTERS),
        ]
        kernel32.GetProcessIoCounters.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        self._kernel32 = kernel32
        self._psapi = psapi

    def _bind_pdh_api(self) -> None:
        pdh = ctypes.WinDLL("pdh", use_last_error=True)
        pdh.PdhOpenQueryW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_size_t,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        pdh.PdhOpenQueryW.restype = wintypes.LONG
        pdh.PdhAddEnglishCounterW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCWSTR,
            ctypes.c_size_t,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        pdh.PdhAddEnglishCounterW.restype = wintypes.LONG
        pdh.PdhCollectQueryData.argtypes = [wintypes.HANDLE]
        pdh.PdhCollectQueryData.restype = wintypes.LONG
        pdh.PdhGetFormattedCounterValue.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(_PDH_FMT_COUNTERVALUE),
        ]
        pdh.PdhGetFormattedCounterValue.restype = wintypes.LONG
        pdh.PdhCloseQuery.argtypes = [wintypes.HANDLE]
        pdh.PdhCloseQuery.restype = wintypes.LONG
        self._pdh = pdh

    def read_host(self) -> dict[str, object]:
        memory = self._read_memory()
        return {
            "cpu_percent": self._read_system_cpu(),
            **memory,
            "disk_busy_percent": self._read_disk_busy(),
        }

    def close(self) -> None:
        self._close_pdh_query()

    def _close_pdh_query(self) -> None:
        if self._pdh is not None and self._pdh_query:
            try:
                self._pdh.PdhCloseQuery(self._pdh_query)
            except Exception:
                pass
        self._pdh_query = wintypes.HANDLE()
        self._pdh_counter = wintypes.HANDLE()
        self._pdh_ready = False

    def read_backend(self, worker_pid: int | None = None) -> dict[str, object]:
        return self._read_backend(worker_pid, None)

    def read_backend_with_worker_baseline(
        self, worker_pid: int, baseline_ready_event: object
    ) -> dict[str, object]:
        return self._read_backend(worker_pid, baseline_ready_event)

    def _read_backend(
        self,
        worker_pid: int | None,
        baseline_ready_event: object | None,
    ) -> dict[str, object]:
        if os.name != "nt":
            return {"available": False}
        pids = [os.getpid()]
        if worker_pid and worker_pid not in pids:
            pids.append(worker_pid)
        now = self._clock()
        process_values: dict[int, tuple[int, int, int, int, int]] = {}
        for pid in pids:
            values = self._read_process(pid)
            if values is None:
                return {"available": False}
            process_values[pid] = values
        total_memory = _number(self._read_memory().get("memory_total_bytes"))
        if total_memory is None or total_memory <= 0:
            return {"available": False}

        total_cpu = 0.0
        working_set = 0
        private_bytes = 0
        read_rate = 0.0
        write_rate = 0.0
        worker_baseline_pending = (
            worker_pid is not None
            and baseline_ready_event is not None
            and not _event_is_set(baseline_ready_event)
        )
        for pid, values in process_values.items():
            cpu_time, working, private, read_bytes, write_bytes = values
            working_set += working
            private_bytes += private
            previous = self._process_previous.get(pid)
            if pid == worker_pid and worker_baseline_pending:
                previous = None
            if previous is not None:
                previous_at, previous_cpu, previous_read, previous_write = previous
                elapsed = max(0.0, now - previous_at)
                if elapsed > 0:
                    total_cpu += max(0.0, cpu_time - previous_cpu) / 10_000_000 / elapsed * 100.0 / self._logical_cpus
                    read_rate += max(0, read_bytes - previous_read) / elapsed
                    write_rate += max(0, write_bytes - previous_write) / elapsed
            self._process_previous[pid] = (now, cpu_time, read_bytes, write_bytes)
        self._process_previous = {
            pid: value for pid, value in self._process_previous.items() if pid in process_values
        }
        if worker_baseline_pending:
            try:
                baseline_ready_event.set()
            except Exception:
                pass
        memory_percent = working_set / total_memory * 100.0
        return {
            "cpu_percent": round(total_cpu, 2),
            "memory_working_set_bytes": working_set,
            "memory_private_bytes": private_bytes,
            "memory_percent": round(memory_percent, 2),
            "disk_read_bytes_per_second": round(read_rate, 2),
            "disk_write_bytes_per_second": round(write_rate, 2),
            "disk_io_bytes_per_second": round(read_rate + write_rate, 2),
        }

    def _read_system_cpu(self) -> float | dict[str, object]:
        if os.name != "nt":
            return {"available": False}
        idle = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        try:
            if self._kernel32 is None or not self._kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            ):
                return {"available": False}
        except Exception:
            return {"available": False}
        current = (_filetime_value(idle), _filetime_value(kernel), _filetime_value(user))
        previous = self._system_previous
        self._system_previous = current
        if previous is None:
            return 0.0
        idle_delta = current[0] - previous[0]
        total_delta = current[1] - previous[1] + current[2] - previous[2]
        if total_delta <= 0:
            return 0.0
        return round(max(0.0, min(100.0, (total_delta - idle_delta) / total_delta * 100.0)), 2)

    def _read_memory(self) -> dict[str, object]:
        if os.name != "nt":
            return {
                "memory_percent": {"available": False},
                "memory_used_bytes": {"available": False},
                "memory_total_bytes": {"available": False},
            }
        status = _MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        try:
            if self._kernel32 is None or not self._kernel32.GlobalMemoryStatusEx(
                ctypes.byref(status)
            ):
                raise OSError
        except Exception:
            return {
                "memory_percent": {"available": False},
                "memory_used_bytes": {"available": False},
                "memory_total_bytes": {"available": False},
            }
        total = int(status.ullTotalPhys)
        available = int(status.ullAvailPhys)
        return {
            "memory_percent": float(status.dwMemoryLoad),
            "memory_used_bytes": max(0, total - available),
            "memory_total_bytes": total,
        }

    def _read_process(self, pid: int) -> tuple[int, int, int, int, int] | None:
        kernel32 = self._kernel32
        psapi = self._psapi
        if kernel32 is None or psapi is None:
            return None
        close_handle = False
        if pid == os.getpid():
            handle = kernel32.GetCurrentProcess()
        else:
            handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
            close_handle = True
        if not handle:
            return None
        try:
            creation = _FILETIME()
            exit_time = _FILETIME()
            kernel = _FILETIME()
            user = _FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            memory = _PROCESS_MEMORY_COUNTERS_EX()
            memory.cb = ctypes.sizeof(memory)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                return None
            io = _IO_COUNTERS()
            if not kernel32.GetProcessIoCounters(handle, ctypes.byref(io)):
                return None
            return (
                _filetime_value(kernel) + _filetime_value(user),
                int(memory.WorkingSetSize),
                int(memory.PrivateUsage),
                int(io.ReadTransferCount),
                int(io.WriteTransferCount),
            )
        finally:
            if close_handle:
                kernel32.CloseHandle(handle)

    def _read_disk_busy(self) -> float | dict[str, object]:
        if os.name != "nt":
            return {"available": False}
        try:
            pdh = self._pdh
            if pdh is None:
                return {"available": False}
            if not self._pdh_ready:
                if pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._pdh_query)) != 0:
                    self._close_pdh_query()
                    return {"available": False}
                if pdh.PdhAddEnglishCounterW(
                    self._pdh_query,
                    r"\PhysicalDisk(_Total)\% Disk Time",
                    0,
                    ctypes.byref(self._pdh_counter),
                ) != 0:
                    self._close_pdh_query()
                    return {"available": False}
                if pdh.PdhCollectQueryData(self._pdh_query) != 0:
                    self._close_pdh_query()
                    return {"available": False}
                self._pdh_ready = True
                return {"available": False, "reason": "warming_up"}
            if pdh.PdhCollectQueryData(self._pdh_query) != 0:
                self._close_pdh_query()
                return {"available": False}
            value = _PDH_FMT_COUNTERVALUE()
            if pdh.PdhGetFormattedCounterValue(
                self._pdh_counter, 0x00000200, None, ctypes.byref(value)
            ) != 0:
                self._close_pdh_query()
                return {"available": False}
            if int(value.CStatus) not in {0, 1}:
                self._close_pdh_query()
                return {"available": False}
            return round(max(0.0, min(100.0, float(value.doubleValue))), 2)
        except Exception:
            self._close_pdh_query()
            return {"available": False}
