"""Closed stdin/stdout protocol shared with the installed OCR runtime."""

from __future__ import annotations

import json
from pathlib import Path
from queue import Empty, Queue
import subprocess
from threading import Thread
from typing import Callable, Mapping, TextIO


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
        finally:
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
    _write_runtime_message(stdout, {"kind": "ready"})
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
    "build_ocr_job",
    "parse_ocr_message",
    "serve_ocr_runtime",
    "validate_ocr_hello",
]
