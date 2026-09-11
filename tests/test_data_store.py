"""Tests for active legacy/SQLite data store selection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import json

from picsyncra import config, data_store, excel_utils, storage_settings
from picsyncra.sqlite_store import SqliteStore


def teardown_function() -> None:
    data_store.reset_active_store_cache()


def test_active_store_defaults_to_legacy() -> None:
    with patch.object(storage_settings, "load_bootstrap_settings", return_value={}):
        store = data_store.get_active_store()

    assert store.mode == "legacy"


def test_active_store_uses_sqlite_when_configured(tmp_path: Path) -> None:
    with patch.object(
        storage_settings,
        "load_bootstrap_settings",
        return_value={
            "data_mode": "sqlite",
            "database_location_mode": "custom",
            "database_path": str(tmp_path / "data.sqlite"),
        },
    ):
        store = data_store.get_active_store()

    assert store.mode == "sqlite"


def test_sqlite_store_adapter_persists_config(tmp_path: Path) -> None:
    with patch.object(
        storage_settings,
        "load_bootstrap_settings",
        return_value={
            "data_mode": "sqlite",
            "database_location_mode": "custom",
            "database_path": str(tmp_path / "data.sqlite"),
        },
    ):
        store = data_store.get_active_store()
        store.save_config({"db_type": "mysql"})
        data_store.reset_active_store_cache()
        store = data_store.get_active_store()

    assert store.load_config()["db_type"] == "mysql"


def test_sqlite_store_adapter_persists_pimcore_submissions(tmp_path: Path) -> None:
    with patch.object(
        storage_settings,
        "load_bootstrap_settings",
        return_value={
            "data_mode": "sqlite",
            "database_location_mode": "custom",
            "database_path": str(tmp_path / "data.sqlite"),
        },
    ):
        store = data_store.get_active_store()
        stored = store.append_pimcore_submission(
            {
                "id": "pim-1",
                "operation_type": "create",
                "username": "operator",
                "ean": "5901234567890",
                "status": "success",
                "values": {"SKU": "SKU-1"},
            }
        )
        rows = store.query_pimcore_submissions(user="operator", query="590123", limit=10)

    assert stored["id"] == "pim-1"
    assert rows[0]["ean"] == "5901234567890"
    assert rows[0]["values"]["SKU"] == "SKU-1"


def test_excel_helpers_use_sqlite_store_in_sqlite_mode(tmp_path: Path) -> None:
    workbook_path = tmp_path / "lists.xlsx"
    with (
        patch.object(
            storage_settings,
            "load_bootstrap_settings",
            return_value={
                "data_mode": "sqlite",
                "database_location_mode": "custom",
                "database_path": str(tmp_path / "data.sqlite"),
            },
        ),
        patch.object(excel_utils.settings, "LISTS_WORKBOOK_PATH", str(workbook_path)),
    ):
        data_store.reset_active_store_cache()
        assert excel_utils.add_to_list("NAZWY", "maggiore") is True
        assert excel_utils.prepare_excel_lists()["NAZWY"] == ["MAGGIORE"]

    assert not workbook_path.exists()


def test_save_ean_entry_uses_sqlite_store_in_sqlite_mode(tmp_path: Path) -> None:
    workbook_path = tmp_path / "lists.xlsx"
    with (
        patch.object(
            storage_settings,
            "load_bootstrap_settings",
            return_value={
                "data_mode": "sqlite",
                "database_location_mode": "custom",
                "database_path": str(tmp_path / "data.sqlite"),
            },
        ),
        patch.object(excel_utils.settings, "LISTS_WORKBOOK_PATH", str(workbook_path)),
    ):
        data_store.reset_active_store_cache()
        result = excel_utils.save_ean_entry(
            "5901234567890",
            "Maggiore",
            "Komoda",
            "MA03",
            "Bialy",
            "",
            "",
            "NO-LED",
            product_id="PRD-1",
        )
        records = excel_utils.prepare_excel_lists()[excel_utils.ENTRY_RECORDS_KEY]

    assert result["product_id"] == "PRD-1"
    assert records[0]["MODEL"] == "MA03"
    assert not workbook_path.exists()


def test_config_load_uses_sqlite_store_in_sqlite_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    raw_config = json.loads(json.dumps(config.DEFAULT_CONFIG))
    raw_config[config.p] = "mysql"
    raw_config[config.SQL_AVAILABLE_COLUMNS_KEY] = ["img_01"]
    SqliteStore(str(db_path)).save_config(raw_config)

    with (
        patch.object(config.settings, "AC", str(tmp_path)),
        patch.object(
            storage_settings,
            "load_bootstrap_settings",
            return_value={
                "data_mode": "sqlite",
                "database_location_mode": "custom",
                "database_path": str(db_path),
            },
        ),
    ):
        data_store.reset_active_store_cache()
        loaded = config.load_config(interactive=False)

    assert loaded[config.p] == "mysql"
    assert loaded[config.SQL_AVAILABLE_COLUMNS_KEY] == ["img_01"]
    assert not (tmp_path / "config.json").exists()


def test_config_save_uses_sqlite_store_in_sqlite_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    payload = json.loads(json.dumps(config.DEFAULT_CONFIG))
    payload[config.p] = "mssql"

    with (
        patch.object(config.settings, "AC", str(tmp_path)),
        patch.object(
            storage_settings,
            "load_bootstrap_settings",
            return_value={
                "data_mode": "sqlite",
                "database_location_mode": "custom",
                "database_path": str(db_path),
            },
        ),
    ):
        data_store.reset_active_store_cache()
        config.save_config(payload)

    assert SqliteStore(str(db_path)).load_config()[config.p] == "mssql"
    assert not (tmp_path / "config.json").exists()
