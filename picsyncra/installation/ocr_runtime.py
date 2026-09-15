"""Closed stdin/stdout protocol shared with the installed OCR runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


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
        "profile_ids": list(profile_ids),
    }


__all__ = [
    "MAX_OCR_MESSAGE_BYTES",
    "OCR_PROTOCOL_VERSION",
    "OcrRuntimeProtocolError",
    "build_ocr_job",
    "parse_ocr_message",
    "validate_ocr_hello",
]
