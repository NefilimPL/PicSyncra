from __future__ import annotations

from unittest.mock import Mock


PROFILE = {
    "type": "mysql",
    "host": "sql.example.test",
    "user": "operator",
    "password": "test-secret",
    "database": "products",
}


class _Cursor:
    def __init__(self, value: str) -> None:
        self.value = value
        self.closed = False

    def execute(self, _query, _params) -> None:
        return None

    def fetchmany(self, _limit: int):
        return [(self.value,)]

    def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(self, values: list[str]) -> None:
        self.values = values
        self.close_count = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self.values.pop(0))

    def close(self) -> None:
        self.close_count += 1


def test_context_reuses_one_connection_for_same_profile() -> None:
    from picsyncra.services.sql_execution_context import SqlExecutionContext

    connection = _Connection(["A", "B"])
    connector = Mock(return_value=connection)

    with SqlExecutionContext(connector=connector) as context:
        first = context.execute(PROFILE, "SELECT 'A'", {}, {}, mappings=[])
        second = context.execute(PROFILE, "SELECT 'B'", {}, {}, mappings=[])

    assert [first.value, second.value] == ["A", "B"]
    connector.assert_called_once_with(PROFILE)
    assert connection.close_count == 1


def test_context_uses_the_supplied_query_executor() -> None:
    from picsyncra.services.pimcore_sql_service import SqlValueResult
    from picsyncra.services.sql_execution_context import SqlExecutionContext

    connection = _Connection(["unused"])
    executor = Mock(return_value=SqlValueResult("A", []))

    with SqlExecutionContext(
        connector=Mock(return_value=connection),
        execute_query=executor,
    ) as context:
        result = context.execute(PROFILE, "SELECT 'A'", {}, {}, mappings=[])

    assert result.value == "A"
    assert executor.call_args.kwargs["connection"] is connection
