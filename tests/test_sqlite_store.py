"""Tests for the SQLite-backed application data store."""

from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from picsyncra import sqlite_store
from picsyncra.excel_utils import ENTRY_RECORDS_KEY
from picsyncra.product_queries import ProductSearchCriteria
from picsyncra.sqlite_store import SCHEMA_VERSION, SqliteStore


def test_schema_creates_expected_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(db_path))

    store.initialize()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {
        "schema_version",
        "app_config_values",
        "slot_definitions",
        "sql_column_map",
        "sql_available_columns",
        "list_values",
        "product_entries",
        "web_users",
        "web_history",
        "file_index_cache",
        "pimcore_submissions",
        "operational_events",
        "operational_event_stream",
        "job_runs",
        "incidents",
        "alert_reads",
        "pimcore_integration_contexts",
        "entra_secret_status",
        "entra_secret_reminders",
        "daily_change_summary_reports",
    } <= tables

    with sqlite3.connect(db_path) as conn:
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        stream_columns = [
            row[1] for row in conn.execute("PRAGMA table_info(operational_event_stream)")
        ]
        stream_foreign_keys = conn.execute(
            "PRAGMA foreign_key_list(operational_event_stream)"
        ).fetchall()

    assert version == SCHEMA_VERSION
    assert stream_columns == ["sequence", "event_id"]
    assert stream_foreign_keys == []


def test_entra_expiry_status_round_trip_returns_only_safe_metadata(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))

    result = store.upsert_entra_secret_status(
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "status": "ok",
            "expires_at": "2026-08-01T10:00:00.000Z",
            "credential_name": "Primary",
            "credential_key_id": "internal-key",
            "application_name": "PicSyncra Mailer",
            "source": "graph",
            "last_checked_at": "2026-07-17T10:00:00.000Z",
            "last_success_at": "2026-07-17T10:00:00.000Z",
            "error_code": "",
            "error_message": "",
            "secret": "must-not-persist",
            "access_token": "must-not-persist",
            "authorization": "must-not-persist",
        }
    )

    assert result == store.get_entra_secret_status("tenant", "client")
    assert result == {
        "tenant_id": "tenant",
        "client_id": "client",
        "status": "ok",
        "expires_at": "2026-08-01T10:00:00.000Z",
        "credential_name": "Primary",
        "application_name": "PicSyncra Mailer",
        "source": "graph",
        "last_checked_at": "2026-07-17T10:00:00.000Z",
        "last_success_at": "2026-07-17T10:00:00.000Z",
        "error_code": "",
        "error_message": "",
    }
    assert store.get_entra_secret_status("missing", "client") == {}
    with store.connection() as conn:
        persisted = conn.execute("SELECT * FROM entra_secret_status").fetchone()
    assert "must-not-persist" not in " ".join(str(value) for value in persisted)


def test_entra_expiry_internal_status_retains_key_id_without_public_projection(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.upsert_entra_secret_status(
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "status": "ok",
            "credential_key_id": "key-internal-only",
        }
    )

    internal = store.get_entra_secret_status_internal("tenant", "client")

    assert internal["credential_key_id"] == "key-internal-only"
    assert "credential_key_id" not in store.get_entra_secret_status("tenant", "client")


def test_entra_expiry_status_requires_canonical_timestamps(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))

    with pytest.raises(ValueError, match="expires_at must be a canonical timestamp"):
        store.upsert_entra_secret_status(
            {
                "tenant_id": "tenant",
                "client_id": "client",
                "status": "ok",
                "expires_at": "2026-08-01T10:00:00Z",
            }
        )


def test_entra_expiry_status_rejects_or_redacts_malformed_public_fields(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.upsert_entra_secret_status(
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "status": "ok",
        }
    )

    with pytest.raises(ValueError, match="tenant_id must be text"):
        store.upsert_entra_secret_status(
            {
                "tenant_id": {"access_token": "tenant-secret"},
                "client_id": ["client_secret=client-secret"],
                "status": "ok",
            }
        )

    result = store.upsert_entra_secret_status(
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "status": {"Authorization": "Bearer status-secret"},
            "error_message": (
                "access_token=error-secret; client_secret=client-secret; "
                "Authorization: Bearer authorization-secret"
            ),
        }
    )

    assert result["status"] == "unknown"
    public_payload = json.dumps(store.get_entra_secret_status("tenant", "client"))
    with store.connection() as conn:
        persisted = conn.execute("SELECT * FROM entra_secret_status").fetchone()
    persisted_values = " ".join(str(value) for value in persisted)
    for secret in (
        "tenant-secret",
        "client-secret",
        "status-secret",
        "error-secret",
        "authorization-secret",
    ):
        assert secret not in public_payload
        assert secret not in persisted_values


