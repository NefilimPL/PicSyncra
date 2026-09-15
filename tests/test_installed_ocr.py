"""Installed OCR components are resolved only from the active managed bundle."""

from __future__ import annotations

import json
from pathlib import Path

from picsyncra.installation.contracts import InstallContext
from picsyncra.installation.ocr_component import resolve_ocr_component


def _context(tmp_path: Path) -> InstallContext:
    program_root = tmp_path / "program"
    state_root = tmp_path / "state"
    program_root.mkdir()
    state_root.mkdir()
    (program_root / "active.json").write_text(
        json.dumps({"schema": 1, "installation_id": "primary", "release_id": 12}),
        encoding="utf-8",
    )
    return InstallContext(
        installation_id="primary",
        program_root=program_root,
        state_root=state_root,
        config_root=state_root / "config",
        database_path=state_root / "data" / "picsyncra.sqlite",
    )


def test_resolve_ocr_component_accepts_only_the_active_component_for_the_release(
    tmp_path: Path,
) -> None:
    """Catches loading an arbitrary OCR executable from a component directory."""

    context = _context(tmp_path)
    component = context.program_root / "components" / "ocr" / "ocr-12"
    component.mkdir(parents=True)
    (component / "PicSyncra-OCR.exe").write_bytes(b"runtime")
    marker = component.parent / "active.json"
    marker.write_text(
        json.dumps(
            {
                "schema": 1,
                "release_id": 12,
                "component_id": "ocr-12",
                "build_id": "release-12",
                "protocol": 1,
            }
        ),
        encoding="utf-8",
    )

    assert resolve_ocr_component(context) == component


def test_resolve_ocr_component_rejects_a_marker_for_another_release(tmp_path: Path) -> None:
    """Catches mixing an OCR runtime with an incompatible active build."""

    context = _context(tmp_path)
    component_root = context.program_root / "components" / "ocr"
    component = component_root / "ocr-11"
    component.mkdir(parents=True)
    (component / "PicSyncra-OCR.exe").write_bytes(b"runtime")
    (component_root / "active.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "release_id": 11,
                "component_id": "ocr-11",
                "build_id": "release-11",
                "protocol": 1,
            }
        ),
        encoding="utf-8",
    )

    assert resolve_ocr_component(context) is None
