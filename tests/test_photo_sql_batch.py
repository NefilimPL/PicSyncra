from picsyncra.services.photo_sql_batch import build_photo_sql_batch
from picsyncra.web import app as web_app
from types import SimpleNamespace
from unittest.mock import patch


def test_builds_parameterized_batch_for_standard_mssql_template():
    batch = build_photo_sql_batch(
        "products",
        " WHERE ean = '5901234567890'",
        {"photo_1": "5901234567890_01.jpg", "photo_2": ""},
        "mssql",
        "UPDATE {table} SET {column} = '{filename}' {where}",
    )

    assert batch is not None
    assert batch.params == ("5901234567890_01.jpg", "")
    assert batch.query == (
        "UPDATE products SET photo_1 = ?, photo_2 = ? WHERE ean = '5901234567890'"
    )


def test_rejects_custom_template_for_legacy_fallback():
    assert (
        build_photo_sql_batch(
            "products",
            " WHERE ean = '5901234567890'",
            {"photo_1": "5901234567890_01.jpg"},
            "mysql",
            "UPDATE {table} SET {column} = CONCAT('/cdn/', '{filename}') {where}",
        )
        is None
    )


def test_accepts_standard_desktop_template_with_concrete_table_and_ean():
    batch = build_photo_sql_batch(
        "products",
        " WHERE EAN = '5901234567890'",
        {"photo_1": "5901234567890_01.jpg"},
        "mysql",
        "UPDATE products SET {col} = '{filename}' WHERE EAN = '{ean}'",
        allow_concrete_template=True,
    )

    assert batch is not None
    assert batch.query == "UPDATE products SET photo_1 = %s WHERE EAN = '5901234567890'"


def test_rejects_unsafe_identifiers():
    assert (
        build_photo_sql_batch(
            "products; DROP TABLE products",
            " WHERE ean = '5901234567890'",
            {"photo_1": "5901234567890_01.jpg"},
            "mssql",
            "UPDATE {table} SET {column} = '{filename}' {where}",
        )
        is None
    )


def test_web_sql_sync_executes_one_standard_batch():
    result = SimpleNamespace(
        ean="5901234567890",
        saved_files=[
            SimpleNamespace(prefix="03", filename="5901234567890_03.jpg"),
            SimpleNamespace(prefix="04", filename="5901234567890_04.jpg"),
        ],
    )

    class Cursor:
        rowcount = -1

        def __init__(self) -> None:
            self.calls = []

        def execute(self, query, params=()):
            self.calls.append((query, params))
            self.rowcount = 1 if str(query).startswith("UPDATE") else -1

        def fetchone(self):
            return (1,)

        def close(self):
            return None

    class Connection:
        def __init__(self) -> None:
            self.cursor_obj = Cursor()
            self.committed = False

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            self.committed = True

        def rollback(self):
            return None

        def close(self):
            return None

    connection = Connection()
    with (
        patch.dict(
            web_app.config.CONFIG,
            {
                web_app.u: True,
                web_app.p: "mssql",
                web_app.w: "UPDATE {table} SET {column} = '{filename}' {where}",
                web_app.SQL_COLUMN_MAP_KEY: {"03": "photo_1", "04": "photo_2"},
            },
            clear=False,
        ),
        patch.object(web_app, "extract_presence_context", return_value=("products", " WHERE ean = '5901234567890'")),
        patch.object(web_app, "connect_db", return_value=connection),
    ):
        payload = web_app._sync_result_to_sql(result)

    assert payload["updated"] == 2
    assert payload["rows"] == 1
    assert connection.committed
    assert connection.cursor_obj.calls[1] == (
        "UPDATE products SET photo_1 = ?, photo_2 = ? WHERE ean = '5901234567890'",
        ("5901234567890_03.jpg", "5901234567890_04.jpg"),
    )
