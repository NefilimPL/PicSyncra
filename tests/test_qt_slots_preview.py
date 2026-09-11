"""Tests for the PySide6 slot preview data helpers."""

from __future__ import annotations

from picsyncra.qt_slots_preview import assign_sample_paths_to_slots


def test_assign_sample_paths_prefers_filename_slot_prefix() -> None:
    slot_defs = [
        {"prefix": "01", "label": "MAIN"},
        {"prefix": "02", "label": "DETAIL"},
        {"prefix": "03", "label": "MOOD"},
    ]
    paths = [
        r"C:\tmp\5901234567890_03_MOOD.jpg",
        r"C:\tmp\unparsed.png",
    ]

    items = assign_sample_paths_to_slots(slot_defs, paths)

    assert items[0].path == paths[1]
    assert items[1].path == ""
    assert items[2].path == paths[0]
