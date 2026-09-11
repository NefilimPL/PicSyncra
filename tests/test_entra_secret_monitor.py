from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from picsyncra.sqlite_store import SqliteStore


UTC = timezone.utc
NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
SECRET = "super-secret-value"
TOKEN = "access-token-value"


def _settings() -> dict[str, object]:
    return {
        "entra": {
            "tenant_id": "tenant-id",
            "client_id": "client-id",
            "client_secret": SECRET,
        }
    }


def _graph_result(*, expires_at: datetime, code: str = "ok", key_id: str = "key-id") -> dict[str, object]:
    if code != "ok":
        return {
            "status": "unavailable",
            "code": code,
            "expires_at": "",
            "remaining_seconds": 0,
            "remaining_days": 0,
            "application_name": "",
            "credential_name": "",
            "credential_key_id": "",
            "source": "microsoft_graph",
            "error_message": "Graph is temporarily unavailable",
        }
    seconds = int((expires_at - NOW).total_seconds())
    return {
        "status": "ok",
        "code": "ok",
        "expires_at": expires_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "remaining_seconds": seconds,
        "remaining_days": max(0, (seconds + 86_399) // 86_400),
        "application_name": "App " + SECRET,
        "credential_name": "Credential " + TOKEN,
        "credential_key_id": key_id,
        "source": "microsoft_graph",
        "error_message": "",
    }


@pytest.fixture
def monitor(tmp_path, monkeypatch):
    import picsyncra.entra_secret_monitor as module

    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.initialize()
    monkeypatch.setattr(module, "_load_email_settings", _settings)
    monkeypatch.setattr(module, "_store", lambda: store)
    return module, store


def test_refresh_persists_only_safe_graph_status(monitor, monkeypatch):
    module, store = monitor
    monkeypatch.setattr(
        module, "fetch_entra_secret_expiry", lambda settings, now: _graph_result(expires_at=NOW + timedelta(days=14))
    )

    result = module.refresh_entra_secret_status(now=NOW)

    assert result["status"] == "ok"
    persisted = store.get_entra_secret_status("tenant-id", "client-id")
    assert persisted["expires_at"] == result["expires_at"]
    serialized = json.dumps({"result": result, "persisted": persisted})
    assert SECRET not in serialized
    assert TOKEN not in serialized
    assert "credential_key_id" not in persisted


def test_refresh_keeps_successful_expiry_when_graph_is_temporarily_unavailable(monitor, monkeypatch):
    module, store = monitor
    monkeypatch.setattr(
        module, "fetch_entra_secret_expiry", lambda settings, now: _graph_result(expires_at=NOW + timedelta(days=7))
    )
    module.refresh_entra_secret_status(now=NOW)
    monkeypatch.setattr(
        module, "fetch_entra_secret_expiry", lambda settings, now: _graph_result(expires_at=NOW, code="transport_unavailable")
    )

    result = module.refresh_entra_secret_status(force=True, now=NOW + timedelta(hours=1))

    assert result["status"] == "ok"
    assert result["source"] == "cached"
    assert result["error_code"] == "transport_unavailable"
    assert result["expires_at"] == (NOW + timedelta(days=7)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    assert store.get_entra_secret_status("tenant-id", "client-id")["last_checked_at"] == "2026-07-20T11:00:00.000Z"


def test_permission_warning_is_emitted_only_when_status_or_code_changes(monitor, monkeypatch):
    module, _store = monitor
    events = []
    monkeypatch.setattr(module, "emit_event", lambda **event: events.append(event))
    monkeypatch.setattr(
        module, "fetch_entra_secret_expiry", lambda settings, now: _graph_result(expires_at=NOW, code="permission_required")
    )

    module.refresh_entra_secret_status(force=True, now=NOW)
    module.refresh_entra_secret_status(force=True, now=NOW + timedelta(hours=1))

    assert len(events) == 1
    assert events[0]["event_type"] == "entra.secret_expiry_permission_required"
    assert events[0]["details"]["suppress_notifications"] is True


@pytest.mark.parametrize("days", [14, 7, 3, 2, 1])
def test_due_thresholds_are_exact_and_emit_critical_events(monitor, monkeypatch, days):
    module, _store = monitor
    events = []
    monkeypatch.setattr(module, "emit_event", lambda **event: events.append(event))
    monkeypatch.setattr(
        module, "fetch_entra_secret_expiry", lambda settings, now: _graph_result(expires_at=NOW + timedelta(days=days))
    )

    assert module.process_due_entra_secret_reminders(now=NOW) == 1

    assert events[0]["severity"] == "critical"
    assert events[0]["event_type"] == "entra.secret_expiry_due"
    assert events[0]["details"]["threshold_days"] == days
    assert events[0]["details"]["application_name"] == "App [REDACTED]"
    assert events[0]["details"]["credential_name"] == "Credential [REDACTED]"
    assert events[0]["details"]["expires_at"] == (NOW + timedelta(days=days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    assert events[0]["details"]["remaining_days"] == days
    assert events[0]["details"]["remaining_time"]


def test_due_reminder_retries_after_claim_failure_without_duplicate_event_or_outbox(
    monitor, monkeypatch
):
    module, store = monitor
    import picsyncra.observability as observability

    monkeypatch.setattr(observability, "observability_store", lambda: store)
    monkeypatch.setattr(module, "emit_event", observability.emit_event)
    monkeypatch.setattr(
        module,
        "fetch_entra_secret_expiry",
        lambda settings, now: _graph_result(expires_at=NOW + timedelta(days=3)),
    )
    original_claim = store.claim_entra_secret_reminder
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("simulated crash before reminder claim")
        return original_claim(*args, **kwargs)

    monkeypatch.setattr(store, "claim_entra_secret_reminder", fail_once)

    assert module.process_due_entra_secret_reminders(now=NOW) == 0
    assert module.process_due_entra_secret_reminders(now=NOW) == 1
    assert module.process_due_entra_secret_reminders(now=NOW) == 0
    assert len(store.query_operational_events(limit=10)["items"]) == 1
    assert len(store.pending_notification_intents(limit=10)) == 1


def test_multiple_due_thresholds_emit_only_the_nearest_unsent_one(monitor, monkeypatch):
    module, _store = monitor
    events = []
    monkeypatch.setattr(module, "emit_event", lambda **event: events.append(event))
    monkeypatch.setattr(
        module, "fetch_entra_secret_expiry", lambda settings, now: _graph_result(expires_at=NOW + timedelta(days=2))
    )

    assert module.process_due_entra_secret_reminders(now=NOW) == 1
    assert module.process_due_entra_secret_reminders(now=NOW) == 0
    assert [event["details"]["threshold_days"] for event in events] == [2]


def test_duplicate_reminder_claim_is_atomic_and_prevents_second_event(monitor, monkeypatch):
    module, _store = monitor
    events = []
    monkeypatch.setattr(module, "emit_event", lambda **event: events.append(event))
    monkeypatch.setattr(
        module, "fetch_entra_secret_expiry", lambda settings, now: _graph_result(expires_at=NOW + timedelta(days=1))
    )

    assert module.process_due_entra_secret_reminders(now=NOW) == 1
    assert module.process_due_entra_secret_reminders(now=NOW) == 0
    assert len(events) == 1


def test_changed_graph_credential_key_id_with_same_expiry_can_send_new_reminder(
    monitor, monkeypatch
):
    module, _store = monitor
    events = []
    current_key = "key-one"
    monkeypatch.setattr(module, "emit_event", lambda **event: events.append(event))
    monkeypatch.setattr(
        module,
        "fetch_entra_secret_expiry",
        lambda settings, now: _graph_result(
            expires_at=NOW + timedelta(days=3), key_id=current_key
        ),
    )

    assert module.process_due_entra_secret_reminders(now=NOW) == 1
    current_key = "key-two"
    module.refresh_entra_secret_status(force=True, now=NOW + timedelta(minutes=1))

    assert module.process_due_entra_secret_reminders(now=NOW + timedelta(minutes=1)) == 1
    assert len(events) == 2


def test_real_reader_expired_credential_reaches_expired_monitor_event(monitor, monkeypatch):
    import picsyncra.entra_secret_expiry as expiry

    module, _store = monitor
    events = []

    class MsalApplication:
        def __init__(self, *_args, **_kwargs):
            pass

        def acquire_token_for_client(self, _scopes):
            return {"access_token": "safe-access-token"}

    class Msal:
        ConfidentialClientApplication = MsalApplication

    class Response:
        def read(self):
            return b'{"appId":"client-id","passwordCredentials":[{"hint":"sup","displayName":"Expired","keyId":"expired-key","endDateTime":"2026-07-19T10:00:00Z"}]}'

        def close(self):
            pass

    monkeypatch.setattr(expiry, "msal", Msal)
    monkeypatch.setattr(
        module,
        "fetch_entra_secret_expiry",
        lambda settings, now: expiry.fetch_entra_secret_expiry(
            settings, now=now, opener=lambda _request, timeout: Response()
        ),
    )
    monkeypatch.setattr(module, "emit_event", lambda **event: events.append(event))

    assert module.process_due_entra_secret_reminders(now=NOW) == 1
    assert events[0]["event_type"] == "entra.secret_expired"


def test_expired_secret_emits_a_separately_deduplicated_critical_event(monitor, monkeypatch):
    module, _store = monitor
    events = []
    monkeypatch.setattr(module, "emit_event", lambda **event: events.append(event))
    monkeypatch.setattr(
        module, "fetch_entra_secret_expiry", lambda settings, now: _graph_result(expires_at=NOW - timedelta(seconds=1))
    )

    assert module.process_due_entra_secret_reminders(now=NOW) == 1
    assert module.process_due_entra_secret_reminders(now=NOW) == 0
    assert events[0]["severity"] == "critical"
    assert events[0]["event_type"] == "entra.secret_expired"


def test_critical_event_details_never_contain_secret_or_token(monitor, monkeypatch):
    module, _store = monitor
    events = []
    monkeypatch.setattr(module, "emit_event", lambda **event: events.append(event))
    monkeypatch.setattr(
        module, "fetch_entra_secret_expiry", lambda settings, now: _graph_result(expires_at=NOW + timedelta(days=3))
    )

    module.process_due_entra_secret_reminders(now=NOW)

    event = events[0]
    assert event["username"] == ""
    assert SECRET not in json.dumps(event)
    assert TOKEN not in json.dumps(event)
