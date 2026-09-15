"""Closed JSON protocol for the separately installed OCR executable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from picsyncra.installation.ocr_runtime import (
    OCR_PROTOCOL_VERSION,
    OcrRuntimeProtocolError,
    build_ocr_job,
    parse_ocr_message,
    validate_ocr_hello,
)


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
