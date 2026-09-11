"""Unit tests for photo slot configuration helpers."""

from __future__ import annotations

import unittest

from picsyncra.slot_utils import (
    next_slot_prefix,
    normalize_slot_definitions,
    normalize_slot_prefix,
    normalize_sql_column_map,
)


class SlotUtilsTests(unittest.TestCase):
    def test_normalize_slot_prefix_accepts_positive_numbers(self) -> None:
        self.assertEqual(normalize_slot_prefix("1"), "01")
        self.assertEqual(normalize_slot_prefix("04"), "04")
        self.assertEqual(normalize_slot_prefix("123"), "123")

    def test_normalize_slot_prefix_rejects_invalid_ids(self) -> None:
        self.assertEqual(normalize_slot_prefix("0"), "")
        self.assertEqual(normalize_slot_prefix("-1"), "")
        self.assertEqual(normalize_slot_prefix("abc"), "")
        self.assertEqual(normalize_slot_prefix(""), "")

    def test_normalize_slot_definitions_treats_unpadded_duplicate_as_same_id(self) -> None:
        slot_defs, issues = normalize_slot_definitions(
            [
                {"prefix": "1", "label": "Main"},
                {"prefix": "01", "label": "Duplicate"},
                {"prefix": "2", "label": "Detail"},
            ]
        )

        self.assertEqual(
            slot_defs,
            [
                {"prefix": "01", "label": "Main"},
                {"prefix": "02", "label": "Detail"},
            ],
        )
        self.assertIn({"type": "slot_def_duplicate", "prefix": "01"}, issues)

    def test_normalize_slot_definitions_keeps_display_and_filename_labels_separate(self) -> None:
        slot_defs, issues = normalize_slot_definitions(
            [{"prefix": "3", "label": "Front web", "filename_label": "DETAIL_pic"}]
        )

        self.assertEqual(
            slot_defs,
            [{"prefix": "03", "label": "Front web", "filename_label": "DETAIL_pic"}],
        )
        self.assertEqual(issues, [])

    def test_normalize_sql_column_map_keeps_mapping_after_prefix_normalization(self) -> None:
        slot_defs, _issues = normalize_slot_definitions(
            [{"prefix": "1", "label": "Main"}]
        )
        sql_map, issues = normalize_sql_column_map({"1": "main_img"}, slot_defs)

        self.assertEqual(sql_map, {"01": "main_img"})
        self.assertEqual(issues, [])

    def test_next_slot_prefix_uses_normalized_numeric_ids(self) -> None:
        prefix = next_slot_prefix(
            [
                {"prefix": "1", "label": "Main"},
                {"prefix": "09", "label": "Detail"},
            ]
        )

        self.assertEqual(prefix, "10")


if __name__ == "__main__":
    unittest.main()
