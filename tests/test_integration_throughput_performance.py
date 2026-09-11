from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from unittest.mock import Mock

from picsyncra.services.photo_sql_batch import build_photo_sql_batch
from picsyncra.services.pimcore_service import pimcore_client_scope
from picsyncra.services.pimcore_sql_service import SqlValueResult
from picsyncra.services.sql_execution_context import SqlExecutionContext
from picsyncra.services.template_execution import execute_independent_operations
from picsyncra.services.translation_cache import TranslationCache
from picsyncra.services.translation_service import TranslationResult


def test_integration_throughput_counters_are_bounded_and_reused() -> None:
    profiles = [
        {"type": "mysql", "host": "one", "user": "u", "database": "d", "password": "a"},
        {"type": "mysql", "host": "two", "user": "u", "database": "d", "password": "b"},
    ]
    connections = []

    class Connection:
        def close(self) -> None:
            return None

    def connector(_profile):
        connection = Connection()
        connections.append(connection)
        return connection

    def query(_profile, query, *_args, **_kwargs):
        return SqlValueResult(str(query), [])

    client = Mock()
    with pimcore_client_scope({"base_url": "https://pimcore.test"}, factory=lambda _settings: client):
        pass

    with SqlExecutionContext(connector=connector, execute_query=query) as context:
        for index in range(8):
            context.execute(profiles[index % 2], index, {}, {}, mappings=[])

    cache = TranslationCache()
    translation_calls = 0
    translation_lock = threading.Lock()

    def translate(key: str) -> TranslationResult:
        nonlocal translation_calls
        with translation_lock:
            translation_calls += 1
        return TranslationResult(key.upper())

    keys = ("a", "b", "c", "d", "a", "b")
    with ThreadPoolExecutor(max_workers=6) as pool:
        translated = list(pool.map(lambda key: cache.get_or_translate(("en", key), lambda: translate(key)), keys))

    active = 0
    peak_workers = 0
    lock = threading.Lock()

    def operation(index: int) -> int:
        nonlocal active, peak_workers
        with lock:
            active += 1
            peak_workers = max(peak_workers, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return index

    rendered = execute_independent_operations(
        [lambda index=index: operation(index) for index in range(8)], max_workers=4
    )
    batch = build_photo_sql_batch(
        "products", " WHERE ean = '5901234567890'", {"photo_1": "a.jpg", "photo_2": "b.jpg"},
        "mssql", "UPDATE {table} SET {column} = '{filename}' {where}",
    )

    assert client.close.call_count == 1
    assert len(connections) == 2
    assert translation_calls == 4
    assert [result.text for result in translated] == ["A", "B", "C", "D", "A", "B"]
    assert batch is not None and batch.query.count("UPDATE") == 1
    assert rendered == list(range(8))
    assert peak_workers <= 4
