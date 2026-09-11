"""Tests for dynamic runtime paths used after startup initialization."""

from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from picsyncra import excel_utils, logging_utils, settings

TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / "pytest-temp"


def _make_test_dir(name: str) -> str:
    path = TEST_TEMP_ROOT / f"{name}-{uuid.uuid4().hex}"
    os.makedirs(path)
    return str(path)


class RuntimePathTests(unittest.TestCase):
    def test_excel_workbook_path_tracks_settings_updates(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        temp_dir = _make_test_dir("excel-paths")
        try:
            first_path = os.path.join(temp_dir, "first", "lists.xlsx")
            second_path = os.path.join(temp_dir, "second", "lists.xlsx")

            with patch.object(settings, "LISTS_WORKBOOK_PATH", first_path):
                excel_utils._ensure_workbook_exists()
            with patch.object(settings, "LISTS_WORKBOOK_PATH", second_path):
                excel_utils._ensure_workbook_exists()

            self.assertTrue(os.path.exists(first_path))
            self.assertTrue(os.path.exists(second_path))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_error_log_path_tracks_settings_updates(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        temp_dir = _make_test_dir("log-paths")
        try:
            log_path = os.path.join(temp_dir, "logs", "error_log.txt")

            with patch.object(settings, "AM", log_path):
                logging_utils.log_error("runtime path test")

            self.assertTrue(os.path.exists(log_path))
            with open(log_path, "r", encoding="utf-8") as handle:
                self.assertIn("runtime path test", handle.read())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
