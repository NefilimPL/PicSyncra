import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

import pytest

from picsyncra import logging_utils, storage_settings
from picsyncra import data_store
from picsyncra.data_store import (
    get_active_store,
    get_sqlite_store,
    invalidate_sqlite_store,
    reset_active_store_cache,
)
from picsyncra.observability import observability_store
from picsyncra import sqlite_store
from picsyncra.sqlite_store import SqliteStore


def test_initialize_runs_schema_once_for_parallel_callers(tmp_path, monkeypatch):
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    original = store._initialize_schema
    calls = 0
    calls_lock = Lock()

    def counted():
        nonlocal calls
        with calls_lock:
            calls += 1
        original()

    monkeypatch.setattr(store, "_initialize_schema", counted)
    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(lambda _index: store.initialize(), range(20)))

    assert calls == 1


def test_initialize_retries_after_schema_failure(tmp_path, monkeypatch):
    store = SqliteStore(str(tmp_path / "retry.sqlite"))
    original = store._initialize_schema
    attempts = 0

    def flaky():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("migration failed")
        original()

    monkeypatch.setattr(store, "_initialize_schema", flaky)
    with pytest.raises(RuntimeError, match="migration failed"):
        store.initialize()
    store.initialize()

    assert attempts == 2


def test_connection_policy_sets_foreign_keys_and_busy_timeout(tmp_path):
    store = SqliteStore(str(tmp_path / "policy.sqlite"))
    store.initialize()

    with store.connection() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_initialize_uses_wal_or_records_the_active_journal_mode(tmp_path):
    store = SqliteStore(str(tmp_path / "journal.sqlite"))
    store.initialize()

    with store.connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0].lower()

    assert store._journal_mode == journal_mode
    assert journal_mode == "wal" or store._wal_fallback_reason


def test_wal_fallback_initializes_and_logs_one_redacted_warning(tmp_path, monkeypatch):
    private_path = tmp_path / "private-user-record.sqlite"
    store = SqliteStore(str(private_path))
    legacy_log_path = tmp_path / "fallback-info.log"
    logger = logging.getLogger("picsyncra.sqlite.wal")
    records = []

    class RecordCapture(logging.Handler):
        def emit(self, record):
            records.append(record)

    def fail_wal(_conn):
        raise sqlite3.OperationalError("private-user-record")

    monkeypatch.setattr(sqlite_store, "try_enable_wal", fail_wal)
    monkeypatch.setattr(logging_utils.settings, "BM", str(legacy_log_path))
    monkeypatch.setattr(logging_utils, "AO", "private-user")
    monkeypatch.setattr(logging_utils, "AF", "private-host")
    capture = RecordCapture()
    logger.addHandler(capture)

    try:
        store.initialize()
    finally:
        logger.removeHandler(capture)

    legacy_entry = (
        legacy_log_path.read_text(encoding="utf-8")
        if legacy_log_path.exists()
        else ""
    )
    configured_entry = "\n".join(
        handler.format(record)
        for handler in logger.handlers
        for record in records
    )
    observable_entry = "\n".join((legacy_entry, configured_entry))

    assert store._initialized is True
    assert store._journal_mode != "wal"
    assert store._wal_fallback_reason == "OperationalError"
    assert len(records) == 1, observable_entry
    assert records[0].levelno == logging.WARNING
    assert str(private_path) not in observable_entry
    assert "private-user-record" not in observable_entry
    assert "private-user" not in observable_entry
    assert "private-host" not in observable_entry


def test_get_sqlite_store_reuses_instance_for_canonical_path(tmp_path):
    first = get_sqlite_store(str(tmp_path / "." / "app.sqlite"))
    second = get_sqlite_store(str(tmp_path / "app.sqlite"))

    assert first is second


def test_get_sqlite_store_is_thread_safe(tmp_path):
    path = str(tmp_path / "parallel.sqlite")

    with ThreadPoolExecutor(max_workers=12) as pool:
        stores = list(pool.map(lambda _index: get_sqlite_store(path), range(40)))

    assert len({id(store) for store in stores}) == 1


def test_invalidate_sqlite_store_replaces_only_target(tmp_path):
    first_path = str(tmp_path / "first.sqlite")
    second_path = str(tmp_path / "second.sqlite")
    first = get_sqlite_store(first_path)
    second = get_sqlite_store(second_path)

    invalidate_sqlite_store(first_path)

    assert get_sqlite_store(first_path) is not first
    assert get_sqlite_store(second_path) is second


