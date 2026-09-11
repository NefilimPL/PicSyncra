"""Unit tests for config normalization helpers."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest
from copy import deepcopy
from unittest.mock import patch

from picsyncra import common, config
from picsyncra.config import (
    _normalize_color_field_labels,
    _normalize_processing_settings,
    _normalize_resource_monitor_settings,
    _normalize_security_settings,
)
from picsyncra.email_settings import (
    EMAIL_CLIENT_SECRET,
    EMAIL_SETTINGS_KEY,
    EMAIL_SMTP_PASSWORD,
    default_email_settings,
)
from picsyncra.encryption import encrypt
from picsyncra.product_fields import PRODUCT_FIELDS_KEY
from picsyncra.sqlite_store import SqliteStore


def _workspace_temp(name: str) -> Path:
    root = Path(__file__).resolve().parents[1] / "tmp_test" / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


class DefaultConfigSafetyTests(unittest.TestCase):
    def test_default_sql_query_is_empty_and_contains_no_production_url(self) -> None:
        self.assertEqual(common.DEFAULT_CONFIG["sql_query"], "")
        self.assertEqual(common.SQL_UPDATE_TEMPLATE, "")
        self.assertNotIn("object_query_1", repr(common.DEFAULT_CONFIG))


class ConfigTests(unittest.TestCase):
    def test_normalize_web_display_settings_accepts_iana_and_falls_back(self) -> None:
        with patch.object(
            config,
            "available_display_time_zones",
            return_value=["UTC", "Europe/Warsaw"],
        ):
            self.assertEqual(
                config.normalize_web_display_settings({"time_zone": "Europe/Warsaw"}),
                {"time_zone": "Europe/Warsaw"},
            )
            self.assertEqual(
                config.normalize_web_display_settings({"time_zone": "CEST"}),
                {"time_zone": "UTC"},
            )

    def test_web_display_settings_are_normalized_at_merge_and_save_boundaries(self) -> None:
        payload = deepcopy(common.DEFAULT_CONFIG)
        payload[common.WEB_DISPLAY_SETTINGS_KEY] = {"time_zone": "CEST"}

        with (
            patch.object(
                config,
                "available_display_time_zones",
                return_value=["UTC", "Europe/Warsaw"],
            ),
            patch.object(config, "_active_sqlite_store", return_value=None),
            patch.object(config, "_write_json_atomic") as write_atomic,
        ):
            merged = config._merge_raw_config(
                {common.WEB_DISPLAY_SETTINGS_KEY: {"time_zone": "Europe/Warsaw"}},
                deepcopy(common.DEFAULT_CONFIG),
            )
            config.save_config(payload)

        self.assertEqual(
            merged[common.WEB_DISPLAY_SETTINGS_KEY],
            {"time_zone": "Europe/Warsaw"},
        )
        self.assertEqual(
            write_atomic.call_args.args[1][common.WEB_DISPLAY_SETTINGS_KEY],
            {"time_zone": "UTC"},
        )

    def test_web_display_settings_roundtrip_through_sqlite(self) -> None:
        temp_dir = _workspace_temp("config-web-display-sqlite")
        try:
            store = SqliteStore(temp_dir / "settings.sqlite")
            store.save_config(
                {common.WEB_DISPLAY_SETTINGS_KEY: {"time_zone": "CEST"}}
            )

            with (
                patch.object(config, "_active_sqlite_store", return_value=store),
                patch.object(
                    config,
                    "available_display_time_zones",
                    return_value=["UTC", "Europe/Warsaw"],
                ),
            ):
                loaded = config.load_config(interactive=False)
                self.assertEqual(
                    loaded[common.WEB_DISPLAY_SETTINGS_KEY],
                    {"time_zone": "UTC"},
                )

                loaded[common.WEB_DISPLAY_SETTINGS_KEY] = {
                    "time_zone": "Europe/Warsaw"
                }
                config.save_config(loaded)
                reloaded = config.load_config(interactive=False)

            self.assertEqual(
                store.load_config()[common.WEB_DISPLAY_SETTINGS_KEY],
                {"time_zone": "Europe/Warsaw"},
            )
            self.assertEqual(
                reloaded[common.WEB_DISPLAY_SETTINGS_KEY],
                {"time_zone": "Europe/Warsaw"},
            )
        finally:
            shutil.rmtree(temp_dir)

    def test_web_display_settings_normalize_and_write_back_legacy_json(self) -> None:
        temp_dir = _workspace_temp("config-web-display-legacy")
        config_path = temp_dir / "config.json"
        try:
            raw = deepcopy(common.DEFAULT_CONFIG)
            raw[common.WEB_DISPLAY_SETTINGS_KEY] = {"time_zone": "CEST"}
            config_path.write_text(json.dumps(raw), encoding="utf-8")

            with (
                patch.object(config, "_active_sqlite_store", return_value=None),
                patch.object(config.settings, "AC", str(temp_dir)),
                patch.object(config, "CONFIG_PATH", str(config_path)),
                patch.object(
                    config,
                    "available_display_time_zones",
                    return_value=["UTC", "Europe/Warsaw"],
                ),
            ):
                loaded = config.load_config(interactive=False)
                persisted_after_invalid = json.loads(
                    config_path.read_text(encoding="utf-8")
                )

                persisted_valid = deepcopy(persisted_after_invalid)
                persisted_valid[common.WEB_DISPLAY_SETTINGS_KEY] = {
                    "time_zone": "Europe/Warsaw"
                }
                config_path.write_text(json.dumps(persisted_valid), encoding="utf-8")
                reloaded = config.load_config(interactive=False)
                persisted_again = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(
                loaded[common.WEB_DISPLAY_SETTINGS_KEY],
                {"time_zone": "UTC"},
            )
            self.assertEqual(
                persisted_after_invalid[common.WEB_DISPLAY_SETTINGS_KEY],
                {"time_zone": "UTC"},
            )
            self.assertEqual(
                reloaded[common.WEB_DISPLAY_SETTINGS_KEY],
                {"time_zone": "Europe/Warsaw"},
            )
            self.assertEqual(
                persisted_again[common.WEB_DISPLAY_SETTINGS_KEY],
                {"time_zone": "Europe/Warsaw"},
            )
        finally:
            shutil.rmtree(temp_dir)

    def test_web_display_settings_first_write_uses_utc_default(self) -> None:
        temp_dir = _workspace_temp("config-web-display-first-write")
        config_path = temp_dir / "config.json"
        try:
            with (
                patch.object(config, "_active_sqlite_store", return_value=None),
                patch.object(config.settings, "AC", str(temp_dir)),
                patch.object(config, "CONFIG_PATH", str(config_path)),
                patch.object(
                    config,
                    "available_display_time_zones",
                    return_value=["UTC", "Europe/Warsaw"],
                ),
            ):
                loaded = config.load_config(interactive=False)

            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                loaded[common.WEB_DISPLAY_SETTINGS_KEY],
                {"time_zone": "UTC"},
            )
            self.assertEqual(
                persisted[common.WEB_DISPLAY_SETTINGS_KEY],
                {"time_zone": "UTC"},
            )
        finally:
            shutil.rmtree(temp_dir)

    def test_save_config_encrypts_both_email_secrets(self) -> None:
        payload = deepcopy(common.DEFAULT_CONFIG)
        payload[EMAIL_SETTINGS_KEY] = default_email_settings()
        payload[EMAIL_SETTINGS_KEY]["entra"][EMAIL_CLIENT_SECRET] = "entra-secret"
        payload[EMAIL_SETTINGS_KEY]["smtp"][EMAIL_SMTP_PASSWORD] = "smtp-secret"

        with (
            patch.object(config, "_active_sqlite_store", return_value=None),
            patch.object(config, "_write_json_atomic") as write_atomic,
        ):
            config.save_config(payload)

        raw = write_atomic.call_args.args[1][EMAIL_SETTINGS_KEY]
        self.assertNotEqual(raw["entra"][EMAIL_CLIENT_SECRET], "entra-secret")
        self.assertNotEqual(raw["smtp"][EMAIL_SMTP_PASSWORD], "smtp-secret")
        self.assertEqual(config.decrypt(raw["entra"][EMAIL_CLIENT_SECRET]), "entra-secret")
        self.assertEqual(config.decrypt(raw["smtp"][EMAIL_SMTP_PASSWORD]), "smtp-secret")

    def test_save_config_preserves_blank_submitted_email_secrets(self) -> None:
        payload = deepcopy(common.DEFAULT_CONFIG)
        payload[EMAIL_SETTINGS_KEY] = default_email_settings()
        raw_entra_secret = encrypt("saved-entra")
        raw_smtp_password = encrypt("saved-smtp")
        raw_config = {
            EMAIL_SETTINGS_KEY: {
                "entra": {EMAIL_CLIENT_SECRET: raw_entra_secret},
                "smtp": {EMAIL_SMTP_PASSWORD: raw_smtp_password},
            }
        }

        with (
            patch.object(config, "_active_sqlite_store", return_value=None),
            patch.object(config, "_write_json_atomic") as write_atomic,
        ):
            config.save_config(
                payload,
                raw_config=raw_config,
                preserve_secrets={
                    EMAIL_SETTINGS_KEY: {
                        "entra.client_secret",
                        "smtp.password",
                    }
                },
            )

        raw = write_atomic.call_args.args[1][EMAIL_SETTINGS_KEY]
        self.assertEqual(raw["entra"][EMAIL_CLIENT_SECRET], raw_entra_secret)
        self.assertEqual(raw["smtp"][EMAIL_SMTP_PASSWORD], raw_smtp_password)

    def test_merge_raw_config_decrypts_both_email_secrets(self) -> None:
        target = deepcopy(common.DEFAULT_CONFIG)
        raw = {
            EMAIL_SETTINGS_KEY: {
                "primary_channel": "smtp",
                "entra": {EMAIL_CLIENT_SECRET: encrypt("entra-secret")},
                "smtp": {EMAIL_SMTP_PASSWORD: encrypt("smtp-secret")},
            }
        }

        merged = config._merge_raw_config(raw, target)

        self.assertEqual(
            merged[EMAIL_SETTINGS_KEY]["entra"][EMAIL_CLIENT_SECRET],
            "entra-secret",
        )
        self.assertEqual(
            merged[EMAIL_SETTINGS_KEY]["smtp"][EMAIL_SMTP_PASSWORD],
            "smtp-secret",
        )

    def test_normalize_color_field_labels_strips_suffixes_and_blanks(self) -> None:
        labels = _normalize_color_field_labels(
            {
                "color1": "  Korpus*: ",
                "color2": "Front:",
                "color3": "   ",
                "other": "ignored",
            }
        )

        self.assertEqual(
            labels,
            {
                "color1": "Korpus",
                "color2": "Front",
            },
        )

    def test_normalize_color_field_labels_ignores_invalid_payload(self) -> None:
        self.assertEqual(_normalize_color_field_labels(None), {})

    def test_normalize_processing_settings_bounds_values(self) -> None:
        settings = _normalize_processing_settings(
            {
                "resize_enabled": False,
                "max_dim": "999999",
                "compress_quality": "0",
                "max_file_kb": "-5",
                "target_format": "jpeg",
                "upload_processing_mode": "client",
                "show_timing_details": True,
            }
        )

        self.assertFalse(settings["resize_enabled"])
        self.assertEqual(settings["max_dim"], 20000)
        self.assertEqual(settings["compress_quality"], 1)
        self.assertEqual(settings["max_file_kb"], 1)
        self.assertEqual(settings["target_format"], "JPG")
        self.assertEqual(settings["upload_processing_mode"], "client")
        self.assertTrue(settings["show_timing_details"])

    def test_normalize_resource_monitor_settings_uses_safe_defaults_and_bounds(self) -> None:
        settings = _normalize_resource_monitor_settings(
            {
                "show_status": "yes",
                "cpu_percent_threshold": "0",
                "memory_percent_threshold": "1000",
                "io_mib_per_second_threshold": "-4",
            }
        )

        self.assertEqual(
            settings,
            {
                "show_status": True,
                "cpu_percent_threshold": 10,
                "memory_percent_threshold": 90,
                "io_mib_per_second_threshold": 1,
            },
        )

    def test_normalize_security_settings_bounds_and_cleans_extensions(self) -> None:
        settings = _normalize_security_settings(
            {
                "max_upload_mb": "999999",
                "max_upload_pixels": "0",
                "allowed_upload_extensions": "jpg, .PNG, exe, dziwny!",
                "blocked_upload_extensions": ["EXE", ".bat", " "],
                "block_executable_uploads": False,
                "antivirus_scan_uploads": True,
            }
        )

        self.assertEqual(settings["max_upload_mb"], 2048)
        self.assertEqual(settings["max_upload_pixels"], 1)
        self.assertEqual(settings["allowed_upload_extensions"], ["jpg", "png", "exe"])
        self.assertEqual(settings["blocked_upload_extensions"], ["exe", "bat"])
        self.assertFalse(settings["block_executable_uploads"])
        self.assertTrue(settings["antivirus_scan_uploads"])

    def test_merge_raw_config_migrates_color_labels_to_product_fields(self) -> None:
        target = deepcopy(common.DEFAULT_CONFIG)

        merged = config._merge_raw_config(
            {"color_field_labels": {"color1": "Korpus"}},
            target,
        )

        self.assertEqual(merged[PRODUCT_FIELDS_KEY]["color1"]["label"], "Korpus")
        self.assertTrue(merged[PRODUCT_FIELDS_KEY]["name"]["required"])

    def test_save_config_persists_normalized_product_fields_to_sqlite(self) -> None:
        payload = deepcopy(common.DEFAULT_CONFIG)
        payload[PRODUCT_FIELDS_KEY] = {
            "model": {"enabled": False, "required": True}
        }
        store = unittest.mock.Mock(database_path="test.sqlite")

        with patch.object(config, "_active_sqlite_store", return_value=store):
            config.save_config(payload)

        saved = store.save_config.call_args.args[0][PRODUCT_FIELDS_KEY]
        self.assertEqual(
            saved["model"],
            {
                "label": "",
                "enabled": False,
                "required": False,
            },
        )

    def test_save_config_roundtrips_product_fields_through_sqlite(self) -> None:
        temp_dir = Path(__file__).resolve().parents[1] / "tmp_test" / "config-product-fields"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True)
        try:
            payload = deepcopy(common.DEFAULT_CONFIG)
            payload[PRODUCT_FIELDS_KEY] = {
                "name": {
                    "label": "Kolekcja",
                    "enabled": True,
                    "required": True,
                }
            }
            store = SqliteStore(temp_dir / "product-fields.sqlite")

            with patch.object(config, "_active_sqlite_store", return_value=store):
                config.save_config(payload)

            self.assertEqual(
                store.load_config()[PRODUCT_FIELDS_KEY]["name"]["label"],
                "Kolekcja",
            )
        finally:
            shutil.rmtree(temp_dir)

    def test_save_config_encrypts_pimcore_api_key(self) -> None:
        payload = deepcopy(common.DEFAULT_CONFIG)
        payload["pimcore"] = {
            **payload["pimcore"],
            "enabled": True,
            "api_key": "pimcore-secret",
            "setup_complete": True,
            "class_id": "7",
            "parent_path": "/Produkty",
        }

        with (
            patch.object(config, "_active_sqlite_store", return_value=None),
            patch.object(config, "_write_json_atomic") as write_atomic,
        ):
            config.save_config(payload)

        raw = write_atomic.call_args.args[1]
        self.assertNotEqual(raw["pimcore"]["api_key"], "pimcore-secret")
        self.assertEqual(config.decrypt(raw["pimcore"]["api_key"]), "pimcore-secret")
        self.assertIs(raw["pimcore"]["setup_complete"], True)
        self.assertEqual(raw["pimcore"]["class_id"], "7")
        self.assertEqual(raw["pimcore"]["parent_path"], "/Produkty")

    def test_save_config_encrypts_additional_sql_profile_passwords(self) -> None:
        payload = deepcopy(common.DEFAULT_CONFIG)
        payload["sql_profiles"] = [
            {
                "id": "stock",
                "label": "Stock",
                "type": "mysql",
                "host": "mysql.local",
                "database": "catalog",
                "user": "reader",
                "password": "profile-secret",
                "enabled": True,
            }
        ]

        with (
            patch.object(config, "_active_sqlite_store", return_value=None),
            patch.object(config, "_write_json_atomic") as write_atomic,
        ):
            config.save_config(payload)

        raw_profiles = write_atomic.call_args.args[1]["sql_profiles"]
        self.assertNotEqual(raw_profiles[0]["password"], "profile-secret")
        self.assertEqual(config.decrypt(raw_profiles[0]["password"]), "profile-secret")


if __name__ == "__main__":
    unittest.main()
