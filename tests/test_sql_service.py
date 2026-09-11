"""Unit tests for SQL metadata helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from picsyncra.services import sql_service
from picsyncra.services.sql_service import (
    build_column_detection_query,
    detect_available_columns,
    extract_presence_context,
    query_presence_details,
)


class SqlServiceTests(unittest.TestCase):
    def test_build_column_detection_query_for_mysql_without_schema(self) -> None:
        query_info = build_column_detection_query(
            "UPDATE object_query_1 SET img = 'x' WHERE EAN = '{ean}'",
            "mysql",
        )

        self.assertIsNotNone(query_info)
        assert query_info is not None
        self.assertEqual(query_info.table_ref, "object_query_1")
        self.assertEqual(
            query_info.query,
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION",
        )
        self.assertEqual(query_info.params, ("object_query_1",))
        self.assertEqual(
            query_info.preview,
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'object_query_1' "
            "ORDER BY ORDINAL_POSITION",
        )

    def test_build_column_detection_query_for_mssql_with_schema(self) -> None:
        query_info = build_column_detection_query(
            "UPDATE [dbo].[object_query_1] SET img = 'x' WHERE EAN = '{ean}'",
            "mssql",
        )

        self.assertIsNotNone(query_info)
        assert query_info is not None
        self.assertEqual(query_info.table_ref, "dbo.object_query_1")
        self.assertEqual(query_info.schema, "dbo")
        self.assertEqual(query_info.table_name, "object_query_1")
        self.assertEqual(
            query_info.query,
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
        )
        self.assertEqual(query_info.params, ("dbo", "object_query_1"))
        self.assertEqual(
            query_info.preview,
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'object_query_1' "
            "ORDER BY ORDINAL_POSITION",
        )

    def test_detect_available_columns_returns_columns_and_preview(self) -> None:
        class Cursor:
            def execute(self, query, params=()):
                self.query = query
                self.params = params

            def fetchall(self):
                return [("img_01",), ("img_02",), ("img_01",)]

            def close(self):
                return None

        class Connection:
            def cursor(self):
                return Cursor()

            def close(self):
                return None

        with patch(
            "picsyncra.services.sql_service.connect_db",
            return_value=Connection(),
        ):
            result = detect_available_columns(
                {
                    "sql_query": (
                        "UPDATE object_query_1 SET img = '' "
                        "WHERE EAN = '{ean}'"
                    ),
                    "db_type": "mysql",
                }
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["columns"], ["img_01", "img_02"])
        self.assertEqual(result["table"], "object_query_1")
        self.assertIn("INFORMATION_SCHEMA.COLUMNS", result["preview"])

    def test_empty_sql_query_is_not_configured_for_column_detection(self) -> None:
        result = detect_available_columns({"sql_query": "", "db_type": "mysql"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["columns"], [])
        self.assertEqual(result["table"], "")
        self.assertIn("nie skonfigurowano", result["message"].lower())

    def test_placeholder_metadata_lists_supported_tokens(self) -> None:
        self.assertTrue(hasattr(sql_service, "sql_placeholder_metadata"))

        placeholders = sql_service.sql_placeholder_metadata()
        tokens = {item["token"] for item in placeholders}

        self.assertEqual(tokens, {"{ean}", "{filename}", "{col}", "{column}"})

    def test_extract_presence_context_normalizes_quoted_table_reference(self) -> None:
        context = extract_presence_context(
            {
                "sql_query": (
                    "UPDATE [catalog].[dbo].[object_query_1] "
                    "SET img = 'x' WHERE EAN = '{ean}'"
                )
            },
            "5901234567890",
        )

        self.assertEqual(
            context,
            (
                "catalog.dbo.object_query_1",
                " WHERE EAN = '5901234567890'",
            ),
        )

    def test_query_presence_details_leaves_presence_unknown_when_row_missing(self) -> None:
        class Cursor:
            def execute(self, _query):
                return None

            def fetchone(self):
                return None

            def close(self):
                return None

        class Connection:
            def cursor(self):
                return Cursor()

            def close(self):
                return None

        with patch("picsyncra.services.sql_service.connect_db", return_value=Connection()):
            presence, values = query_presence_details(
                [("03", "img_03", "DETAIL_pic")],
                "object_query_1",
                " WHERE EAN = '5901234567890'",
                "mysql",
            )

        self.assertIsNone(presence["03"])
        self.assertEqual(values["03"], "")


if __name__ == "__main__":
    unittest.main()