def test_successful_storage_settings_change_resets_store_cache(tmp_path, monkeypatch):
    settings_path = tmp_path / "local_settings.json"
    first_path = tmp_path / "first.sqlite"
    second_path = tmp_path / "second.sqlite"
    settings_path.write_text(
        json.dumps(
            {
                storage_settings.DATA_MODE_KEY: storage_settings.DATA_MODE_SQLITE,
                storage_settings.DATABASE_LOCATION_MODE_KEY: storage_settings.DATABASE_LOCATION_CUSTOM,
                storage_settings.DATABASE_PATH_KEY: str(first_path),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(storage_settings.settings, "BASE_DIR_SETTINGS_PATH", str(settings_path))
    reset_active_store_cache()

    try:
        first = get_active_store().store

        storage_settings.save_bootstrap_settings(
            {storage_settings.DATABASE_PATH_KEY: str(second_path)}
        )

        assert get_sqlite_store(str(first_path)) is not first
    finally:
        reset_active_store_cache()


def test_failed_storage_settings_write_preserves_store_cache(tmp_path, monkeypatch):
    settings_path = tmp_path / "local_settings.json"
    first_path = tmp_path / "first.sqlite"
    settings_path.write_text(
        json.dumps(
            {
                storage_settings.DATA_MODE_KEY: storage_settings.DATA_MODE_SQLITE,
                storage_settings.DATABASE_LOCATION_MODE_KEY: storage_settings.DATABASE_LOCATION_CUSTOM,
                storage_settings.DATABASE_PATH_KEY: str(first_path),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(storage_settings.settings, "BASE_DIR_SETTINGS_PATH", str(settings_path))
    reset_active_store_cache()
    original_replace = storage_settings.os.replace

    def fail_settings_publish(_source, destination):
        if Path(destination).resolve() == settings_path.resolve():
            raise OSError("disk full")
        return original_replace(_source, destination)

    monkeypatch.setattr(storage_settings.os, "replace", fail_settings_publish)
    try:
        active_store = get_active_store().store

        with pytest.raises(OSError, match="disk full"):
            storage_settings.save_bootstrap_settings({"language": "pl"})

        assert get_sqlite_store(str(first_path)) is active_store
    finally:
        reset_active_store_cache()


def test_observability_store_and_active_adapter_share_instance(tmp_path, monkeypatch):
    database_path = str(tmp_path / "shared.sqlite")
    monkeypatch.setattr(
        storage_settings,
        "load_bootstrap_settings",
        lambda: {storage_settings.DATA_MODE_KEY: storage_settings.DATA_MODE_SQLITE},
    )
    monkeypatch.setattr(
        storage_settings,
        "resolve_sqlite_path",
        lambda _bootstrap=None: database_path,
    )
    reset_active_store_cache()

    try:
        active_store = get_active_store()

        assert observability_store() is active_store.store
    finally:
        reset_active_store_cache()


def test_reset_active_store_cache_clears_a_concurrent_active_store_creation(
    tmp_path, monkeypatch
):
    database_path = str(tmp_path / "concurrent.sqlite")
    construction_started = threading.Event()
    allow_construction = threading.Event()

    class InterleavingRegistryLock:
        def __init__(self, lock):
            self._lock = lock
            self.active_thread_id = None
            self.reset_attempted = threading.Event()
            self.reset_holds_lock = threading.Event()
            self.allow_reset = threading.Event()

        def __enter__(self):
            is_reset = (
                self.active_thread_id is not None
                and threading.get_ident() != self.active_thread_id
                and not self.reset_attempted.is_set()
            )
            if is_reset:
                self.reset_attempted.set()
            self._lock.acquire()
            if is_reset:
                self.reset_holds_lock.set()
                assert self.allow_reset.wait(timeout=5)
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self._lock.release()

    class BlockingAdapter:
        mode = storage_settings.DATA_MODE_SQLITE

        def __init__(self, path):
            lock.active_thread_id = threading.get_ident()
            construction_started.set()
            assert allow_construction.wait(timeout=5)
            self.store = get_sqlite_store(path)

    reset_active_store_cache()
    lock = InterleavingRegistryLock(data_store._STORE_REGISTRY_LOCK)
    monkeypatch.setattr(data_store, "_STORE_REGISTRY_LOCK", lock)
    monkeypatch.setattr(data_store, "SqliteDataStoreAdapter", BlockingAdapter)
    monkeypatch.setattr(
        storage_settings,
        "load_bootstrap_settings",
        lambda: {storage_settings.DATA_MODE_KEY: storage_settings.DATA_MODE_SQLITE},
    )
    monkeypatch.setattr(
        storage_settings,
        "resolve_sqlite_path",
        lambda _bootstrap=None: database_path,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        stale_adapter = pool.submit(get_active_store)
        assert construction_started.wait(timeout=5)
        reset = pool.submit(reset_active_store_cache)
        assert lock.reset_attempted.wait(timeout=5)
        allow_construction.set()
        assert lock.reset_holds_lock.wait(timeout=5)
        lock.allow_reset.set()
        stale_adapter = stale_adapter.result(timeout=5)
        reset.result(timeout=5)

    try:
        assert get_active_store() is not stale_adapter
    finally:
        reset_active_store_cache()
