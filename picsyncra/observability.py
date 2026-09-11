"""Structured operational events, redaction, and incident correlation."""

from __future__ import annotations

import hashlib
import json
import traceback
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from . import storage_settings
from .data_store import get_sqlite_store
from .redaction import (
    SECRET_KEY_RE,
    redact_sensitive_value,
    sanitize_free_text,
)
from .sqlite_store import SqliteStore


SEVERITIES = ("info", "warning", "error", "critical")
SCALAR_TEXT_LIMIT = 8 * 1024
TRACEBACK_TEXT_LIMIT = 32 * 1024
INCIDENT_NOTIFICATION_WINDOW = timedelta(minutes=15)
LIVE_EVENT_RETENTION = timedelta(hours=24)

EventMirror = Callable[[dict[str, object]], object]
_event_mirror: EventMirror | None = None


def _text(value: object) -> str:
    return sanitize_free_text(value, limit=SCALAR_TEXT_LIMIT).strip()


def _utc_datetime(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _iso_utc(value: datetime | None = None) -> str:
    return _utc_datetime(value).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _utc_datetime(value)
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc_datetime(parsed)


def redact_value(value: object, key: str = "") -> object:
    """Recursively redact secret-bearing keys and bound scalar strings."""

    return redact_sensitive_value(value, key, text_limit=SCALAR_TEXT_LIMIT)


def register_event_mirror(callback: EventMirror | None) -> None:
    """Register the single best-effort fallback mirror for structured events."""

    global _event_mirror
    _event_mirror = callback


def _mirror_event(event: dict[str, object]) -> None:
    callback = _event_mirror
    if callback is None:
        return
    try:
        safe_event = redact_value(event)
        callback(dict(safe_event) if isinstance(safe_event, dict) else {})
    except Exception:
        # The mirror is a last-resort sink and must never recurse or mask SQLite.
        pass


def observability_store() -> SqliteStore:
    """Resolve and initialize the configured observability database."""

    return get_sqlite_store(storage_settings.resolve_sqlite_path())


def emit_event(
    *,
    severity: str,
    event_type: str,
    summary: str,
    module: str = "",
    stage: str = "",
    username: str = "",
    ean: str = "",
    product_id: str = "",
    slot: str = "",
    job_id: str = "",
    correlation_id: str = "",
    recommended_action: str = "",
    details: object = None,
    exception: BaseException | None = None,
    strict: bool = False,
    event_id: str = "",
    created_at: datetime | str | None = None,
) -> dict[str, object]:
    """Normalize, redact, and persist one operational event."""

    normalized_severity = _text(severity).lower()
    if normalized_severity not in SEVERITIES:
        raise ValueError(f"Unsupported event severity: {severity!r}")

    exception_type = ""
    traceback_text = ""
    if exception is not None:
        exception_type = _text(type(exception).__name__)
        traceback_text = sanitize_free_text(
            "".join(
                traceback.format_exception(
                    type(exception), exception, exception.__traceback__
                )
            ),
            limit=TRACEBACK_TEXT_LIMIT,
        )

    safe_details = redact_value(details if isinstance(details, dict) else {})
    event: dict[str, object] = {
        "id": _text(event_id) or f"evt-{uuid.uuid4().hex}",
        "created_at": _iso_utc(_parse_datetime(created_at)),
        "severity": normalized_severity,
        "event_type": _text(event_type),
        "module": _text(module),
        "stage": _text(stage),
        "username": _text(username),
        "ean": _text(ean),
        "product_id": _text(product_id),
        "slot": _text(slot),
        "job_id": _text(job_id),
        "correlation_id": _text(correlation_id),
        "incident_id": "",
        "summary": _text(summary),
        "recommended_action": _text(recommended_action),
        "details": safe_details,
        "exception_type": exception_type,
        "traceback_text": traceback_text,
    }
    if normalized_severity == "info":
        try:
            store = observability_store()
            if bool(getattr(store, "supports_notification_outbox", False)):
                return store.append_operational_event(
                    event, create_notification_intent=False
                )
            return store.append_operational_event(event)
        except Exception:
            _mirror_event(event)
            if strict:
                raise
            return event
    try:
        incident = coalesce_incident(event)
    except Exception:
        _mirror_event(event)
        if strict:
            raise
        return event
    if incident is None:
        return event
    safe_details = event.get("details")
    suppress = isinstance(safe_details, dict) and bool(
        safe_details.get("suppress_notifications")
    )
    if suppress or not bool(incident.get("notification_due")):
        return event
    if bool(incident.get("notification_intent_persisted")):
        return event
    try:
        from .notification_service import queue_incident_notification

        delivery = queue_incident_notification(event, incident)
        if delivery is None:
            raise RuntimeError("notification queue did not persist a delivery")
    except Exception:
        _release_notification_claim(incident)
        _emit_queue_failure_diagnostic(event, incident)
    return event


def _release_notification_claim(incident: dict[str, object]) -> None:
    claimed_at = _text(incident.get("notification_claim_at"))
    if not claimed_at:
        return
    try:
        store = observability_store()
        release = getattr(store, "release_incident_notification", None)
        if callable(release):
            release(
                _text(incident.get("id")),
                claimed_at=claimed_at,
                previous_at=_text(
                    incident.get("notification_previous_window_at")
                ),
            )
    except Exception:
        pass


def _emit_queue_failure_diagnostic(
    event: dict[str, object], incident: dict[str, object]
) -> None:
    try:
        emit_event(
            severity="error",
            event_type="notification.queue_failed",
            module="notifications",
            stage="queue",
            job_id=_text(event.get("job_id")),
            correlation_id=_text(event.get("correlation_id")),
            summary="Nie udało się trwale zapisać powiadomienia e-mail.",
            recommended_action="Sprawdź stan SQLite i konfigurację powiadomień.",
            details={
                "code": "notification_queue_unavailable",
                "incident_id": _text(incident.get("id")),
                "event_id": _text(event.get("id")),
                "suppress_notifications": True,
            },
        )
    except Exception:
        pass


def record_job(job: dict[str, object]) -> dict[str, object]:
    """Redact and persist one durable process-job snapshot."""

    safe_job = redact_value(job)
    if not isinstance(safe_job, dict):
        safe_job = {}
    return observability_store().upsert_job_run(safe_job)


def _fingerprint_value(value: object) -> str:
    return _text(value).casefold()


def _incident_fingerprint(event: dict[str, object]) -> str:
    stable = {
        "event_type": _fingerprint_value(event.get("event_type")),
        "module": _fingerprint_value(event.get("module")),
        "stage": _fingerprint_value(event.get("stage")),
        "exception_type": _fingerprint_value(event.get("exception_type")),
        "ean": _fingerprint_value(event.get("ean")),
        "slot": _fingerprint_value(event.get("slot")),
    }
    encoded = json.dumps(
        stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _incident_context_payload(event: dict[str, object]) -> dict[str, object]:
    context: dict[str, object] = {}
    for key in (
        "module",
        "stage",
        "username",
        "ean",
        "product_id",
        "slot",
        "summary",
        "recommended_action",
    ):
        value = _text(event.get(key))
        if value:
            context[key] = value
    details = redact_value(event.get("details"))
    if isinstance(details, dict) and details:
        context["details"] = details
    return context


def _higher_severity(first: object, second: object) -> str:
    left = _text(first).lower()
    right = _text(second).lower()
    left_rank = SEVERITIES.index(left) if left in SEVERITIES else -1
    right_rank = SEVERITIES.index(right) if right in SEVERITIES else -1
    return left if left_rank >= right_rank else right


def coalesce_incident(
    event: dict[str, object], now: datetime | None = None
) -> dict[str, object] | None:
    """Create or update the open incident matching a stable event fingerprint."""

    severity = _text(event.get("severity")).lower()
    if severity == "info":
        return None

    current = _utc_datetime(now)
    current_iso = _iso_utc(current)
    fingerprint = _incident_fingerprint(event)
    store = observability_store()
    latest_context = _incident_context_payload(event)
    atomic_coalesce = getattr(store, "coalesce_incident", None)
    occurrence = {
        "id": f"inc-{uuid.uuid4().hex}",
        "fingerprint": fingerprint,
        "severity": severity,
        "event_type": _text(event.get("event_type")),
        "status": "open",
        "first_seen_at": current_iso,
        "last_seen_at": current_iso,
        "occurrence_count": 1,
        "first_event_id": _text(event.get("id")),
        "latest_event_id": _text(event.get("id")),
        "job_id": _text(event.get("job_id")),
        "correlation_id": _text(event.get("correlation_id")),
        "notification_window_at": current_iso,
        "context": latest_context,
    }
    atomic_incident_event = bool(
        getattr(store, "supports_atomic_incident_event", False)
    )
    supports_outbox = bool(
        getattr(store, "supports_notification_outbox", False)
    )
    event_details = event.get("details")
    suppress_notifications = isinstance(event_details, dict) and bool(
        event_details.get("suppress_notifications")
    )
    if callable(atomic_coalesce):
        if atomic_incident_event:
            source_event = redact_value(event)
            if not isinstance(source_event, dict):
                source_event = {}
            kwargs: dict[str, object] = {"source_event": source_event}
            if supports_outbox:
                kwargs["create_notification_intent"] = not suppress_notifications
            incident_result = dict(atomic_coalesce(occurrence, **kwargs))
        else:
            incident_result = dict(atomic_coalesce(occurrence))
        notification_due = bool(incident_result.get("notification_due"))
    else:
        incident_result, notification_due = _coalesce_with_legacy_store(
            store,
            event,
            fingerprint=fingerprint,
            severity=severity,
            current=current,
            current_iso=current_iso,
            latest_context=latest_context,
        )

    incident_result["notification_due"] = notification_due
    incident_result["notification_intent_persisted"] = bool(
        supports_outbox and notification_due and not suppress_notifications
    )

    event["incident_id"] = _text(incident_result.get("id"))
    persisted_event = redact_value(event)
    if not isinstance(persisted_event, dict):
        persisted_event = {}
    persisted_event.pop("notification_due", None)
    if not atomic_incident_event:
        # Test/lightweight stores have no shared transaction capability.
        # Production observability_store() always returns atomic SqliteStore.
        store.append_operational_event(persisted_event)
    return incident_result


def _coalesce_with_legacy_store(
    store: object,
    event: dict[str, object],
    *,
    fingerprint: str,
    severity: str,
    current: datetime,
    current_iso: str,
    latest_context: dict[str, object],
) -> tuple[dict[str, object], bool]:
    """Keep lightweight test doubles compatible; SQLite uses its atomic method."""

    existing = store.find_open_incident(fingerprint)
    notification_due = existing is None
    notification_previous_window_at = ""
    notification_claim_at = current_iso if existing is None else ""

    if existing is None:
        incident: dict[str, object] = {
            "id": f"inc-{uuid.uuid4().hex}",
            "fingerprint": fingerprint,
            "severity": severity,
            "event_type": _text(event.get("event_type")),
            "status": "open",
            "first_seen_at": current_iso,
            "last_seen_at": current_iso,
            "occurrence_count": 1,
            "first_event_id": _text(event.get("id")),
            "latest_event_id": _text(event.get("id")),
            "job_id": _text(event.get("job_id")),
            "correlation_id": _text(event.get("correlation_id")),
            "notification_window_at": current_iso,
            "context": latest_context,
        }
    else:
        incident = dict(existing)
        notification_previous_window_at = _text(
            incident.get("notification_window_at")
        )
        previous_context = incident.get("context")
        merged_context = (
            dict(previous_context) if isinstance(previous_context, dict) else {}
        )
        merged_context.update(latest_context)
        try:
            occurrence_count = int(incident.get("occurrence_count") or 0) + 1
        except (TypeError, ValueError):
            occurrence_count = 2
        incident.update(
            {
                "severity": _higher_severity(incident.get("severity"), severity),
                "last_seen_at": current_iso,
                "occurrence_count": occurrence_count,
                "latest_event_id": _text(event.get("id")),
                "context": merged_context,
            }
        )
        latest_job_id = _text(event.get("job_id"))
        latest_correlation_id = _text(event.get("correlation_id"))
        if latest_job_id or latest_correlation_id:
            incident["job_id"] = latest_job_id
            incident["correlation_id"] = latest_correlation_id
        window_started = _parse_datetime(incident.get("notification_window_at"))
        if window_started is None or current - window_started >= INCIDENT_NOTIFICATION_WINDOW:
            notification_due = True
            incident["notification_window_at"] = current_iso
            notification_claim_at = current_iso

    persisted = store.upsert_incident(incident)
    incident_result = dict(persisted)
    incident_result["notification_claim_at"] = notification_claim_at
    incident_result["notification_previous_window_at"] = (
        notification_previous_window_at
    )
    return incident_result, notification_due


def _bounded_context_limit(value: object) -> int:
    try:
        return max(0, min(5, int(value)))
    except (TypeError, ValueError):
        return 5


def incident_context(
    incident: dict[str, object], *, before_limit: int = 5, after_limit: int = 5
) -> dict[str, object]:
    """Delegate bounded incident context retrieval to the indexed repository."""

    empty: dict[str, object] = {
        "before": [],
        "problem": [],
        "after": [],
        "problem_next_cursor": "",
    }
    incident_id = _text(incident.get("id"))
    if not incident_id:
        return empty
    context = observability_store().query_incident_context(
        incident_id,
        before_limit=_bounded_context_limit(before_limit),
        after_limit=_bounded_context_limit(after_limit),
    )
    return context if isinstance(context, dict) else empty


def prune_live_events(now: datetime | None = None) -> int:
    """Remove informational live-console events older than 24 hours."""

    boundary = _utc_datetime(now) - LIVE_EVENT_RETENTION
    return observability_store().prune_info_events(_iso_utc(boundary))
