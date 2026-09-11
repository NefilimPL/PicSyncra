"""Tests for structured operational persistence."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest

from picsyncra.data_store import SqliteDataStoreAdapter
from picsyncra import sqlite_store
from picsyncra.sqlite_store import SqliteStore


def _event(
    identity: str,
    created_at: str,
    severity: str = "info",
    **overrides: object,
) -> dict[str, object]:
    event: dict[str, object] = {
        "id": identity,
        "created_at": created_at,
        "severity": severity,
        "event_type": "job.started",
        "module": "process",
        "stage": "prepare",
        "username": "alice",
        "ean": "5900000000001",
        "product_id": "product-1",
        "slot": "01",
        "job_id": "job-1",
        "correlation_id": "correlation-1",
        "summary": "Start",
        "recommended_action": "Wait",
        "details": {"step": 1},
    }
    event.update(overrides)
    return event


def _history_record(index: int, *, ean: str | None = None) -> dict[str, object]:
    created_at = datetime(2026, 7, 16, 10, tzinfo=timezone.utc) + timedelta(
        seconds=index
    )
    return {
        "id": f"history-{index:03d}",
        "created_at": created_at.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
        "user": "alice",
        "action": "save",
        "ean": ean or f"590{index:010d}",
        "product_id": f"product-{index}",
        "summary": f"Saved product {index}",
        "details": {"entry": {"name": f"Product {index}"}},
    }


def _append_history_before_query(
    store: SqliteStore,
    writer: SqliteStore,
    monkeypatch: pytest.MonkeyPatch,
    *,
    query_prefix: str,
    record: dict[str, object],
) -> tuple[list[bool], list[BaseException]]:
    original_connect = store.connect
    appended = [False]
    errors: list[BaseException] = []

    def connect_with_append_hook() -> sqlite3.Connection:
        conn = original_connect()

        def append_before_query(statement: str) -> None:
            normalized = " ".join(statement.split()).lower()
            if appended[0] or not normalized.startswith(query_prefix):
                return
            appended[0] = True
            try:
                writer.append_history(record)
            except BaseException as exc:  # pragma: no cover - asserted by caller
                errors.append(exc)

        conn.set_trace_callback(append_before_query)
        return conn

    monkeypatch.setattr(store, "connect", connect_with_append_hook)
    return appended, errors


def test_history_summary_snapshot_uses_index_without_payload_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "app.sqlite"
    records = [_history_record(index) for index in range(60)]
    migration_secret = "migration-secret-must-not-leak"
    first_details = records[0]["details"]
    assert isinstance(first_details, dict)
    first_entry = first_details["entry"]
    assert isinstance(first_entry, dict)
    first_entry["api_token"] = migration_secret
    with sqlite3.connect(database) as conn:
        conn.executescript(
            """
            PRAGMA user_version = 10;
            CREATE TABLE web_history (
                id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO web_history (id, payload_json, created_at)
            VALUES (?, ?, ?)
            """,
            [
                (record["id"], json.dumps(record), record["created_at"])
                for record in records
            ],
        )

    store = SqliteStore(str(database))
    store.initialize()
    with store.connection() as conn:
        index_rows = conn.execute(
            """
            SELECT id, ean, username, product_id, action, summary, entry_json,
                search_text, created_at
            FROM web_history_index
            ORDER BY id
            """
        ).fetchall()
    expected_rows = []
    for index, record in enumerate(records):
        entry = {"name": f"Product {index}"}
        search_entry_values = [f"Product {index}"]
        if index == 0:
            entry["api_token"] = "[REDACTED]"
            search_entry_values.append("[REDACTED]")
        expected_rows.append(
            (
                record["id"],
                record["ean"],
                "alice",
                record["product_id"],
                "save",
                record["summary"],
                json.dumps(entry, ensure_ascii=False, sort_keys=True),
                " ".join(
                    [
                        str(record["ean"]),
                        str(record["product_id"]),
                        str(record["summary"]),
                        "save",
                        "alice",
                        *search_entry_values,
                    ]
                ).casefold(),
                record["created_at"],
            )
        )
    assert [tuple(row) for row in index_rows] == expected_rows
    assert migration_secret not in "\n".join(
        str(value) for row in index_rows for value in row
    )
    monkeypatch.setattr(
        sqlite_store,
        "_json_loads",
        lambda *_: (_ for _ in ()).throw(AssertionError("payload decode")),
    )

    payload = store.history_summary_snapshot(page=2, page_size=50)

    assert payload["page"] == 2
    assert len(payload["groups"]) == 10


def test_history_summary_snapshot_is_stable_during_concurrent_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "app.sqlite"
    store = SqliteStore(str(database))
    writer = SqliteStore(str(database))
    initial = _history_record(0, ean="old-ean")
    incoming = _history_record(1, ean="new-ean")
    incoming["user"] = "bob"
    store.save_history([initial])
    with sqlite3.connect(database) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
    appended, errors = _append_history_before_query(
        store,
        writer,
        monkeypatch,
        query_prefix="with filtered as",
        record=incoming,
    )

    payload = store.history_summary_snapshot()

    assert appended == [True]
    assert errors == []
    assert payload["count"] == payload["total_groups"] == 1
    assert [group["ean"] for group in payload["groups"]] == ["old-ean"]
    assert payload["users"] == ["alice"]


def test_history_group_snapshot_decodes_only_requested_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.save_history([_history_record(index, ean="5901") for index in range(60)])
    store.initialize()  # one-time index backfill before measuring hot reads
    calls = 0
    original = sqlite_store._json_loads

    def counted(value: object, fallback: object) -> object:
        nonlocal calls
        calls += 1
        return original(value, fallback)

    monkeypatch.setattr(sqlite_store, "_json_loads", counted)

    payload = store.history_group_snapshot(ean="5901", page=2, page_size=25)

    assert payload is not None
    assert len(payload["items"]) == calls == 25
    assert payload["total_items"] == 60
    assert payload["total_pages"] == 3


def test_history_group_snapshot_is_stable_during_concurrent_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "app.sqlite"
    store = SqliteStore(str(database))
    writer = SqliteStore(str(database))
    initial = _history_record(0, ean="5901")
    incoming = _history_record(1, ean="5901")
    store.save_history([initial])
    with sqlite3.connect(database) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
    appended, errors = _append_history_before_query(
        store,
        writer,
        monkeypatch,
        query_prefix="with page_ids as",
        record=incoming,
    )

    payload = store.history_group_snapshot(ean="5901")

    assert appended == [True]
    assert errors == []
    assert payload is not None
    assert payload["total_items"] == 1
    assert [item["id"] for item in payload["items"]] == [initial["id"]]
    assert payload["latest_ts"] == pytest.approx(
        datetime.fromisoformat(
            str(initial["created_at"]).replace("Z", "+00:00")
        ).timestamp()
    )


def test_save_history_replaces_same_count_index_rows_in_one_transaction(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.save_history([_history_record(0, ean="old-ean")])
    store.initialize()

    store.save_history([_history_record(0, ean="new-ean")])

    summary = store.history_summary_snapshot()
    detail = store.history_group_snapshot(ean="new-ean")
    assert [group["ean"] for group in summary["groups"]] == ["new-ean"]
    assert store.history_group_snapshot(ean="old-ean") is None
    assert detail is not None
    assert [item["ean"] for item in detail["items"]] == ["new-ean"]


def test_append_history_keeps_payload_and_index_at_retention_limit(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))

    for index in range(2001):
        store.append_history(_history_record(index, ean=f"590{index:010d}"))

    with store.connection() as conn:
        payload_count = conn.execute("SELECT COUNT(*) FROM web_history").fetchone()[0]
        index_count = conn.execute(
            "SELECT COUNT(*) FROM web_history_index"
        ).fetchone()[0]
        payload_ids = {
            row[0] for row in conn.execute("SELECT id FROM web_history").fetchall()
        }
        index_ids = {
            row[0]
            for row in conn.execute("SELECT id FROM web_history_index").fetchall()
        }
    assert payload_count == index_count == 2000
    expected_ids = {f"history-{index:03d}" for index in range(1, 2001)}
    assert payload_ids == index_ids == expected_ids


def test_save_history_keeps_payload_and_index_at_retention_limit(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.save_history([_history_record(index) for index in range(2001)])

    with store.connection() as conn:
        payload_count = conn.execute("SELECT COUNT(*) FROM web_history").fetchone()[0]
        index_count = conn.execute(
            "SELECT COUNT(*) FROM web_history_index"
        ).fetchone()[0]
        payload_ids = {
            row[0] for row in conn.execute("SELECT id FROM web_history").fetchall()
        }
        index_ids = {
            row[0]
            for row in conn.execute("SELECT id FROM web_history_index").fetchall()
        }
    assert payload_count == index_count == 2000
    expected_ids = {f"history-{index:03d}" for index in range(1, 2001)}
    assert payload_ids == index_ids == expected_ids


def test_history_index_search_uses_unicode_casefold(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    record = _history_record(0, ean="5901")
    record["summary"] = "Straße"
    store.save_history([record])

    summary = store.history_summary_snapshot(query="STRASSE")
    detail = store.history_group_snapshot(ean="5901", query="strasse")

    assert [group["ean"] for group in summary["groups"]] == ["5901"]
    assert detail is not None
    assert [item["summary"] for item in detail["items"]] == ["Straße"]


def _delivery(identity: str, created_at: str, **overrides: object) -> dict[str, object]:
    delivery: dict[str, object] = {
        "id": identity,
        "incident_id": "inc-1",
        "event_id": "evt-1",
        "severity": "error",
        "status": "pending",
        "primary_channel": "entra",
        "used_channel": "",
        "recipients": ["admin@example.com"],
        "message": {"subject": "FTP failed", "message_id": "incident-1"},
        "attempts": [],
        "created_at": created_at,
        "updated_at": created_at,
        "next_attempt_at": "",
    }
    delivery.update(overrides)
    return delivery


def test_v6_schema_adds_notification_deliveries_to_fresh_and_existing_databases(
    tmp_path: Path,
) -> None:
    fresh_path = tmp_path / "fresh.sqlite"
    SqliteStore(str(fresh_path)).initialize()
    with sqlite3.connect(fresh_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == sqlite_store.SCHEMA_VERSION
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'notification_deliveries'"
        ).fetchone()
        indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(notification_deliveries)")
        }
    assert "idx_notification_deliveries_pending" in indexes
    assert "idx_notification_deliveries_incident" in indexes

    existing_path = tmp_path / "existing-v6.sqlite"
    existing = SqliteStore(str(existing_path))
    existing.initialize()
    with sqlite3.connect(existing_path) as conn:
        conn.execute("DROP TABLE notification_deliveries")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == sqlite_store.SCHEMA_VERSION
    SqliteStore(str(existing_path)).initialize()
    with sqlite3.connect(existing_path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'notification_deliveries'"
        ).fetchone()


def test_notification_delivery_repository_decodes_updates_filters_and_pages(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    first = store.enqueue_notification_delivery(
        _delivery("delivery-1", "2026-07-16T10:00:00.000Z")
    )
    store.enqueue_notification_delivery(
        _delivery(
            "delivery-2",
            "2026-07-16T10:01:00.000Z",
            incident_id="inc-2",
            next_attempt_at="2999-01-01T00:00:00.000Z",
        )
    )
    store.enqueue_notification_delivery(
        _delivery("delivery-3", "2026-07-16T10:02:00.000Z")
    )

    assert first["recipients"] == ["admin@example.com"]
    assert first["message"] == {"message_id": "incident-1", "subject": "FTP failed"}
    assert first["attempts"] == []
    assert "recipients_json" not in first

    pending = store.pending_notification_deliveries(limit=20)
    assert [item["id"] for item in pending] == ["delivery-1", "delivery-3"]

    claimed = store.update_notification_delivery(
        "delivery-1",
        status="sending",
        updated_at="2026-07-16T10:02:30.000Z",
    )
    assert claimed["status"] == "sending"
    updated = store.update_notification_delivery(
        "delivery-1",
        status="sent",
        used_channel="smtp",
        attempts=[{"channel": "entra", "status": "error"}],
        updated_at="2026-07-16T10:03:00.000Z",
    )
    assert updated["status"] == "sent"
    assert updated["used_channel"] == "smtp"
    assert updated["attempts"] == [{"channel": "entra", "status": "error"}]

    first_page = store.query_notification_deliveries(limit=2)
    assert [item["id"] for item in first_page["items"]] == [
        "delivery-3",
        "delivery-2",
    ]
    second_page = store.query_notification_deliveries(
        cursor=first_page["next_cursor"], limit=2
    )
    assert [item["id"] for item in second_page["items"]] == ["delivery-1"]
    assert [
        item["id"]
        for item in store.query_notification_deliveries(incident_id="inc-1")["items"]
    ] == ["delivery-3", "delivery-1"]


def test_pending_deliveries_order_by_effective_due_time_without_starvation(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.enqueue_notification_delivery(
        _delivery(
            "retry-overdue",
            "2026-07-16T10:30:00.000Z",
            next_attempt_at="2026-07-16T09:00:00.000Z",
        )
    )
    for index in range(5):
        store.enqueue_notification_delivery(
            _delivery(
                f"immediate-{index}",
                f"2026-07-16T10:0{index}:00.000Z",
            )
        )
    store.enqueue_notification_delivery(
        _delivery(
            "retry-future",
            "2026-07-16T08:00:00.000Z",
            next_attempt_at="2999-01-01T00:00:00.000Z",
        )
    )

    first_batch = store.pending_notification_deliveries(limit=2)

    assert [item["id"] for item in first_batch] == [
        "retry-overdue",
        "immediate-0",
    ]
    assert "retry-future" not in {item["id"] for item in first_batch}


def test_notification_deliveries_for_incidents_caps_ids_dedupes_and_orders_ties(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    same_time = "2026-07-16T10:00:00.000Z"
    for index in range(102):
        store.enqueue_notification_delivery(
            _delivery(
                f"delivery-{index:03d}",
                same_time,
                incident_id=f"inc-{index:03d}",
            )
        )
    for suffix in range(12):
        store.enqueue_notification_delivery(
            _delivery(
                f"inc-zero-extra-{suffix:02d}",
                same_time,
                incident_id="inc-000",
            )
        )

    rows = store.notification_deliveries_for_incidents(
        ["inc-000", "inc-000", *[f"inc-{index:03d}" for index in range(1, 103)]],
        per_incident_limit=99,
    )

    assert {row["incident_id"] for row in rows} == {
        f"inc-{index:03d}" for index in range(100)
    }
    zero_rows = [row for row in rows if row["incident_id"] == "inc-000"]
    assert len(zero_rows) == 10
    assert [row["id"] for row in zero_rows] == sorted(
        [row["id"] for row in zero_rows], reverse=True
    )
    assert [row["id"] for row in rows] == sorted(
        [row["id"] for row in rows], reverse=True
    )


def test_sqlite_adapter_forwards_incident_delivery_batch_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter = SqliteDataStoreAdapter(str(tmp_path / "app.sqlite"))
    captured = {}

    def load(ids, *, per_incident_limit):
        captured["ids"] = ids
        captured["limit"] = per_incident_limit
        return [{"id": "delivery-1"}]

    monkeypatch.setattr(adapter.store, "notification_deliveries_for_incidents", load)

    assert adapter.notification_deliveries_for_incidents(
        ["inc-1", "inc-1"], per_incident_limit=7
    ) == [{"id": "delivery-1"}]
    assert captured == {"ids": ["inc-1", "inc-1"], "limit": 7}


def test_notification_delivery_claim_is_atomic_across_connections(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    SqliteStore(str(db_path)).enqueue_notification_delivery(
        _delivery("delivery-1", "2026-07-16T10:00:00.000Z")
    )
    stores = [SqliteStore(str(db_path)), SqliteStore(str(db_path))]
    barrier = Barrier(2)

    def claim(index: int) -> dict[str, object]:
        barrier.wait()
        return stores[index].update_notification_delivery(
            "delivery-1",
            status="sending",
            updated_at="2026-07-16T10:01:00.000Z",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, range(2)))

    assert sorted(bool(item) for item in claims) == [False, True]
    assert [item["status"] for item in claims if item] == ["sending"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ""),
        ("status", "unknown"),
        ("primary_channel", "unknown"),
        ("used_channel", "unknown"),
        ("created_at", "not-a-timestamp"),
        ("updated_at", "2026-07-16T10:00:00Z"),
        ("next_attempt_at", "2026-07-16 10:00:00.000+00:00"),
        ("attempts", {}),
    ],
)
def test_enqueue_notification_delivery_rejects_malformed_rows(
    tmp_path: Path, field: str, value: object
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    record = _delivery("delivery-1", "2026-07-16T10:00:00.000Z")
    record[field] = value

    with pytest.raises(ValueError):
        store.enqueue_notification_delivery(record)


@pytest.mark.parametrize(
    ("kwargs"),
    [
        {"status": "unknown", "updated_at": "2026-07-16T10:01:00.000Z"},
        {
            "status": "sending",
            "used_channel": "unknown",
            "updated_at": "2026-07-16T10:01:00.000Z",
        },
        {"status": "sending", "updated_at": "not-a-timestamp"},
        {
            "status": "sending",
            "updated_at": "2026-07-16T10:01:00.000Z",
            "next_attempt_at": "2026-07-16T10:02:00Z",
        },
        {
            "status": "sending",
            "updated_at": "2026-07-16T10:01:00.000Z",
            "attempts": {},
        },
    ],
)
def test_update_notification_delivery_rejects_invalid_values(
    tmp_path: Path, kwargs: dict[str, object]
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.enqueue_notification_delivery(
        _delivery(
            "delivery-1",
            "2026-07-16T10:00:00.000Z",
            attempts=[{"status": "queued"}],
        )
    )

    with pytest.raises(ValueError):
        store.update_notification_delivery("delivery-1", **kwargs)

    stored = store.query_notification_deliveries()["items"][0]
    assert stored["status"] == "pending"
    assert stored["attempts"] == [{"status": "queued"}]


def test_notification_delivery_enforces_transitions_and_stale_recovery(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.enqueue_notification_delivery(
        _delivery("delivery-1", "2026-07-16T10:00:00.000Z")
    )

    with pytest.raises(ValueError):
        store.update_notification_delivery(
            "delivery-1",
            status="sent",
            updated_at="2026-07-16T10:01:00.000Z",
        )

    assert store.update_notification_delivery(
        "delivery-1",
        status="sending",
        updated_at="2026-07-16T10:01:00.000Z",
    )["status"] == "sending"
    assert store.update_notification_delivery(
        "delivery-1",
        status="pending",
        updated_at="2026-07-16T10:02:00.000Z",
        next_attempt_at="2026-07-16T10:03:00.000Z",
    )["status"] == "pending"
    assert store.update_notification_delivery(
        "delivery-1",
        status="sending",
        updated_at="2026-07-16T10:03:00.000Z",
    )["status"] == "sending"
    assert store.update_notification_delivery(
        "delivery-1",
        status="error",
        used_channel="entra",
        attempts=[{"channel": "entra", "status": "error"}],
        updated_at="2026-07-16T10:04:00.000Z",
    )["status"] == "error"

    with pytest.raises(ValueError):
        store.update_notification_delivery(
            "delivery-1",
            status="pending",
            updated_at="2026-07-16T10:05:00.000Z",
        )


def test_update_notification_delivery_requires_nonempty_id(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))

    with pytest.raises(ValueError):
        store.update_notification_delivery(
            "",
            status="sending",
            updated_at="2026-07-16T10:00:00.000Z",
        )


def test_sqlite_adapter_delegates_notification_delivery_repository(tmp_path: Path) -> None:
    adapter = SqliteDataStoreAdapter(str(tmp_path / "app.sqlite"))
    queued = adapter.enqueue_notification_delivery(
        _delivery("delivery-1", "2026-07-16T10:00:00.000Z")
    )

    assert queued["id"] == "delivery-1"
    assert adapter.pending_notification_deliveries()[0]["id"] == "delivery-1"
    assert adapter.update_notification_delivery(
        "delivery-1",
        status="sending",
        updated_at="2026-07-16T10:00:30.000Z",
    )["status"] == "sending"
    assert adapter.update_notification_delivery(
        "delivery-1",
        status="sent",
        updated_at="2026-07-16T10:01:00.000Z",
    )["status"] == "sent"
    assert adapter.query_notification_deliveries(incident_id="inc-1")["items"][0][
        "id"
    ] == "delivery-1"

    incident = adapter.coalesce_incident(
        {
            "id": "inc-release",
            "fingerprint": "release-test",
            "severity": "error",
            "event_type": "mail.failed",
            "first_seen_at": "2026-07-16T11:00:00.000Z",
            "last_seen_at": "2026-07-16T11:00:00.000Z",
            "first_event_id": "evt-release",
            "latest_event_id": "evt-release",
            "notification_window_at": "2026-07-16T11:00:00.000Z",
        }
    )
    assert adapter.release_incident_notification(
        incident["id"],
        claimed_at=incident["notification_claim_at"],
        previous_at=incident["notification_previous_window_at"],
    ) is True


def test_operational_schema_and_cursor_queries(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    first = store.append_operational_event(
        _event("evt-1", "2026-07-16T10:00:00.000Z")
    )
    store.append_operational_event(
        {
            **first,
            "id": "evt-2",
            "created_at": "2026-07-16T10:01:00.000Z",
            "severity": "error",
            "summary": "FTP failed",
        }
    )
    store.append_operational_event(
        _event(
            "evt-3",
            "2026-07-16T10:02:00.000Z",
            "warning",
            username="bob",
            ean="5900000000002",
            job_id="job-2",
            correlation_id="correlation-2",
            module="pimcore",
            summary="Pimcore warning",
        )
    )
    error_page = store.query_operational_events(severities=("error",), limit=20)
    assert [item["id"] for item in error_page["items"]] == ["evt-2"]
    assert error_page["items"][0]["details"] == {"step": 1}
    assert "details_json" not in error_page["items"][0]
    assert error_page["next_cursor"] == ""

    first_page = store.query_operational_events(limit=2)
    assert [item["id"] for item in first_page["items"]] == ["evt-3", "evt-2"]
    assert first_page["next_cursor"]
    second_page = store.query_operational_events(cursor=first_page["next_cursor"], limit=2)
    assert [item["id"] for item in second_page["items"]] == ["evt-1"]
    assert second_page["next_cursor"] == ""

    assert [
        item["id"]
        for item in store.query_operational_events(
            username="bob",
            ean="5900000000002",
            job_id="job-2",
            module="pimcore",
            query="warning",
            since="2026-07-16T10:01:30.000Z",
        )["items"]
    ] == ["evt-3"]
    assert [
        item["id"]
        for item in store.query_operational_events(after_id="evt-1")["items"]
    ] == ["evt-3", "evt-2"]
    assert [
        item["id"]
        for item in store.query_operational_events(correlation_id="correlation-1")[
            "items"
        ]
    ] == ["evt-2", "evt-1"]


def test_incident_context_is_indexed_bounded_and_cursor_paginated(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.sqlite"
    store = SqliteStore(str(db_path))
    for index in range(7):
        store.append_operational_event(
            _event(
                f"before-{index:03d}",
                f"2026-07-16T09:{index:02d}:00.000Z",
                job_id="job-context",
            )
        )
    for index in range(125):
        store.append_operational_event(
            _event(
                f"problem-{index:03d}",
                f"2026-07-16T10:{index // 60:02d}:{index % 60:02d}.000Z",
                "error",
                job_id="job-context",
            )
        )
    for index in range(7):
        store.append_operational_event(
            _event(
                f"after-{index:03d}",
                f"2026-07-16T13:{index:02d}:00.000Z",
                job_id="job-context",
            )
        )
    store.append_operational_event(
        _event(
            "unrelated",
            "2026-07-16T10:30:30.000Z",
            "critical",
            job_id="job-other",
        )
    )
    store.upsert_incident(
        {
            "id": "inc-context",
            "fingerprint": "context",
            "severity": "error",
            "event_type": "test.failure",
            "first_seen_at": "2026-07-16T10:00:00.000Z",
            "last_seen_at": "2026-07-16T10:02:04.000Z",
            "first_event_id": "problem-000",
            "latest_event_id": "problem-124",
            "job_id": "job-context",
        }
    )

    first = store.query_incident_context("inc-context", problem_limit=20)
    second = store.query_incident_context(
        "inc-context",
        problem_cursor=first["problem_next_cursor"],
        problem_limit=1000,
    )

    assert [item["id"] for item in first["before"]] == [
        "before-002",
        "before-003",
        "before-004",
        "before-005",
        "before-006",
    ]
    assert [item["id"] for item in first["problem"]] == [
        f"problem-{index:03d}" for index in range(20)
    ]
    assert first["problem_next_cursor"]
    assert [item["id"] for item in second["problem"]] == [
        f"problem-{index:03d}" for index in range(20, 120)
    ]
    assert second["problem_next_cursor"]
    assert [item["id"] for item in first["after"]] == [
        f"after-{index:03d}" for index in range(5)
    ]
    assert "unrelated" not in json.dumps(first)

    with sqlite3.connect(db_path) as conn:
        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(operational_events)")
        }
        job_plan = " ".join(
            str(row[3])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                + sqlite_store._INCIDENT_CONTEXT_BEFORE_SQL.format(
                    scope_column="job_id"
                ),
                (
                    "job-context",
                    "2026-07-16T10:00:00.000Z",
                    "problem-000",
                    5,
                ),
            )
        )
        correlation_plan = " ".join(
            str(row[3])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                + sqlite_store._INCIDENT_CONTEXT_AFTER_SQL.format(
                    scope_column="correlation_id"
                ),
                (
                    "correlation-1",
                    "2026-07-16T10:00:00.000Z",
                    "problem-000",
                    5,
                ),
            )
        )
        problem_plan = " ".join(
            str(row[3])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                + sqlite_store._INCIDENT_CONTEXT_PROBLEM_SQL.format(
                    scope_column="job_id",
                    cursor_clause="AND (created_at, id) > (?, ?)",
                ),
                (
                    "job-context",
                    "2026-07-16T10:00:00.000Z",
                    "problem-000",
                    "2026-07-16T10:02:04.000Z",
                    "problem-124",
                    "2026-07-16T10:00:19.000Z",
                    "problem-019",
                    21,
                ),
            )
        )
    assert "idx_operational_events_job_created_at_id" in indexes
    assert "idx_operational_events_correlation_created_at_id" in indexes
    assert "idx_operational_events_job_created_at_id" in job_plan
    assert "idx_operational_events_correlation_created_at_id" in correlation_plan
    assert "idx_operational_events_job_created_at_id" in problem_plan


def test_incident_context_uses_correlation_ties_and_rejects_bad_cursor(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    for identity in ("evt-a", "evt-b", "evt-c", "evt-d"):
        store.append_operational_event(
            _event(
                identity,
                "2026-07-16T10:00:00.000Z",
                "error",
                job_id="",
                correlation_id="corr-context",
            )
        )
    store.upsert_incident(
        {
            "id": "inc-ties",
            "fingerprint": "ties",
            "severity": "error",
            "event_type": "test.failure",
            "first_seen_at": "2026-07-16T10:00:00.000Z",
            "last_seen_at": "2026-07-16T10:00:00.000Z",
            "first_event_id": "evt-a",
            "latest_event_id": "evt-d",
            "correlation_id": "corr-context",
        }
    )

    first = store.query_incident_context("inc-ties", problem_limit=2)
    second = store.query_incident_context(
        "inc-ties", problem_cursor=first["problem_next_cursor"], problem_limit=2
    )

    assert [item["id"] for item in first["problem"]] == ["evt-a", "evt-b"]
    assert [item["id"] for item in second["problem"]] == ["evt-c", "evt-d"]
    assert second["problem_next_cursor"] == ""
    assert store.query_incident_context("missing") is None
    with pytest.raises(ValueError):
        store.query_incident_context("inc-ties", problem_cursor="not-base64!")


def test_incident_context_falls_back_to_latest_scope_when_first_job_is_old(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.append_operational_event(
        _event("old-first", "2026-07-16T10:00:00.000Z", job_id="job-old")
    )
    store.append_operational_event(
        _event("new-before", "2026-07-16T10:00:30.000Z", job_id="job-new")
    )
    store.append_operational_event(
        _event("new-latest", "2026-07-16T10:01:00.000Z", job_id="job-new")
    )
    store.append_operational_event(
        _event("new-after", "2026-07-16T10:02:00.000Z", job_id="job-new")
    )
    store.upsert_incident(
        {
            "id": "inc-cross-job",
            "fingerprint": "cross-job",
            "severity": "error",
            "event_type": "test.failure",
            "first_event_id": "old-first",
            "latest_event_id": "new-latest",
            "job_id": "job-new",
            "occurrence_count": 2,
        }
    )

    context = store.query_incident_context("inc-cross-job")

    assert [item["id"] for item in context["before"]] == ["new-before"]
    assert [item["id"] for item in context["problem"]] == ["new-latest"]
    assert [item["id"] for item in context["after"]] == ["new-after"]
    assert store.query_incidents()["items"][0]["occurrence_count"] == 2


def test_live_snapshot_pages_entire_24h_archive_without_eager_loading(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    since = "2026-07-16T00:00:00.000Z"
    store.initialize()
    with store.connection() as conn:
        for index in range(4000):
            payload = store._normalize_operational_event(
                _event(
                f"evt-{index:04d}",
                (datetime(2026, 7, 16, tzinfo=timezone.utc) + timedelta(seconds=index))
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                )
            )
            store._insert_operational_event(conn, payload)

    seed = store.snapshot_operational_event_stream(since=since, limit=200)
    assert len(seed["items"]) == 200
    assert seed["archive_since"] == since
    assert seed["next_cursor"]
    reached = {item["id"] for item in seed["items"]}
    cursor = seed["next_cursor"]
    page_count = 0
    while cursor:
        page = store.query_operational_events(
            cursor=cursor, since=seed["archive_since"], limit=100
        )
        reached.update(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        page_count += 1

    assert page_count == 38
    assert len(reached) == 4000
    assert "evt-0000" in reached


def test_event_timestamps_are_canonical_and_sort_chronologically(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    store.append_operational_event(
        _event("evt-whole", "2026-07-16T10:00:00Z")
    )
    store.append_operational_event(
        _event("evt-fraction", "2026-07-16T10:00:00.999Z")
    )
    offset = store.append_operational_event(
        _event("evt-offset", "2026-07-16T12:00:00+02:00")
    )
    malformed = store.append_operational_event(
        _event("evt-malformed", "not-aTtimestampZ")
    )

    page = store.query_operational_events(
        since="2026-07-16T10:00:00.000Z", limit=20
    )
    ordered_ids = [item["id"] for item in page["items"]]
    assert ordered_ids.index("evt-fraction") < ordered_ids.index("evt-whole")
    by_id = {item["id"]: item for item in page["items"]}
    assert by_id["evt-whole"]["created_at"] == "2026-07-16T10:00:00.000Z"
    assert by_id["evt-fraction"]["created_at"] == "2026-07-16T10:00:00.999Z"
    assert offset["created_at"] == "2026-07-16T10:00:00.000Z"
    assert malformed["created_at"] != "not-aTtimestampZ"
    datetime.fromisoformat(malformed["created_at"].replace("Z", "+00:00"))


def test_equal_timestamp_cursor_uses_id_tie_breaker_and_handles_bad_cursor(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    for identity in ("evt-a", "evt-b", "evt-c"):
        store.append_operational_event(
            _event(identity, "2026-07-16T10:00:00.000Z")
        )

    first = store.query_operational_events(limit=2)
    second = store.query_operational_events(cursor=first["next_cursor"], limit=2)
    malformed = store.query_operational_events(cursor="not-base64!", limit=200)

    assert [item["id"] for item in first["items"]] == ["evt-c", "evt-b"]
    assert [item["id"] for item in second["items"]] == ["evt-a"]
    assert [item["id"] for item in malformed["items"]] == [
        "evt-c",
        "evt-b",
        "evt-a",
    ]


def test_archive_filters_are_case_insensitive_literal_substrings(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.append_operational_event(
        _event(
            "evt-pim-literal",
            "2026-07-16T10:00:00.000Z",
            module="Pim%core_BŁĄD_ŻÓŁĆ\\Service",
            username="Alice.Admin",
            ean="EAN_590",
            job_id="JOB%_42",
            summary="Literal 100% marker ŻÓŁĆ_\\plik",
        )
    )
    store.append_operational_event(
        _event(
            "evt-pim-decoy",
            "2026-07-16T10:01:00.000Z",
            module="PimXcore-BŁĄDXŻÓŁĆ/Service",
            username="Bob",
            ean="EANX590",
            job_id="JOBXX42",
            summary="Literal 100X marker ŻÓŁĆX/plik",
        )
    )
    store.append_operational_event(
        _event(
            "evt-id-only-needle",
            "2026-07-16T10:02:00.000Z",
            module="FTP",
            job_id="unrelated-job",
        )
    )
    store.append_operational_event(
        _event(
            "evt-fallback-needle",
            "2026-07-16T10:03:00.000Z",
            module="FTP",
            job_id="",
        )
    )

    assert [
        item["id"]
        for item in store.query_operational_events(module="pim%core")["items"]
    ] == ["evt-pim-literal"]
    assert [
        item["id"]
        for item in store.query_operational_events(module="błąd_żółć\\ser")["items"]
    ] == ["evt-pim-literal"]
    assert [
        item["id"]
        for item in store.query_operational_events(username="alice.ad")["items"]
    ] == ["evt-pim-literal"]
    assert [
        item["id"]
        for item in store.query_operational_events(ean="ean_5")["items"]
    ] == ["evt-pim-literal"]
    assert [
        item["id"]
        for item in store.query_operational_events(job_id="job%_4")["items"]
    ] == ["evt-pim-literal"]
    assert [
        item["id"]
        for item in store.query_operational_events(query="100%")["items"]
    ] == ["evt-pim-literal"]
    assert [
        item["id"]
        for item in store.query_operational_events(query="żółć_\\p")["items"]
    ] == ["evt-pim-literal"]
    assert {
        item["id"]
        for item in store.query_operational_events(query="pim")["items"]
    } == {"evt-pim-literal", "evt-pim-decoy"}
    assert {
        item["id"]
        for item in store.query_operational_events(query="2026-07")["items"]
    } == {
        "evt-pim-literal",
        "evt-pim-decoy",
        "evt-id-only-needle",
        "evt-fallback-needle",
    }
    assert store.query_operational_events(query="created_at")["items"] == []
    assert [
        item["id"]
        for item in store.query_operational_events(job_id="needle")["items"]
    ] == ["evt-fallback-needle"]


def test_filtered_live_snapshot_and_older_page_share_literal_filter_semantics(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    since = "2026-07-16T00:00:00.000Z"
    store.initialize()
    with store.connection() as conn:
        for index in range(205):
            payload = store._normalize_operational_event(
                _event(
                    f"evt-pim-{index:03d}",
                    (datetime(2026, 7, 16, tzinfo=timezone.utc) + timedelta(seconds=index))
                    .isoformat(timespec="milliseconds")
                    .replace("+00:00", "Z"),
                    module=(
                        "ŻÓŁĆ Pimcore"
                        if index != 0
                        else "ŻÓŁĆ%_\\Pimcore"
                    ),
                )
            )
            store._insert_operational_event(conn, payload)
        store._insert_operational_event(
            conn,
            store._normalize_operational_event(
                _event(
                    "evt-decoy",
                    "2026-07-16T00:01:00.500Z",
                    module="FTP",
                )
            ),
        )

    seed = store.snapshot_operational_event_stream(
        since=since, limit=200, module="żółć"
    )
    older = store.query_operational_events(
        since=seed["archive_since"],
        cursor=seed["next_cursor"],
        module="żółć",
        limit=20,
    )
    literal = store.snapshot_operational_event_stream(
        since=since, limit=20, module="żółć%_\\p"
    )

    assert len(seed["items"]) == 200
    assert len(older["items"]) == 5
    assert {item["module"] for item in seed["items"]} == {"ŻÓŁĆ Pimcore"}
    assert "evt-pim-000" in {item["id"] for item in older["items"]}
    assert [item["id"] for item in literal["items"]] == ["evt-pim-000"]


def test_every_store_connection_registers_deterministic_unicode_lower(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))

    for _ in range(2):
        with store.connection() as conn:
            assert conn.execute(
                "SELECT picsyncra_lower(?)",
                ("BŁĄD ŻÓŁĆ",),
            ).fetchone()[0] == "błąd żółć"
            function = next(
                row
                for row in conn.execute("PRAGMA function_list")
                if row[0] == "picsyncra_lower" and row[4] == 1
            )
            assert int(function[5]) & 0x800


def test_stream_position_pages_every_later_insert_without_timestamp_ordering(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    marker = store.append_operational_event(
        _event("evt-marker", "2026-07-16T10:00:00.000Z")
    )
    expected = []
    for index in range(205):
        identity = f"evt-{index:03d}"
        if index == 204:
            identity = "evt-000-later-lower-id"
        expected.append(identity)
        store.append_operational_event(
            _event(identity, marker["created_at"])
        )

    start = store.start_operational_event_stream(after_id="evt-marker")
    position = start["position"]
    streamed = []
    page_sizes = []
    while True:
        page = store.poll_operational_event_stream(position=position, limit=100)
        page_sizes.append(len(page["items"]))
        streamed.extend(item["id"] for item in page["items"])
        assert all("sequence" not in item for item in page["items"])
        position = page["position"]
        if not page["items"]:
            break

    assert page_sizes == [100, 100, 5, 0]
    assert streamed == expected
    assert len(streamed) == len(set(streamed))


def test_stream_missing_marker_resets_to_high_water_without_replay(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.append_operational_event(_event("evt-old", "2026-07-16T10:00:00.000Z"))

    start = store.start_operational_event_stream(after_id="evt-deleted")
    assert start["items"] == []
    assert store.poll_operational_event_stream(position=start["position"])["items"] == []

    store.append_operational_event(_event("evt-new", "2026-07-16T10:01:00.000Z"))
    page = store.poll_operational_event_stream(position=start["position"])
    assert [item["id"] for item in page["items"]] == ["evt-new"]


def test_connected_stream_survives_pruning_and_full_clear(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.append_operational_event(_event("evt-marker", "2026-07-15T09:00:00.000Z"))

    assert store.prune_info_events("2026-07-16T09:00:00.000Z") == 1
    store.append_operational_event(_event("evt-after-prune", "2026-07-16T10:00:00.000Z"))
    reconnect_after_prune = store.start_operational_event_stream(after_id="evt-marker")
    after_prune = store.poll_operational_event_stream(
        position=reconnect_after_prune["position"]
    )
    assert [item["id"] for item in after_prune["items"]] == ["evt-after-prune"]

    store.clear_operational_data()
    store.append_operational_event(_event("evt-after-clear", "2026-07-16T10:01:00.000Z"))
    reconnect_after_clear = store.start_operational_event_stream(after_id="evt-marker")
    after_clear = store.poll_operational_event_stream(
        position=reconnect_after_clear["position"]
    )
    assert [item["id"] for item in after_clear["items"]] == ["evt-after-clear"]
    assert store.poll_operational_event_stream(position=after_clear["position"])["items"] == []
    with sqlite3.connect(tmp_path / "app.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM operational_events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM operational_event_stream").fetchone()[0] == 4


def test_v5_migration_backfills_stream_once_in_rowid_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "legacy-v5.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            PRAGMA user_version = 5;
            CREATE TABLE schema_version (
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_version VALUES (5, '2026-07-16T09:00:00.000Z');
            CREATE TABLE operational_events (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                severity TEXT NOT NULL,
                event_type TEXT NOT NULL,
                module TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                ean TEXT NOT NULL DEFAULT '',
                product_id TEXT NOT NULL DEFAULT '',
                slot TEXT NOT NULL DEFAULT '',
                job_id TEXT NOT NULL DEFAULT '',
                correlation_id TEXT NOT NULL DEFAULT '',
                incident_id TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL,
                recommended_action TEXT NOT NULL DEFAULT '',
                details_json TEXT NOT NULL DEFAULT '{}',
                exception_type TEXT NOT NULL DEFAULT '',
                traceback_text TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO operational_events (id, created_at, severity, event_type, summary)
            VALUES ('evt-z', '2026-07-16T10:02:00.000Z', 'info', 'legacy', 'first');
            INSERT INTO operational_events (id, created_at, severity, event_type, summary)
            VALUES ('evt-a', '2026-07-16T10:00:00.000Z', 'info', 'legacy', 'second');
            INSERT INTO operational_events (id, created_at, severity, event_type, summary)
            VALUES ('evt-m', '2026-07-16T10:01:00.000Z', 'info', 'legacy', 'third');
            """
        )

    traced_sql: list[str] = []
    store = SqliteStore(str(db_path))
    original_connect = store.connect

    def traced_connect() -> sqlite3.Connection:
        conn = original_connect()
        conn.set_trace_callback(traced_sql.append)
        return conn

    monkeypatch.setattr(store, "connect", traced_connect)
    store.initialize()

    first_initialize_backfills = [
        statement
        for statement in traced_sql
        if "INSERT OR IGNORE INTO operational_event_stream (event_id)" in statement
        and "SELECT id FROM operational_events ORDER BY rowid" in statement
    ]
    assert len(first_initialize_backfills) == 1
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == sqlite_store.SCHEMA_VERSION
        mappings = conn.execute(
            "SELECT sequence, event_id FROM operational_event_stream ORDER BY sequence"
        ).fetchall()
    assert mappings[0][0] == 0
    assert mappings[0][1]
    assert mappings[1:] == [(1, "evt-z"), (2, "evt-a"), (3, "evt-m")]

    traced_sql.clear()
    store.initialize()

    assert not any(
        "INSERT OR IGNORE INTO operational_event_stream (event_id)" in statement
        or "SELECT id FROM operational_events ORDER BY rowid" in statement
        for statement in traced_sql
    )

    start = store.start_operational_event_stream(after_id="evt-z")
    page = store.poll_operational_event_stream(position=start["position"])
    assert [item["id"] for item in page["items"]] == ["evt-a", "evt-m"]


