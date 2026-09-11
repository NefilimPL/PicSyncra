from __future__ import annotations

from datetime import datetime, timezone

import pytest

from picsyncra import observability
from picsyncra.sqlite_store import SqliteStore


UTC = timezone.utc


class FakeStore:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.jobs: list[dict[str, object]] = []
        self.incidents: dict[str, dict[str, object]] = {}
        self.prune_boundaries: list[str] = []
        self.context_response: dict[str, object] | None = None
        self.context_requests: list[tuple[str, dict[str, object]]] = []

    def append_operational_event(
        self, event: dict[str, object]
    ) -> dict[str, object]:
        stored = dict(event)
        self.events.append(stored)
        return stored

    def upsert_job_run(self, job: dict[str, object]) -> dict[str, object]:
        stored = dict(job)
        self.jobs.append(stored)
        return stored

    def find_open_incident(self, fingerprint: str) -> dict[str, object] | None:
        incident = self.incidents.get(fingerprint)
        return dict(incident) if incident else None

    def upsert_incident(self, incident: dict[str, object]) -> dict[str, object]:
        stored = dict(incident)
        self.incidents[str(stored["fingerprint"])] = stored
        return dict(stored)

    def query_operational_events(self, **filters: object) -> dict[str, object]:
        events = list(reversed(self.events))
        job_id = str(filters.get("job_id") or "")
        correlation_id = str(filters.get("correlation_id") or "")
        if job_id:
            events = [item for item in events if item.get("job_id") == job_id]
        if correlation_id:
            events = [
                item
                for item in events
                if item.get("correlation_id") == correlation_id
            ]
        return {"items": events, "next_cursor": ""}

    def query_incident_context(
        self, incident_id: str, **options: object
    ) -> dict[str, object] | None:
        self.context_requests.append((incident_id, dict(options)))
        return self.context_response

    def prune_info_events(self, before: str) -> int:
        self.prune_boundaries.append(before)
        return 3


def _event(identity: str, **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "id": identity,
        "created_at": "2026-07-16T10:00:00.000Z",
        "severity": "error",
        "event_type": "pimcore.update_failed",
        "module": "pimcore",
        "stage": "update",
        "username": "alice",
        "ean": "5900000000001",
        "product_id": "PRD-1",
        "slot": "A",
        "job_id": "job-1",
        "correlation_id": "corr-1",
        "incident_id": "",
        "summary": "Failure",
        "recommended_action": "Retry",
        "details": {},
        "exception_type": "RuntimeError",
        "traceback_text": "",
    }
    event.update(overrides)
    return event


def test_redact_value_handles_nested_secrets_and_caps_scalar_strings() -> None:
    value = {
        "Password": "secret",
        "nested": [
            {"api-key": "abc", "safe": "x" * 9000},
            ("plain", {"Authorization": "Bearer token"}),
        ],
        "cookieJar": "session",
    }

    redacted = observability.redact_value(value)

    assert redacted == {
        "Password": "[REDACTED]",
        "nested": [
            {"api-key": "[REDACTED]", "safe": "x" * 8192},
            ["plain", {"Authorization": "[REDACTED]"}],
        ],
        "cookieJar": "[REDACTED]",
    }
    assert len(str(observability.redact_value("ą" * 8192)).encode("utf-8")) <= 8192


def test_emit_event_normalizes_and_redacts_before_storage(monkeypatch) -> None:
    fake = FakeStore()
    monkeypatch.setattr(observability, "observability_store", lambda: fake)

    event = observability.emit_event(
        severity=" ERROR ",
        event_type=" pimcore.update_failed ",
        summary=" Failure ",
        details={
            "client_secret": "secret",
            "nested": {"token": "abc", "safe": 2},
        },
    )

    assert event["severity"] == "error"
    assert event["event_type"] == "pimcore.update_failed"
    assert event["summary"] == "Failure"
    assert event["details"] == {
        "client_secret": "[REDACTED]",
        "nested": {"token": "[REDACTED]", "safe": 2},
    }
    assert str(event["id"]).startswith("evt-")
    assert str(event["created_at"]).endswith("Z")
    assert fake.events[0] == event


