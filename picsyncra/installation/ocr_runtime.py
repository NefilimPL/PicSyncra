"""Closed stdin/stdout protocol shared with the installed OCR runtime."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
from threading import Thread, RLock, Event
import time
from typing import Callable, Mapping, TextIO

from .contracts import InstallContext
from .ocr_component import resolve_active_ocr_component


OCR_PROTOCOL_VERSION = 1
MAX_OCR_MESSAGE_BYTES = 8 * 1024
# Commands contain paths and profile IDs; results also contain every OCR box.
MAX_OCR_EVENT_BYTES = 8 * 1024 * 1024
_MESSAGE_KINDS = frozenset(
    {
        "hello",
        "ready",
        "stage_started",
        "result",
        "error",
        "job",
        "update_limits",
        "limits_updated",
        "stop",
    }
)


class OcrRuntimeProtocolError(ValueError):
    """A runtime message violates the fixed OCR IPC contract."""


def _launch_runtime(arguments: list[str]) -> subprocess.Popen[str]:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        arguments,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        bufsize=1,
        creationflags=creation_flags,
    )


def parse_ocr_message(raw: str, *, max_bytes: int = MAX_OCR_MESSAGE_BYTES) -> dict[str, object]:
    """Decode one bounded JSON message without accepting arbitrary commands."""

    if not isinstance(raw, str) or len(raw.encode("utf-8")) > max_bytes:
        raise OcrRuntimeProtocolError("OCR runtime message is too large.")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise OcrRuntimeProtocolError("OCR runtime message is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise OcrRuntimeProtocolError("OCR runtime message must be an object.")
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in _MESSAGE_KINDS:
        raise OcrRuntimeProtocolError("OCR runtime message kind is not supported.")
    return {str(key): value for key, value in payload.items()}


def validate_ocr_hello(
    hello: Mapping[str, object],
    *,
    expected_build_id: str,
    expected_component_id: str,
) -> dict[str, object]:
    """Confirm that a launched runtime belongs to the selected release."""

    if not isinstance(hello, Mapping) or set(hello) != {
        "kind",
        "protocol",
        "build_id",
        "component_id",
    }:
        raise OcrRuntimeProtocolError("OCR runtime hello has an invalid schema.")
    if hello.get("kind") != "hello" or hello.get("protocol") != OCR_PROTOCOL_VERSION:
        raise OcrRuntimeProtocolError("OCR runtime protocol is incompatible.")
    if hello.get("build_id") != expected_build_id:
        raise OcrRuntimeProtocolError("OCR runtime build does not match the active release.")
    if hello.get("component_id") != expected_component_id:
        raise OcrRuntimeProtocolError("OCR runtime component does not match the active release.")
    return {str(key): value for key, value in hello.items()}


def build_ocr_job(
    run_id: str,
    path: Path,
    *,
    work_root: Path,
    profile_ids: list[str],
) -> dict[str, object]:
    """Construct the only file-reading runtime command for one job directory."""

    if not isinstance(run_id, str) or not run_id or len(run_id) > 128:
        raise OcrRuntimeProtocolError("OCR run identifier is invalid.")
    if not isinstance(profile_ids, list) or not profile_ids or not all(
        isinstance(profile_id, str) and profile_id for profile_id in profile_ids
    ):
        raise OcrRuntimeProtocolError("OCR profiles are invalid.")
    try:
        root = Path(work_root).resolve(strict=True)
        image = Path(path).resolve(strict=True)
        image.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise OcrRuntimeProtocolError("OCR input must be inside its job directory.") from exc
    if image == root or not image.is_file():
        raise OcrRuntimeProtocolError("OCR input must be a file inside its job directory.")
    return {
        "kind": "job",
        "run_id": run_id,
        "path": str(image),
        "work_root": str(root),
        "profile_ids": list(profile_ids),
    }


class InstalledOcrWorker:
    """Supervise the trusted installed OCR executable over newline-delimited JSON."""

    def __init__(
        self,
        *,
        executable: Path,
        build_id: str,
        component_id: str,
        process_factory=_launch_runtime,
        startup_timeout_seconds: float = 120.0,
    ) -> None:
        if not isinstance(build_id, str) or not build_id:
            raise ValueError("build_id must be non-empty text.")
        if not isinstance(component_id, str) or not component_id:
            raise ValueError("component_id must be non-empty text.")
        self._executable = Path(executable)
        self._build_id = build_id
        self._component_id = component_id
        self._process_factory = process_factory
        if not math.isfinite(startup_timeout_seconds) or startup_timeout_seconds <= 0:
            raise ValueError('OCR startup timeout must be finite and positive.')
        self._startup_timeout_seconds = startup_timeout_seconds
        self._process: object | None = None
        self._events: Queue[dict[str, object]] = Queue()
        self._exit_reported = False

    def start(self) -> None:
        """Launch the component and require its matching hello before any job."""

        if self._process is not None:
            return
        process = self._process_factory(
            [
                str(self._executable),
                "--build-id",
                self._build_id,
                "--component-id",
                self._component_id,
            ]
        )
        stdout = getattr(process, "stdout", None)
        if stdout is None:
            self._terminate(process)
            raise OcrRuntimeProtocolError("OCR runtime does not expose stdout.")
        # Own the child during its handshake, so shutdown can stop it even if
        # it never emits a complete line. A bounded reader also rejects a peer
        # that keeps sending bytes without a newline.
        self._process = process
        reply = Queue()
        def read_hello():
            try: reply.put((stdout.readline(MAX_OCR_MESSAGE_BYTES + 1), None))
            except Exception as exc: reply.put((None, exc))
        reader = Thread(target=read_hello, daemon=True, name='PicSyncraOCRHello')
        reader.start()
        deadline = time.monotonic() + self._startup_timeout_seconds
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OcrRuntimeProtocolError('OCR nie potwierdził gotowości w wymaganym czasie. Ponów zadanie OCR.')
                try:
                    line, error = reply.get(timeout=min(0.1, remaining))
                    break
                except Empty:
                    if self._process is not process or process.poll() is not None:
                        raise OcrRuntimeProtocolError('Proces OCR zakończył pracę przed potwierdzeniem gotowości.')
            if error: raise error
            hello = parse_ocr_message(line.rstrip("\r\n"))
            validate_ocr_hello(
                hello,
                expected_build_id=self._build_id,
                expected_component_id=self._component_id,
            )
        except Exception:
            self._terminate(process)
            reader.join(timeout=1)
            self._process = None
            raise
        self._process = process
        self._exit_reported = False
        Thread(target=self._read_events, args=(process,), daemon=True).start()

    def submit(self, payload: Mapping[str, object]) -> None:
        """Send one closed job payload; arbitrary commands and paths are rejected."""

        if set(payload) != {"run_id", "path", "work_root", "profile_ids"}:
            raise OcrRuntimeProtocolError("OCR job has an invalid schema.")
        command = build_ocr_job(
            str(payload["run_id"]),
            Path(str(payload["path"])),
            work_root=Path(str(payload["work_root"])),
            profile_ids=payload["profile_ids"],  # type: ignore[arg-type]
        )
        self._send(command)

    def poll(self) -> list[dict[str, object]]:
        """Return runtime events and a single explicit event when the process exits."""

        events: list[dict[str, object]] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except Empty:
                break
        process = self._process
        if (
            process is not None
            and getattr(process, "poll")() is not None
            and not self._exit_reported
        ):
            self._exit_reported = True
            events.append({"kind": "error", "code": "runtime_exited"})
        return events

    def poll_events(self) -> list[dict[str, object]]:
        """Compatibility surface used by the existing OCR execution service."""

        return self.poll()

    def update_limits(self, *, cpu_percent: int) -> None:
        if isinstance(cpu_percent, bool) or not isinstance(cpu_percent, int):
            raise ValueError("OCR CPU limit must be an integer.")
        if not 1 <= cpu_percent <= 100:
            raise ValueError("OCR CPU limit must be between 1 and 100.")
        self._send({"kind": "update_limits", "cpu_percent": cpu_percent})

    def status(self) -> dict[str, object]:
        process = self._process
        if process is None:
            return {"pid": None, "alive": False, "exit_code": None}
        exit_code = getattr(process, "poll")()
        return {
            "pid": getattr(process, "pid", None),
            "alive": exit_code is None,
            "exit_code": exit_code,
        }

    def cancel(self, run_id: str) -> None:
        """The closed protocol has no per-job kill; end its single active worker."""

        del run_id
        self.stop(force=True)

    def stop(self, *, force: bool) -> None:
        """Ask the runtime to stop, terminating it only when force is explicit."""

        process = self._process
        if process is None:
            return
        try:
            self._send({"kind": "stop"})
            getattr(process, "wait")(5.0)
        except Exception:
            if force:
                self._terminate(process)
                self._process = None
            return
        self._process = None

    def _send(self, command: dict[str, object]) -> None:
        process = self._process
        if process is None:
            raise OcrRuntimeProtocolError("OCR runtime has not been started.")
        encoded = json.dumps(command, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_OCR_MESSAGE_BYTES:
            raise OcrRuntimeProtocolError("OCR runtime message is too large.")
        stdin = getattr(process, "stdin", None)
        if stdin is None:
            raise OcrRuntimeProtocolError("OCR runtime does not accept commands.")
        stdin.write(encoded + "\n")
        stdin.flush()

    def _read_events(self, process: object) -> None:
        stdout = getattr(process, "stdout", None)
        if stdout is None:
            return
        while True:
            line = stdout.readline(MAX_OCR_EVENT_BYTES + 1)
            if not line:
                return
            try:
                self._events.put(parse_ocr_message(line.rstrip("\r\n"), max_bytes=MAX_OCR_EVENT_BYTES))
            except OcrRuntimeProtocolError:
                self._events.put({"kind": "error", "code": "invalid_runtime_message"})
                if len(line.rstrip("\r\n").encode("utf-8")) > MAX_OCR_EVENT_BYTES:
                    self._terminate(process)
                    return

    @staticmethod
    def _terminate(process: object) -> None:
        try:
            getattr(process, "terminate")()
            try: getattr(process, 'wait')(2.0)
            except (TimeoutError, subprocess.TimeoutExpired):
                getattr(process, 'kill')()
                getattr(process, 'wait')(2.0)
        except Exception:
            pass


class StagedInstalledOcrWorker:
    """Adapt the installed runtime to the existing OCR execution-service worker API."""

    _RUN_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?")

    def __init__(self, *, runtime: object, staging_root: Path) -> None:
        self._runtime = runtime
        self._staging_root = Path(staging_root)
        self._runs: dict[str, Path] = {}
        self._pending_events: list[dict[str, object]] = []

    def start(self) -> None:
        getattr(self._runtime, "start")()

    def submit(
        self,
        *,
        run_id: str,
        path: str,
        profile_ids: list[object],
        resource_settings: dict[str, object] | None = None,
    ) -> None:
        """Copy one source image into the controlled job root before submission."""

        del resource_settings
        if not isinstance(run_id, str) or self._RUN_ID.fullmatch(run_id) is None:
            raise OcrRuntimeProtocolError("OCR run identifier is invalid.")
        if run_id in self._runs:
            raise OcrRuntimeProtocolError("OCR run identifier is already active.")
        try:
            source = Path(path).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise OcrRuntimeProtocolError("OCR source image is unavailable.") from exc
        if not source.is_file():
            raise OcrRuntimeProtocolError("OCR source must be a file.")
        root = self._staging_root.resolve(strict=False)
        run_directory = root / run_id
        suffix = source.suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,10}", source.suffix) else ".img"
        staged_path = run_directory / f"input{suffix.lower()}"
        try:
            run_directory.mkdir(parents=True, exist_ok=False)
            shutil.copy2(source, staged_path)
            getattr(self._runtime, "submit")(
                {
                    "run_id": run_id,
                    "path": str(staged_path),
                    "work_root": str(run_directory),
                    "profile_ids": [str(profile) for profile in profile_ids],
                }
            )
        except Exception:
            self._remove_run_directory(run_directory, root)
            raise
        self._runs[run_id] = run_directory

    def update_telemetry(self, telemetry: object) -> None:
        del telemetry  # Resource policy remains enforced by the WEB execution service.

    def update_limits(self, *, cpu_percent: int) -> None:
        getattr(self._runtime, "update_limits")(cpu_percent=cpu_percent)

    def poll_events(self) -> list[dict[str, object]]:
        events = list(self._pending_events)
        self._pending_events.clear()
        events.extend(getattr(self._runtime, "poll")())
        for event in events:
            run_id = event.get("run_id")
            if (
                isinstance(run_id, str)
                and event.get("kind") in {"result", "error"}
                and run_id in self._runs
            ):
                self._remove_run(run_id)
        return events

    def cancel(self, run_id: str) -> None:
        if run_id not in self._runs:
            return
        getattr(self._runtime, "stop")(force=True)
        self._remove_run(run_id)
        self._pending_events.append(
            {"kind": "error", "run_id": run_id, "message": "OCR job cancelled."}
        )

    def status(self) -> dict[str, object]:
        return dict(getattr(self._runtime, "status")())

    def stop(self, *, timeout: float) -> None:
        del timeout
        getattr(self._runtime, "stop")(force=True)
        for run_id in tuple(self._runs):
            self._remove_run(run_id)

    def _remove_run(self, run_id: str) -> None:
        directory = self._runs.pop(run_id, None)
        if directory is not None:
            self._remove_run_directory(directory, self._staging_root.resolve(strict=False))

    @staticmethod
    def _remove_run_directory(directory: Path, root: Path) -> None:
        try:
            resolved = directory.resolve(strict=True)
            resolved.relative_to(root.resolve(strict=True))
        except (OSError, RuntimeError, ValueError):
            return
        if resolved.is_dir() and not resolved.is_symlink():
            shutil.rmtree(resolved)


class LazyInstalledOcrWorker:
    """Keep OCR verification and handshake outside WEB's startup transaction."""
    deferred_submission = True

    def __init__(self, factory):
        self._factory, self._worker = factory, None
        self._lock = RLock()
        self._start_lock = RLock()
        self._cpu_percent = None
        self._starting = False
        self._starting_worker = None
        self._closed = False
        self._abort_start = Event()
        self._cancelled = set()
        self._initializing_run_id = None
        self._runs = set()
        self._pending_events = Queue()

    def start(self):
        # The independent runtime is needed only when submitting an OCR job.
        pass

    def submit(self, **kwargs):
        with self._start_lock:
            run_id = kwargs.get('run_id')
            if self._closed: raise OcrRuntimeProtocolError('Moduł OCR został zatrzymany.')
            if run_id in self._cancelled: raise OcrRuntimeProtocolError('Anulowano zadanie OCR.')
            if self._worker is not None and self._worker.status().get('alive') is False:
                # Preserve terminal events for the previous generation before
                # replacing it; otherwise its jobs retain maintenance leases.
                terminal = set()
                for event in self._worker.poll_events():
                    self._pending_events.put(event)
                    if event.get('kind') in {'result', 'error'}: terminal.add(event.get('run_id'))
                for previous in tuple(self._runs - terminal):
                    self._pending_events.put({'kind': 'error', 'run_id': previous, 'message': 'Proces OCR zakończył pracę.'})
                self._runs.clear()
                self._worker.stop(timeout=2)
                self._worker = None
            if self._worker is None:
                self._starting = True
                self._initializing_run_id = run_id
                self._abort_start.clear()
                if run_id in self._cancelled or self._closed: self._abort_start.set()
                try: self._start_worker()
                finally:
                    self._starting = False
                    self._initializing_run_id = None
            if run_id in self._cancelled or self._closed: raise OcrRuntimeProtocolError('Anulowano zadanie OCR.')
            self._runs.add(run_id)
            try: self._worker.submit(**kwargs)
            except Exception:
                self._runs.discard(run_id)
                raise

    def _start_worker(self):
        worker = self._factory()
        if worker is None:
            raise OcrRuntimeProtocolError('Nie można uruchomić zweryfikowanego modułu OCR. Sprawdź instalację modułu.')
        try:
            self._starting_worker = worker
            if self._abort_start.is_set() or self._closed: raise OcrRuntimeProtocolError('Anulowano uruchamianie OCR.')
            worker.start()
            if self._abort_start.is_set() or self._closed: raise OcrRuntimeProtocolError('Anulowano uruchamianie OCR.')
            if self._cpu_percent is not None: worker.update_limits(cpu_percent=self._cpu_percent)
        except Exception:
            worker.stop(timeout=2)
            raise
        finally:
            self._starting_worker = None
        self._worker = worker

    def update_limits(self, *, cpu_percent):
        with self._lock:
            self._cpu_percent = cpu_percent
            if self._worker is not None and self._worker.status().get('alive') is not False:
                self._worker.update_limits(cpu_percent=cpu_percent)

    def update_telemetry(self, telemetry):
        if self._worker is not None: self._worker.update_telemetry(telemetry)

    def poll_events(self):
        events = []
        while True:
            try: events.append(self._pending_events.get_nowait())
            except Empty: break
        if self._worker is not None: events.extend(self._worker.poll_events())
        for event in events:
            if event.get('kind') in {'result', 'error'}: self._runs.discard(event.get('run_id'))
        return events

    def status(self):
        if self._starting: return {'pid': None, 'alive': None, 'exit_code': None, 'starting': True}
        return self._worker.status() if self._worker is not None else {'pid': None, 'alive': False, 'exit_code': None}

    def cancel(self, run_id):
        self._cancelled.add(run_id)
        if self._initializing_run_id == run_id:
            self._abort_start.set()
            if self._starting_worker is not None: self._starting_worker.stop(timeout=2)
        if self._worker is not None and run_id in self._runs: self._worker.cancel(run_id)

    def stop(self, *, timeout):
        self._closed = True
        self._abort_start.set()
        worker = self._worker or self._starting_worker
        if worker is not None: worker.stop(timeout=timeout)
        self._worker = None


