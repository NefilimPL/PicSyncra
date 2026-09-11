from __future__ import annotations

import pytest

from picsyncra.services.pimcore_sql_service import (
    SqlValueError,
    bind_sql_value_query,
    execute_sql_value_query,
    validate_sql_value_query,
)


def test_validate_sql_value_query_accepts_single_select():
    query = "SELECT stock FROM product WHERE ean = {ean}"

    assert validate_sql_value_query(query) == query


@pytest.mark.parametrize(
    "query",
    [
        "",
        "UPDATE product SET stock = 1",
        "SELECT stock FROM product; SELECT 1",
        "DELETE FROM product",
        "EXEC dbo.read_stock",
    ],
)
def test_validate_sql_value_query_rejects_unsafe_sql(query):
    with pytest.raises(SqlValueError):
        validate_sql_value_query(query)


def test_bind_sql_value_query_uses_mysql_parameters():
    query, params = bind_sql_value_query(
        "SELECT stock FROM product WHERE ean = {ean} AND sku = {pimcore:SKU}",
        {"ean": "5901234567890"},
        {"SKU": "ABC"},
        "mysql",
    )

    assert query == "SELECT stock FROM product WHERE ean = %s AND sku = %s"
    assert params == ("5901234567890", "ABC")


def test_bind_sql_value_query_uses_mssql_parameters_and_empty_missing_values():
    query, params = bind_sql_value_query(
        "SELECT TOP 1 stock FROM product WHERE ean = {EAN} AND model = {model}",
        {"ean": "5901234567890"},
        {},
        "mssql",
    )

    assert query == "SELECT TOP 1 stock FROM product WHERE ean = ? AND model = ?"
    assert params == ("5901234567890", "")


def test_bind_sql_value_query_uses_template_placeholder_catalog_and_functions():
    query, params = bind_sql_value_query(
        (
            "SELECT stock FROM product "
            "WHERE name = {Nazwa|title} "
            "AND model = {PRODUCT:model|upper} "
            "AND sku = {PIMCORE:SKU|keep} "
            "AND title = {Tytul Pimcore|lower}"
        ),
        {"name": "vivo szafka", "model": "ab-12"},
        {"SKU": "SKU-1", "TITLE": "Duzy Stolik"},
        "mysql",
        mappings=[
            {"source": "SKU", "label": "SKU"},
            {"source": "TITLE", "label": "Tytul Pimcore"},
        ],
    )

    assert query == (
        "SELECT stock FROM product "
        "WHERE name = %s "
        "AND model = %s "
        "AND sku = %s "
        "AND title = %s"
    )
    assert params == ("Vivo Szafka", "AB-12", "SKU-1", "duzy stolik")


def test_bind_sql_value_query_removes_quotes_around_placeholder_parameter():
    query, params = bind_sql_value_query(
        (
            "SELECT TOP 1 t.tw_Symbol AS SKU "
            "FROM dbo.tw__Towar t "
            "WHERE LTRIM(RTRIM(CONVERT(varchar(50), t.tw_PodstKodKresk))) = "
            "'{PRODUCT:ean|keep}'"
        ),
        {"ean": "5907763645590"},
        {},
        "mssql",
    )

    assert query == (
        "SELECT TOP 1 t.tw_Symbol AS SKU "
        "FROM dbo.tw__Towar t "
        "WHERE LTRIM(RTRIM(CONVERT(varchar(50), t.tw_PodstKodKresk))) = "
        "?"
    )
    assert params == ("5907763645590",)


def test_execute_sql_value_query_returns_first_value_and_multiple_row_warning():
    class Cursor:
        def execute(self, query, params):
            self.query = query
            self.params = params

        def fetchmany(self, count):
            return [("12",), ("13",)]

        def close(self):
            return None

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            return None

    result = execute_sql_value_query(
        {"id": "stock", "type": "mysql"},
        "SELECT stock FROM product WHERE ean = {ean}",
        {"ean": "5901234567890"},
        {},
        connector=lambda profile: Connection(),
    )

    assert result.value == "12"
    assert result.warnings[0]["code"] == "multiple_rows"


def test_execute_sql_value_query_returns_empty_with_warning_when_no_row():
    class Cursor:
        def execute(self, query, params):
            return None

        def fetchmany(self, count):
            return []

        def close(self):
            return None

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            return None

    result = execute_sql_value_query(
        {"id": "stock", "type": "mysql"},
        "SELECT stock FROM product WHERE ean = {ean}",
        {"ean": "5901234567890"},
        {},
        connector=lambda profile: Connection(),
    )

    assert result.value == ""
    assert result.warnings[0]["code"] == "no_rows"