def test_info_events_are_persisted_without_an_immediate_mail_intent(monkeypatch) -> None:
    class InfoStore(FakeStore):
        supports_notification_outbox = True

        def __init__(self) -> None:
            super().__init__()
            self.intent_flags: list[bool] = []

        def append_operational_event(
            self, event: dict[str, object], *, create_notification_intent: bool = False
        ) -> dict[str, object]:
            self.intent_flags.append(create_notification_intent)
            return super().append_operational_event(event)

    store = InfoStore()
    monkeypatch.setattr(observability, "observability_store", lambda: store)

    observability.emit_event(
        severity="info", event_type="pimcore.updated", summary="Updated"
    )

    assert len(store.events) == 1
    assert store.intent_flags == [False]


def test_emit_event_rejects_unknown_severity(monkeypatch) -> None:
    fake = FakeStore()
    monkeypatch.setattr(observability, "observability_store", lambda: fake)

    with pytest.raises(ValueError, match="severity"):
        observability.emit_event(
            severity="debug", event_type="job.debug", summary="Debug"
        )

    assert fake.events == []


def test_emit_event_captures_exception_with_bounded_traceback(monkeypatch) -> None:
    fake = FakeStore()
    monkeypatch.setattr(observability, "observability_store", lambda: fake)
    try:
        raise RuntimeError("ą" * 40_000)
    except RuntimeError as exc:
        event = observability.emit_event(
            severity="critical",
            event_type="backend.unhandled",
            summary="Unhandled",
            exception=exc,
        )

    assert event["exception_type"] == "RuntimeError"
    assert len(str(event["traceback_text"]).encode("utf-8")) <= 32 * 1024


def test_emit_event_coalesces_and_queues_due_incident_best_effort(monkeypatch) -> None:
    fake = FakeStore()
    queued: list[tuple[dict[str, object], dict[str, object]]] = []
    monkeypatch.setattr(observability, "observability_store", lambda: fake)
    monkeypatch.setattr(
        "picsyncra.notification_service.queue_incident_notification",
        lambda event, incident: (
            queued.append((dict(event), dict(incident))) or {"status": "pending"}
        ),
    )

    event = observability.emit_event(
        severity="error",
        event_type="ftp.upload_failed",
        summary="FTP failed",
        username="alice",
    )

    assert event["incident_id"].startswith("inc-")
    assert len(queued) == 1
    assert queued[0][0]["id"] == event["id"]
    assert queued[0][1]["notification_due"] is True


def test_non_info_event_enters_stream_once_with_incident_id(
    monkeypatch, tmp_path
) -> None:
    class PublishingStore(SqliteStore):
        def __init__(self, path: str) -> None:
            super().__init__(path)
            self.published: list[dict[str, object]] = []

        def _insert_operational_event(self, conn, payload):
            self.published.append(dict(payload))
            return super()._insert_operational_event(conn, payload)

    store = PublishingStore(str(tmp_path / "events.sqlite"))
    monkeypatch.setattr(observability, "observability_store", lambda: store)
    monkeypatch.setattr(
        "picsyncra.notification_service.queue_incident_notification",
        lambda *_args: {"status": "pending"},
    )

    event = observability.emit_event(
        severity="error",
        event_type="ftp.upload_failed",
        summary="FTP failed",
    )
    stream = store.start_operational_event_stream(initial_limit=20)

    assert len(stream["items"]) == 1
    assert len(store.published) == 1
    assert store.published[0]["incident_id"] == event["incident_id"]
    assert stream["items"][0]["id"] == event["id"]
    assert stream["items"][0]["incident_id"] == event["incident_id"]
    assert event["incident_id"].startswith("inc-")


