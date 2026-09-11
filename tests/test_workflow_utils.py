"""Unit tests for the pure workflow helpers."""

from __future__ import annotations

import os
import unittest

from picsyncra.workflow_utils import (
    build_output_filename,
    build_product_path,
    build_remote_slot_filename,
    build_sql_presence_query,
    parse_slot_filename,
    select_remote_files_for_ean,
    sql_row_to_presence_map,
    sql_row_to_value_map,
)


class WorkflowUtilsTests(unittest.TestCase):
    def test_build_product_path_normalizes_colors_and_extra(self) -> None:
        path = build_product_path(
            "/tmp/base",
            "Maggiore",
            "komoda",
            "ma03",
            ["Bialy", "", "dab artisan"],
            "led_rgb",
        )
        self.assertEqual(
            path,
            os.path.join(
                "/tmp/base",
                "MAGGIORE",
                "KOMODA",
                "MA03",
                "BIALY-DAB ARTISAN",
                "LED-RGB",
            ),
        )

    def test_build_output_filename_keeps_structured_segments(self) -> None:
        filename = build_output_filename(
            "5901234567890",
            "03",
            "DETAIL",
            "Maggiore",
            "Komoda",
            "MA03",
            ["Bialy", "Czarny"],
            "",
            ".jpg",
        )
        self.assertEqual(
            filename,
            "5901234567890_03_DETAIL_MAGGIORE_KOMODA_MA03_BIALY_CZARNY_NO-LED.jpg",
        )

    def test_build_remote_slot_filename_uses_short_ftp_format(self) -> None:
        filename = build_remote_slot_filename(
            "5901234567890",
            "03",
            ".png",
        )
        self.assertEqual(filename, "5901234567890_03.png")

    def test_parse_slot_filename_preserves_suffix_when_normalizing(self) -> None:
        parsed = parse_slot_filename("5901234567890_3_DETAIL_MAGGIORE.jpg")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.normalized_label, "03")
        self.assertEqual(
            parsed.normalized_name,
            "5901234567890_03_DETAIL_MAGGIORE.jpg",
        )

    def test_select_remote_files_for_ean_filters_and_normalizes(self) -> None:
        files = select_remote_files_for_ean(
            "5901234567890",
            [
                "5901234567890_1_MAIN.jpg",
                "/remote/path/5901234567890_02_DETAIL.png",
                "1111111111111_03_OTHER.jpg",
            ],
        )
        self.assertEqual(
            files,
            {
                "01": "5901234567890_1_MAIN.jpg",
                "02": "5901234567890_02_DETAIL.png",
            },
        )

    def test_build_sql_presence_query_uses_single_select(self) -> None:
        mysql_query = build_sql_presence_query(
            "object_query_1",
            " WHERE EAN = '590'",
            ["img1", "img2", "img3"],
            "mysql",
        )
        mssql_query = build_sql_presence_query(
            "object_query_1",
            " WHERE EAN = '590'",
            ["img1", "img2", "img3"],
            "sql",
        )
        self.assertEqual(
            mysql_query,
            "SELECT img1, img2, img3 FROM object_query_1 WHERE EAN = '590' LIMIT 1",
        )
        self.assertEqual(
            mssql_query,
            "SELECT TOP 1 img1, img2, img3 FROM object_query_1 WHERE EAN = '590'",
        )

    def test_sql_row_to_presence_map_handles_strings_and_binary_values(self) -> None:
        values = sql_row_to_presence_map(
            ["01", "02", "03", "04"],
            ("https://img/1.jpg", "   ", memoryview(b"abc"), None),
        )
        self.assertEqual(
            values,
            {
                "01": True,
                "02": False,
                "03": True,
                "04": False,
            },
        )

    def test_sql_row_to_value_map_returns_trimmed_raw_values(self) -> None:
        values = sql_row_to_value_map(
            ["01", "02", "03", "04"],
            (" https://img/1.jpg ", "   ", memoryview(b"abc"), None),
        )
        self.assertEqual(
            values,
            {
                "01": "https://img/1.jpg",
                "02": "",
                "03": "abc",
                "04": "",
            },
        )


if __name__ == "__main__":
    unittest.main()
