"""CI smoke tests for desktop launchers and packaged assets."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import py_compile
import unittest


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PICSYNCRA_HEADLESS", "1")
os.environ.setdefault("CI", "1")


class DesktopSmokeCiTests(unittest.TestCase):
    def test_picsyncra_entrypoints_and_package_exist(self) -> None:
        required_paths = [
            ROOT / "picsyncra" / "__init__.py",
            ROOT / "PicSyncra.pyw",
            ROOT / "PicSyncra-WEB.pyw",
            ROOT / "PicSyncra-QtSlots.pyw",
        ]

        self.assertEqual(
            [str(path.relative_to(ROOT)) for path in required_paths if not path.is_file()],
            [],
        )

    def test_desktop_entrypoints_compile(self) -> None:
        entrypoints = [
            ROOT / "PicSyncra.pyw",
            ROOT / "PicSyncra-WEB.pyw",
            ROOT / "PicSyncra-QtSlots.pyw",
        ]

        for entrypoint in entrypoints:
            with self.subTest(entrypoint=entrypoint.name):
                py_compile.compile(str(entrypoint), doraise=True)

    def test_critical_modules_import_in_headless_mode(self) -> None:
        modules = [
            "picsyncra.bootstrap",
            "picsyncra.config",
            "picsyncra.settings",
            "picsyncra.workflow_utils",
            "picsyncra.web_workflow",
            "picsyncra.web_data",
            "picsyncra.web.app",
            "picsyncra.app",
        ]

        errors: dict[str, str] = {}
        for module_name in modules:
            try:
                importlib.import_module(module_name)
            except Exception as exc:  # pragma: no cover - failure is reported below
                errors[module_name] = f"{type(exc).__name__}: {exc}"

        self.assertEqual(errors, {})

    def test_localization_files_are_valid_json(self) -> None:
        localization_dir = ROOT / "picsyncra" / "Localization"
        expected_files = {"pl.json", "eng.json", "ua.json"}
        required_product_field_keys = {
            "product_fields_section",
            "product_fields_hint",
            "product_field_custom_label",
            "product_field_enabled",
            "product_field_required",
        }
        found_files = {path.name for path in localization_dir.glob("*.json")}

        self.assertEqual(expected_files - found_files, set())
        for path in sorted(localization_dir.glob("*.json")):
            with self.subTest(path=path.name):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(payload, dict)
                self.assertGreater(len(payload), 10)
                self.assertEqual(
                    required_product_field_keys - set(payload),
                    set(),
                    path.name,
                )

    def test_required_image_assets_exist_for_desktop_and_web(self) -> None:
        required_assets = [
            ROOT / "pic" / "PIC9_LOCAL.png",
            ROOT / "pic" / "PIC9_WEB.png",
            ROOT / "pic" / "PIC9_WEB-OCR.png",
            ROOT / "picsyncra" / "VERSION",
            ROOT / "picsyncra" / "web" / "static" / "index.html",
            ROOT / "picsyncra" / "web" / "static" / "login.html",
            ROOT / "picsyncra" / "web" / "static" / "app.css",
            ROOT / "picsyncra" / "web" / "static" / "app.js",
        ]

        missing_or_empty = [
            str(path.relative_to(ROOT))
            for path in required_assets
            if not path.is_file() or path.stat().st_size <= 0
        ]

        self.assertEqual(missing_or_empty, [])


if __name__ == "__main__":
    unittest.main()