def test_durable_outbox_keeps_notification_window_claim_after_event_commit(
    monkeypatch, tmp_path
) -> None:
    store = SqliteStore(str(tmp_path / "events.sqlite"))
    monkeypatch.setattr(observability, "observability_store", lambda: store)
    queued: list[dict[str, object]] = []

    def forbidden_post_commit_queue(event, incident):
        queued.append(dict(incident))
        raise AssertionError("production outbox must not queue after commit")

    monkeypatch.setattr(
        "picsyncra.notification_service.queue_incident_notification",
        forbidden_post_commit_queue,
    )
    first_now = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
    second_now = datetime(2026, 7, 17, 10, 1, tzinfo=UTC)
    monkeypatch.setattr(observability, "_utc_datetime", lambda _now=None: first_now)

    first = observability.emit_event(
        severity="error", event_type="ftp.failed", summary="FTP failed"
    )
    first_incident = next(
        item
        for item in store.query_incidents(limit=20)["items"]
        if item["id"] == first["incident_id"]
    )

    assert first_incident["id"] == first["incident_id"]
    assert (
        first_incident["notification_window_at"]
        == "2026-07-17T10:00:00.000Z"
    )
    assert [item["event_id"] for item in store.pending_notification_intents(10)] == [
        first["id"]
    ]

    monkeypatch.setattr(observability, "_utc_datetime", lambda _now=None: second_now)
    second = observability.emit_event(
        severity="error", event_type="ftp.failed", summary="FTP failed"
    )

    assert second["incident_id"] == first["incident_id"]
    assert queued == []
    assert len(store.pending_notification_intents(10)) == 1


def test_emit_event_suppress_notifications_prevents_recursive_queue(monkeypatch) -> None:
    fake = FakeStore()
    queued: list[object] = []
    monkeypatch.setattr(observability, "observability_store", lambda: fake)
    monkeypatch.setattr(
        "picsyncra.notification_service.queue_incident_notification",
        lambda *_args: queued.append(object()),
    )

    event = observability.emit_event(
        severity="error",
        event_type="notification.failed",
        summary="Delivery failed",
        details={"suppress_notifications": True},
    )

    assert event["incident_id"].startswith("inc-")
    assert queued == []


def test_incidents_have_stable_fingerprints_and_fifteen_minute_windows(
    monkeypatch,
) -> None:
    fake = FakeStore()
    monkeypatch.setattr(observability, "observability_store", lambda: fake)
    times = [
        datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
        datetime(2026, 7, 16, 10, 14, tzinfo=UTC),
        datetime(2026, 7, 16, 10, 16, tzinfo=UTC),
    ]

    first = observability.coalesce_incident(
        _event("evt-1", summary="First message", created_at="earlier"), times[0]
    )
    second = observability.coalesce_incident(
        _event("evt-2", summary="Different message", created_at="later"), times[1]
    )
    third = observability.coalesce_incident(
        _event("evt-3", summary="Third message"), times[2]
    )

    assert first is not None and second is not None and third is not None
    assert first["fingerprint"] == second["fingerprint"] == third["fingerprint"]
    assert first["id"] == second["id"] == third["id"]
    assert first["notification_due"] is True
    assert second["notification_due"] is False
    assert third["notification_due"] is True
    assert [
        first["occurrence_count"],
        second["occurrence_count"],
        third["occurrence_count"],
    ] == [1, 2, 3]
    assert second["notification_window_at"] == "2026-07-16T10:00:00.000Z"
    assert third["notification_window_at"] == "2026-07-16T10:16:00.000Z"
    assert fake.events[-1]["incident_id"] == first["id"]
    assert "notification_due" not in fake.events[-1]


