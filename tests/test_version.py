"""Tests for application version helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from picsyncra import version


class VersionTests(unittest.TestCase):
    def test_env_version_takes_precedence(self) -> None:
        with patch.dict("os.environ", {version.VERSION_ENV_VAR: "v1.2.3"}):
            self.assertEqual(version.get_app_version(), "v1.2.3")
            self.assertEqual(version.get_display_version(), "v1.2.3")

    def test_display_version_adds_v_prefix_for_plain_tags(self) -> None:
        with patch.dict("os.environ", {version.VERSION_ENV_VAR: "1.2.3"}):
            self.assertEqual(version.get_display_version(), "v1.2.3")


if __name__ == "__main__":
    unittest.main()
