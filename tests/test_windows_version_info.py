"""Tests for Windows EXE metadata generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import generate_windows_version_info as version_info


class WindowsVersionInfoTests(unittest.TestCase):
    def test_version_to_windows_tuple_handles_release_tags(self) -> None:
        self.assertEqual(
            version_info.version_to_windows_tuple("v0.4.0"),
            (0, 4, 0, 0),
        )
        self.assertEqual(
            version_info.version_to_windows_tuple("1.2.3.4"),
            (1, 2, 3, 4),
        )

    def test_version_to_windows_tuple_handles_dev_versions(self) -> None:
        self.assertEqual(
            version_info.version_to_windows_tuple("dev-125"),
            (0, 0, 0, 125),
        )
        self.assertEqual(
            version_info.version_to_windows_tuple("dev"),
            (0, 0, 0, 0),
        )

    def test_generated_version_info_contains_expected_metadata(self) -> None:
        text = version_info.build_version_info_text(
            version="v0.4.0",
            file_description="PicSyncra desktop application",
            internal_name="PicSyncra",
            original_filename="PicSyncra.exe",
            product_name="PicSyncra",
            company_name="NefilimPL",
            legal_copyright="Copyright (C) NefilimPL",
        )

        self.assertIn("filevers=(0, 4, 0, 0)", text)
        self.assertIn("StringStruct('FileDescription', 'PicSyncra desktop application')", text)
        self.assertIn("StringStruct('FileVersion', 'v0.4.0')", text)
        self.assertIn("StringStruct('OriginalFilename', 'PicSyncra.exe')", text)

    def test_read_build_version_uses_env_before_version_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            version_dir = repo_root / "picsyncra"
            version_dir.mkdir()
            (version_dir / "VERSION").write_text("v1.0.0", encoding="utf-8")

            with patch.dict(
                "os.environ",
                {version_info.VERSION_ENV_VAR: "v2.0.0"},
            ):
                self.assertEqual(
                    version_info.read_build_version(repo_root),
                    "v2.0.0",
                )

    def test_github_metadata_uses_repository_context(self) -> None:
        metadata = version_info.resolve_build_metadata(
            metadata_source="github",
            env={
                "GITHUB_ACTIONS": "true",
                "GITHUB_REPOSITORY": "NefilimPL/PicSyncra",
                "GITHUB_REPOSITORY_OWNER": "NefilimPL",
            },
        )

        self.assertEqual(metadata.source, "github")
        self.assertEqual(metadata.product_name, "PicSyncra")
        self.assertEqual(metadata.company_name, "NefilimPL")
        self.assertIn("NefilimPL", metadata.legal_copyright)

    def test_windows_metadata_prefers_registered_organization(self) -> None:
        with patch.object(
            version_info,
            "_read_windows_registered_values",
            return_value=("Example Org", "Example Owner"),
        ):
            metadata = version_info.resolve_build_metadata(
                metadata_source="windows",
                env={"USERNAME": "kbober"},
            )

        self.assertEqual(metadata.source, "windows")
        self.assertEqual(metadata.product_name, "PicSyncra")
        self.assertEqual(metadata.company_name, "Example Org")

    def test_windows_metadata_falls_back_to_username(self) -> None:
        with patch.object(
            version_info,
            "_read_windows_registered_values",
            return_value=("", ""),
        ):
            metadata = version_info.resolve_build_metadata(
                metadata_source="windows",
                env={"USERNAME": "kbober"},
            )

        self.assertEqual(metadata.company_name, "kbober")


if __name__ == "__main__":
    unittest.main()