def test_fingerprint_changes_with_stable_context(monkeypatch) -> None:
    fake = FakeStore()
    monkeypatch.setattr(observability, "observability_store", lambda: fake)
    now = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)

    first = observability.coalesce_incident(_event("evt-1", slot=" A "), now)
    same = observability.coalesce_incident(_event("evt-2", slot="A"), now)
    different = observability.coalesce_incident(_event("evt-3", slot="B"), now)

    assert first is not None and same is not None and different is not None
    assert first["fingerprint"] == same["fingerprint"]
    assert first["fingerprint"] != different["fingerprint"]


def test_info_events_never_create_incidents(monkeypatch) -> None:
    fake = FakeStore()
    monkeypatch.setattr(observability, "observability_store", lambda: fake)

    incident = observability.coalesce_incident(
        _event("evt-info", severity="info"),
        datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
    )

    assert incident is None
    assert fake.incidents == {}
    assert fake.events == []


def test_coalesce_incident_redacts_the_event_rewrite(monkeypatch) -> None:
    fake = FakeStore()
    monkeypatch.setattr(observability, "observability_store", lambda: fake)
    event = _event(
        "evt-secret",
        details={"password": "secret", "nested": {"token": "abc"}},
    )

    observability.coalesce_incident(
        event, datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
    )

    assert fake.events[0]["details"] == {
        "password": "[REDACTED]",
        "nested": {"token": "[REDACTED]"},
    }


def test_incident_scope_follows_the_latest_correlation(monkeypatch) -> None:
    fake = FakeStore()
    monkeypatch.setattr(observability, "observability_store", lambda: fake)
    first = observability.coalesce_incident(
        _event("evt-corr-1", job_id="", correlation_id="corr-1"),
        datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
    )
    second = observability.coalesce_incident(
        _event(
            "evt-corr-2",
            created_at="2026-07-16T10:01:00.000Z",
            job_id="",
            correlation_id="corr-2",
        ),
        datetime(2026, 7, 16, 10, 1, tzinfo=UTC),
    )

    assert first is not None and second is not None
    assert second["id"] == first["id"]
    assert second["correlation_id"] == "corr-2"
    fake.context_response = {
        "before": [],
        "problem": [_event("evt-corr-2", job_id="", correlation_id="corr-2")],
        "after": [],
        "problem_next_cursor": "",
    }
    context = observability.incident_context(second)
    assert [item["id"] for item in context["problem"]] == ["evt-corr-2"]
    assert all(
        item["correlation_id"] == "corr-2"
        for section in (context["before"], context["problem"], context["after"])
        for item in section
    )


def test_incident_context_uses_correlation_and_excludes_nearby_events(
    monkeypatch,
) -> None:
    fake = FakeStore()
    fake.events = [
        _event("evt-before", created_at="2026-07-16T09:59:00.000Z", job_id=""),
        _event(
            "evt-unrelated",
            created_at="2026-07-16T09:59:30.000Z",
            job_id="",
            correlation_id="other",
        ),
        _event("evt-first", created_at="2026-07-16T10:00:00.000Z", job_id=""),
        _event("evt-latest", created_at="2026-07-16T10:01:00.000Z", job_id=""),
        _event("evt-after", created_at="2026-07-16T10:02:00.000Z", job_id=""),
    ]
    monkeypatch.setattr(observability, "observability_store", lambda: fake)
    fake.context_response = {
        "before": [fake.events[0]],
        "problem": [fake.events[2], fake.events[3]],
        "after": [fake.events[4]],
        "problem_next_cursor": "",
    }

    context = observability.incident_context(
        {
            "id": "inc-correlation",
            "correlation_id": "corr-1",
            "first_event_id": "evt-first",
            "latest_event_id": "evt-latest",
        }
    )

    assert [item["id"] for item in context["before"]] == ["evt-before"]
    assert [item["id"] for item in context["problem"]] == [
        "evt-first",
        "evt-latest",
    ]
    assert [item["id"] for item in context["after"]] == ["evt-after"]


