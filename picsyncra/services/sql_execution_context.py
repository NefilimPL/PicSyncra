"""Render-scoped ownership of reusable Pimcore SQL connections."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .pimcore_sql_service import SqlValueResult, connect_profile, execute_sql_value_query


def _profile_key(profile: dict[str, object]) -> tuple[str, str, str, str, str]:
    password = str(profile.get("password") or "")
    return (
        str(profile.get("type") or "").casefold(),
        str(profile.get("host") or ""),
        str(profile.get("user") or ""),
        str(profile.get("database") or ""),
        password,
    )


class SqlExecutionContext:
    def __init__(
        self,
        *,
        connector: Callable[[dict[str, object]], object] = connect_profile,
        execute_query: Callable[..., SqlValueResult] = execute_sql_value_query,
    ):
        self._connector = connector
        self._execute_query = execute_query
        self._connections: dict[tuple[str, str, str, str, str], object] = {}

    def __enter__(self) -> "SqlExecutionContext":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> bool:
        for connection in self._connections.values():
            connection.close()
        self._connections.clear()
        return False

    def execute(
        self,
        profile: dict[str, object],
        query: object,
        product_values: dict[str, object],
        pimcore_values: dict[str, object],
        mappings: Sequence[dict[str, object]] | None = None,
    ) -> SqlValueResult:
        key = _profile_key(profile)
        connection = self._connections.get(key)
        if connection is None:
            connection = self._connector(profile)
            self._connections[key] = connection
        return self._execute_query(
            profile,
            query,
            product_values,
            pimcore_values,
            mappings=mappings,
            connection=connection,
        )