def test_entra_expiry_reminder_claim_is_idempotent_and_identity_sensitive(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    first_claim = (
        "tenant",
        "client",
        "key-a",
        "2026-08-01T00:00:00.000Z",
        7,
        "2026-07-25T00:00:00.000Z",
    )

    assert store.claim_entra_secret_reminder(*first_claim)
    assert not store.claim_entra_secret_reminder(
        *first_claim[:-1], "2026-07-25T00:00:01.000Z"
    )
    assert store.claim_entra_secret_reminder(
        "tenant",
        "client",
        "key-b",
        "2026-08-01T00:00:00.000Z",
        7,
        "2026-07-25T00:00:00.000Z",
    )
    assert store.claim_entra_secret_reminder(
        "tenant",
        "client",
        "key-a",
        "2026-09-01T00:00:00.000Z",
        7,
        "2026-08-25T00:00:00.000Z",
    )


def test_operational_clear_preserves_entra_expiry_status_and_reminder_claims(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.upsert_entra_secret_status(
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "status": "ok",
            "expires_at": "2026-08-01T00:00:00.000Z",
            "last_checked_at": "2026-07-17T00:00:00.000Z",
        }
    )
    assert store.claim_entra_secret_reminder(
        "tenant",
        "client",
        "key-a",
        "2026-08-01T00:00:00.000Z",
        7,
        "2026-07-25T00:00:00.000Z",
    )

    store.clear_operational_data()

    assert store.get_entra_secret_status("tenant", "client")["status"] == "ok"
    assert not store.claim_entra_secret_reminder(
        "tenant",
        "client",
        "key-a",
        "2026-08-01T00:00:00.000Z",
        7,
        "2026-07-25T00:00:01.000Z",
    )


def test_clear_entra_expiry_status_also_removes_matching_reminder_claims(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.upsert_entra_secret_status(
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "status": "ok",
            "expires_at": "2026-08-01T00:00:00.000Z",
        }
    )
    assert store.claim_entra_secret_reminder(
        "tenant",
        "client",
        "key-a",
        "2026-08-01T00:00:00.000Z",
        7,
        "2026-07-25T00:00:00.000Z",
    )

    assert store.clear_entra_secret_status("tenant", "client") == 1
    assert store.get_entra_secret_status("tenant", "client") == {}
    assert store.claim_entra_secret_reminder(
        "tenant",
        "client",
        "key-a",
        "2026-08-01T00:00:00.000Z",
        7,
        "2026-07-25T00:00:01.000Z",
    )


def test_pimcore_integration_context_is_bound_redacted_and_one_time(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    now = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)
    context_id = store.create_pimcore_integration_context(
        username="alice",
        mode="edit",
        object_id=91,
        results={
            "sql_profiles": [
                {"profile_id": "stock", "status": "error", "error": "password=secret"}
            ]
        },
        ttl_seconds=600,
        now=now,
    )

    assert len(context_id) >= 32
    assert store.consume_pimcore_integration_context(
        context_id, username="mallory", mode="edit", object_id=91, now=now
    ) is None
    assert store.consume_pimcore_integration_context(
        context_id, username="alice", mode="create", object_id=None, now=now
    ) is None
    assert store.consume_pimcore_integration_context(
        context_id, username="alice", mode="edit", object_id=92, now=now
    ) is None
    result = store.consume_pimcore_integration_context(
        context_id, username="alice", mode="edit", object_id=91, now=now
    )
    assert result["sql_profiles"][0]["profile_id"] == "stock"
    assert "secret" not in json.dumps(result)
    assert store.consume_pimcore_integration_context(
        context_id, username="alice", mode="edit", object_id=91, now=now
    ) is None


def test_pimcore_integration_context_expiry_prune_and_clear(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    now = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)
    context_id = store.create_pimcore_integration_context(
        username="alice", mode="create", object_id=None, results={}, ttl_seconds=1, now=now
    )

    assert store.consume_pimcore_integration_context(
        context_id,
        username="alice",
        mode="create",
        object_id=None,
        now=now + timedelta(seconds=31),
    ) is None
    assert store.prune_pimcore_integration_contexts(now=now + timedelta(seconds=31)) == 0
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pimcore_integration_contexts").fetchone()[0] == 0

    store.create_pimcore_integration_context(
        username="alice", mode="create", object_id=None, results={}, now=now
    )
    deleted = store.clear_operational_data()
    assert deleted["pimcore_integration_contexts"] == 1


def test_pimcore_integration_context_concurrent_consume_has_one_winner(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    now = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)
    context_id = store.create_pimcore_integration_context(
        username="alice",
        mode="edit",
        object_id=91,
        results={"sql_profiles": [{"profile_id": "stock", "status": "success"}]},
        now=now,
    )

    def consume() -> object:
        return store.consume_pimcore_integration_context(
            context_id, username="alice", mode="edit", object_id=91, now=now
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _item: consume(), range(2)))

    assert sum(result is not None for result in results) == 1


def test_pimcore_submissions_roundtrip_and_filter(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()

    store.append_pimcore_submission(
        {
            "operation_id": "op-1",
            "operation_type": "manual_create",
            "username": "operator",
            "ean": "5901234567890",
            "object_id": "91",
            "object_path": "/Produkty/91",
            "status": "completed",
            "values": {"EAN": "5901234567890", "STOCK": "12"},
            "payload": {"className": "Product"},
            "result": {"object_id": 91},
            "warnings": [],
        }
    )

    rows = store.query_pimcore_submissions(user="operator", query="590123", limit=20)

    assert len(rows) == 1
    assert rows[0]["operation_id"] == "op-1"
    assert rows[0]["values"]["STOCK"] == "12"
    assert rows[0]["payload"]["className"] == "Product"
    assert rows[0]["created_at"].endswith("Z")


def test_config_roundtrip_preserves_payload(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()

    store.save_config({"db_type": "mysql", "enable_sql_update": True})

    assert store.load_config()["db_type"] == "mysql"
    assert store.load_config()["enable_sql_update"] is True


def test_config_is_stored_as_readable_path_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(db_path))
    store.initialize()

    store.save_config(
        {
            "db_type": "mysql",
            "enable_sql_update": True,
            "ftp": {"host": "ftp.example.com", "port": 21},
            "processing": {"formats": ["jpg", "png"]},
        }
    )

    with sqlite3.connect(db_path) as conn:
        rows = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                """
                SELECT path, value_json, updated_at
                FROM app_config_values
                ORDER BY path
                """
            )
        }
        legacy_config = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_settings'"
        ).fetchone()

    assert legacy_config is None
    assert rows["db_type"][0] == '"mysql"'
    assert rows["enable_sql_update"][0] == "true"
    assert rows["ftp.host"][0] == '"ftp.example.com"'
    assert rows["ftp.port"][0] == "21"
    assert rows["processing.formats"][0] == '["jpg", "png"]'
    assert rows["db_type"][1].endswith("Z")
    assert "T" in rows["db_type"][1]


def test_load_config_falls_back_to_legacy_json_blob(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(db_path))
    store.initialize()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE app_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO app_settings (key, value_json, updated_at)
            VALUES ('config', ?, ?)
            """,
            ('{"db_type": "mssql", "ftp": {"host": "legacy.example.com"}}', "2026-06-25T12:00:00.000Z"),
        )

    assert store.load_config() == {
        "db_type": "mssql",
        "ftp": {"host": "legacy.example.com"},
    }


def test_save_config_drops_legacy_app_settings_when_it_becomes_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(db_path))
    store.initialize()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE app_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO app_settings (key, value_json, updated_at)
            VALUES ('config', ?, ?)
            """,
            ('{"db_type": "mssql"}', "2026-06-25T12:00:00.000Z"),
        )

    store.save_config({"db_type": "mysql"})

    with sqlite3.connect(db_path) as conn:
        app_settings_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_settings'"
        ).fetchone()

    assert app_settings_exists is None


