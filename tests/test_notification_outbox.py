from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from picsyncra import notification_service, observability
from picsyncra.notification_service import NotificationService
from picsyncra.sqlite_store import SqliteStore


UTC = timezone.utc
NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _event(identity: str, severity: str = "error") -> dict[str, object]:
    return {
        "id": identity,
        "created_at": "2026-07-17T12:00:00.000Z",
        "severity": severity,
        "event_type": "ftp.upload_failed" if severity != "info" else "job.started",
        "module": "ftp",
        "stage": "upload",
        "username": "alice",
        "ean": "5900000000001",
        "product_id": "product-1",
        "slot": "01",
        "job_id": "job-1",
        "correlation_id": "corr-1",
        "incident_id": "",
        "summary": "FTP failed" if severity != "info" else "Job started",
        "recommended_action": "Retry" if severity != "info" else "",
        "details": {},
        "exception_type": "",
        "traceback_text": "",
    }


def _occurrence(event: dict[str, object]) -> dict[str, object]:
    return {
        "id": "inc-1",
        "fingerprint": "ftp-upload-failed",
        "severity": event["severity"],
        "event_type": event["event_type"],
        "status": "open",
        "first_seen_at": event["created_at"],
        "last_seen_at": event["created_at"],
        "occurrence_count": 1,
        "first_event_id": event["id"],
        "latest_event_id": event["id"],
        "job_id": event["job_id"],
        "correlation_id": event["correlation_id"],
        "notification_window_at": event["created_at"],
        "context": {"summary": event["summary"]},
    }


def _settings(*, info_enabled: bool = False) -> dict[str, object]:
    return {
        "primary_channel": "entra",
        "fallback_enabled": False,
        "entra": {"from_address": "alerts@example.com"},
        "smtp": {},
        "rules": {
            severity: {
                "enabled": severity != "info" or info_enabled,
                "recipients": ["admin@example.com"],
                "include_actor": False,
            }
            for severity in ("info", "warning", "error", "critical")
        },
    }


class RecordingTransport:
    def __init__(self) -> None:
        self.messages: list[object] = []

    def send(self, message: object) -> dict[str, object]:
        self.messages.append(message)
        return {"status": "sent", "elapsed_ms": 1}


def _service(
    store: SqliteStore,
    transport: RecordingTransport,
    *,
    info_enabled: bool = False,
) -> NotificationService:
    return NotificationService(
        store=store,
        transport_factory=lambda _channel, _settings: transport,
        settings_loader=lambda: _settings(info_enabled=info_enabled),
        user_lookup=lambda _username: None,
        event_emitter=lambda **_kwargs: None,
        now=lambda: NOW,
    )


def test_same_v7_database_adds_notification_outbox_idempotently(tmp_path: Path) -> None:
    path = tmp_path / "app.sqlite"
    store = SqliteStore(str(path))
    store.initialize()
    store.initialize()

    with store.connection() as conn:
        # The outbox migration was introduced in schema v11; later independent
        # migrations must not invalidate this idempotency check.
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 11
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notification_outbox'"
        ).fetchone()
        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(notification_outbox)")
        }
    assert "idx_notification_outbox_pending" in indexes