def create_installed_ocr_worker(
    context: InstallContext,
    *,
    process_factory=_launch_runtime,
    lazy: bool = False,
    cancel_check=None,
) -> StagedInstalledOcrWorker | LazyInstalledOcrWorker | None:
    """Build the WEB-compatible worker only from an active verified component."""

    if lazy:
        from .module_state import read_module_set
        marker = json.loads((context.program_root / 'active.json').read_text(encoding='utf-8'))
        if marker.get('schema') == 2:
            ids = {module.module_id for module in read_module_set(context).modules}
            if not {'ocr_runtime', 'ocr_models'} <= ids: return None
            worker = LazyInstalledOcrWorker(lambda: create_installed_ocr_worker(context, process_factory=process_factory,
                cancel_check=worker._abort_start.is_set))
            return worker
    active = resolve_active_ocr_component(context, **({'cancel_check': cancel_check} if cancel_check else {}))
    if active is None:
        return None
    runtime = InstalledOcrWorker(
        executable=active.directory / "PicSyncra-OCR.exe",
        build_id=active.build_id,
        component_id=active.component_id,
        process_factory=process_factory,
    )
    return StagedInstalledOcrWorker(
        runtime=runtime,
        staging_root=context.state_root / "cache" / "ocr-jobs",
    )