def test_initialize_recovers_missing_v6_stream_table(tmp_path: Path) -> None:
    db_path = tmp_path / "missing-stream.sqlite"
    store = SqliteStore(str(db_path))
    store.append_operational_event(_event("evt-a", "2026-07-16T10:00:00.000Z"))
    store.append_operational_event(_event("evt-b", "2026-07-16T10:01:00.000Z"))
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == sqlite_store.SCHEMA_VERSION
        conn.execute("DROP TABLE operational_event_stream")

    store = SqliteStore(str(db_path))
    store.initialize()

    with sqlite3.connect(db_path) as conn:
        mappings = conn.execute(
            "SELECT sequence, event_id FROM operational_event_stream ORDER BY sequence"
        ).fetchall()
    assert mappings[0][0] == 0
    assert mappings[0][1]
    assert mappings[1:] == [(1, "evt-a"), (2, "evt-b")]


def test_empty_stream_marker_returns_bounded_latest_snapshot(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    for index in range(105):
        store.append_operational_event(
            _event(f"evt-{index:03d}", f"2026-07-16T10:{index // 60:02d}:{index % 60:02d}.000Z")
        )

    start = store.start_operational_event_stream(initial_limit=100)

    assert [item["id"] for item in start["items"]] == [
        f"evt-{index:03d}" for index in range(5, 105)
    ]
    assert store.poll_operational_event_stream(position=start["position"])["items"] == []


def test_live_snapshot_returns_origin_marker_for_empty_stream(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))

    snapshot = store.snapshot_operational_event_stream(
        since="2026-07-16T00:00:00.000Z"
    )

    assert snapshot["items"] == []
    assert snapshot["stream_after_id"]
    with sqlite3.connect(tmp_path / "app.sqlite") as conn:
        assert conn.execute(
            "SELECT sequence, event_id FROM operational_event_stream"
        ).fetchall() == [(0, snapshot["stream_after_id"])]
        assert conn.execute("SELECT COUNT(*) FROM operational_events").fetchone()[0] == 0