def test_info_intent_foreign_primary_key_collision_rolls_back_event(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    with store.connection() as conn:
        conn.execute(
            """
            INSERT INTO notification_outbox (
                id, event_id, incident_id, severity, status,
                created_at, updated_at, completed_at
            ) VALUES (?, ?, '', 'info', 'pending', ?, ?, '')
            """,
            (
                "intent-evt-info-collision",
                "evt-foreign",
                "2026-07-17T11:00:00.000Z",
                "2026-07-17T11:00:00.000Z",
            ),
        )

    with pytest.raises(sqlite3.IntegrityError):
        store.append_operational_event(
            _event("evt-info-collision", "info"),
            create_notification_intent=True,
        )

    assert store.query_operational_events()["items"] == []
    with store.connection() as conn:
        row = conn.execute(
            "SELECT event_id FROM notification_outbox WHERE id = ?",
            ("intent-evt-info-collision",),
        ).fetchone()
    assert row["event_id"] == "evt-foreign"


def test_committed_intent_wakes_once_after_commit(
    monkeypatch, tmp_path: Path
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    wake_snapshots: list[list[str]] = []

    def observe_wake() -> None:
        wake_snapshots.append(
            [
                str(item["event_id"])
                for item in store.pending_notification_intents(limit=10)
            ]
        )

    monkeypatch.setattr(
        notification_service, "wake_notification_worker", observe_wake
    )

    store.append_operational_event(
        _event("evt-wake", "info"), create_notification_intent=True
    )

    assert wake_snapshots == [["evt-wake"]]


def test_incident_intent_foreign_primary_key_collision_rolls_back_everything(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    with store.connection() as conn:
        conn.execute(
            """
            INSERT INTO notification_outbox (
                id, event_id, incident_id, severity, status,
                created_at, updated_at, completed_at
            ) VALUES (?, ?, '', 'error', 'pending', ?, ?, '')
            """,
            (
                "intent-evt-incident-collision",
                "evt-foreign",
                "2026-07-17T11:00:00.000Z",
                "2026-07-17T11:00:00.000Z",
            ),
        )
    event = _event("evt-incident-collision")

    with pytest.raises(sqlite3.IntegrityError):
        store.coalesce_incident(
            _occurrence(event),
            source_event=event,
            create_notification_intent=True,
        )

    assert store.query_operational_events()["items"] == []
    assert store.query_incidents()["items"] == []
    with store.connection() as conn:
        row = conn.execute(
            "SELECT event_id FROM notification_outbox WHERE id = ?",
            ("intent-evt-incident-collision",),
        ).fetchone()
    assert row["event_id"] == "evt-foreign"


def test_replayed_event_id_must_match_deterministic_intent_identity(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    with store.connection() as conn:
        conn.execute(
            """
            INSERT INTO notification_outbox (
                id, event_id, incident_id, severity, status,
                created_at, updated_at, completed_at
            ) VALUES ('intent-wrong', 'evt-replay', '', 'info', 'pending', ?, ?, '')
            """,
            ("2026-07-17T11:00:00.000Z", "2026-07-17T11:00:00.000Z"),
        )

    with pytest.raises(RuntimeError, match="identity conflict"):
        store.append_operational_event(
            _event("evt-replay", "info"), create_notification_intent=True
        )

    assert store.query_operational_events()["items"] == []


def test_incident_event_window_claim_and_outbox_intent_commit_atomically(
    monkeypatch, tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    event = _event("evt-atomic")
    wake_snapshots: list[list[str]] = []
    monkeypatch.setattr(
        notification_service,
        "wake_notification_worker",
        lambda: wake_snapshots.append(
            [
                str(item["event_id"])
                for item in store.pending_notification_intents(limit=10)
            ]
        ),
    )

    incident = store.coalesce_incident(
        _occurrence(event), source_event=event, create_notification_intent=True
    )

    intents = store.pending_notification_intents(limit=10)
    assert incident["notification_due"] is True
    assert [(item["event_id"], item["incident_id"]) for item in intents] == [
        ("evt-atomic", incident["id"])
    ]
    assert store.query_operational_events()["items"][0]["incident_id"] == incident["id"]
    assert wake_snapshots == [["evt-atomic"]]


def test_outbox_insert_failure_rolls_back_event_and_incident_claim(
    monkeypatch, tmp_path: Path
) -> None:
    class FailingStore(SqliteStore):
        def _insert_notification_intent(self, conn, **values):
            super()._insert_notification_intent(conn, **values)
            raise RuntimeError("forced crash")

    store = FailingStore(str(tmp_path / "app.sqlite"))
    event = _event("evt-rollback")
    wakes = []
    monkeypatch.setattr(
        notification_service, "wake_notification_worker", lambda: wakes.append(True)
    )

    with pytest.raises(RuntimeError, match="forced crash"):
        store.coalesce_incident(
            _occurrence(event), source_event=event, create_notification_intent=True
        )

    assert store.query_operational_events()["items"] == []
    assert store.query_incidents()["items"] == []
    assert store.pending_notification_intents(limit=10) == []
    assert wakes == []


def test_committed_delivery_enqueue_wakes_once_after_commit(
    monkeypatch, tmp_path: Path
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    wake_snapshots: list[list[str]] = []
    monkeypatch.setattr(
        notification_service,
        "wake_notification_worker",
        lambda: wake_snapshots.append(
            [
                str(item["id"])
                for item in store.query_notification_deliveries()["items"]
            ]
        ),
    )
    delivery = {
        "id": "delivery-wake",
        "incident_id": "",
        "event_id": "",
        "severity": "warning",
        "status": "pending",
        "primary_channel": "smtp",
        "used_channel": "",
        "recipients": ["admin@example.com"],
        "message": {},
        "attempts": [],
        "created_at": "2026-07-17T12:00:00.000Z",
        "updated_at": "2026-07-17T12:00:00.000Z",
        "next_attempt_at": "",
    }

    store.enqueue_notification_delivery(delivery)
    store.enqueue_notification_delivery(delivery)

    assert wake_snapshots == [["delivery-wake"]]


def test_materializing_delivery_and_completing_intent_is_atomic_and_idempotent(
    monkeypatch, tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    event = _event("evt-materialize")
    incident = store.coalesce_incident(
        _occurrence(event), source_event=event, create_notification_intent=True
    )
    intent = store.pending_notification_intents(limit=1)[0]
    delivery = {
        "id": "delivery-evt-materialize",
        "incident_id": incident["id"],
        "event_id": event["id"],
        "severity": "error",
        "status": "pending",
        "primary_channel": "entra",
        "used_channel": "",
        "recipients": ["admin@example.com"],
        "message": {"message_id": "notify-evt-materialize", "subject": "Failure"},
        "attempts": [],
        "created_at": "2026-07-17T12:00:00.000Z",
        "updated_at": "2026-07-17T12:00:00.000Z",
        "next_attempt_at": "",
    }
    wake_snapshots: list[list[str]] = []
    monkeypatch.setattr(
        notification_service,
        "wake_notification_worker",
        lambda: wake_snapshots.append(
            [
                str(item["id"])
                for item in store.query_notification_deliveries()["items"]
            ]
        ),
    )

    first = store.materialize_notification_intent(
        str(intent["id"]), delivery=delivery, completed_at="2026-07-17T12:00:01.000Z"
    )
    second = store.materialize_notification_intent(
        str(intent["id"]), delivery=delivery, completed_at="2026-07-17T12:00:02.000Z"
    )

    assert first["id"] == second["id"] == "delivery-evt-materialize"
    assert store.pending_notification_intents(limit=10) == []
    assert len(store.query_notification_deliveries()["items"]) == 1
    assert wake_snapshots == [["delivery-evt-materialize"]]


def test_materialization_failure_rolls_back_delivery_and_leaves_intent_pending(
    monkeypatch, tmp_path: Path,
) -> None:
    class FailingStore(SqliteStore):
        def _insert_notification_delivery(self, conn, payload):
            super()._insert_notification_delivery(conn, payload)
            raise RuntimeError("forced materialization crash")

    store = FailingStore(str(tmp_path / "app.sqlite"))
    event = _event("evt-materialize-rollback")
    incident = store.coalesce_incident(
        _occurrence(event), source_event=event, create_notification_intent=True
    )
    intent = store.pending_notification_intents(limit=1)[0]
    delivery = {
        "id": "delivery-evt-materialize-rollback",
        "incident_id": incident["id"],
        "event_id": event["id"],
        "severity": "error",
        "status": "pending",
        "primary_channel": "entra",
        "used_channel": "",
        "recipients": ["admin@example.com"],
        "message": {"message_id": "notify-evt-materialize-rollback"},
        "attempts": [],
        "created_at": "2026-07-17T12:00:00.000Z",
        "updated_at": "2026-07-17T12:00:00.000Z",
        "next_attempt_at": "",
    }
    wakes = []
    monkeypatch.setattr(
        notification_service, "wake_notification_worker", lambda: wakes.append(True)
    )

    with pytest.raises(RuntimeError, match="forced materialization crash"):
        store.materialize_notification_intent(
            str(intent["id"]),
            delivery=delivery,
            completed_at="2026-07-17T12:00:01.000Z",
        )

    assert [item["id"] for item in store.pending_notification_intents(10)] == [
        intent["id"]
    ]
    assert store.query_notification_deliveries()["items"] == []
    assert wakes == []


def test_deterministic_delivery_id_conflict_never_completes_wrong_intent(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    event = _event("evt-conflict")
    incident = store.coalesce_incident(
        _occurrence(event), source_event=event, create_notification_intent=True
    )
    intent = store.pending_notification_intents(1)[0]
    store.enqueue_notification_delivery(
        {
            "id": "delivery-evt-conflict",
            "incident_id": "inc-other",
            "event_id": "evt-other",
            "severity": "error",
            "status": "pending",
            "primary_channel": "entra",
            "used_channel": "",
            "recipients": ["other@example.com"],
            "message": {"message_id": "other"},
            "attempts": [],
            "created_at": "2026-07-17T11:00:00.000Z",
            "updated_at": "2026-07-17T11:00:00.000Z",
            "next_attempt_at": "",
        }
    )
    desired = {
        "id": "delivery-evt-conflict",
        "incident_id": incident["id"],
        "event_id": event["id"],
        "severity": "error",
        "status": "pending",
        "primary_channel": "entra",
        "used_channel": "",
        "recipients": ["admin@example.com"],
        "message": {"message_id": "notify-evt-conflict"},
        "attempts": [],
        "created_at": "2026-07-17T12:00:00.000Z",
        "updated_at": "2026-07-17T12:00:00.000Z",
        "next_attempt_at": "",
    }

    with pytest.raises(RuntimeError, match="identity conflict"):
        store.materialize_notification_intent(
            str(intent["id"]),
            delivery=desired,
            completed_at="2026-07-17T12:00:01.000Z",
        )

    assert [item["id"] for item in store.pending_notification_intents(10)] == [
        intent["id"]
    ]
    deliveries = store.query_notification_deliveries()["items"]
    assert [(item["id"], item["event_id"]) for item in deliveries] == [
        ("delivery-evt-conflict", "evt-other")
    ]


def test_concurrent_materialization_creates_exactly_one_delivery(tmp_path: Path) -> None:
    path = tmp_path / "app.sqlite"
    first = SqliteStore(str(path))
    second = SqliteStore(str(path))
    event = _event("evt-concurrent")
    incident = first.coalesce_incident(
        _occurrence(event), source_event=event, create_notification_intent=True
    )
    intent = first.pending_notification_intents(1)[0]
    delivery = {
        "id": "delivery-evt-concurrent",
        "incident_id": incident["id"],
        "event_id": event["id"],
        "severity": "error",
        "status": "pending",
        "primary_channel": "entra",
        "used_channel": "",
        "recipients": ["admin@example.com"],
        "message": {"message_id": "notify-evt-concurrent"},
        "attempts": [],
        "created_at": "2026-07-17T12:00:00.000Z",
        "updated_at": "2026-07-17T12:00:00.000Z",
        "next_attempt_at": "",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda store: store.materialize_notification_intent(
                    str(intent["id"]),
                    delivery=delivery,
                    completed_at="2026-07-17T12:00:01.000Z",
                ),
                (first, second),
            )
        )

    assert [result["id"] for result in results] == [
        "delivery-evt-concurrent",
        "delivery-evt-concurrent",
    ]
    assert len(first.query_notification_deliveries()["items"]) == 1
    assert first.pending_notification_intents(10) == []


def test_committed_intent_survives_materialization_failure_and_worker_retries_once(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    event = _event("evt-crash")
    store.coalesce_incident(
        _occurrence(event), source_event=event, create_notification_intent=True
    )
    transport = RecordingTransport()
    broken = NotificationService(
        store=store,
        transport_factory=lambda _channel, _settings: transport,
        settings_loader=lambda: (_ for _ in ()).throw(RuntimeError("temporarily unavailable")),
        user_lookup=lambda _username: None,
        event_emitter=lambda **_kwargs: None,
        now=lambda: NOW,
    )

    assert broken.process_notification_intents(limit=10) == 0
    assert len(store.pending_notification_intents(limit=10)) == 1
    assert store.query_notification_deliveries()["items"] == []

    working = _service(store, transport)
    assert working.process_pending_batch(limit=10) == 1
    assert working.process_pending_batch(limit=10) == 0
    assert len(transport.messages) == 1
    assert len(store.query_notification_deliveries()["items"]) == 1


def test_transient_actor_lookup_failure_leaves_intent_pending(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    event = _event("evt-user-lookup")
    store.coalesce_incident(
        _occurrence(event), source_event=event, create_notification_intent=True
    )
    settings = _settings()
    settings["rules"]["error"] = {
        "enabled": True,
        "recipients": [],
        "include_actor": True,
    }
    service = NotificationService(
        store=store,
        settings_loader=lambda: settings,
        user_lookup=lambda _username: (_ for _ in ()).throw(
            RuntimeError("temporary user store failure")
        ),
        event_emitter=lambda **_kwargs: None,
        now=lambda: NOW,
    )

    assert service.process_notification_intents(limit=10) == 0
    assert [item["event_id"] for item in store.pending_notification_intents(10)] == [
        event["id"]
    ]
    assert store.query_notification_deliveries()["items"] == []


def test_info_event_is_stored_without_creating_an_immediate_outbox_intent(
    monkeypatch, tmp_path: Path
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    monkeypatch.setattr(observability, "observability_store", lambda: store)

    event = observability.emit_event(
        severity="info", event_type="job.started", summary="Job started"
    )
    assert event["incident_id"] == ""
    assert store.pending_notification_intents(10) == []
    assert store.query_notification_deliveries()["items"] == []


def test_enabled_info_rule_does_not_send_one_mail_per_operational_event(
    monkeypatch, tmp_path: Path
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    monkeypatch.setattr(observability, "observability_store", lambda: store)
    event = observability.emit_event(
        severity="info", event_type="job.started", summary="Job started"
    )
    assert store.pending_notification_intents(limit=10) == []
    assert store.query_notification_deliveries()["items"] == []


def test_legacy_info_intent_is_completed_without_creating_a_delivery(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    event = _event("evt-legacy-info", "info")
    store.append_operational_event(event, create_notification_intent=True)
    transport = RecordingTransport()
    service = _service(store, transport, info_enabled=True)

    assert service.process_notification_intents(limit=10) == 1

    assert store.pending_notification_intents(limit=10) == []
    assert store.query_notification_deliveries()["items"] == []
    assert transport.messages == []


def test_suppressed_notification_event_never_creates_an_outbox_intent(
    monkeypatch, tmp_path: Path
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    monkeypatch.setattr(observability, "observability_store", lambda: store)

    observability.emit_event(
        severity="error",
        event_type="notification.failed",
        summary="Delivery failed",
        details={"suppress_notifications": True},
    )

    assert store.pending_notification_intents(limit=10) == []


def test_done_intent_retention_and_clear_preserve_idempotency_boundary(
    tmp_path: Path,
) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    for identity, completed_at in (
        ("evt-old", "2026-07-10T12:00:00.000Z"),
        ("evt-new", "2026-07-17T12:00:00.000Z"),
    ):
        event = _event(identity, "info")
        store.append_operational_event(event, create_notification_intent=True)
        intent = next(
            item for item in store.pending_notification_intents(10) if item["event_id"] == identity
        )
        store.materialize_notification_intent(
            str(intent["id"]), delivery=None, completed_at=completed_at
        )

    assert store.prune_done_notification_intents("2026-07-16T00:00:00.000Z") == 1
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 1
    cleared = store.clear_operational_data()
    assert cleared["notification_outbox"] == 1


def test_info_retention_does_not_delete_source_of_pending_intent(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    event = _event("evt-pending-old", "info")
    event["created_at"] = "2026-07-10T12:00:00.000Z"
    store.append_operational_event(event, create_notification_intent=True)

    assert store.prune_info_events("2026-07-16T00:00:00.000Z") == 0
    intent = store.pending_notification_intents(10)[0]
    assert store.notification_intent_context(str(intent["id"]))["event"]["id"] == event["id"]
