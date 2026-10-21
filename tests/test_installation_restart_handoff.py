from __future__ import annotations

from pathlib import Path

from picsyncra.installation.contracts import InstallContext


def _context(tmp_path: Path) -> InstallContext:
    program = tmp_path / "program"
    state = tmp_path / "state"
    (program / "versions" / "41").mkdir(parents=True)
    (program / "versions" / "42").mkdir()
    (program / "components" / "ocr").mkdir(parents=True)
    (program / "active.json").write_text(
        '{"schema":1,"installation_id":"site-1","release_id":42}', encoding="utf-8"
    )
    return InstallContext("site-1", program, state, state / "config", state / "data.sqlite")


def test_restart_handoff_restores_previous_release_and_ocr_marker(tmp_path: Path) -> None:
    from picsyncra.installation.restart_handoff import (
        create_restart_handoff,
        read_restart_handoff,
        restore_restart_handoff,
    )
    from picsyncra.installation.update_helper import read_active_release

    context = _context(tmp_path)
    marker = context.program_root / "components" / "ocr" / "active.json"
    marker.write_bytes(b'{"component_id":"new"}')
    handoff = create_restart_handoff(
        context, operation_id="op-1", previous_release=41, target_release=42, previous_ocr_marker=b'{"component_id":"old"}'
    )

    assert read_restart_handoff(context) == handoff
    restore_restart_handoff(context, handoff)

    assert read_active_release(context) == 41
    assert marker.read_bytes() == b'{"component_id":"old"}'


def test_restart_handoff_can_restore_an_absent_ocr_marker(tmp_path: Path) -> None:
    from picsyncra.installation.restart_handoff import create_restart_handoff, restore_restart_handoff

    context = _context(tmp_path)
    marker = context.program_root / "components" / "ocr" / "active.json"
    marker.write_bytes(b'{"component_id":"new"}')
    handoff = create_restart_handoff(
        context, operation_id="op-1", previous_release=41, target_release=42, previous_ocr_marker=None
    )

    restore_restart_handoff(context, handoff)

    assert not marker.exists()