def test_origin_checkpoint_drains_all_later_events_and_survives_clear(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    initial = store.snapshot_operational_event_stream(
        since="2026-07-16T00:00:00.000Z"
    )
    origin_id = initial["stream_after_id"]
    expected = []
    for index in range(205):
        identity = f"evt-after-origin-{index:03d}"
        expected.append(identity)
        store.append_operational_event(
            _event(identity, "2026-07-16T10:00:00.000Z")
        )

    start = store.start_operational_event_stream(after_id=origin_id)
    position = start["position"]
    streamed = []
    page_sizes = []
    while True:
        page = store.poll_operational_event_stream(position=position, limit=100)
        page_sizes.append(len(page["items"]))
        streamed.extend(item["id"] for item in page["items"])
        position = page["position"]
        if not page["items"]:
            break

    assert start["items"] == []
    assert page_sizes == [100, 100, 5, 0]
    assert streamed == expected
    assert origin_id not in streamed
    assert all(
        "sequence" not in item
        for item in store.query_operational_events(limit=100)["items"]
    )

    store.clear_operational_data()
    cleared = store.snapshot_operational_event_stream(
        since="2026-07-16T00:00:00.000Z"
    )
    assert cleared["items"] == []
    assert cleared["stream_after_id"]
    with sqlite3.connect(tmp_path / "app.sqlite") as conn:
        assert conn.execute(
            "SELECT event_id FROM operational_event_stream WHERE sequence = 0"
        ).fetchone() == (origin_id,)


def test_initialize_recovers_missing_origin_without_disturbing_real_sequence(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    origin_id = store.snapshot_operational_event_stream(
        since="2026-07-16T00:00:00.000Z"
    )["stream_after_id"]
    with sqlite3.connect(tmp_path / "app.sqlite") as conn:
        conn.execute("DELETE FROM operational_event_stream WHERE sequence = 0")

    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    store.append_operational_event(_event("evt-real", "2026-07-16T10:00:00.000Z"))

    with sqlite3.connect(tmp_path / "app.sqlite") as conn:
        mappings = conn.execute(
            "SELECT sequence, event_id FROM operational_event_stream ORDER BY sequence"
        ).fetchall()
    assert mappings == [(0, origin_id), (1, "evt-real")]


def test_live_snapshot_uses_tombstone_checkpoint_and_drains_every_later_event(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.append_operational_event(_event("evt-old", "2026-07-15T09:00:00.000Z"))
    store.append_operational_event(_event("evt-visible", "2026-07-16T10:00:00.000Z"))
    store.append_operational_event(_event("evt-tombstone", "2026-07-16T10:01:00.000Z"))
    with sqlite3.connect(tmp_path / "app.sqlite") as conn:
        conn.execute("DELETE FROM operational_events WHERE id = ?", ("evt-tombstone",))

    snapshot = store.snapshot_operational_event_stream(
        since="2026-07-16T00:00:00.000Z"
    )
    expected = []
    for index in range(205):
        identity = f"evt-later-{index:03d}"
        expected.append(identity)
        store.append_operational_event(
            _event(identity, "2026-07-16T10:02:00.000Z")
        )

    assert [item["id"] for item in snapshot["items"]] == ["evt-visible"]
    assert snapshot["stream_after_id"] == "evt-tombstone"
    assert all("sequence" not in item for item in snapshot["items"])
    start = store.start_operational_event_stream(
        after_id=snapshot["stream_after_id"]
    )
    position = start["position"]
    streamed = []
    while True:
        page = store.poll_operational_event_stream(position=position, limit=100)
        streamed.extend(item["id"] for item in page["items"])
        position = page["position"]
        if not page["items"]:
            break
    assert streamed == expected


def test_live_snapshot_returns_bounded_newest_window_with_older_cursor(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    started_at = datetime(2026, 7, 16, 10, tzinfo=timezone.utc)
    store.initialize()
    with store.connection() as conn:
        for index in range(2005):
            payload = store._normalize_operational_event(
                _event(
                    f"evt-{index:04d}",
                    (started_at + timedelta(seconds=index))
                    .isoformat(timespec="milliseconds")
                    .replace("+00:00", "Z"),
                )
            )
            store._insert_operational_event(conn, payload)

    snapshot = store.snapshot_operational_event_stream(
        since="2026-07-16T00:00:00.000Z",
        limit=9999,
    )

    assert len(snapshot["items"]) == 500
    assert snapshot["items"][0]["id"] == "evt-1505"
    assert snapshot["items"][-1]["id"] == "evt-2004"
    assert snapshot["stream_after_id"] == "evt-2004"
    assert snapshot["next_cursor"]
    assert all("sequence" not in item for item in snapshot["items"])


def test_job_and_incident_roundtrips_use_descending_cursors(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    first_job = store.upsert_job_run(
        {
            "id": "job-1",
            "username": "alice",
            "ean": "5900000000001",
            "status": "running",
            "summary": "Preparing",
            "started_at": "2026-07-16T10:00:00.000Z",
            "stages": [{"name": "prepare", "status": "running"}],
            "details": {"files": 2},
        }
    )
    store.upsert_job_run(
        {
            **first_job,
            "status": "completed",
            "finished_at": "2026-07-16T10:03:00.000Z",
        }
    )
    store.upsert_job_run(
        {
            "id": "job-2",
            "status": "failed",
            "started_at": "2026-07-16T10:02:00.000Z",
        }
    )
    jobs = store.query_job_runs(limit=1)
    assert [item["id"] for item in jobs["items"]] == ["job-2"]
    assert jobs["next_cursor"]
    older_jobs = store.query_job_runs(cursor=jobs["next_cursor"], limit=1)
    assert older_jobs["items"][0]["id"] == "job-1"
    assert older_jobs["items"][0]["stages"][0]["name"] == "prepare"
    assert older_jobs["items"][0]["details"] == {"files": 2}

    first_incident = store.upsert_incident(
        {
            "id": "inc-1",
            "fingerprint": "ftp-failed",
            "severity": "error",
            "event_type": "ftp.failed",
            "first_seen_at": "2026-07-16T10:00:00.000Z",
            "last_seen_at": "2026-07-16T10:00:00.000Z",
            "first_event_id": "evt-1",
            "latest_event_id": "evt-1",
            "job_id": "job-1",
            "context": {"host": "ftp.example.com"},
        }
    )
    store.upsert_incident(
        {
            **first_incident,
            "last_seen_at": "2026-07-16T10:01:00.000Z",
            "latest_event_id": "evt-2",
            "occurrence_count": 2,
        }
    )
    store.upsert_incident(
        {
            "id": "inc-2",
            "fingerprint": "disk-full",
            "severity": "critical",
            "event_type": "disk.full",
            "first_seen_at": "2026-07-16T10:02:00.000Z",
            "last_seen_at": "2026-07-16T10:02:00.000Z",
            "first_event_id": "evt-3",
            "latest_event_id": "evt-3",
        }
    )

    found = store.find_open_incident("ftp-failed")
    assert found is not None
    assert found["occurrence_count"] == 2
    assert found["context"] == {"host": "ftp.example.com"}
    incidents = store.query_incidents(severity="error", limit=1)
    assert [item["id"] for item in incidents["items"]] == ["inc-1"]
    assert incidents["next_cursor"] == ""


def test_atomic_incident_coalescing_across_store_connections(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    stores = [SqliteStore(str(db_path)), SqliteStore(str(db_path))]
    for store in stores:
        store.initialize()
    barrier = Barrier(2)

    def coalesce(index: int) -> dict[str, object]:
        barrier.wait()
        return stores[index].coalesce_incident(
            {
                "id": f"inc-{index}",
                "fingerprint": "same-failure",
                "severity": "error",
                "event_type": "ftp.failed",
                "status": "open",
                "first_seen_at": "2026-07-16T10:00:00.000Z",
                "last_seen_at": "2026-07-16T10:00:00.000Z",
                "first_event_id": f"evt-{index}",
                "latest_event_id": f"evt-{index}",
                "correlation_id": f"corr-{index}",
                "notification_window_at": "2026-07-16T10:00:00.000Z",
                "context": {"attempt": index},
            }
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(coalesce, range(2)))

    stored = stores[0].find_open_incident("same-failure")
    assert stored is not None
    assert stored["occurrence_count"] == 2
    assert len({item["id"] for item in results}) == 1
    assert sorted(item["notification_due"] for item in results) == [False, True]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE fingerprint = ? AND status = 'open'",
            ("same-failure",),
        ).fetchone()[0] == 1


def test_release_incident_notification_is_compare_and_swap_safe(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    incident = store.coalesce_incident(
        {
            "id": "inc-1",
            "fingerprint": "ftp-failed",
            "severity": "error",
            "event_type": "ftp.failed",
            "first_seen_at": "2026-07-17T10:00:00.000Z",
            "last_seen_at": "2026-07-17T10:00:00.000Z",
            "first_event_id": "evt-1",
            "latest_event_id": "evt-1",
            "notification_window_at": "2026-07-17T10:00:00.000Z",
        }
    )

    assert incident["notification_claim_at"] == "2026-07-17T10:00:00.000Z"
    assert incident["notification_previous_window_at"] == ""
    assert store.release_incident_notification(
        "inc-1",
        claimed_at="2026-07-17T09:59:00.000Z",
        previous_at="",
    ) is False
    assert store.release_incident_notification(
        "inc-1",
        claimed_at=incident["notification_claim_at"],
        previous_at=incident["notification_previous_window_at"],
    ) is True
    assert store.find_open_incident("ftp-failed")["notification_window_at"] == ""


def test_atomic_incident_event_insert_rolls_back_new_incident_on_event_failure(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    with store.connection() as conn:
        conn.execute(
            """
            CREATE TRIGGER force_event_failure
            BEFORE INSERT ON operational_events
            BEGIN
                SELECT RAISE(ABORT, 'forced event failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced event failure"):
        store.coalesce_incident(
            {
                "id": "inc-new",
                "fingerprint": "atomic-new",
                "severity": "error",
                "event_type": "ftp.failed",
                "first_seen_at": "2026-07-17T10:00:00.000Z",
                "last_seen_at": "2026-07-17T10:00:00.000Z",
                "first_event_id": "evt-new",
                "latest_event_id": "evt-new",
                "notification_window_at": "2026-07-17T10:00:00.000Z",
            },
            source_event=_event(
                "evt-new", "2026-07-17T10:00:00.000Z", "error"
            ),
        )

    assert store.find_open_incident("atomic-new") is None
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM operational_events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM operational_event_stream").fetchone()[0] == 1


def test_atomic_incident_event_insert_rolls_back_existing_incident_update(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    first = store.coalesce_incident(
        {
            "id": "inc-existing",
            "fingerprint": "atomic-existing",
            "severity": "warning",
            "event_type": "ftp.failed",
            "first_seen_at": "2026-07-17T10:00:00.000Z",
            "last_seen_at": "2026-07-17T10:00:00.000Z",
            "first_event_id": "evt-first",
            "latest_event_id": "evt-first",
            "notification_window_at": "2026-07-17T10:00:00.000Z",
        },
        source_event=_event(
            "evt-first", "2026-07-17T10:00:00.000Z", "warning"
        ),
    )
    with store.connection() as conn:
        conn.execute(
            """
            CREATE TRIGGER force_event_failure
            BEFORE INSERT ON operational_events
            WHEN NEW.id = 'evt-second'
            BEGIN
                SELECT RAISE(ABORT, 'forced event failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced event failure"):
        store.coalesce_incident(
            {
                "id": "inc-unused",
                "fingerprint": "atomic-existing",
                "severity": "critical",
                "event_type": "ftp.failed",
                "first_seen_at": "2026-07-17T10:16:00.000Z",
                "last_seen_at": "2026-07-17T10:16:00.000Z",
                "first_event_id": "evt-second",
                "latest_event_id": "evt-second",
                "notification_window_at": "2026-07-17T10:16:00.000Z",
            },
            source_event=_event(
                "evt-second", "2026-07-17T10:16:00.000Z", "critical"
            ),
        )

    stored = store.find_open_incident("atomic-existing")
    assert stored is not None
    assert stored["id"] == first["id"]
    assert stored["severity"] == "warning"
    assert stored["occurrence_count"] == 1
    assert stored["latest_event_id"] == "evt-first"
    assert stored["last_seen_at"] == "2026-07-17T10:00:00.000Z"
    assert stored["notification_window_at"] == "2026-07-17T10:00:00.000Z"
    with store.connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM operational_events WHERE id = 'evt-second'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM operational_event_stream WHERE event_id = 'evt-second'"
        ).fetchone()[0] == 0


def test_atomic_incident_event_insert_publishes_exactly_once_with_incident_id(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    event = _event("evt-atomic", "2026-07-17T10:00:00.000Z", "error")

    incident = store.coalesce_incident(
        {
            "id": "inc-atomic",
            "fingerprint": "atomic-success",
            "severity": "error",
            "event_type": "ftp.failed",
            "first_seen_at": "2026-07-17T10:00:00.000Z",
            "last_seen_at": "2026-07-17T10:00:00.000Z",
            "first_event_id": "evt-atomic",
            "latest_event_id": "evt-atomic",
            "notification_window_at": "2026-07-17T10:00:00.000Z",
        },
        source_event=event,
    )

    stream = store.start_operational_event_stream(initial_limit=20)
    assert [item["id"] for item in stream["items"]] == ["evt-atomic"]
    assert stream["items"][0]["incident_id"] == incident["id"]
    with store.connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM operational_event_stream WHERE event_id = 'evt-atomic'"
        ).fetchone()[0] == 1


def test_initialize_reconciles_duplicate_open_incidents_before_unique_index(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy-v5.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_version (
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_version (version, applied_at)
            VALUES (5, '2026-07-16T08:00:00.000Z');
            CREATE TABLE incidents (
                id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                severity TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                first_event_id TEXT NOT NULL,
                latest_event_id TEXT NOT NULL,
                job_id TEXT NOT NULL DEFAULT '',
                correlation_id TEXT NOT NULL DEFAULT '',
                notification_window_at TEXT NOT NULL DEFAULT '',
                context_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO incidents (
                id, fingerprint, severity, event_type, status,
                first_seen_at, last_seen_at, occurrence_count,
                first_event_id, latest_event_id, job_id, correlation_id,
                notification_window_at, context_json
            ) VALUES (?, 'duplicate', ?, 'ftp.failed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "inc-old", "warning", "open",
                    "2026-07-16T09:00:00.000Z", "2026-07-16T09:05:00.000Z", 2,
                    "evt-first", "evt-old", "job-old", "corr-old",
                    "2026-07-16T09:00:00.000Z",
                    '{"old": 1, "shared": "old"}',
                ),
                (
                    "inc-new", "critical", "open",
                    "2026-07-16T09:01:00.000Z", "2026-07-16T09:10:00.000Z", 3,
                    "evt-new-first", "evt-latest", "job-new", "corr-new",
                    "2026-07-16T09:10:00.000Z",
                    '{"new": 2, "shared": "new"}',
                ),
                (
                    "inc-closed", "error", "closed",
                    "2026-07-16T08:00:00.000Z", "2026-07-16T08:10:00.000Z", 4,
                    "evt-closed-first", "evt-closed-last", "", "",
                    "2026-07-16T08:00:00.000Z", '{"closed": true}',
                ),
            ],
        )

    store = SqliteStore(str(db_path))
    store.initialize()

    open_incident = store.find_open_incident("duplicate")
    assert open_incident is not None
    assert open_incident["id"] == "inc-old"
    assert open_incident["first_seen_at"] == "2026-07-16T09:00:00.000Z"
    assert open_incident["first_event_id"] == "evt-first"
    assert open_incident["last_seen_at"] == "2026-07-16T09:10:00.000Z"
    assert open_incident["latest_event_id"] == "evt-latest"
    assert open_incident["job_id"] == "job-new"
    assert open_incident["correlation_id"] == "corr-new"
    assert open_incident["occurrence_count"] == 5
    assert open_incident["severity"] == "critical"
    assert open_incident["context"]["old"] == 1
    assert open_incident["context"]["new"] == 2
    assert open_incident["context"]["shared"] == "new"
    assert open_incident["context"]["merged_incident_ids"] == ["inc-new"]
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, status, context_json FROM incidents ORDER BY id"
        ).fetchall()
        assert len(rows) == 3
        merged = next(row for row in rows if row[0] == "inc-new")
        assert merged[1] == "merged"
        assert json.loads(merged[2])["merged_into_incident_id"] == "inc-old"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO incidents (
                    id, fingerprint, severity, event_type, status,
                    first_seen_at, last_seen_at, first_event_id, latest_event_id
                ) VALUES (
                    'inc-conflict', 'duplicate', 'error', 'ftp.failed', 'open',
                    '2026-07-16T10:00:00.000Z', '2026-07-16T10:00:00.000Z',
                    'evt-conflict', 'evt-conflict'
                )
                """
            )


def test_delayed_older_incident_does_not_regress_latest_state(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    newer_store = SqliteStore(str(db_path))
    older_store = SqliteStore(str(db_path))
    newer_store.initialize()
    older_store.initialize()

    newer_store.coalesce_incident(
        {
            "id": "inc-newer",
            "fingerprint": "delayed-failure",
            "severity": "error",
            "event_type": "ftp.failed",
            "first_seen_at": "2026-07-16T10:05:00.000Z",
            "last_seen_at": "2026-07-16T10:05:00.000Z",
            "first_event_id": "evt-newer",
            "latest_event_id": "evt-newer",
            "job_id": "job-newer",
            "correlation_id": "corr-newer",
            "notification_window_at": "2026-07-16T10:05:00.000Z",
            "context": {"state": "newer", "newer": True},
        }
    )
    older_store.coalesce_incident(
        {
            "id": "inc-older",
            "fingerprint": "delayed-failure",
            "severity": "warning",
            "event_type": "ftp.failed",
            "first_seen_at": "2026-07-16T10:00:00.000Z",
            "last_seen_at": "2026-07-16T10:00:00.000Z",
            "first_event_id": "evt-older",
            "latest_event_id": "evt-older",
            "job_id": "job-older",
            "correlation_id": "corr-older",
            "notification_window_at": "2026-07-16T10:00:00.000Z",
            "context": {"state": "older", "older": True},
        }
    )

    stored = newer_store.find_open_incident("delayed-failure")
    assert stored is not None
    assert stored["occurrence_count"] == 2
    assert stored["first_seen_at"] == "2026-07-16T10:00:00.000Z"
    assert stored["first_event_id"] == "evt-older"
    assert stored["last_seen_at"] == "2026-07-16T10:05:00.000Z"
    assert stored["latest_event_id"] == "evt-newer"
    assert stored["job_id"] == "job-newer"
    assert stored["correlation_id"] == "corr-newer"
    assert stored["context"] == {"state": "newer", "newer": True}


def test_closed_incident_allows_a_new_open_lifecycle(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    first = store.coalesce_incident(
        {
            "id": "inc-first",
            "fingerprint": "reopened-failure",
            "severity": "error",
            "event_type": "ftp.failed",
            "first_seen_at": "2026-07-16T10:00:00.000Z",
            "last_seen_at": "2026-07-16T10:00:00.000Z",
            "first_event_id": "evt-first",
            "latest_event_id": "evt-first",
            "notification_window_at": "2026-07-16T10:00:00.000Z",
        }
    )
    store.upsert_incident({**first, "status": "closed"})

    reopened = store.coalesce_incident(
        {
            "id": "inc-reopened",
            "fingerprint": "reopened-failure",
            "severity": "error",
            "event_type": "ftp.failed",
            "first_seen_at": "2026-07-16T11:00:00.000Z",
            "last_seen_at": "2026-07-16T11:00:00.000Z",
            "first_event_id": "evt-reopened",
            "latest_event_id": "evt-reopened",
            "notification_window_at": "2026-07-16T11:00:00.000Z",
        }
    )

    assert reopened["id"] == "inc-reopened"
    assert reopened["occurrence_count"] == 1
    assert reopened["notification_due"] is True
    with sqlite3.connect(store.path) as conn:
        assert conn.execute(
            "SELECT id, status FROM incidents ORDER BY id"
        ).fetchall() == [
            ("inc-first", "closed"),
            ("inc-reopened", "open"),
        ]


def test_unread_alert_markers_are_per_user_and_severity(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    store.append_operational_event(
        _event("evt-warning", "2026-07-16T10:00:00.000Z", "warning")
    )
    store.append_operational_event(
        _event("evt-error", "2026-07-16T10:01:00.000Z", "error")
    )
    store.append_operational_event(
        _event("evt-critical", "2026-07-16T10:02:00.000Z", "critical")
    )

    assert store.unread_alert_summary("alice") == {
        "warning": 1,
        "error": 1,
        "critical": 1,
        "total": 3,
        "highest": "critical",
    }
    store.mark_alerts_read(
        "alice", "error", "evt-error", "2026-07-16T10:01:00.000Z"
    )
    assert store.unread_alert_summary("alice")["error"] == 0
    assert store.unread_alert_summary("bob")["error"] == 1


def test_alert_read_marker_does_not_regress_to_an_older_event(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    store = SqliteStore(str(db_path))
    store.initialize()
    store.append_operational_event(
        _event("evt-old", "2026-07-16T10:00:00.000Z", "error")
    )
    store.append_operational_event(
        _event("evt-new", "2026-07-16T10:01:00.000Z", "error")
    )

    store.mark_alerts_read(
        "alice", "error", "evt-new", "2026-07-16T10:01:00.000Z"
    )
    store.mark_alerts_read(
        "alice", "error", "evt-old", "2026-07-16T10:00:00.000Z"
    )
    store.mark_alerts_read(
        "alice", "error", "evt-aaa", "2026-07-16T10:01:00.000Z"
    )

    assert store.unread_alert_summary("alice")["error"] == 0
    with sqlite3.connect(db_path) as conn:
        marker = conn.execute(
            """
            SELECT event_id, created_at FROM alert_reads
            WHERE username = 'alice' AND severity = 'error'
            """
        ).fetchone()
    assert marker == ("evt-new", "2026-07-16T10:01:00.000Z")


def test_prune_and_clear_operational_data_preserve_web_history(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    store.append_history(
        {"id": "history-1", "created_at": "2026-07-15T09:00:00.000Z"}
    )
    store.append_operational_event(
        _event("evt-old", "2026-07-15T09:59:59.999Z")
    )
    store.append_operational_event(
        _event("evt-boundary", "2026-07-15T10:00:00.000Z")
    )
    store.append_operational_event(
        _event("evt-warning", "2026-07-15T09:00:00.000Z", "warning")
    )
    store.upsert_job_run(
        {"id": "job-1", "status": "running", "started_at": "2026-07-16T10:00:00.000Z"}
    )
    store.upsert_incident(
        {
            "id": "inc-1",
            "fingerprint": "failure",
            "severity": "warning",
            "event_type": "job.warning",
            "first_seen_at": "2026-07-16T10:00:00.000Z",
            "last_seen_at": "2026-07-16T10:00:00.000Z",
            "first_event_id": "evt-warning",
            "latest_event_id": "evt-warning",
        }
    )
    store.mark_alerts_read(
        "alice", "warning", "evt-warning", "2026-07-15T09:00:00.000Z"
    )
    store.enqueue_notification_delivery(
        _delivery("delivery-1", "2026-07-16T10:00:00.000Z")
    )
    store.append_pimcore_submission(
        {
            "id": "submission-1",
            "operation_type": "create",
            "status": "success",
            "created_at": "2026-07-16T10:00:00.000Z",
        }
    )

    assert store.prune_info_events("2026-07-15T10:00:00.000Z") == 1
    assert [
        item["id"] for item in store.query_operational_events(limit=20)["items"]
    ] == ["evt-boundary", "evt-warning"]

    assert store.clear_operational_data() == {
        "operational_events": 2,
        "job_runs": 1,
        "incidents": 1,
        "alert_reads": 1,
        "notification_deliveries": 1,
        "notification_outbox": 0,
        "pimcore_integration_contexts": 0,
    }
    assert store.load_history()[0]["id"] == "history-1"
    assert store.query_pimcore_submissions()[0]["id"] == "submission-1"
    with sqlite3.connect(tmp_path / "app.sqlite") as conn:
        stream_ids = conn.execute(
            "SELECT event_id FROM operational_event_stream ORDER BY sequence"
        ).fetchall()
        assert stream_ids[0][0]
        assert stream_ids[1:] == [("evt-boundary",), ("evt-warning",)]


def test_prune_info_events_compacts_old_tombstones_but_keeps_origin_and_checkpoint(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    for index in range(150):
        store.append_operational_event(
            _event(f"evt-old-{index:03d}", "2026-07-15T09:00:00.000Z", "info")
        )
    store.append_operational_event(
        _event("evt-current", "2026-07-16T10:00:00.000Z", "info")
    )

    assert store.prune_info_events("2026-07-16T00:00:00.000Z") == 150

    with store.connection() as conn:
        rows = conn.execute(
            "SELECT sequence, event_id FROM operational_event_stream ORDER BY sequence"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == 0
    assert rows[1][1] == "evt-current"
    # Reconnect markers older than retention resume at the current high-water;
    # the archive snapshot is the source for retained history.
    reconnect = store.start_operational_event_stream(after_id="evt-old-000")
    assert reconnect["items"] == []
    assert reconnect["position"] == rows[1][0]


def test_sqlite_adapter_delegates_observability_repository(tmp_path: Path) -> None:
    adapter = SqliteDataStoreAdapter(str(tmp_path / "app.sqlite"))
    adapter.append_operational_event(
        _event("evt-1", "2026-07-16T10:00:00.000Z", "error")
    )
    assert adapter.query_operational_events(severities=("error",))["items"][0][
        "id"
    ] == "evt-1"
    assert adapter.query_operational_events(correlation_id="correlation-1")[
        "items"
    ][0]["id"] == "evt-1"


def test_sqlite_adapter_delegates_atomic_incident_coalescing(tmp_path: Path) -> None:
    adapter = SqliteDataStoreAdapter(str(tmp_path / "app.sqlite"))

    incident = adapter.coalesce_incident(
        {
            "id": "inc-1",
            "fingerprint": "failure",
            "severity": "error",
            "event_type": "ftp.failed",
            "first_seen_at": "2026-07-16T10:00:00.000Z",
            "last_seen_at": "2026-07-16T10:00:00.000Z",
            "first_event_id": "evt-1",
            "latest_event_id": "evt-1",
            "notification_window_at": "2026-07-16T10:00:00.000Z",
        }
    )

    assert incident["id"] == "inc-1"
    assert incident["notification_due"] is True
