"""Tests for local web user account helpers."""

from __future__ import annotations

import os
import gc
import json
from pathlib import Path
import shutil
import time
import unittest
from unittest.mock import Mock, patch
import uuid

from picsyncra import data_store, email_settings, storage_settings, web_data
from picsyncra.sqlite_store import SqliteStore


def _workspace_temp(name: str) -> Path:
    root = Path(__file__).resolve().parents[1] / "tmp_test" / name
    if root.exists():
        _remove_workspace_temp(root)
    root.mkdir(parents=True)
    return root


def _remove_workspace_temp(path: Path) -> None:
    """Release SQLite test state before removing its Windows-hosted directory."""

    data_store.reset_active_store_cache()
    deadline = time.monotonic() + 5.0
    while True:
        gc.collect()
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


class WebDataUserTests(unittest.TestCase):
    def setUp(self) -> None:
        data_store.reset_active_store_cache()

    def tearDown(self) -> None:
        web_data._FILE_INDEX = None
        web_data._FILE_INDEX_KEY = None
        web_data._FILE_INDEX_REFRESH_STARTED = False
        data_store.reset_active_store_cache()

    def test_default_admin_can_authenticate(self) -> None:
        temp_dir = _workspace_temp("web_data_users_default")
        try:
            with patch.object(web_data.settings, "AC", str(temp_dir)):
                user = web_data.authenticate_user("admin", "admin")
        finally:
            _remove_workspace_temp(temp_dir)

        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "admin")

    def test_user_snapshot_keeps_raw_epoch_for_auth_times(self) -> None:
        record = web_data._default_admin()
        expected = {
            "extension_token_issued_ts": 946_684_800.125,
            "extension_token_last_used_ts": 978_307_200.25,
            "lock_expires_ts": 1_893_456_000.5,
            "last_failed_login_ts": 1_609_459_200.75,
        }
        record.update(
            {
                "extension_token_issued_at": expected["extension_token_issued_ts"],
                "extension_token_last_used_at": expected[
                    "extension_token_last_used_ts"
                ],
                "last_failed_login_at": expected["last_failed_login_ts"],
            }
        )
        record["login_locked_until"] = expected["lock_expires_ts"]
        record["login_lock_manual"] = False
        with (
            patch.object(web_data, "load_user_records", return_value=[record]),
            patch.object(web_data.time, "time", return_value=1_800_000_000.0),
        ):
            snapshot = web_data.find_user("admin")

        self.assertIsNotNone(snapshot)
        for key, value in expected.items():
            self.assertEqual(snapshot[key], value)

    def test_existing_user_without_email_normalizes_to_empty_string(self) -> None:
        record = web_data._normalized_user_record(
            {"username": "operator", "password_hash": "hash"}
        )

        self.assertEqual(record["email"], "")
        self.assertEqual(web_data._public_user(record)["email"], "")

    def test_legacy_user_ids_are_migrated_and_persisted(self) -> None:
        temp_dir = _workspace_temp("web_data_users_uuid_migration")
        try:
            users_path = temp_dir / web_data.WEB_USERS_PATH
            users_path.write_text(
                json.dumps([{"username": "operator", "password_hash": "hash"}]),
                encoding="utf-8",
            )
            with patch.object(web_data.settings, "AC", str(temp_dir)):
                first = web_data.find_user("operator")
                stored = json.loads(users_path.read_text(encoding="utf-8"))
                second = web_data.find_user("operator")
        finally:
            _remove_workspace_temp(temp_dir)

        self.assertIsNotNone(first)
        self.assertEqual(uuid.UUID(first["id"]).version, 4)
        stored_operator = next(user for user in stored if user["username"] == "operator")
        self.assertEqual(stored_operator["id"], first["id"])
        self.assertEqual(second["id"], first["id"])

    def test_find_user_by_id_returns_public_user(self) -> None:
        record = web_data._default_admin()
        with patch.object(web_data, "load_user_records", return_value=[record]):
            user = web_data.find_user_by_id(record["id"])

        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "admin")
        self.assertEqual(user["id"], record["id"])

    def test_add_user_persists_normalized_email(self) -> None:
        saved_records = []

        def fake_save(users):
            saved_records.extend(users)
            return [web_data._public_user(item) for item in users]

        with (
            patch.object(web_data, "load_user_records", return_value=[web_data._default_admin()]),
            patch.object(web_data, "save_users", side_effect=fake_save),
        ):
            users = web_data.add_user(
                "operator",
                "secret",
                email=" Operator@Example.COM ",
            )

        operator = next(user for user in users if user["username"] == "operator")
        saved_operator = next(
            user for user in saved_records if user["username"] == "operator"
        )
        self.assertEqual(saved_operator["email"], "Operator@example.com")
        self.assertEqual(operator["email"], "Operator@example.com")
        self.assertEqual(uuid.UUID(saved_operator["id"]).version, 4)
        self.assertEqual(operator["id"], saved_operator["id"])

    def test_update_user_persists_normalized_email(self) -> None:
        with (
            patch.object(
                web_data,
                "load_user_records",
                return_value=[web_data._default_admin()],
            ),
            patch.object(
                web_data,
                "save_users",
                side_effect=lambda users: [
                    web_data._public_user(item) for item in users
                ],
            ),
        ):
            users = web_data.update_user("admin", email=" Admin@Example.COM ")

        self.assertEqual(users[0]["email"], "Admin@example.com")

    def test_update_user_empty_email_clears_address(self) -> None:
        admin = web_data._default_admin()
        admin["email"] = "admin@example.com"
        with (
            patch.object(web_data, "load_user_records", return_value=[admin]),
            patch.object(
                web_data,
                "save_users",
                side_effect=lambda users: [
                    web_data._public_user(item) for item in users
                ],
            ),
        ):
            users = web_data.update_user("admin", email="")

        self.assertEqual(users[0]["email"], "")

    def test_update_user_rejects_invalid_email_address(self) -> None:
        with (
            patch.object(
                web_data,
                "load_user_records",
                return_value=[web_data._default_admin()],
            ),
            patch.object(web_data, "save_users") as save_users,
        ):
            with self.assertRaisesRegex(ValueError, "Niepoprawny adres e-mail"):
                web_data.update_user("admin", email="Admin <admin@example.com>")

        save_users.assert_not_called()

    def test_normalize_email_address_rejects_multiple_addresses(self) -> None:
        with self.assertRaisesRegex(ValueError, "Niepoprawny adres e-mail"):
            email_settings.normalize_email_address(
                "admin@example.com, operator@example.com"
            )

    def test_update_user_blocks_disabling_current_account(self) -> None:
        temp_dir = _workspace_temp("web_data_users_update")
        try:
            with patch.object(web_data.settings, "AC", str(temp_dir)):
                web_data.add_user("operator", "secret", "user")
                with self.assertRaises(ValueError):
                    web_data.update_user("operator", enabled=False, current_username="operator")

                users = web_data.update_user("operator", enabled=False, current_username="admin")
        finally:
            _remove_workspace_temp(temp_dir)

        operator = next(user for user in users if user["username"] == "operator")
        self.assertFalse(operator["enabled"])

    def test_failed_login_temporarily_locks_regular_user(self) -> None:
        temp_dir = _workspace_temp("web_data_users_temp_lock")
        try:
            with patch.object(web_data.settings, "AC", str(temp_dir)):
                web_data.add_user("operator", "secret", "user")
                result = {}
                for _index in range(web_data.LOGIN_FAILURE_LIMIT):
                    result = web_data.authenticate_login(
                        "operator",
                        "bad",
                        remote_address="10.0.0.5",
                    )

                self.assertFalse(result["ok"])
                self.assertTrue(result["user"]["locked"])
                self.assertFalse(result["user"]["lock_manual"])
                self.assertEqual(result["user"]["failed_login_count"], web_data.LOGIN_FAILURE_LIMIT)
                self.assertIsNone(web_data.authenticate_user("operator", "secret"))

                users = web_data.unlock_user("operator")
                operator = next(user for user in users if user["username"] == "operator")
                self.assertFalse(operator["locked"])
                self.assertEqual(operator["failed_login_count"], 0)
                self.assertIsNotNone(web_data.authenticate_user("operator", "secret"))
        finally:
            _remove_workspace_temp(temp_dir)

    def test_failed_login_locks_admin_until_manual_unlock(self) -> None:
        temp_dir = _workspace_temp("web_data_users_admin_lock")
        try:
            with patch.object(web_data.settings, "AC", str(temp_dir)):
                result = {}
                for _index in range(web_data.LOGIN_FAILURE_LIMIT):
                    result = web_data.authenticate_login("admin", "bad")

                self.assertFalse(result["ok"])
                self.assertTrue(result["user"]["locked"])
                self.assertTrue(result["user"]["lock_manual"])
                self.assertIsNone(web_data.authenticate_user("admin", "admin"))

                web_data.unlock_user("admin")
                self.assertIsNotNone(web_data.authenticate_user("admin", "admin"))
        finally:
            _remove_workspace_temp(temp_dir)

    def test_password_change_bumps_session_and_extension_versions(self) -> None:
        temp_dir = _workspace_temp("web_data_users_session_version")
        try:
            with patch.object(web_data.settings, "AC", str(temp_dir)):
                web_data.add_user("operator", "secret", "user")
                before = web_data.find_user("operator")
                users = web_data.update_user("operator", password="new-secret")
                after = next(user for user in users if user["username"] == "operator")

            self.assertEqual(before["session_version"], 0)
            self.assertEqual(before["extension_token_version"], 0)
            self.assertEqual(after["session_version"], 1)
            self.assertEqual(after["extension_token_version"], 1)
        finally:
            _remove_workspace_temp(temp_dir)

    def test_extension_token_issue_and_use_metadata_is_public(self) -> None:
        temp_dir = _workspace_temp("web_data_users_extension_metadata")
        try:
            with patch.object(web_data.settings, "AC", str(temp_dir)):
                web_data.add_user("operator", "secret", "user")
                issued = web_data.mark_browser_extension_token_issued("operator")
                used = web_data.mark_browser_extension_token_used(
                    "operator",
                    issued["extension_token_version"],
                )

            self.assertTrue(issued["extension_token_issued_at"])
            self.assertTrue(used["extension_token_last_used_at"])
        finally:
            _remove_workspace_temp(temp_dir)

    def test_add_list_value_rejects_case_insensitive_duplicate(self) -> None:
        with (
            patch.object(web_data, "prepare_excel_lists", return_value={"NAZWY": ["Żyrandol"]}),
            patch.object(web_data, "add_to_list") as add_to_list,
        ):
            with self.assertRaises(ValueError):
                web_data.add_list_value("names", "zyrandol")

        add_to_list.assert_not_called()

    def test_remove_list_value_blocks_values_used_by_entries(self) -> None:
        used_by = [{"product_id": "PRD-1", "ean": "5901234567890", "label": "MAGGIORE"}]
        with (
            patch.object(web_data, "find_list_value_usage", return_value=used_by),
            patch.object(web_data, "remove_from_list") as remove_from_list,
        ):
            with self.assertRaises(web_data.ListValueInUseError) as caught:
                web_data.remove_list_value("names", "MAGGIORE")

        self.assertEqual(caught.exception.used_by, used_by)
        self.assertEqual(caught.exception.list_key, "names")
        self.assertEqual(caught.exception.value, "MAGGIORE")
        remove_from_list.assert_not_called()

    def test_history_snapshot_filters_search_and_limits_page_size(self) -> None:
        records = []
        for index in range(60):
            records.append(
                {
                    "ts": 1000 - index,
                    "ean": f"5900000000{index:02}",
                    "product_id": f"PRD-{index:02}",
                    "summary": f"Zmiana {index}",
                    "user": "alice" if index % 2 else "bob",
                    "details": {
                        "entry": {
                            "NAZWA": "Target Lamp" if index == 10 else f"Name {index}",
                            "MODEL": f"Model {index}",
                        },
                        "timing": {"total_ms": index, "stages": []},
                    },
                }
            )

        with patch.object(web_data, "_load_history_records", return_value=records):
            search_payload = web_data.history_snapshot(query="target", page_size=50)
            page_payload = web_data.history_snapshot(page=2, page_size=80)

        self.assertEqual(search_payload["total_groups"], 1)
        self.assertEqual(search_payload["groups"][0]["ean"], "590000000010")
        self.assertEqual(page_payload["page_size"], 50)
        self.assertEqual(page_payload["page"], 2)
        self.assertEqual(page_payload["total_pages"], 2)
        self.assertEqual(len(page_payload["groups"]), 10)

    def test_history_snapshot_returns_paged_summaries_after_one_load(self) -> None:
        records = [
            {
                "ts": 1000 - index,
                "ean": f"5900000000{index:02}",
                "user": "alice" if index % 2 else "bob",
                "details": {
                    "entry": {"NAZWA": f"Name {index}"},
                    "timing": {"stages": ["large"]},
                },
            }
            for index in range(60)
        ]
        loader = Mock(return_value=records)

        with patch.object(web_data, "_load_history_records", loader):
            payload = web_data.history_snapshot(page=2, page_size=50)

        self.assertEqual(loader.call_count, 1)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(len(payload["groups"]), 10)
        self.assertEqual(
            set(payload["groups"][0]),
            {"ean", "latest_ts", "change_count", "entry"},
        )
        self.assertNotIn("items", payload["groups"][0])

    def test_history_group_snapshot_returns_only_filtered_ean_items(self) -> None:
        records = [
            {
                "ean": "5901",
                "user": "alice",
                "ts": 2,
                "details": {"entry": {"NAZWA": "A"}},
            },
            {"ean": "5901", "user": "bob", "ts": 1, "details": {}},
            {"ean": "5902", "user": "alice", "ts": 3, "details": {}},
        ]

        with patch.object(web_data, "_load_history_records", return_value=records):
            payload = web_data.history_group_snapshot(ean="5901", user="alice")

        self.assertEqual(payload["ean"], "5901")
        self.assertEqual([item["user"] for item in payload["items"]], ["alice"])

    def test_history_group_snapshot_pages_legacy_records(self) -> None:
        records = [
            {"ean": "5901", "ts": 1000 - index, "details": {}}
            for index in range(60)
        ]

        with patch.object(web_data, "_load_history_records", return_value=records):
            payload = web_data.history_group_snapshot(ean="5901", page=2, page_size=25)

        self.assertEqual(len(payload["items"]), 25)
        self.assertEqual(
            (payload["page"], payload["total_items"], payload["total_pages"]),
            (2, 60, 3),
        )

    def test_history_snapshots_delegate_to_sqlite_store_without_full_load(self) -> None:
        store = Mock(spec=["history_summary_snapshot", "history_group_snapshot"])
        summary_payload = {"groups": [], "page": 2}
        details_payload = {"ean": "5901", "items": [], "page": 2}
        store.history_summary_snapshot.return_value = summary_payload
        store.history_group_snapshot.return_value = details_payload

        with (
            patch.object(web_data, "_active_sqlite_store", return_value=store),
            patch.object(
                web_data,
                "_load_history_records",
                side_effect=AssertionError("SQLite snapshots must not load all history"),
            ),
        ):
            self.assertIs(
                web_data.history_snapshot(user="alice", query="lamp", page=2, page_size=30),
                summary_payload,
            )
            self.assertIs(
                web_data.history_group_snapshot(
                    ean="5901", user="alice", query="lamp", page=2, page_size=20
                ),
                details_payload,
            )

        store.history_summary_snapshot.assert_called_once_with(
            user="alice", query="lamp", page=2, page_size=30
        )
        store.history_group_snapshot.assert_called_once_with(
            ean="5901", user="alice", query="lamp", page=2, page_size=20
        )

    def test_ftp_cache_dir_can_be_scoped_per_user_session(self) -> None:
        temp_dir = _workspace_temp("web_data_ftp_cache_scope")
        try:
            with patch.object(web_data.settings, "AC", str(temp_dir)):
                scoped = Path(web_data._ftp_cache_dir("5901234567890", cache_scope="admin-session"))
                unscoped = Path(web_data._ftp_cache_dir("5901234567890"))
        finally:
            _remove_workspace_temp(temp_dir)

        self.assertEqual(scoped, temp_dir / "web_ftp_cache" / "admin-session" / "5901234567890")
        self.assertEqual(unscoped, temp_dir / "web_ftp_cache" / "5901234567890")

    def test_cleanup_web_ftp_cache_removes_only_stale_files(self) -> None:
        temp_dir = _workspace_temp("web_data_ftp_cache_cleanup")
        try:
            cache_dir = temp_dir / "web_ftp_cache" / "admin-session" / "5901234567890"
            cache_dir.mkdir(parents=True)
            old_file = cache_dir / "old.jpg"
            new_file = cache_dir / "new.jpg"
            old_file.write_bytes(b"old")
            new_file.write_bytes(b"new")
            old_time = time.time() - 3 * 24 * 60 * 60
            os.utime(old_file, (old_time, old_time))

            with patch.object(web_data.settings, "AC", str(temp_dir)):
                result = web_data.cleanup_web_ftp_cache(
                    max_age_seconds=24 * 60 * 60,
                    min_interval_seconds=1,
                    force=True,
                )

            self.assertEqual(result["deleted_files"], 1)
            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())
        finally:
            _remove_workspace_temp(temp_dir)

    def test_invalidate_ftp_preview_cache_removes_changed_slot_file(self) -> None:
        temp_dir = _workspace_temp("web_data_ftp_cache_invalidate")
        try:
            with patch.object(web_data.settings, "AC", str(temp_dir)):
                cache_dir = Path(web_data._ftp_cache_dir("5901234567890", cache_scope="admin-session"))
                cache_dir.mkdir(parents=True)
                cached = cache_dir / web_data._ftp_cache_filename("5901234567890_03.jpg")
                cached.write_bytes(b"old")

                result = web_data.invalidate_ftp_preview_cache(
                    "5901234567890",
                    {"5901234567890_03.jpg"},
                    cache_scope="admin-session",
                )
        finally:
            _remove_workspace_temp(temp_dir)

        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["errors"], [])
        self.assertFalse(cached.exists())

    def test_cache_ftp_preview_returns_existing_cache_without_ftp(self) -> None:
        temp_dir = _workspace_temp("web_data_ftp_cache_hit")
        try:
            with patch.object(web_data.settings, "AC", str(temp_dir)):
                cache_dir = Path(web_data._ftp_cache_dir("5901234567890", cache_scope="admin-session"))
                cached = cache_dir / web_data._ftp_cache_filename("5901234567890_03.jpg")
                cache_dir.mkdir(parents=True)
                cached.write_bytes(b"cached")

                with patch.object(web_data, "connect_ftp") as connect_ftp:
                    result = web_data.cache_ftp_preview(
                        "5901234567890",
                        "5901234567890_03.jpg",
                        cache_scope="admin-session",
                    )

                self.assertEqual(Path(result), cached)
                connect_ftp.assert_not_called()
        finally:
            _remove_workspace_temp(temp_dir)

    def test_cache_ftp_preview_downloads_directly_without_remote_listing(self) -> None:
        temp_dir = _workspace_temp("web_data_ftp_direct_download")

        class FakeFtp:
            def retrbinary(self, command, callback):
                self.command = command
                callback(b"ftp-bytes")

            def quit(self):
                return None

        ftp = FakeFtp()
        try:
            with (
                patch.object(web_data.settings, "AC", str(temp_dir)),
                patch.object(web_data, "connect_ftp", return_value=ftp),
                patch.object(web_data, "list_remote_filenames") as list_remote,
            ):
                result = web_data.cache_ftp_preview(
                    "5901234567890",
                    "5901234567890_03.jpg",
                    cache_scope="admin-session",
                )

            self.assertEqual(Path(result).read_bytes(), b"ftp-bytes")
            self.assertEqual(ftp.command, "RETR 5901234567890_03.jpg")
            list_remote.assert_not_called()
        finally:
            _remove_workspace_temp(temp_dir)

    def test_save_web_entry_preserves_ean_for_existing_product_id_when_missing(self) -> None:
        with (
            patch.object(
                web_data,
                "find_entry_by_identity",
                return_value={"product_id": "PRD-1", "ean": "5901234567890"},
            ),
            patch.object(
                web_data,
                "save_ean_entry",
                return_value={"updated": True, "product_id": "PRD-1", "entry": {}},
            ) as save_ean_entry,
        ):
            result = web_data.save_web_entry(
                {
                    "product_id": "PRD-1",
                    "name": "Maggiore",
                    "type_name": "Komoda",
                    "model": "MA03",
                    "color1": "Bialy",
                }
            )

        self.assertEqual(result["product_id"], "PRD-1")
        args, kwargs = save_ean_entry.call_args
        self.assertEqual(args[0], "5901234567890")
        self.assertEqual(kwargs["product_id"], "PRD-1")

    def test_find_product_photos_merges_live_files_when_index_is_stale(self) -> None:
        class StaleIndex:
            def has_snapshot(self) -> bool:
                return True

            def get_product_files(self, *_args, **_kwargs):
                return []

        temp_dir = _workspace_temp("web_data_live_photos")
        try:
            product_dir = Path(
                web_data.build_product_directory(
                    str(temp_dir / "processed"),
                    "Maggiore",
                    "komoda",
                    "MA03",
                    ["bialy", "", ""],
                    "",
                )
            )
            product_dir.mkdir(parents=True)
            filename = "5901234567890_03_DETAIL_MAGGIORE_KOMODA_MA03_BIALY_NO-LED.jpg"
            (product_dir / filename).write_bytes(b"fake")
            with (
                patch.object(web_data.settings, "l", str(temp_dir / "processed")),
                patch.object(web_data, "_get_file_index", return_value=StaleIndex()),
            ):
                photos = web_data.find_product_photos(
                    {
                        "ean": "5901234567890",
                        "name": "Maggiore",
                        "type_name": "komoda",
                        "model": "MA03",
                        "color1": "bialy",
                    },
                    include_ftp=False,
                    include_sql=False,
                )
        finally:
            _remove_workspace_temp(temp_dir)

        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]["prefix"], "03")
        self.assertTrue(photos[0]["local"])

    def test_find_product_photos_reports_sql_presence_without_sql_urls(self) -> None:
        config_payload = {
            web_data.SLOT_DEFS_KEY: [
                {"prefix": "03", "label": "DETAIL_pic"},
                {"prefix": "04", "label": "MAIN_pic"},
            ],
            web_data.SQL_COLUMN_MAP_KEY: {"03": "img_03", "04": "img_04"},
        }
        with (
            patch.object(web_data.config, "CONFIG", config_payload),
            patch.object(web_data, "should_check_presence", return_value=True),
            patch.object(
                web_data,
                "extract_presence_context",
                return_value=("object_query_1", " WHERE EAN = '5901234567890'"),
            ),
            patch.object(
                web_data,
                "query_presence_details",
                return_value=(
                    {"03": True, "04": False},
                    {"03": "https://cdn.example.test/img/5901234567890_03.jpg", "04": ""},
                ),
            ),
        ):
            photos = web_data.find_product_photos(
                {
                    "ean": "5901234567890",
                    "name": "Maggiore",
                    "type_name": "komoda",
                    "model": "MA03",
                    "color1": "bialy",
                },
                include_local=False,
                include_ftp=False,
                include_sql=True,
            )

        self.assertEqual([photo["prefix"] for photo in photos], ["03"])
        self.assertTrue(photos[0]["sql"])
        self.assertTrue(photos[0]["sql_checked"])
        self.assertEqual(
            photos[0]["sql_value"],
            "https://cdn.example.test/img/5901234567890_03.jpg",
        )
        self.assertFalse(photos[0]["is_image"])

    def test_find_product_photos_keeps_local_slot_when_sql_is_empty(self) -> None:
        temp_dir = _workspace_temp("web_data_local_sql_empty")
        try:
            product_dir = Path(
                web_data.build_product_directory(
                    str(temp_dir / "processed"),
                    "Maggiore",
                    "komoda",
                    "MA03",
                    ["bialy", "", ""],
                    "",
                )
            )
            product_dir.mkdir(parents=True)
            filename = "5901234567890_03_DETAIL_MAGGIORE_KOMODA_MA03_BIALY_NO-LED.jpg"
            (product_dir / filename).write_bytes(b"fake")
            config_payload = {
                web_data.SLOT_DEFS_KEY: [{"prefix": "03", "label": "DETAIL_pic"}],
                web_data.SQL_COLUMN_MAP_KEY: {"03": "img_03"},
            }
            with (
                patch.object(web_data.settings, "l", str(temp_dir / "processed")),
                patch.object(web_data.config, "CONFIG", config_payload),
                patch.object(web_data, "_get_file_index", return_value=None),
                patch.object(web_data, "should_check_presence", return_value=True),
                patch.object(
                    web_data,
                    "extract_presence_context",
                    return_value=("object_query_1", " WHERE EAN = '5901234567890'"),
                ),
                patch.object(
                    web_data,
                    "query_presence_details",
                    return_value=({"03": False}, {"03": ""}),
                ),
            ):
                photos = web_data.find_product_photos(
                    {
                        "ean": "5901234567890",
                        "name": "Maggiore",
                        "type_name": "komoda",
                        "model": "MA03",
                        "color1": "bialy",
                    },
                    include_local=True,
                    include_ftp=False,
                    include_sql=True,
                )
        finally:
            _remove_workspace_temp(temp_dir)

        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]["prefix"], "03")
        self.assertTrue(photos[0]["local"])
        self.assertFalse(photos[0]["sql"])
        self.assertTrue(photos[0]["sql_checked"])
        self.assertEqual(photos[0]["sql_value"], "")

    def test_find_product_photos_leaves_sql_unchecked_when_sql_row_missing(self) -> None:
        temp_dir = _workspace_temp("web_data_local_sql_row_missing")
        try:
            product_dir = Path(
                web_data.build_product_directory(
                    str(temp_dir / "processed"),
                    "Maggiore",
                    "komoda",
                    "MA03",
                    ["bialy", "", ""],
                    "",
                )
            )
            product_dir.mkdir(parents=True)
            filename = "5901234567890_03_DETAIL_MAGGIORE_KOMODA_MA03_BIALY_NO-LED.jpg"
            (product_dir / filename).write_bytes(b"fake")
            config_payload = {
                web_data.SLOT_DEFS_KEY: [{"prefix": "03", "label": "DETAIL_pic"}],
                web_data.SQL_COLUMN_MAP_KEY: {"03": "img_03"},
            }
            with (
                patch.object(web_data.settings, "l", str(temp_dir / "processed")),
                patch.object(web_data.config, "CONFIG", config_payload),
                patch.object(web_data, "_get_file_index", return_value=None),
                patch.object(web_data, "should_check_presence", return_value=True),
                patch.object(
                    web_data,
                    "extract_presence_context",
                    return_value=("object_query_1", " WHERE EAN = '5901234567890'"),
                ),
                patch.object(
                    web_data,
                    "query_presence_details",
                    return_value=({"03": None}, {"03": ""}),
                ),
            ):
                photos = web_data.find_product_photos(
                    {
                        "ean": "5901234567890",
                        "name": "Maggiore",
                        "type_name": "komoda",
                        "model": "MA03",
                        "color1": "bialy",
                    },
                    include_local=True,
                    include_ftp=False,
                    include_sql=True,
                )
        finally:
            _remove_workspace_temp(temp_dir)

        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]["prefix"], "03")
        self.assertTrue(photos[0]["local"])
        self.assertFalse(photos[0]["sql"])
        self.assertFalse(photos[0]["sql_checked"])
        self.assertEqual(photos[0]["sql_value"], "")

    def test_web_base_dir_change_updates_local_settings_and_runtime(self) -> None:
        temp_dir = _workspace_temp("web_data_base_dir_change")
        old_values = {
            name: getattr(web_data.settings, name, None)
            for name in (
                "AC",
                "l",
                "LISTS_WORKBOOK_PATH",
                "AD",
                "AM",
                "BM",
                "AN",
                "BASE_DIR_OVERRIDE",
                "BASE_DIR_OVERRIDE_WARNING",
                "BASE_DIR_SETTINGS_PATH",
                "_RUNTIME_INITIALIZED",
            )
        }
        try:
            settings_path = temp_dir / "settings-root" / "local_settings.json"
            requested = temp_dir / "new-base"
            with patch.object(web_data.settings, "BASE_DIR_SETTINGS_PATH", str(settings_path)):
                changed = web_data._apply_base_dir_from_web(f'"{requested}"')

            self.assertTrue(changed)
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(Path(payload["base_dir_override"]), requested.resolve())
            self.assertEqual(Path(web_data.settings.AC), requested.resolve())
        finally:
            for name, value in old_values.items():
                setattr(web_data.settings, name, value)
            _remove_workspace_temp(temp_dir)

    def test_web_base_dir_change_reports_inaccessible_path(self) -> None:
        temp_dir = _workspace_temp("web_data_base_dir_invalid")
        try:
            settings_path = temp_dir / "local_settings.json"
            with (
                patch.object(web_data.settings, "BASE_DIR_SETTINGS_PATH", str(settings_path)),
                patch.object(
                    web_data.settings,
                    "_ensure_directory_access",
                    return_value=(False, PermissionError("denied")),
                ),
            ):
                with self.assertRaises(ValueError) as caught:
                    web_data._apply_base_dir_from_web(str(temp_dir / "denied"))

            self.assertIn("Nie mozna uzyc katalogu bazowego", str(caught.exception))
            self.assertFalse(settings_path.exists())
        finally:
            _remove_workspace_temp(temp_dir)

    def test_update_settings_reloads_target_config_after_base_dir_change(self) -> None:
        old_config = {"old_only": True, web_data.LOCAL_FILE_INDEX_KEY: False}
        target_config = {"target_only": True, web_data.LOCAL_FILE_INDEX_KEY: False}
        saved_configs = []

        def reload_target_config(*_args, **_kwargs):
            web_data.config.CONFIG.clear()
            web_data.config.CONFIG.update(target_config)
            return web_data.config.CONFIG

        def capture_save_config(config_payload, *_args, **_kwargs):
            saved_configs.append(dict(config_payload))

        with (
            patch.object(web_data.config, "CONFIG", old_config),
            patch.object(web_data, "_apply_base_dir_from_web", return_value=True),
            patch.object(web_data.config, "initialize_config", side_effect=reload_target_config),
            patch.object(web_data, "save_config", side_effect=capture_save_config),
            patch.object(web_data, "settings_snapshot", return_value={}),
        ):
            web_data.update_settings(
                {"app": {"base_dir": "C:\\PicSyncra", web_data.LOCAL_FILE_INDEX_KEY: True}}
            )

        self.assertEqual(len(saved_configs), 1)
        saved_config = saved_configs[0]
        self.assertNotIn("old_only", saved_config)
        self.assertTrue(saved_config["target_only"])
        self.assertTrue(saved_config[web_data.LOCAL_FILE_INDEX_KEY])

    def test_settings_snapshot_and_partial_update_expose_web_display_time_zone(self) -> None:
        cfg = json.loads(json.dumps(web_data.config.DEFAULT_CONFIG))
        saved_configs = []

        with (
            patch.object(web_data.config, "CONFIG", cfg),
            patch.object(
                web_data.config,
                "available_display_time_zones",
                return_value=["UTC", "Europe/Warsaw"],
            ),
            patch.object(
                web_data,
                "save_config",
                side_effect=lambda payload, **_kwargs: saved_configs.append(
                    json.loads(json.dumps(payload))
                ),
            ),
            patch.object(web_data.config, "initialize_config", return_value=cfg),
            patch.object(web_data, "load_users", return_value=[]),
        ):
            initial = web_data.settings_snapshot()
            updated = web_data.update_settings(
                {"web_display": {"time_zone": "Europe/Warsaw"}}
            )

        self.assertEqual(initial["web_display"], {"time_zone": "UTC"})
        self.assertEqual(
            saved_configs[0]["web_display"],
            {"time_zone": "Europe/Warsaw"},
        )
        self.assertEqual(updated["web_display"], {"time_zone": "Europe/Warsaw"})

    def test_update_settings_rejects_invalid_time_zone_without_overwriting_saved_value(self) -> None:
        cfg = json.loads(json.dumps(web_data.config.DEFAULT_CONFIG))
        cfg["web_display"] = {"time_zone": "Europe/Warsaw"}
        saved_configs = []

        with (
            patch.object(web_data.config, "CONFIG", cfg),
            patch.object(
                web_data.config,
                "available_display_time_zones",
                return_value=["UTC", "Europe/Warsaw"],
            ),
            patch.object(
                web_data,
                "save_config",
                side_effect=lambda payload, **_kwargs: saved_configs.append(
                    json.loads(json.dumps(payload))
                ),
            ),
            patch.object(web_data.config, "initialize_config", return_value=cfg),
            patch.object(
                web_data,
                "settings_snapshot",
                side_effect=lambda: {"web_display": dict(cfg["web_display"])},
            ),
        ):
            for invalid in ("CEST", "Invalid/Time_Zone"):
                with self.assertRaisesRegex(ValueError, "strefa czasowa"):
                    web_data.update_settings({"web_display": {"time_zone": invalid}})
                self.assertEqual(cfg["web_display"], {"time_zone": "Europe/Warsaw"})
                self.assertEqual(saved_configs, [])

            updated = web_data.update_settings({"web_display": {"time_zone": "UTC"}})

        self.assertEqual(cfg["web_display"], {"time_zone": "UTC"})
        self.assertEqual(len(saved_configs), 1)
        self.assertEqual(saved_configs[0]["web_display"], {"time_zone": "UTC"})
        self.assertEqual(updated["web_display"], {"time_zone": "UTC"})

    def test_update_settings_persists_storage_bootstrap(self) -> None:
        temp_dir = _workspace_temp("web_data_storage_update")
        try:
            image_dir = temp_dir / "photos"
            db_path = temp_dir / "db" / "data.sqlite"
            with (
                patch.object(web_data, "_apply_base_dir_from_web", return_value=True) as apply_base,
                patch.object(web_data.storage_settings, "save_bootstrap_settings") as save_bootstrap,
                patch.object(web_data.data_store, "reset_active_store_cache") as reset_store,
                patch.object(web_data.config, "initialize_config", return_value=web_data.config.CONFIG),
                patch.object(web_data, "save_config"),
                patch.object(web_data, "settings_snapshot", return_value={}),
            ):
                web_data.update_settings(
                    {
                        "app": {
                            "image_dir": str(image_dir),
                            "data_mode": "sqlite",
                            "database_location_mode": "custom",
                            "database_path": str(db_path),
                        }
                    }
                )

            apply_base.assert_called_once_with(str(image_dir))
            save_bootstrap.assert_called_once_with(
                {
                    "data_mode": "sqlite",
                    "database_location_mode": "custom",
                    "database_path": str(db_path),
                }
            )
            reset_store.assert_called()
        finally:
            _remove_workspace_temp(temp_dir)

    def test_update_settings_preserves_unsubmitted_encrypted_secrets(self) -> None:
        preserve = web_data._preserve_unsubmitted_config_secrets(
            {
                "ftp": {"host": "ftp.example.com", "user": "", "password": ""},
                "database": {
                    "mssql": {"server": "sql", "user": "", "password": ""},
                    "mysql": {"server": "mysql", "user": "new-user", "password": ""},
                },
            }
        )

        self.assertEqual(preserve[web_data.H], {web_data.N, web_data.M})
        self.assertEqual(preserve[web_data.P], {web_data.N, web_data.M})
        self.assertEqual(preserve[web_data.K], {web_data.M})

    def test_settings_snapshot_exposes_public_sql_profiles(self) -> None:
        cfg = json.loads(json.dumps(web_data.config.DEFAULT_CONFIG))
        cfg["sql_profiles"] = [
            {
                "id": "stock",
                "label": "Stock",
                "type": "mysql",
                "host": "mysql.local",
                "database": "catalog",
                "user": "reader",
                "password": "stock-password-value",
                "enabled": True,
            }
        ]

        with (
            patch.object(web_data.config, "CONFIG", cfg),
            patch.object(web_data, "load_users", return_value=[]),
        ):
            snapshot = web_data.settings_snapshot()

        self.assertEqual([item["id"] for item in snapshot["database"]["profiles"]], ["stock"])
        self.assertEqual(snapshot["database"]["profiles"][0]["usage"], "pimcore_sql")
        self.assertTrue(snapshot["database"]["profiles"][0]["user_set"])
        self.assertTrue(snapshot["database"]["profiles"][0]["password_set"])
        self.assertNotIn("reader", json.dumps(snapshot))
        self.assertNotIn("stock-password-value", json.dumps(snapshot))

    def test_update_settings_saves_additional_sql_profiles_and_preserves_blank_credentials(self) -> None:
        cfg = json.loads(json.dumps(web_data.config.DEFAULT_CONFIG))
        cfg["sql_profiles"] = [
            {
                "id": "stock",
                "label": "Stock",
                "type": "mysql",
                "host": "old.local",
                "database": "catalog",
                "user": "saved-reader",
                "password": "saved-secret",
                "enabled": True,
            }
        ]
        saved = []

        with (
            patch.object(web_data.config, "CONFIG", cfg),
            patch.object(
                web_data,
                "save_config",
                side_effect=lambda payload, **kwargs: saved.append(
                    json.loads(json.dumps(payload))
                ),
            ),
            patch.object(web_data.config, "initialize_config", return_value=cfg),
            patch.object(web_data, "settings_snapshot", return_value={}),
        ):
            web_data.update_settings(
                {
                    "database": {
                        "profiles": [
                            {
                                "id": "stock",
                                "label": "Stock",
                                "type": "mysql",
                                "host": "new.local",
                                "database": "catalog",
                                "user": "",
                                "password": "",
                                "enabled": True,
                            }
                        ]
                    }
                }
            )

        self.assertEqual(saved[0]["sql_profiles"][0]["host"], "new.local")
        self.assertEqual(saved[0]["sql_profiles"][0]["user"], "saved-reader")
        self.assertEqual(saved[0]["sql_profiles"][0]["password"], "saved-secret")

    def test_update_settings_stores_security_payload_separately_from_processing(self) -> None:
        saved_configs = []
        cfg = {
            web_data.PROCESSING_SETTINGS_KEY: {"max_dim": 2000},
            web_data.SECURITY_SETTINGS_KEY: {"max_upload_mb": 50},
        }

        def capture_save_config(config_payload, *_args, **_kwargs):
            saved_configs.append(dict(config_payload))

        with (
            patch.object(web_data.config, "CONFIG", cfg),
            patch.object(web_data, "save_config", side_effect=capture_save_config),
            patch.object(web_data.config, "initialize_config", return_value=cfg),
            patch.object(web_data, "settings_snapshot", return_value={}),
        ):
            web_data.update_settings(
                {
                    "processing": {"max_dim": 1600},
                    "security": {
                        "max_upload_mb": 75,
                        "max_upload_pixels": 12_000_000,
                        "allowed_upload_extensions": "jpg,png",
                        "blocked_upload_extensions": "exe,bat",
                        "block_executable_uploads": True,
                        "antivirus_scan_uploads": True,
                    },
                }
            )

        saved_config = saved_configs[0]
        self.assertEqual(saved_config[web_data.PROCESSING_SETTINGS_KEY]["max_dim"], 1600)
        self.assertNotIn("max_upload_mb", saved_config[web_data.PROCESSING_SETTINGS_KEY])
        self.assertEqual(saved_config[web_data.SECURITY_SETTINGS_KEY]["max_upload_mb"], 75)
        self.assertEqual(
            saved_config[web_data.SECURITY_SETTINGS_KEY]["allowed_upload_extensions"],
            ["jpg", "png"],
        )
        self.assertTrue(saved_config[web_data.SECURITY_SETTINGS_KEY]["antivirus_scan_uploads"])

    def test_update_settings_returns_normalized_resource_monitor_settings(self) -> None:
        cfg = json.loads(json.dumps(web_data.config.DEFAULT_CONFIG))

        with (
            patch.object(web_data.config, "CONFIG", cfg),
            patch.object(web_data, "save_config"),
            patch.object(web_data.config, "initialize_config", return_value=cfg),
            patch.object(web_data, "load_users", return_value=[]),
        ):
            snapshot = web_data.update_settings(
                {
                    "resource_monitor": {
                        "show_status": False,
                        "cpu_percent_threshold": 35,
                        "memory_percent_threshold": 25,
                        "io_mib_per_second_threshold": 8,
                    }
                }
            )

        self.assertEqual(
            snapshot["resource_monitor"],
            {
                "show_status": False,
                "cpu_percent_threshold": 35,
                "memory_percent_threshold": 25,
                "io_mib_per_second_threshold": 8,
            },
        )

    def test_security_settings_default_hide_active_web_users(self) -> None:
        normalized = web_data.config._normalize_security_settings({})

        self.assertFalse(normalized["show_active_web_users"])

    def test_update_settings_stores_active_web_users_security_flag(self) -> None:
        saved_configs = []
        cfg = {
            web_data.SECURITY_SETTINGS_KEY: {"max_upload_mb": 50},
        }

        def capture_save_config(config_payload, *_args, **_kwargs):
            saved_configs.append(json.loads(json.dumps(config_payload)))

        with (
            patch.object(web_data.config, "CONFIG", cfg),
            patch.object(web_data, "save_config", side_effect=capture_save_config),
            patch.object(web_data.config, "initialize_config", return_value=cfg),
            patch.object(web_data, "settings_snapshot", return_value={}),
        ):
            web_data.update_settings({"security": {"show_active_web_users": True}})

        self.assertTrue(
            saved_configs[0][web_data.SECURITY_SETTINGS_KEY]["show_active_web_users"]
        )

    def test_update_settings_normalizes_and_saves_product_fields(self) -> None:
        saved_configs = []
        cfg = json.loads(json.dumps(web_data.config.DEFAULT_CONFIG))

        with (
            patch.object(web_data.config, "CONFIG", cfg),
            patch.object(
                web_data,
                "save_config",
                side_effect=lambda payload, **_kwargs: saved_configs.append(
                    json.loads(json.dumps(payload))
                ),
            ),
            patch.object(web_data, "settings_snapshot", return_value={}),
        ):
            web_data.update_settings(
                {
                    "app": {
                        "product_fields": {
                            "model": {
                                "label": "Wersja",
                                "enabled": False,
                                "required": True,
                            }
                        }
                    }
                }
            )

        self.assertEqual(
            saved_configs[0]["product_fields"]["model"],
            {
                "label": "Wersja",
                "enabled": False,
                "required": False,
            },
        )

    def test_save_web_entry_clears_disabled_values_before_persistence(self) -> None:
        cfg = {
            "product_fields": {
                "type": {"enabled": False},
            }
        }

        with (
            patch.object(web_data.config, "CONFIG", cfg),
            patch.object(
                web_data,
                "save_ean_entry",
                return_value={"ok": True},
            ) as save_entry,
        ):
            web_data.save_web_entry(
                {
                    "name": "N",
                    "type_name": "KOMODA",
                    "model": "M",
                    "color1": "C",
                }
            )

        self.assertEqual(save_entry.call_args.args[2], "")

    def test_settings_snapshot_exposes_normalized_product_fields(self) -> None:
        cfg = {
            "product_fields": {
                "name": {
                    "label": "Kolekcja",
                    "enabled": True,
                    "required": True,
                }
            }
        }

        with (
            patch.object(web_data.config, "CONFIG", cfg),
            patch.object(web_data, "load_users", return_value=[]),
        ):
            snapshot = web_data.settings_snapshot()

        self.assertEqual(snapshot["product_fields"]["name"]["label"], "Kolekcja")
        self.assertTrue(snapshot["product_fields"]["color1"]["required"])

    def test_find_product_photos_ignores_disabled_identity_fields(self) -> None:
        cfg = {"product_fields": {"type": {"enabled": False}}}

        with (
            patch.object(web_data.config, "CONFIG", cfg),
            patch.object(
                web_data,
                "build_product_directory",
                return_value="C:\\processed\\MAGGIORE",
            ) as build_directory,
        ):
            web_data.find_product_photos(
                {
                    "name": "MAGGIORE",
                    "type_name": "KOMODA",
                    "model": "MA03",
                    "color1": "BIALY",
                },
                include_local=False,
                include_ftp=False,
                include_sql=False,
            )

        self.assertEqual(build_directory.call_args.args[2], "")

    def test_settings_secret_values_returns_current_decrypted_config(self) -> None:
        config_payload = {
            web_data.H: {web_data.N: "ftp-user", web_data.M: "ftp-pass"},
            web_data.P: {web_data.N: "mssql-user", web_data.M: "mssql-pass"},
            web_data.K: {web_data.N: "mysql-user", web_data.M: "mysql-pass"},
            web_data.SQL_PROFILES_KEY: [
                {
                    "id": "stock",
                    "label": "Stock",
                    "type": "mysql",
                    "host": "mysql.local",
                    "database": "catalog",
                    "user": "profile-user",
                    "password": "profile-pass",
                    "enabled": True,
                }
            ],
        }
        with (
            patch.object(web_data.config, "CONFIG", config_payload),
            patch.object(web_data.common, "APP_SECRET", "secret-from-local-settings"),
        ):
            payload = web_data.settings_secret_values()

        self.assertEqual(payload["app_secret"], "secret-from-local-settings")
        self.assertEqual(payload["ftp"]["user"], "ftp-user")
        self.assertEqual(payload["ftp"]["password"], "ftp-pass")
        self.assertEqual(payload["database"]["mssql"]["password"], "mssql-pass")
        self.assertEqual(payload["database"]["mysql"]["user"], "mysql-user")
        self.assertEqual(payload["database"]["profiles"]["stock"]["user"], "profile-user")
        self.assertEqual(payload["database"]["profiles"]["stock"]["password"], "profile-pass")

    def test_sqlite_mode_persists_web_user_without_json_file(self) -> None:
        temp_dir = _workspace_temp("web_data_sqlite_users")
        try:
            bootstrap = {
                "data_mode": "sqlite",
                "database_location_mode": "custom",
                "database_path": str(temp_dir / "data.sqlite"),
            }
            with (
                patch.object(web_data.settings, "AC", str(temp_dir)),
                patch.object(storage_settings, "load_bootstrap_settings", return_value=bootstrap),
            ):
                data_store.reset_active_store_cache()
                web_data.add_user("operator", "secret", "user")
                users = web_data.load_users()

            self.assertTrue(any(user["username"] == "operator" for user in users))
            self.assertFalse((temp_dir / web_data.WEB_USERS_PATH).exists())
        finally:
            _remove_workspace_temp(temp_dir)

    def test_sqlite_mode_records_history_without_json_file(self) -> None:
        temp_dir = _workspace_temp("web_data_sqlite_history")
        try:
            bootstrap = {
                "data_mode": "sqlite",
                "database_location_mode": "custom",
                "database_path": str(temp_dir / "data.sqlite"),
            }
            with (
                patch.object(web_data.settings, "AC", str(temp_dir)),
                patch.object(storage_settings, "load_bootstrap_settings", return_value=bootstrap),
            ):
                data_store.reset_active_store_cache()
                web_data.record_history(
                    username="admin",
                    action="save",
                    ean="5901234567890",
                    summary="Zapis",
                )
                snapshot = web_data.history_snapshot()

            self.assertEqual(snapshot["groups"][0]["ean"], "5901234567890")
            self.assertFalse((temp_dir / web_data.WEB_HISTORY_PATH).exists())
        finally:
            _remove_workspace_temp(temp_dir)

    def test_record_history_appends_to_sqlite_without_full_history_load(self) -> None:
        store = Mock()

        with (
            patch.object(web_data, "_active_sqlite_store", return_value=store),
            patch.object(
                web_data,
                "_load_history_records",
                side_effect=AssertionError("full load"),
            ),
        ):
            web_data.record_history(username="alice", action="save", ean="5901")

        store.append_history.assert_called_once()

    def test_sqlite_mode_file_index_uses_database_cache_without_json_file(self) -> None:
        temp_dir = _workspace_temp("web_data_sqlite_file_index")
        try:
            root = temp_dir / "_ZDJECIA PRZEROBIONE_"
            product_dir = root / "MAGGIORE" / "KOMODA" / "MA03" / "BIALY" / "NO-LED"
            product_dir.mkdir(parents=True)
            (product_dir / "5901234567890_01_MAIN.jpg").write_text("a", encoding="utf-8")
            db_path = temp_dir / "data.sqlite"
            bootstrap = {
                "data_mode": "sqlite",
                "database_location_mode": "custom",
                "database_path": str(db_path),
            }
            with (
                patch.object(web_data.settings, "AC", str(temp_dir)),
                patch.object(web_data.settings, "l", str(root)),
                patch.object(web_data.config, "CONFIG", {web_data.LOCAL_FILE_INDEX_KEY: True}),
                patch.object(storage_settings, "load_bootstrap_settings", return_value=bootstrap),
            ):
                data_store.reset_active_store_cache()
                index = web_data._get_file_index(start=False)
                self.assertIsNotNone(index)
                self.assertTrue(index.refresh_sync())

            self.assertFalse((temp_dir / "file_index.json").exists())
            self.assertEqual(
                SqliteStore(str(db_path)).load_file_index_cache()["names"],
                ["MAGGIORE"],
            )
        finally:
            _remove_workspace_temp(temp_dir)

    def test_file_index_status_accepts_iso_generated_at(self) -> None:
        class Index:
            def get_status(self):
                return {
                    "state": "ready",
                    "cache_loaded": True,
                    "has_snapshot": True,
                    "dirs_scanned": 1,
                    "products_scanned": 1,
                    "name_count": 1,
                    "generated_at": "2026-06-25T13:02:34.300Z",
                    "error": "",
                }

        with (
            patch.object(web_data, "_file_index_enabled", return_value=True),
            patch.object(web_data, "_get_file_index", return_value=Index()),
        ):
            status = web_data.file_index_status()

        self.assertEqual(status["generated_at"], "2026-06-25T13:02:34.300Z")
        self.assertEqual(status["label"], "Indeks lokalny")

    def test_manual_file_index_refresh_forces_rebuild(self) -> None:
        class Index:
            def __init__(self) -> None:
                self.force_values: list[bool] = []

            def refresh_if_stale(self, *, force: bool = False) -> bool:
                self.force_values.append(force)
                return True

        index = Index()
        with (
            patch.object(web_data, "_get_file_index", return_value=index),
            patch.object(web_data, "file_index_status", return_value={"state": "ready"}),
        ):
            status = web_data.refresh_file_index()

        self.assertEqual(status, {"state": "ready"})
        self.assertEqual(index.force_values, [True])

    def test_settings_snapshot_exposes_storage_locations(self) -> None:
        temp_dir = _workspace_temp("web_data_storage_snapshot")
        try:
            bootstrap = {
                "data_mode": "sqlite",
                "database_location_mode": "custom",
                "database_path": str(temp_dir / "data.sqlite"),
            }
            with (
                patch.object(web_data.settings, "AC", str(temp_dir)),
                patch.object(storage_settings, "load_bootstrap_settings", return_value=bootstrap),
                patch.object(web_data, "load_users", return_value=[]),
            ):
                snapshot = web_data.settings_snapshot()

            self.assertEqual(snapshot["data_mode"], "sqlite")
            self.assertEqual(snapshot["image_dir"], str(temp_dir))
            self.assertEqual(snapshot["database_location_mode"], "custom")
            self.assertTrue(snapshot["database_path"].endswith("data.sqlite"))
        finally:
            _remove_workspace_temp(temp_dir)

    def test_settings_snapshot_exposes_backup_settings(self) -> None:
        temp_dir = _workspace_temp("web_data_backup_settings")
        try:
            with (
                patch.object(web_data.settings, "AC", str(temp_dir)),
                patch.object(
                    web_data.storage_settings,
                    "load_backup_settings",
                    return_value={
                        "enabled": True,
                        "days": ["mon"],
                        "hours": [8],
                        "max_copies": 3,
                        "last_run_slots": [],
                    },
                ),
                patch.object(
                    web_data.storage_settings,
                    "resolve_backup_dir",
                    return_value=str(temp_dir / "BACKUP"),
                ),
            ):
                snapshot = web_data.settings_snapshot()

            self.assertEqual(snapshot["sqlite_backup"]["days"], ["mon"])
            self.assertEqual(snapshot["sqlite_backup_dir"], str(temp_dir / "BACKUP"))
        finally:
            _remove_workspace_temp(temp_dir)

    def test_entra_settings_change_invalidates_and_refreshes_without_secret_logging(self) -> None:
        original_config = dict(web_data.config.CONFIG)
        prior_secret = "prior-client-secret"
        updated_secret = "updated-client-secret"
        store = Mock()
        try:
            web_data.config.CONFIG.clear()
            web_data.config.CONFIG.update(
                {
                    email_settings.EMAIL_SETTINGS_KEY: email_settings.normalize_email_settings(
                        {"entra": {"tenant_id": "tenant", "client_id": "client", "client_secret": prior_secret}}
                    )
                }
            )
            with (
                patch.object(web_data, "save_config"),
                patch.object(web_data.config, "initialize_config", return_value=web_data.config.CONFIG),
                patch.object(web_data, "settings_snapshot", return_value={}),
                patch("picsyncra.observability.observability_store", return_value=store),
                patch("picsyncra.entra_secret_monitor.refresh_entra_secret_status") as refresh,
                patch.object(web_data, "log_error") as log_error,
            ):
                web_data.update_settings(
                    {
                        email_settings.EMAIL_SETTINGS_KEY: {
                            "entra": {"tenant_id": "tenant", "client_id": "client", "client_secret": updated_secret}
                        }
                    }
                )

            refresh.assert_called_once_with(force=True)
            self.assertEqual(store.clear_entra_secret_status.call_count, 1)
            self.assertFalse(log_error.called)
            self.assertNotIn(updated_secret, repr(log_error.call_args_list))
        finally:
            web_data.config.CONFIG.clear()
            web_data.config.CONFIG.update(original_config)


if __name__ == "__main__":
    unittest.main()