def test_sqlite_timestamps_are_iso_8601_text(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(db_path))
    store.initialize()

    store.save_sql_columns(["img_01"], table_name="object_query_1")
    store.save_product_entry(
        {
            "EAN": "5901234567890",
            "NAZWA": "MAGGIORE",
            "TYP": "KOMODA",
            "MODEL": "MA03",
            "KOLOR1": "BIALY",
            "KOLOR2": "",
            "KOLOR3": "",
            "DODATKI": "NO-LED",
            "PRODUCT_ID": "PRD-1",
        }
    )
    store.save_users([{"username": "operator", "role": "user"}])
    store.save_file_index_cache({"version": 1, "names": ["MAGGIORE"]})

    with sqlite3.connect(db_path) as conn:
        values = [
            conn.execute("SELECT applied_at FROM schema_version").fetchone()[0],
            conn.execute("SELECT detected_at FROM sql_available_columns").fetchone()[0],
            conn.execute("SELECT updated_at FROM product_entries").fetchone()[0],
            conn.execute("SELECT updated_at FROM web_users").fetchone()[0],
            conn.execute(
                "SELECT generated_at FROM file_index_generations WHERE complete = 1"
            ).fetchone()[0],
        ]

    for value in values:
        assert isinstance(value, str)
        assert value.endswith("Z")
        assert "T" in value


