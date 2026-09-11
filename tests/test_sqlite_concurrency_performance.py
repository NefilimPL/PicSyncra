"""SQLite concurrency regressions and an opt-in performance report."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import time

import pytest

from picsyncra.sqlite_store import SqliteStore
from picsyncra.web.process_progress import ProcessProgressGate


_OPERATIONS = 1000


class _CountingSqliteStore(SqliteStore):
    def __init__(self, path: str):
        super().__init__(path)
        self.schema_initializations = 0

    def _initialize_schema(self) -> None:
        self.schema_initializations += 1
        super()._initialize_schema()


def _run_mixed_workload(store: SqliteStore) -> int:
    def writer(index: int) -> str:
        try:
            store.upsert_job_run(
                {
                    "id": f"job-{index}",
                    "status": "running",
                    "created_at": "2026-07-27T10:00:00.000Z",
                }
            )
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                return "locked"
            raise
        return "ok"

    def reader(_index: int) -> str:
        try:
            store.query_job_runs(limit=20)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                return "locked"
            raise
        return "ok"

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [
            pool.submit(writer if index % 5 == 0 else reader, index)
            for index in range(_OPERATIONS)
        ]
        return sum(future.result() == "locked" for future in futures)


def _progress_persistence_count() -> int:
    gate = ProcessProgressGate(min_interval_seconds=0.5)
    return sum(
        gate.should_persist(
            "benchmark-job",
            stage="images",
            status="running",
            now=index / 100,
        )
        for index in range(100)
    )


def test_concurrent_readers_and_writers_do_not_lock_database(tmp_path):
    store = _CountingSqliteStore(str(tmp_path / "concurrent.sqlite"))
    store.initialize()

    locked_errors = _run_mixed_workload(store)

    assert locked_errors == 0
    assert store.schema_initializations == 1


@pytest.mark.performance
def test_sqlite_lifecycle_and_progress_performance_report(tmp_path):
    store = _CountingSqliteStore(str(tmp_path / "benchmark.sqlite"))
    store.initialize()

    started = time.perf_counter()
    locked_errors = _run_mixed_workload(store)
    elapsed = time.perf_counter() - started
    persist_calls = _progress_persistence_count()
    report = {
        "operations": _OPERATIONS,
        "schema_initializations": store.schema_initializations,
        "locked_errors": locked_errors,
        "elapsed_seconds": elapsed,
        "progress_updates": 100,
        "progress_persists": persist_calls,
        "journal_mode": store._journal_mode,
    }
    print(json.dumps(report, sort_keys=True))

    assert locked_errors == 0
    assert store.schema_initializations == 1
    assert persist_calls <= 3