def test_incident_context_prefers_job_scope_and_honors_limits(monkeypatch) -> None:
    fake = FakeStore()
    fake.events = [
        _event(f"evt-{index}", created_at=f"2026-07-16T10:0{index}:00.000Z")
        for index in range(7)
    ]
    monkeypatch.setattr(observability, "observability_store", lambda: fake)
    fake.context_response = {
        "before": [fake.events[1]],
        "problem": [fake.events[2], fake.events[3]],
        "after": [fake.events[4], fake.events[5]],
        "problem_next_cursor": "",
    }

    context = observability.incident_context(
        {
            "id": "inc-job",
            "job_id": "job-1",
            "correlation_id": "other",
            "first_event_id": "evt-2",
            "latest_event_id": "evt-3",
        },
        before_limit=1,
        after_limit=2,
    )

    assert [item["id"] for item in context["before"]] == ["evt-1"]
    assert [item["id"] for item in context["problem"]] == ["evt-2", "evt-3"]
    assert [item["id"] for item in context["after"]] == ["evt-4", "evt-5"]


def test_incident_context_delegates_once_without_operational_event_page_scan(
    monkeypatch,
) -> None:
    class PagedStore(FakeStore):
        def __init__(self) -> None:
            super().__init__()
            self.requested_limits: list[int] = []

        def query_operational_events(self, **filters: object) -> dict[str, object]:
            limit = int(filters.get("limit") or 0)
            self.requested_limits.append(limit)
            correlation_id = str(filters.get("correlation_id") or "")
            events = list(reversed(self.events))
            if correlation_id:
                events = [
                    item
                    for item in events
                    if item.get("correlation_id") == correlation_id
                ]
            start = int(str(filters.get("cursor") or "0"))
            end = start + limit
            return {
                "items": events[start:end],
                "next_cursor": str(end) if end < len(events) else "",
            }

    fake = PagedStore()
    fake.events = [
        _event(
            f"target-{index:02d}",
            created_at=f"2026-07-16T10:{index:02d}:00.000Z",
            job_id="",
            correlation_id="target",
        )
        for index in range(25)
    ] + [
        _event(
            f"other-{index:02d}",
            created_at=f"2026-07-16T11:{index:02d}:00.000Z",
            job_id="",
            correlation_id="other",
        )
        for index in range(10)
    ]
    monkeypatch.setattr(observability, "observability_store", lambda: fake)
    fake.context_response = {
        "before": [],
        "problem": fake.events[2:5],
        "after": [],
        "problem_next_cursor": "next-problem-page",
    }

    context = observability.incident_context(
        {
            "id": "inc-target",
            "correlation_id": "target",
            "first_event_id": "target-02",
            "latest_event_id": "target-04",
        }
    )

    assert fake.requested_limits == []
    assert fake.context_requests == [
        ("inc-target", {"before_limit": 5, "after_limit": 5})
    ]
    assert [item["id"] for item in context["problem"]] == [
        "target-02",
        "target-03",
        "target-04",
    ]
    assert all(
        item["correlation_id"] == "target"
        for section in (context["before"], context["problem"], context["after"])
        for item in section
    )


def test_incident_context_clamps_public_limits_to_five(monkeypatch) -> None:
    fake = FakeStore()
    fake.events = [
        _event(f"evt-{index:02d}", created_at=f"2026-07-16T10:{index:02d}:00.000Z")
        for index in range(14)
    ]
    monkeypatch.setattr(observability, "observability_store", lambda: fake)
    fake.context_response = {
        "before": fake.events[1:6],
        "problem": fake.events[6:8],
        "after": fake.events[8:13],
        "problem_next_cursor": "",
    }

    context = observability.incident_context(
        {
            "id": "inc-limits",
            "job_id": "job-1",
            "first_event_id": "evt-06",
            "latest_event_id": "evt-07",
        },
        before_limit=999,
        after_limit=999,
    )

    assert [item["id"] for item in context["before"]] == [
        "evt-01",
        "evt-02",
        "evt-03",
        "evt-04",
        "evt-05",
    ]
    assert [item["id"] for item in context["after"]] == [
        "evt-08",
        "evt-09",
        "evt-10",
        "evt-11",
        "evt-12",
    ]
    assert fake.context_requests == [
        ("inc-limits", {"before_limit": 5, "after_limit": 5})
    ]