def _write_runtime_message(stdout: TextIO, message: dict[str, object]) -> None:
    encoded = json.dumps(message, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_OCR_EVENT_BYTES:
        raise OcrRuntimeProtocolError("OCR runtime response is too large.")
    stdout.write(encoded + "\n")
    stdout.flush()


def serve_ocr_runtime(
    stdin: TextIO,
    stdout: TextIO,
    *,
    build_id: str,
    component_id: str,
    run_job: Callable[[dict[str, object]], Mapping[str, object]],
) -> int:
    """Run the child-side protocol, repeating all job-path validation locally."""

    _write_runtime_message(
        stdout,
        {
            "kind": "hello",
            "protocol": OCR_PROTOCOL_VERSION,
            "build_id": build_id,
            "component_id": component_id,
        },
    )
    _write_runtime_message(stdout, {"kind": "ready", "pid": os.getpid()})
    for line in stdin:
        try:
            command = parse_ocr_message(line.rstrip("\r\n"))
        except OcrRuntimeProtocolError:
            _write_runtime_message(stdout, {"kind": "error", "code": "invalid_command"})
            continue
        if command.get("kind") == "stop":
            if set(command) != {"kind"}:
                _write_runtime_message(stdout, {"kind": "error", "code": "invalid_command"})
                continue
            return 0
        if command.get("kind") == "update_limits":
            cpu_percent = command.get("cpu_percent")
            if (
                set(command) != {"kind", "cpu_percent"}
                or isinstance(cpu_percent, bool)
                or not isinstance(cpu_percent, int)
                or not 1 <= cpu_percent <= 100
            ):
                _write_runtime_message(stdout, {"kind": "error", "code": "invalid_command"})
                continue
            _write_runtime_message(
                stdout, {"kind": "limits_updated", "cpu_percent": cpu_percent}
            )
            continue
        if command.get("kind") != "job" or set(command) != {
            "kind",
            "run_id",
            "path",
            "work_root",
            "profile_ids",
        }:
            _write_runtime_message(stdout, {"kind": "error", "code": "invalid_command"})
            continue
        try:
            job = build_ocr_job(
                command["run_id"],
                Path(command["path"]),
                work_root=Path(command["work_root"]),
                profile_ids=command["profile_ids"],
            )
        except (OcrRuntimeProtocolError, TypeError):
            _write_runtime_message(stdout, {"kind": "error", "code": "invalid_job"})
            continue
        _write_runtime_message(
            stdout, {"kind": "stage_started", "run_id": job["run_id"], "stage": "full_image"}
        )
        try:
            diagnostics = dict(run_job(job))
            _write_runtime_message(
                stdout,
                {"kind": "result", "run_id": job["run_id"], "diagnostics": diagnostics},
            )
        except Exception as exc:
            from .ocr_errors import format_ocr_error

            _write_runtime_message(
                stdout, {
                    "kind": "error", "run_id": job["run_id"], "code": "job_failed",
                    "message": format_ocr_error(exc),
                }
            )
    return 0


__all__ = [
    "MAX_OCR_MESSAGE_BYTES",
    "MAX_OCR_EVENT_BYTES",
    "OCR_PROTOCOL_VERSION",
    "OcrRuntimeProtocolError",
    "InstalledOcrWorker",
    "StagedInstalledOcrWorker",
    "build_ocr_job",
    "create_installed_ocr_worker",
    "parse_ocr_message",
    "serve_ocr_runtime",
    "validate_ocr_hello",
]
