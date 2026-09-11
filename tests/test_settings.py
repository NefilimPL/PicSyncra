"""Tests for runtime base directory resolution."""

from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from picsyncra import settings

TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / "pytest-temp"


def _make_test_dir(name: str) -> str:
    path = TEST_TEMP_ROOT / f"{name}-{uuid.uuid4().hex}"
    os.makedirs(path)
    return str(path)


class SettingsBaseDirTests(unittest.TestCase):
    def test_interactive_first_run_prompts_instead_of_using_default_root(self) -> None:
        settings_path = r"C:\App\local_settings.json"
        fallback_dir = r"C:\App"
        selected_dir = r"D:\PicSyncraData"

        with (
            patch.object(settings, "HEADLESS_ENV", False),
            patch.object(settings, "_load_saved_base_dir_override", return_value=""),
            patch.object(
                settings,
                "_prompt_for_base_dir",
                return_value=(selected_dir, None),
            ) as prompt,
            patch.object(settings, "_ensure_directory_access") as ensure_access,
        ):
            resolved, warning = settings._ensure_base_dir_override(
                settings_path,
                dict(settings.BASE_DIR_SETTINGS_TEMPLATE),
                fallback_dir,
            )

        self.assertEqual(resolved, selected_dir)
        self.assertIsNone(warning)
        prompt.assert_called_once()
        self.assertEqual(prompt.call_args.args[2], fallback_dir)
        ensure_access.assert_not_called()

    def test_interactive_uses_saved_override_without_prompting(self) -> None:
        settings_path = r"C:\App\local_settings.json"
        selected_dir = r"D:\PicSyncraData"

        with (
            patch.object(settings, "HEADLESS_ENV", False),
            patch.object(
                settings, "_load_saved_base_dir_override", return_value=selected_dir
            ),
            patch.object(
                settings, "_ensure_directory_access", return_value=(True, None)
            ),
            patch.object(settings, "_prompt_for_base_dir") as prompt,
        ):
            resolved, warning = settings._ensure_base_dir_override(
                settings_path,
                dict(settings.BASE_DIR_SETTINGS_TEMPLATE),
                r"C:\App",
            )

        self.assertEqual(resolved, selected_dir)
        self.assertIsNone(warning)
        prompt.assert_not_called()

    def test_headless_invalid_saved_override_returns_fallback_warning(self) -> None:
        settings_path = r"C:\App\local_settings.json"
        selected_dir = r"G:\MissingData"

        with patch.object(
            settings,
            "_ensure_directory_access",
            side_effect=[(False, FileNotFoundError("missing")), (True, None)],
        ):
            resolved, warning = settings._resolve_headless_base_dir(
                settings_path,
                dict(settings.BASE_DIR_SETTINGS_TEMPLATE),
                selected_dir,
            )

        self.assertEqual(resolved, r"C:\App")
        self.assertIsNotNone(warning)
        self.assertIn(selected_dir, warning)

    def test_log_paths_are_under_settings_root_logs_dir(self) -> None:
        old_values = {
            name: getattr(settings, name, None)
            for name in ("AC", "l", "LISTS_WORKBOOK_PATH", "AD", "AM", "BM", "AN", "BASE_DIR_OVERRIDE", "LOG_DIR")
        }
        settings_root = None
        base_dir = None
        try:
            TEST_TEMP_ROOT.mkdir(exist_ok=True)
            settings_root = _make_test_dir("settings-root")
            base_dir = _make_test_dir("base-dir")
            with patch.object(settings, "_resolve_settings_root", return_value=settings_root):
                settings._apply_base_dir(base_dir)

            expected_log_dir = os.path.join(settings_root, "logs")
            self.assertEqual(settings.LOG_DIR, expected_log_dir)
            self.assertEqual(settings.AM, os.path.join(expected_log_dir, "error_log.txt"))
            self.assertEqual(settings.BM, os.path.join(expected_log_dir, "changes_log.txt"))
            self.assertFalse(settings.AM.startswith(base_dir))
        finally:
            for name, value in old_values.items():
                setattr(settings, name, value)
            for path in (settings_root, base_dir):
                if path:
                    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
