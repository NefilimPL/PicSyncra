"""Safely publish the optional OCR bundle for the active installed release."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from .contracts import ComponentRef, InstallContext
from .ocr_component import OCR_COMPONENT_PROTOCOL
from .package_apply import PackageApplyError, _extract
from .update_helper import read_active_release


def _write_marker(root: Path, payload: dict[str, object]) -> None:
    temporary = root / f".active.{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root / "active.json")
    finally:
        temporary.unlink(missing_ok=True)


def install_ocr_component(context: InstallContext, component: ComponentRef, archive: Path) -> str:
    """Extract a hash-verified OCR archive and atomically make it active."""
    if component.name != "ocr":
        raise PackageApplyError("Expected an OCR component.")
    release_id = read_active_release(context)
    root = context.program_root / "components" / "ocr"
    target = root / component.component_id
    if target.exists() or target.is_symlink():
        raise PackageApplyError("OCR component is already installed.")
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".{component.component_id}.{uuid4().hex}.tmp"
    try:
        temporary.mkdir()
        _extract(component, archive, temporary)
        if not (temporary / "PicSyncra-OCR.exe").is_file():
            raise PackageApplyError("OCR component executable is missing.")
        os.replace(temporary, target)
        _write_marker(
            root,
            {
                "schema": 1,
                "release_id": release_id,
                "component_id": component.component_id,
                "build_id": f"release-{release_id}",
                "protocol": OCR_COMPONENT_PROTOCOL,
            },
        )
        return component.component_id
    finally:
        if temporary.exists() and not temporary.is_symlink():
            shutil.rmtree(temporary, ignore_errors=True)


__all__ = ["install_ocr_component"]