def test_record_job_redacts_all_nested_data(monkeypatch) -> None:
    fake = FakeStore()
    monkeypatch.setattr(observability, "observability_store", lambda: fake)

    stored = observability.record_job(
        {
            "id": "job-1",
            "status": "failed",
            "stages": [{"name": "ftp", "password": "secret"}],
            "details": {"nested": {"access_token": "abc"}},
        }
    )

    assert stored["stages"] == [
        {"name": "ftp", "password": "[REDACTED]"}
    ]
    assert stored["details"] == {"nested": {"access_token": "[REDACTED]"}}
    assert fake.jobs[0] == stored


def test_observability_store_uses_registry_for_each_resolved_database(
    monkeypatch,
) -> None:
    paths = iter(["first.sqlite", "second.sqlite"])
    registered: list[str] = []

    class Store:
        def __init__(self, path: str) -> None:
            self.path = path

    def registered_store(path: str) -> Store:
        registered.append(path)
        return Store(path)

    monkeypatch.setattr(
        observability.storage_settings,
        "resolve_sqlite_path",
        lambda: next(paths),
    )
    monkeypatch.setattr(observability, "get_sqlite_store", registered_store)

    first = observability.observability_store()
    second = observability.observability_store()

    assert (first.path, second.path) == ("first.sqlite", "second.sqlite")
    assert registered == ["first.sqlite", "second.sqlite"]


def test_emit_event_mirrors_persistence_failure_and_is_strict_only_on_request(
    monkeypatch,
) -> None:
    class FailingStore:
        def append_operational_event(self, event: dict[str, object]) -> None:
            raise OSError("database unavailable")

        def coalesce_incident(self, occurrence: dict[str, object]) -> None:
            raise OSError("database unavailable")

    mirrored: list[dict[str, object]] = []
    monkeypatch.setattr(observability, "observability_store", FailingStore)
    observability.register_event_mirror(lambda event: mirrored.append(dict(event)))
    try:
        event = observability.emit_event(
            severity="error",
            event_type="ftp.failed",
            summary="Failure",
            details={"password": "secret"},
        )
        with pytest.raises(OSError, match="database unavailable"):
            observability.emit_event(
                severity="error",
                event_type="ftp.failed",
                summary="Failure",
                strict=True,
            )
    finally:
        observability.register_event_mirror(None)

    assert event["details"] == {"password": "[REDACTED]"}
    assert mirrored[0] == event
    assert len(mirrored) == 2


def test_failing_mirror_does_not_recurse_or_replace_storage_failure(
    monkeypatch,
) -> None:
    class FailingStore:
        def append_operational_event(self, event: dict[str, object]) -> None:
            raise OSError("database unavailable")

        def coalesce_incident(self, occurrence: dict[str, object]) -> None:
            raise OSError("database unavailable")

    calls = 0

    def failing_mirror(event: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("mirror unavailable")

    monkeypatch.setattr(observability, "observability_store", FailingStore)
    observability.register_event_mirror(failing_mirror)
    try:
        with pytest.raises(OSError, match="database unavailable"):
            observability.emit_event(
                severity="critical",
                event_type="backend.unhandled",
                summary="Failure",
                strict=True,
            )
    finally:
        observability.register_event_mirror(None)

    assert calls == 1


def test_prune_live_events_uses_utc_twenty_four_hour_boundary(monkeypatch) -> None:
    fake = FakeStore()
    monkeypatch.setattr(observability, "observability_store", lambda: fake)

    removed = observability.prune_live_events(
        datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
    )

    assert removed == 3
    assert fake.prune_boundaries == ["2026-07-15T10:00:00.000Z"]