def test_web_history_schema_uses_iso_created_at(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()
    store.save_history(
        [
            {
                "id": "hist-1",
                "ts": 1782392554.3,
                "time": "2026-06-25 13:02:34",
                "user": "admin",
                "ean": "5901234567890",
            }
        ]
    )

    with sqlite3.connect(tmp_path / "data.sqlite") as conn:
        columns = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(web_history)")}
        row = conn.execute("SELECT created_at, payload_json FROM web_history WHERE id = 'hist-1'").fetchone()

    assert columns["created_at"].upper() == "TEXT"
    assert isinstance(row[0], str)
    assert row[0].endswith("Z")
    assert "T" in row[0]
    payload = json.loads(row[1])
    assert payload["created_at"] == row[0]


def test_daily_change_summary_claims_one_retryable_continuous_window(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    first_end = "2026-07-20T14:00:00.000Z"
    second_end = "2026-07-21T14:00:00.000Z"

    first = store.claim_daily_change_summary(first_end, claimed_at=first_end)

    assert {key: first[key] for key in ("window_start", "window_end", "status")} == {
        "window_start": "2026-07-19T14:00:00.000Z",
        "window_end": first_end,
        "status": "sending",
    }
    assert first["claim_token"]
    assert store.claim_daily_change_summary(first_end, claimed_at=first_end) is None
    assert store.finalize_daily_change_summary(
        first_end, status="pending", claim_token=first["claim_token"]
    ) is True
    retry = store.claim_daily_change_summary(first_end, claimed_at=first_end)
    assert retry is not None
    assert {key: retry[key] for key in ("window_start", "window_end", "status")} == {
        key: first[key] for key in ("window_start", "window_end", "status")
    }
    assert retry["claim_token"] != first["claim_token"]
    assert store.finalize_daily_change_summary(
        first_end, status="sent", claim_token=retry["claim_token"]
    ) is True

    second = store.claim_daily_change_summary(second_end, claimed_at=second_end)

    assert second is not None
    assert {key: second[key] for key in ("window_start", "window_end", "status")} == {
        "window_start": first_end,
        "window_end": second_end,
        "status": "sending",
    }


def test_daily_change_summary_retries_the_oldest_pending_window_before_a_new_one(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    first_end = "2026-07-20T14:00:00.000Z"
    retry_at = "2026-07-21T14:05:00.000Z"
    next_end = "2026-07-22T14:00:00.000Z"

    first = store.claim_daily_change_summary(first_end, claimed_at=first_end)
    assert first is not None
    assert store.finalize_daily_change_summary(
        first_end,
        status="pending",
        claim_token=first["claim_token"],
        next_attempt_at=retry_at,
    ) is True

    # A bounded backoff must prevent a new, overlapping interval.
    assert store.claim_daily_change_summary(next_end, claimed_at="2026-07-21T14:01:00.000Z") is None
    retried = store.claim_daily_change_summary(next_end, claimed_at=retry_at)

    assert retried is not None
    assert {key: retried[key] for key in ("window_start", "window_end", "status")} == {
        "window_start": "2026-07-19T14:00:00.000Z",
        "window_end": first_end,
        "status": "sending",
    }
    assert store.finalize_daily_change_summary(
        first_end, status="sent", claim_token=retried["claim_token"]
    ) is True
    next_report = store.claim_daily_change_summary(next_end, claimed_at=next_end)
    assert next_report is not None
    assert {key: next_report[key] for key in ("window_start", "window_end", "status")} == {
        "window_start": first_end,
        "window_end": next_end,
        "status": "sending",
    }


def test_daily_change_summary_claim_serializes_a_later_window(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()
    original_connect = store.connect
    older_ready = threading.Event()
    release_older = threading.Event()
    newer_done = threading.Event()
    results: dict[str, dict[str, str] | None] = {}

    def connect_with_older_read_barrier() -> sqlite3.Connection:
        conn = original_connect()
        if threading.current_thread().name == "daily-summary-older":
            def pause_before_outstanding_read(statement: str) -> None:
                if "SELECT window_start, window_end, status, next_attempt_at" in statement:
                    older_ready.set()
                    release_older.wait(timeout=5)

            conn.set_trace_callback(pause_before_outstanding_read)
        return conn

    store.connect = connect_with_older_read_barrier  # type: ignore[method-assign]
    store.initialize = lambda: None  # type: ignore[method-assign]

    def claim(name: str, window_end: str) -> None:
        results[name] = store.claim_daily_change_summary(
            window_end, claimed_at=window_end
        )
        if name == "newer":
            newer_done.set()

    older = threading.Thread(
        target=claim,
        args=("older", "2026-07-20T14:00:00.000Z"),
        name="daily-summary-older",
    )
    newer = threading.Thread(
        target=claim,
        args=("newer", "2026-07-21T14:00:00.000Z"),
        name="daily-summary-newer",
    )
    older.start()
    assert older_ready.wait(timeout=2)
    newer.start()
    newer_done.wait(timeout=1)
    release_older.set()
    older.join(timeout=5)
    newer.join(timeout=5)

    assert not older.is_alive()
    assert not newer.is_alive()
    assert results["older"] is not None
    assert results["newer"] is None


def test_daily_change_summary_recovery_only_releases_stale_sending_claims(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    old_end = "2026-07-20T14:00:00.000Z"
    active_end = "2026-07-21T14:00:00.000Z"
    old_claim = store.claim_daily_change_summary(
        old_end, claimed_at="2026-07-20T14:00:00.000Z"
    )
    assert old_claim
    assert store.finalize_daily_change_summary(
        old_end, status="sent", claim_token=old_claim["claim_token"]
    )
    assert store.claim_daily_change_summary(active_end, claimed_at="2026-07-21T14:00:00.000Z")

    released = store.recover_daily_change_summaries(
        stale_before="2026-07-21T13:55:00.000Z"
    )

    assert released == 0
    assert store.claim_daily_change_summary(
        "2026-07-22T14:00:00.000Z", claimed_at="2026-07-22T14:00:00.000Z"
    ) is None
    assert store.recover_daily_change_summaries(
        stale_before="2026-07-21T14:10:00.000Z"
    ) == 1


def test_daily_change_summary_migrates_existing_v8_report_table_for_retry(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE daily_change_summary_reports (
                window_end TEXT PRIMARY KEY,
                window_start TEXT NOT NULL,
                status TEXT NOT NULL,
                claimed_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT ''
            )
            """
        )

    SqliteStore(str(db_path)).initialize()

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(daily_change_summary_reports)")
        }
    assert "next_attempt_at" in columns
    assert "claim_token" in columns


def test_daily_change_summary_recovered_claim_cannot_be_finalized_by_old_worker(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    window_end = "2026-07-20T14:00:00.000Z"
    first_claim = store.claim_daily_change_summary(
        window_end, claimed_at="2026-07-20T14:00:00.000Z"
    )
    assert first_claim is not None

    assert store.recover_daily_change_summaries(
        stale_before="2026-07-20T14:10:00.000Z"
    ) == 1
    second_claim = store.claim_daily_change_summary(
        window_end, claimed_at="2026-07-20T14:10:00.000Z"
    )
    assert second_claim is not None
    assert second_claim["claim_token"] != first_claim["claim_token"]

    assert store.finalize_daily_change_summary(
        window_end, status="sent", claim_token=first_claim["claim_token"]
    ) is False
    assert store.finalize_daily_change_summary(
        window_end, status="sent", claim_token=second_claim["claim_token"]
    ) is True


def test_migration_converts_legacy_web_history_ts_real(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL);
            INSERT INTO schema_version VALUES (2, '2026-06-25T12:00:00.000Z');
            CREATE TABLE web_history (id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, ts REAL NOT NULL);
            INSERT INTO web_history VALUES (
                'hist-1',
                '{"id":"hist-1","ts":1782392554.3,"user":"admin","ean":"5901234567890"}',
                1782392554.3
            );
            """
        )

    store = SqliteStore(str(db_path))
    store.initialize()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(web_history)")}
        row = conn.execute("SELECT created_at, payload_json FROM web_history WHERE id = 'hist-1'").fetchone()

    assert "created_at" in columns
    assert row[0].endswith("Z")
    payload = json.loads(row[1])
    assert payload["created_at"] == row[0]
    assert isinstance(payload["ts"], str)
    assert payload["ts"].endswith("Z")


def test_file_index_segments_are_saved_by_product_name(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()
    snapshot = {
        "version": 1,
        "root": "C:/photos",
        "generated_at": "2026-06-25T13:02:34.300Z",
        "names": ["LUNA", "MAGGIORE"],
        "types": {"LUNA": ["SZAFKA"], "MAGGIORE": ["KOMODA"]},
        "models": {},
        "colors": {},
        "extras": {},
        "files": {},
    }

    store.save_file_index_cache(snapshot)

    with sqlite3.connect(tmp_path / "data.sqlite") as conn:
        rows = conn.execute(
            """
            SELECT segment_key, section, lookup_key, payload_json
            FROM file_index_segments
            ORDER BY segment_key, section, lookup_key
            """
        ).fetchall()

    assert ("LUNA", "names", "LUNA", '"LUNA"') in rows
    assert ("MAGGIORE", "names", "MAGGIORE", '"MAGGIORE"') in rows


def test_file_index_generation_copies_unchanged_segments_in_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(database_path))
    first_snapshot = {
        "version": 1,
        "root": "C:/photos",
        "generated_at": "2026-06-25T13:02:34.300Z",
        "names": ["ALFA", "BETA"],
        "types": {"ALFA": ["KOMODA"], "BETA": ["SZAFKA"]},
        "models": {},
        "colors": {},
        "extras": {},
        "files": {},
    }
    store.save_file_index_cache(first_snapshot)

    second_snapshot = {
        **first_snapshot,
        "generated_at": "2026-06-25T13:03:34.300Z",
        "types": {"ALFA": ["KOMODA"], "BETA": ["SZAFKA", "STOL"]},
    }

    store.save_file_index_cache(second_snapshot, reused_segment_keys=("ALFA",))

    with sqlite3.connect(database_path) as conn:
        rows = conn.execute(
            """
            SELECT segment_key, section, lookup_key, payload_json
            FROM file_index_segments
            ORDER BY segment_key, section, lookup_key
            """
        ).fetchall()
        complete_generations = conn.execute(
            "SELECT COUNT(*) FROM file_index_generations WHERE complete = 1"
        ).fetchone()[0]

    assert ("ALFA", "types", "ALFA", '["KOMODA"]') in rows
    assert ("BETA", "types", "BETA", '["SZAFKA", "STOL"]') in rows
    assert complete_generations == 1


def test_file_index_generation_failure_keeps_previous_complete_snapshot(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(database_path))
    first_snapshot = {
        "version": 1,
        "root": "C:/photos",
        "generated_at": "2026-06-25T13:02:34.300Z",
        "names": ["ALFA", "BETA"],
        "types": {"ALFA": ["KOMODA"], "BETA": ["SZAFKA"]},
        "models": {},
        "colors": {},
        "extras": {},
        "files": {"BETA\x1fSZAFKA": ["before.jpg"]},
    }
    store.save_file_index_cache(first_snapshot)
    with store.connection() as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_changed_file_index_segment
            BEFORE INSERT ON file_index_segments
            WHEN NEW.section = 'files'
            BEGIN
                SELECT RAISE(ABORT, 'injected file index failure');
            END
            """
        )

    second_snapshot = {
        **first_snapshot,
        "generated_at": "2026-06-25T13:03:34.300Z",
        "files": {"BETA\x1fSZAFKA": ["after.jpg"]},
    }

    with pytest.raises(sqlite3.IntegrityError, match="injected file index failure"):
        store.save_file_index_cache(second_snapshot, reused_segment_keys=("ALFA",))

    assert store.load_file_index_cache()["files"] == {
        "BETA\x1fSZAFKA": ["before.jpg"]
    }
    with sqlite3.connect(database_path) as conn:
        generation_count = conn.execute(
            "SELECT COUNT(*) FROM file_index_generations"
        ).fetchone()[0]
    assert generation_count == 1


def test_legacy_file_index_payload_migrates_to_complete_generation(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()
    snapshot = {
        "version": 1,
        "root": "C:/photos",
        "generated_at": "2026-06-25T13:02:34.300Z",
        "dirs_scanned": 1,
        "products_scanned": 1,
        "names": ["ALFA"],
        "types": {"ALFA": ["KOMODA"]},
        "models": {},
        "colors": {},
        "extras": {},
        "files": {},
    }
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO file_index_cache (cache_key, payload_json, updated_at) VALUES (?, ?, ?)",
            ("default", json.dumps(snapshot), snapshot["generated_at"]),
        )

    generation = store.load_file_index_generation()

    assert generation.complete is True
    assert generation.snapshot["names"] == ["ALFA"]
    with store.connection() as conn:
        legacy = conn.execute(
            "SELECT payload_json FROM file_index_cache WHERE cache_key = 'default'"
        ).fetchone()
        segment_count = conn.execute("SELECT COUNT(*) FROM file_index_segments").fetchone()[0]
    assert legacy is None or legacy[0] in ("", "{}")
    assert segment_count > 0


def test_slots_and_sql_columns_roundtrip(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()

    store.save_slots(
        [{"prefix": "01", "label": "MAIN", "filename_label": "MAIN_pic"}],
        {"01": "img_01"},
    )
    store.save_sql_columns(["img_01", "img_02"], table_name="object_query_1")

    slots, sql_map = store.load_slots()
    assert slots == [{"prefix": "01", "label": "MAIN", "filename_label": "MAIN_pic"}]
    assert sql_map == {"01": "img_01"}
    assert store.load_sql_columns() == ["img_01", "img_02"]


def test_lists_roundtrip_uses_excel_payload_shape(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()

    store.save_lists(
        {
            "NAZWY": ["MAGGIORE"],
            "TYPY": ["KOMODA"],
            "MODELE": ["MA03"],
            "KOLORY": ["BIALY"],
            "DODATKI": ["NO-LED"],
            ENTRY_RECORDS_KEY: [
                {
                    "EAN": "5901234567890",
                    "NAZWA": "MAGGIORE",
                    "TYP": "KOMODA",
                    "MODEL": "MA03",
                    "KOLOR1": "BIALY",
                    "KOLOR2": "",
                    "KOLOR3": "",
                    "DODATKI": "NO-LED",
                    "PRODUCT_ID": "PRD-1",
                }
            ],
        }
    )

    payload = store.load_lists()
    assert payload["NAZWY"] == ["MAGGIORE"]
    assert payload["TYPY"] == ["KOMODA"]
    assert payload[ENTRY_RECORDS_KEY][0]["PRODUCT_ID"] == "PRD-1"


def test_add_and_remove_list_value(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()

    assert store.add_list_value("NAZWY", "maggiore") is True
    assert store.add_list_value("NAZWY", "MAGGIORE") is False
    assert store.load_lists()["NAZWY"] == ["MAGGIORE"]

    store.remove_list_value("NAZWY", "maggiore")

    assert store.load_lists()["NAZWY"] == []


def _usage_entry() -> dict[str, str]:
    return {
        "EAN": "5901234567890", "NAZWA": "ŻYRANDOL", "TYP": "STÓŁ",
        "MODEL": "MA-03", "KOLOR1": "BIAŁY", "KOLOR2": "DĄB",
        "KOLOR3": "BIAŁY", "DODATKI": "LED-RGB", "PRODUCT_ID": "PRD-USAGE-1",
    }


def test_find_list_value_usage_matches_every_sqlite_list_field(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()
    store.save_product_entry(_usage_entry())
    expected = {
        "NAZWY": ("zyrandol", "NAZWA"), "TYPY": ("stol", "TYP"),
        "MODELE": ("ma-03", "MODEL"), "KOLORY": ("bialy", "KOLOR1, KOLOR3"),
        "DODATKI": ("led_rgb", "DODATKI"),
    }
    for sheet, (value, fields) in expected.items():
        usage = store.find_list_value_usage(sheet, value)
        assert len(usage) == 1
        assert usage[0]["product_id"] == "PRD-USAGE-1"
        assert usage[0]["fields"] == fields
        assert usage[0]["label"].startswith("ŻYRANDOL | STÓŁ | MA-03")


def test_find_list_value_usage_rejects_unknown_or_blank_list_lookups(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()
    store.save_product_entry(_usage_entry())
    assert store.find_list_value_usage("NIEZNANA", "ŻYRANDOL") == []
    assert store.find_list_value_usage("NAZWY", "") == []


def test_save_product_entry_updates_by_product_id(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()

    first = store.save_product_entry(
        {
            "EAN": "5901234567890",
            "NAZWA": "MAGGIORE",
            "TYP": "KOMODA",
            "MODEL": "MA03",
            "KOLOR1": "BIALY",
            "KOLOR2": "",
            "KOLOR3": "",
            "DODATKI": "NO-LED",
            "PRODUCT_ID": "PRD-1",
        }
    )
    second = store.save_product_entry(
        {
            "EAN": "5901234567890",
            "NAZWA": "MAGGIORE",
            "TYP": "KOMODA",
            "MODEL": "MA04",
            "KOLOR1": "BIALY",
            "KOLOR2": "",
            "KOLOR3": "",
            "DODATKI": "NO-LED",
            "PRODUCT_ID": "PRD-1",
        }
    )

    records = store.load_lists()[ENTRY_RECORDS_KEY]
    assert first["updated"] is False
    assert second["updated"] is True
    assert len(records) == 1
    assert records[0]["MODEL"] == "MA04"


def test_product_queries_use_indexed_exact_identity_and_form_criteria(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()
    store.save_product_entry(
        {
            "EAN": "5901234567890",
            "NAZWA": "MAGGIORE",
            "TYP": "KOMODA",
            "MODEL": "MA03",
            "KOLOR1": "BIALY",
            "KOLOR2": "",
            "KOLOR3": "",
            "DODATKI": "NO-LED",
            "PRODUCT_ID": "PRD-1",
        }
    )
    store.save_product_entry(
        {
            "EAN": "5901234567891",
            "NAZWA": "MAGGIORE",
            "TYP": "KOMODA",
            "MODEL": "MA04",
            "KOLOR1": "CZARNY",
            "KOLOR2": "",
            "KOLOR3": "",
            "DODATKI": "NO-LED",
            "PRODUCT_ID": "PRD-2",
        }
    )

    assert store.get_product_by_ean(" 5901234567890 ")["PRODUCT_ID"] == "PRD-1"
    assert store.get_product_by_id("prd-2")["MODEL"] == "MA04"
    assert store.search_product_entries(
        ProductSearchCriteria(name="maggiore", type_name="komoda"), limit=1
    ) == [
        {
            "PRODUCT_ID": "PRD-1",
            "EAN": "5901234567890",
            "NAZWA": "MAGGIORE",
            "TYP": "KOMODA",
            "MODEL": "MA03",
            "KOLOR1": "BIALY",
            "KOLOR2": "",
            "KOLOR3": "",
            "DODATKI": "NO-LED",
        }
    ]
    assert store.search_product_entries(
        ProductSearchCriteria(product_id="PRD-2", name="not-a-match"), limit=10
    )[0]["PRODUCT_ID"] == "PRD-2"

    with sqlite3.connect(store.path) as conn:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT * FROM product_entries WHERE ean_key = ? LIMIT 1",
            ("5901234567890",),
        ).fetchall()
    assert any("INDEX" in str(row).upper() for row in plan)
    assert not any("SCAN PRODUCT_ENTRIES" in str(row).upper() for row in plan)


def test_product_field_suggestions_validate_context_and_limit_results(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.save_product_entry(
        {
            "EAN": "5901",
            "NAZWA": "ALFA",
            "TYP": "STÓŁ",
            "MODEL": "A2",
            "PRODUCT_ID": "PRD-1",
        }
    )
    store.save_product_entry(
        {
            "EAN": "5902",
            "NAZWA": "ALFA",
            "TYP": "STÓŁ",
            "MODEL": "A1",
            "PRODUCT_ID": "PRD-2",
        }
    )

    assert store.suggest_product_field("model", "a", {"name": "alfa"}, limit=1) == [
        "A1"
    ]
    assert store.suggest_product_field("unknown", "", {}, limit=20) == []


def test_product_query_filters_before_limit_and_suggests_color_and_extra(tmp_path: Path) -> None:
    """Free-text and every web suggestion field stay selective SQLite queries."""

    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.save_product_entry(
        {
            "EAN": "5901",
            "NAZWA": "ALFA",
            "TYP": "STOL",
            "MODEL": "A1",
            "KOLOR1": "BIALY",
            "DODATKI": "MISS",
            "PRODUCT_ID": "PRD-1",
        }
    )
    store.save_product_entry(
        {
            "EAN": "5902",
            "NAZWA": "ALFA",
            "TYP": "STOL",
            "MODEL": "A2",
            "KOLOR1": "CZARNY",
            "DODATKI": "TARGET",
            "PRODUCT_ID": "PRD-2",
        }
    )

    assert store.search_product_entries(
        ProductSearchCriteria(name="ALFA", query="target"), limit=1
    )[0]["PRODUCT_ID"] == "PRD-2"
    assert store.suggest_product_field("color1", "", {"name": "ALFA"}) == [
        "BIALY",
        "CZARNY",
    ]
    assert store.suggest_product_field("extra", "tar", {"name": "ALFA"}) == [
        "TARGET"
    ]


def test_free_text_product_search_uses_index_and_tracks_every_mutation(
    tmp_path: Path,
) -> None:
    """Catch a fallback to table scans or stale FTS content after product writes."""

    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.save_product_entry(
        {
            "EAN": "5901",
            "NAZWA": 'ALFA "DELUXE"',
            "TYP": "STOL",
            "MODEL": "A1",
            "PRODUCT_ID": "PRD-ALPHA",
        }
    )
    store.save_product_entry(
        {
            "EAN": "5902",
            "NAZWA": "ALPHA TWO",
            "TYP": "STOL",
            "MODEL": "A2",
            "PRODUCT_ID": "PRD-BETA",
        }
    )

    cross_field = ProductSearchCriteria(query="pha 5901")
    assert [
        row["PRODUCT_ID"] for row in store.search_product_entries(cross_field)
    ] == ["PRD-ALPHA"]
    assert store.search_product_entries(ProductSearchCriteria(query='"del'))[0][
        "PRODUCT_ID"
    ] == "PRD-ALPHA"
    assert [
        row["PRODUCT_ID"]
        for row in store.search_product_entries(ProductSearchCriteria(query="alpha"))
    ] == ["PRD-ALPHA", "PRD-BETA"]

    explain = getattr(store, "explain_product_search", None)
    assert explain is not None, "production free-text search must expose its real plan"
    plan = explain(cross_field, limit=50)
    assert any("VIRTUAL TABLE INDEX" in detail.upper() for detail in plan)
    assert not any(
        detail.upper().strip() == "SCAN P"
        or detail.upper().strip().startswith("SCAN P ")
        for detail in plan
    )

    store.save_product_entry(
        {
            "EAN": "5901",
            "NAZWA": "OMEGA",
            "TYP": "STOL",
            "MODEL": "A1",
            "PRODUCT_ID": "PRD-ALPHA",
        }
    )
    assert store.search_product_entries(ProductSearchCriteria(query="deluxe")) == []
    assert store.search_product_entries(ProductSearchCriteria(query="mega"))[0][
        "PRODUCT_ID"
    ] == "PRD-ALPHA"

    store.save_lists(
        {
            ENTRY_RECORDS_KEY: [
                {
                    "EAN": "5903",
                    "NAZWA": "GAMMA",
                    "TYP": "SZAFA",
                    "MODEL": "G1",
                    "PRODUCT_ID": "PRD-GAMMA",
                }
            ]
        }
    )
    assert store.search_product_entries(ProductSearchCriteria(query="mega")) == []
    assert store.search_product_entries(ProductSearchCriteria(query="amm"))[0][
        "PRODUCT_ID"
    ] == "PRD-GAMMA"
    assert store.search_product_entries(ProductSearchCriteria(query="mm"))[0][
        "PRODUCT_ID"
    ] == "PRD-GAMMA"
    short_plan = explain(ProductSearchCriteria(query="mm"), limit=50)
    assert any("VIRTUAL TABLE INDEX" in detail.upper() for detail in short_plan)
    assert not any(
        detail.upper().strip() == "SCAN P"
        or detail.upper().strip().startswith("SCAN P ")
        for detail in short_plan
    )


def test_missing_fts_triggers_force_rebuild_before_search_is_reenabled(
    tmp_path: Path,
) -> None:
    """A stale surviving FTS table must never become a false-negative filter."""

    db_path = tmp_path / "data.sqlite"
    store = SqliteStore(str(db_path))
    store.save_product_entry(
        {"PRODUCT_ID": "P-1", "EAN": "5901", "NAZWA": "ALPHA"}
    )
    with store.connection() as conn:
        conn.executescript(
            """
            DROP TRIGGER trg_product_entries_fts_insert;
            DROP TRIGGER trg_product_entries_fts_delete;
            DROP TRIGGER trg_product_entries_fts_update;
            """
        )
        conn.execute(
            """
            UPDATE product_entries
            SET name = 'OMEGA', name_key = 'omega',
                search_text_key = replace(search_text_key, 'alpha', 'omega')
            WHERE product_id = 'P-1'
            """
        )

    reopened = SqliteStore(str(db_path))
    assert reopened.search_product_entries(ProductSearchCriteria(query="omega"))[
        0
    ]["PRODUCT_ID"] == "P-1"


def test_save_lists_rejects_duplicate_real_eans_before_replacing_data(
    tmp_path: Path,
) -> None:
    """Bulk replacement must reject, not collapse, blank-ID EAN conflicts."""

    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.save_lists(
        {
            "NAZWY": ["EXISTING"],
            ENTRY_RECORDS_KEY: [
                {"PRODUCT_ID": "P-OLD", "EAN": "OLD-EAN", "NAZWA": "EXISTING"}
            ],
        }
    )
    conflict_error = getattr(sqlite_store, "ProductEanConflictError", ValueError)

    with pytest.raises(conflict_error):
        store.save_lists(
            {
                "NAZWY": ["REPLACEMENT"],
                ENTRY_RECORDS_KEY: [
                    {"EAN": "DUP-EAN", "NAZWA": "FIRST"},
                    {"EAN": " dup-ean ", "NAZWA": "SECOND"},
                ],
            }
        )

    product_id_conflict_error = getattr(
        sqlite_store,
        "ProductIdConflictError",
        ValueError,
    )
    with pytest.raises(product_id_conflict_error):
        store.save_lists(
            {
                "NAZWY": ["REPLACEMENT"],
                ENTRY_RECORDS_KEY: [
                    {"PRODUCT_ID": "DUP-ID", "EAN": "EAN-1", "NAZWA": "FIRST"},
                    {"PRODUCT_ID": " dup-id ", "EAN": "EAN-2", "NAZWA": "SECOND"},
                ],
            }
        )

    lists = store.load_lists()
    assert lists["NAZWY"] == ["EXISTING"]
    assert [row["PRODUCT_ID"] for row in lists[ENTRY_RECORDS_KEY]] == ["P-OLD"]


def test_sqlite_rejects_normalized_real_ean_duplicates_and_reuses_blank_id(
    tmp_path: Path,
) -> None:
    """Catch SQLite accepting an EAN already owned by another product."""

    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.save_product_entry(
        {
            "EAN": "ean-123",
            "NAZWA": "ALFA",
            "PRODUCT_ID": "P-1",
        }
    )
    conflict_error = getattr(sqlite_store, "ProductEanConflictError", ValueError)

    with pytest.raises(conflict_error):
        store.save_product_entry(
            {
                "EAN": " EAN-123 ",
                "NAZWA": "BETA",
                "PRODUCT_ID": "P-2",
            }
        )

    updated = store.save_product_entry(
        {
            "EAN": " EAN-123 ",
            "NAZWA": "UPDATED",
        }
    )
    assert updated["product_id"] == "P-1"
    assert updated["updated"] is True
    assert store.get_product_by_ean("ean-123")["NAZWA"] == "UPDATED"
    with store.connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM product_entries WHERE ean_key = ?",
            ("ean-123",),
        ).fetchone()[0] == 1


def test_sqlite_allows_multiple_blank_and_placeholder_eans(tmp_path: Path) -> None:
    """Blank and BRAK-EAN values do not claim a real product identity."""

    store = SqliteStore(str(tmp_path / "data.sqlite"))
    for index, ean in enumerate(("", "", "BRAK-EAN", " brak-ean ")):
        store.save_product_entry(
            {
                "EAN": ean,
                "NAZWA": f"PRODUCT-{index}",
                "PRODUCT_ID": f"P-{index}",
            }
        )

    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM product_entries").fetchone()[0] == 4


def test_insert_or_replace_cannot_steal_another_products_real_ean(
    tmp_path: Path,
) -> None:
    """The database trigger must run before REPLACE can delete either owner."""

    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.save_product_entry({"PRODUCT_ID": "P-1", "EAN": "EAN-1", "NAZWA": "ONE"})
    store.save_product_entry({"PRODUCT_ID": "P-2", "EAN": "EAN-2", "NAZWA": "TWO"})

    with store.connection() as conn:
        source = dict(
            conn.execute(
                "SELECT * FROM product_entries WHERE product_id = 'P-2'"
            ).fetchone()
        )
        source["product_id"] = "P-1"
        source["product_id_key"] = "p-1"
        columns = tuple(source)
        statement = (
            f"INSERT OR REPLACE INTO product_entries ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _column in columns)})"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement, tuple(source[column] for column in columns))

    with store.connection() as conn:
        rows = conn.execute(
            "SELECT product_id, ean FROM product_entries ORDER BY product_id"
        ).fetchall()
    assert [tuple(row) for row in rows] == [("P-1", "EAN-1"), ("P-2", "EAN-2")]


def test_v13_duplicate_ean_migration_preserves_rows_and_quarantines_conflict(
    tmp_path: Path,
) -> None:
    """Historical conflicts stay intact while new collisions become impossible."""

    db_path = tmp_path / "legacy-duplicates.sqlite"
    seed_store = SqliteStore(str(db_path))
    seed_store.initialize()
    insert_sql = """
        INSERT INTO product_entries (
            product_id, ean, name, type_name, model,
            product_id_key, ean_key, name_key, type_name_key, model_key,
            color1, color2, color3, extra,
            color1_key, color2_key, color3_key, extra_key,
            search_text_key, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    def raw_row(product_id: str, ean: str, name: str):
        values = (
            product_id,
            ean,
            name,
            "STOL",
            "A1",
            product_id.casefold(),
            ean.casefold(),
            name.casefold(),
            "stol",
            "a1",
            "",
            "",
            "",
            "NO-LED",
            "",
            "",
            "",
            "no-led",
        )
        return (*values, " ".join(str(value) for value in values[:5]).casefold(), "2026-08-05T00:00:00.000Z")

    with seed_store.connection() as conn:
        conn.executescript(
            """
            DROP INDEX IF EXISTS uq_product_entries_real_ean_key;
            DROP TRIGGER IF EXISTS trg_product_entries_real_ean_insert;
            DROP TRIGGER IF EXISTS trg_product_entries_real_ean_update;
            DELETE FROM product_entries;
            """
        )
        conn.execute(insert_sql, raw_row("P-1", "EAN-LEGACY", "ALFA"))
        conn.execute(insert_sql, raw_row("P-2", "EAN-LEGACY", "BETA"))
        conn.execute("PRAGMA user_version = 13")
        before = conn.execute(
            """
            SELECT product_id, ean, name, type_name, model,
                   color1, color2, color3, extra, updated_at
            FROM product_entries ORDER BY rowid
            """
        ).fetchall()

    migrated = SqliteStore(str(db_path))
    migrated.initialize()
    conflict_error = getattr(sqlite_store, "ProductEanConflictError", ValueError)
    with migrated.connection() as conn:
        after = conn.execute(
            """
            SELECT product_id, ean, name, type_name, model,
                   color1, color2, color3, extra, updated_at
            FROM product_entries ORDER BY rowid
            """
        ).fetchall()
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    assert "uq_product_entries_real_ean_key" not in indexes
    with pytest.raises(conflict_error):
        migrated.get_product_by_ean("ean-legacy")
    with pytest.raises(conflict_error):
        migrated.load_lists()

    unchanged = migrated.save_product_entry(
        {
            "PRODUCT_ID": "P-1",
            "EAN": "EAN-LEGACY",
            "NAZWA": "ALFA",
            "TYP": "STOL",
            "MODEL": "A1",
        }
    )
    assert unchanged["updated"] is True
    with pytest.raises(conflict_error):
        migrated.save_product_entry(
            {
                "PRODUCT_ID": "P-3",
                "EAN": "EAN-LEGACY",
                "NAZWA": "GAMMA",
            }
        )
    with migrated.connection() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert_sql, raw_row("P-3", "EAN-LEGACY", "GAMMA"))

    migrated.save_product_entry(
        {
            "PRODUCT_ID": "P-2",
            "EAN": "EAN-OTHER",
            "NAZWA": "BETA",
            "TYP": "STOL",
            "MODEL": "A1",
        }
    )
    reinitialized = SqliteStore(str(db_path))
    reinitialized.initialize()
    with reinitialized.connection() as conn:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    assert "uq_product_entries_real_ean_key" in indexes


def test_product_query_key_migration_normalizes_legacy_whitespace_and_casefold(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE product_entries (
                product_id TEXT PRIMARY KEY,
                ean TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                type_name TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                color1 TEXT NOT NULL DEFAULT '',
                color2 TEXT NOT NULL DEFAULT '',
                color3 TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO product_entries (
                product_id, ean, name, type_name, model,
                color1, color2, color3, extra, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                " P-ß ",
                " 5901234567890 ",
                " Straße ",
                " STÓŁ ",
                " A1 ",
                "",
                "",
                "",
                "NO-LED",
                "2026-07-28T00:00:00.000Z",
            ),
        )

    store = SqliteStore(str(db_path))

    assert store.get_product_by_ean("5901234567890") == {
        "PRODUCT_ID": " P-ß ",
        "EAN": " 5901234567890 ",
        "NAZWA": " Straße ",
        "TYP": " STÓŁ ",
        "MODEL": " A1 ",
        "KOLOR1": "",
        "KOLOR2": "",
        "KOLOR3": "",
        "DODATKI": "NO-LED",
    }
    assert store.search_product_entries(ProductSearchCriteria(name="strasse"))[0][
        "PRODUCT_ID"
    ] == " P-ß "


def test_product_query_indexes_work_with_raw_sqlite_maintenance_connections(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "data.sqlite"))
    store.initialize()

    with sqlite3.connect(store.path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with sqlite3.connect(store.path) as conn:
        conn.execute("ANALYZE")
    with sqlite3.connect(store.path) as conn:
        conn.execute("VACUUM")


def test_clear_ocr_crop_queue_removes_unfinished_jobs_but_keeps_completed_history(
    tmp_path: Path,
) -> None:
    """A restart must discard work waiting in the OCR crop queue."""

    store = SqliteStore(str(tmp_path / "data.sqlite"))
    completed_id = store.enqueue_ocr_crop_job(
        {"image_hash": "completed", "bbox": [1, 2, 3, 4], "thumbnail_path": "done.png"}
    )
    assert store.claim_ocr_crop_job()["id"] == completed_id
    store.complete_ocr_crop_job(completed_id, [])
    pending_id = store.enqueue_ocr_crop_job(
        {"image_hash": "pending", "bbox": [5, 6, 7, 8], "thumbnail_path": "pending.png"}
    )
    processing_id = store.enqueue_ocr_crop_job(
        {"image_hash": "processing", "bbox": [5, 6, 7, 8], "thumbnail_path": "processing.png"}
    )
    assert store.claim_ocr_crop_job()["id"] == pending_id

    cleared = store.clear_ocr_crop_queue()

    assert sorted(cleared) == ["pending.png", "processing.png"]
    assert [job["id"] for job in store.list_ocr_crop_jobs()] == [completed_id]


def test_product_query_key_backfill_skips_current_schema_database(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "data.sqlite"
    SqliteStore(str(db_path)).initialize()
    monkeypatch.setattr(
        sqlite_store,
        "_migrate_product_entry_search_keys",
        lambda _conn: (_ for _ in ()).throw(AssertionError("unexpected backfill")),
    )

    SqliteStore(str(db_path)).initialize()


def test_product_query_key_migration_streams_rows_without_fetchall(tmp_path: Path) -> None:
    """Large v12 upgrades must backfill product keys in bounded cursor batches."""

    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE product_entries (
                product_id TEXT PRIMARY KEY,
                ean TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                type_name TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                color1 TEXT NOT NULL DEFAULT '',
                color2 TEXT NOT NULL DEFAULT '',
                color3 TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO product_entries (
                product_id, ean, name, type_name, model,
                color1, color2, color3, extra, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f"P-{index}",
                    str(index),
                    "ALFA",
                    "STOL",
                    "A1",
                    "BIALY",
                    "",
                    "",
                    "NO-LED",
                    "now",
                )
                for index in range(3)
            ],
        )

    class _CursorWithoutFetchall:
        def __init__(self, cursor):
            self._cursor = cursor

        def fetchmany(self, size):
            return self._cursor.fetchmany(size)

        def fetchall(self):
            raise AssertionError("migration must not materialize all product rows")

    class _StreamingConnection:
        def __init__(self, connection):
            self._connection = connection

        def executescript(self, script):
            return self._connection.executescript(script)

        def execute(self, sql, parameters=()):
            cursor = self._connection.execute(sql, parameters)
            if sql.startswith("SELECT rowid,"):
                return _CursorWithoutFetchall(cursor)
            return cursor

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        sqlite_store._migrate_product_entry_search_keys(_StreamingConnection(conn))
        rows = conn.execute(
            "SELECT color1_key, extra_key, search_text_key FROM product_entries ORDER BY rowid"
        ).fetchall()

    assert [tuple(row) for row in rows] == [
        ("bialy", "no-led", f"p-{index} {index} alfa stol a1 bialy   no-led")
        for index in range(3)
    ]
