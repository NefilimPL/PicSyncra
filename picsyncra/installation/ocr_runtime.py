"""Closed stdin/stdout protocol shared with the installed OCR runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
from threading import Thread
from typing import Callable, Mapping, TextIO

from .contracts import InstallContext
from .ocr_component import resolve_active_ocr_component


OCR_PROTOCOL_VERSION = 1
MAX_OCR_MESSAGE_BYTES = 8 * 1024
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


def parse_ocr_message(raw: str) -> dict[str, object]:
    """Decode one bounded JSON message without accepting arbitrary commands."""

    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_OCR_MESSAGE_BYTES:
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
    ) -> None:
        if not isinstance(build_id, str) or not build_id:
            raise ValueError("build_id must be non-empty text.")
        if not isinstance(component_id, str) or not component_id:
            raise ValueError("component_id must be non-empty text.")
        self._executable = Path(executable)
        self._build_id = build_id
        self._component_id = component_id
        self._process_factory = process_factory
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
        try:
            hello = parse_ocr_message(stdout.readline().rstrip("\r\n"))
            validate_ocr_hello(
                hello,
                expected_build_id=self._build_id,
                expected_component_id=self._component_id,
            )
        except Exception:
            self._terminate(process)
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
            line = stdout.readline()
            if not line:
                return
            try:
                self._events.put(parse_ocr_message(line.rstrip("\r\n")))
            except OcrRuntimeProtocolError:
                self._events.put({"kind": "error", "code": "invalid_runtime_message"})

    @staticmethod
    def _terminate(process: object) -> None:
        try:
            getattr(process, "terminate")()
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


def create_installed_ocr_worker(
    context: InstallContext,
    *,
    process_factory=_launch_runtime,
) -> StagedInstalledOcrWorker | None:
    """Build the WEB-compatible worker only from an active verified component."""

    active = resolve_active_ocr_component(context)
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
    if len(encoded.encode("utf-8")) > MAX_OCR_MESSAGE_BYTES:
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
        except Exception:
            _write_runtime_message(
                stdout, {"kind": "error", "run_id": job["run_id"], "code": "job_failed"}
            )
    return 0


__all__ = [
    "MAX_OCR_MESSAGE_BYTES",
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
