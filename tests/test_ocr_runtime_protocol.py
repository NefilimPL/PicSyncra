"""Closed JSON protocol for the separately installed OCR executable."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from collections import deque

import pytest

from picsyncra.installation.ocr_runtime import (
    OCR_PROTOCOL_VERSION,
    OcrRuntimeProtocolError,
    InstalledOcrWorker,
    build_ocr_job,
    parse_ocr_message,
    serve_ocr_runtime,
    validate_ocr_hello,
)


class _Output:
    def __init__(self, lines: list[str]) -> None:
        self._lines = deque(lines)

    def readline(self) -> str:
        return self._lines.popleft() if self._lines else ""


class _Input:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.flushed = 0

    def write(self, value: str) -> int:
        self.writes.append(value)
        return len(value)

    def flush(self) -> None:
        self.flushed += 1


class _Process:
    def __init__(self, lines: list[str], *, returncode: int | None = None) -> None:
        self.stdin = _Input()
        self.stdout = _Output(lines)
        self.returncode = returncode
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 1

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode if self.returncode is not None else 0


class _UnresponsiveProcess(_Process):
    def wait(self, timeout: float | None = None) -> int:
        del timeout
        raise TimeoutError("runtime did not stop")


def test_hello_requires_the_expected_protocol_build_and_component() -> None:
    """Catches accepting a stale or unrelated OCR executable."""

    hello = validate_ocr_hello(
        {
            "kind": "hello",
            "protocol": OCR_PROTOCOL_VERSION,
            "build_id": "release-12",
            "component_id": "ocr-12",
        },
        expected_build_id="release-12",
        expected_component_id="ocr-12",
    )

    assert hello["kind"] == "hello"
    with pytest.raises(OcrRuntimeProtocolError):
        validate_ocr_hello(
            {**hello, "component_id": "ocr-11"},
            expected_build_id="release-12",
            expected_component_id="ocr-12",
        )


def test_job_accepts_only_a_file_under_its_declared_work_root(tmp_path: Path) -> None:
    """Catches a WEB request making the OCR executable read arbitrary files."""

    work_root = tmp_path / "job"
    work_root.mkdir()
    image = work_root / "image.png"
    image.write_bytes(b"fixture")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private")

    assert build_ocr_job("run-1", image, work_root=work_root, profile_ids=["fast"]) == {
        "kind": "job",
        "run_id": "run-1",
        "path": str(image.resolve()),
        "work_root": str(work_root.resolve()),
        "profile_ids": ["fast"],
    }
    with pytest.raises(OcrRuntimeProtocolError):
        build_ocr_job("run-1", outside, work_root=work_root, profile_ids=["fast"])


def test_parser_rejects_unknown_or_oversized_runtime_messages() -> None:
    """Catches protocol expansion or unbounded input from a crashed process."""

    with pytest.raises(OcrRuntimeProtocolError):
        parse_ocr_message(json.dumps({"kind": "shell", "command": "cmd.exe"}))
    with pytest.raises(OcrRuntimeProtocolError):
        parse_ocr_message("x" * 8_193)


def test_installed_worker_validates_hello_and_sends_only_closed_job_messages(
    tmp_path: Path,
) -> None:
    """Catches passing arbitrary runtime arguments or skipping the handshake."""

    work_root = tmp_path / "job"
    work_root.mkdir()
    image = work_root / "image.png"
    image.write_bytes(b"fixture")
    process = _Process(
        [
            json.dumps(
                {
                    "kind": "hello",
                    "protocol": OCR_PROTOCOL_VERSION,
                    "build_id": "release-12",
                    "component_id": "ocr-12",
                }
            )
            + "\n"
        ]
    )
    process_arguments: list[list[str]] = []
    worker = InstalledOcrWorker(
        executable=tmp_path / "PicSyncra-OCR.exe",
        build_id="release-12",
        component_id="ocr-12",
        process_factory=lambda args: process_arguments.append(args) or process,
    )

    worker.start()
    worker.submit(
        {
            "run_id": "run-1",
            "path": str(image),
            "work_root": str(work_root),
            "profile_ids": ["fast"],
        }
    )
    worker.stop(force=False)

    assert [json.loads(line) for line in process.stdin.writes] == [
        {
            "kind": "job",
            "run_id": "run-1",
            "path": str(image.resolve()),
            "work_root": str(work_root.resolve()),
            "profile_ids": ["fast"],
        },
        {"kind": "stop"},
    ]
    assert process.stdin.flushed == 2
    assert process_arguments == [
        [
            str(tmp_path / "PicSyncra-OCR.exe"),
            "--build-id",
            "release-12",
            "--component-id",
            "ocr-12",
        ]
    ]


def test_installed_worker_reports_a_runtime_that_exits_after_startup(tmp_path: Path) -> None:
    """Catches treating a dead OCR executable as ready for another job."""

    process = _Process(
        [
            json.dumps(
                {
                    "kind": "hello",
                    "protocol": OCR_PROTOCOL_VERSION,
                    "build_id": "release-12",
                    "component_id": "ocr-12",
                }
            )
            + "\n"
        ],
        returncode=3,
    )
    worker = InstalledOcrWorker(
        executable=tmp_path / "PicSyncra-OCR.exe",
        build_id="release-12",
        component_id="ocr-12",
        process_factory=lambda _args: process,
    )

    worker.start()

    assert worker.poll() == [{"kind": "error", "code": "runtime_exited"}]


def test_graceful_stop_keeps_an_unresponsive_runtime_available_for_forced_cleanup(
    tmp_path: Path,
) -> None:
    """Catches graceful shutdown forgetting a still-running OCR process."""

    process = _UnresponsiveProcess(
        [
            json.dumps(
                {
                    "kind": "hello",
                    "protocol": OCR_PROTOCOL_VERSION,
                    "build_id": "release-12",
                    "component_id": "ocr-12",
                }
            )
            + "\n"
        ]
    )
    worker = InstalledOcrWorker(
        executable=tmp_path / "PicSyncra-OCR.exe",
        build_id="release-12",
        component_id="ocr-12",
        process_factory=lambda _args: process,
    )

    worker.start()
    worker.stop(force=False)

    assert process.terminated is False
    assert worker.status()["alive"] is True


def test_runtime_server_acknowledges_only_valid_cpu_limits() -> None:
    """Catches a component silently ignoring WEB's resource limit updates."""

    stdin = StringIO(
        json.dumps({"kind": "update_limits", "cpu_percent": 42})
        + "\n"
        + json.dumps({"kind": "update_limits", "cpu_percent": 101})
        + "\n"
        + json.dumps({"kind": "stop"})
        + "\n"
    )
    stdout = StringIO()

    assert (
        serve_ocr_runtime(
            stdin,
            stdout,
            build_id="release-12",
            component_id="ocr-12",
            run_job=lambda _job: {},
        )
        == 0
    )

    messages = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert messages[2:] == [
        {"kind": "limits_updated", "cpu_percent": 42},
        {"kind": "error", "code": "invalid_command"},
    ]


def test_runtime_server_revalidates_each_job_before_returning_a_result(tmp_path: Path) -> None:
    """Catches a direct stdin caller bypassing the adapter's job-root guard."""

    work_root = tmp_path / "job"
    work_root.mkdir()
    image = work_root / "image.png"
    image.write_bytes(b"fixture")
    stdin = StringIO(
        json.dumps(
            {
                "kind": "job",
                "run_id": "run-1",
                "path": str(image),
                "work_root": str(work_root),
                "profile_ids": ["fast"],
            }
        )
        + "\n"
        + json.dumps({"kind": "stop"})
        + "\n"
    )
    stdout = StringIO()

    assert (
        serve_ocr_runtime(
            stdin,
            stdout,
            build_id="release-12",
            component_id="ocr-12",
            run_job=lambda job: {"available": True, "path": job["path"]},
        )
        == 0
    )

    messages = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [message["kind"] for message in messages] == [
        "hello",
        "ready",
        "stage_started",
        "result",
    ]
    assert isinstance(messages[1].get("pid"), int)
    assert messages[-1] == {
        "kind": "result",
        "run_id": "run-1",
        "diagnostics": {"available": True, "path": str(image.resolve())},
    }
