"""Durable incident e-mail queue, recipient rules, and background worker."""

from __future__ import annotations

import html
import json
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .email_delivery import MailAttachment, MailMessage, MailTransport, build_transport
from .email_settings import (
    EMAIL_SETTINGS_KEY,
    normalize_email_address,
    normalize_email_settings,
)
from .entra_secret_monitor import process_due_entra_secret_reminders
from .notification_scheduler import WakeableDeadlineScheduler
from .redaction import sanitize_free_text


WORKER_MAX_IDLE_SECONDS = 60.0
WORKER_BATCH_LIMIT = 20
WORKER_STOP_TIMEOUT_SECONDS = 23.0
WORKER_PRUNE_INTERVAL = timedelta(seconds=60)
STALE_SENDING_AFTER = timedelta(minutes=5)
OUTBOX_DONE_RETENTION = timedelta(days=7)
DAILY_SUMMARY_TIME_ZONE = ZoneInfo("Europe/Warsaw")
DAILY_SUMMARY_RETRY_DELAY = timedelta(minutes=5)
DAILY_SUMMARY_STALE_CLAIM_AFTER = timedelta(minutes=10)
_EXCEPTION_ATTACHMENT_FILENAME = "picsyncra-exception.txt"
_EXCEPTION_ATTACHMENT_LIMIT = 24 * 1024
_INCIDENT_DETAILS_ATTACHMENT_FILENAME = "picsyncra-incident-details.json"
_EXCEPTION_SECRET_RE = re.compile(
    r"(?i)(?P<prefix>(?<![\w-])[\"']?(?:credential[_ -]*key[_ -]*id|"
    r"client[_ -]*secret|password|token|key[_ -]*id)[\"']?[ \t]*[:=][ \t]*)"
    r"(?:\[REDACTED\]|\"(?:\\[^\r\n]|[^\"\\\r\n])*\"|"
    r"'(?:\\[^\r\n]|[^'\\\r\n])*'|[^\s;,)\]}]+)"
)


_TEST_NOTIFICATION_SCENARIOS: tuple[dict[str, object], ...] = (
    {
        "kind": "pimcore_rejection",
        "severity": "warning",
        "event_type": "pimcore.update_rejected",
        "summary": "PIMcore odrzucił aktualizację produktu",
        "recommended_action": "Sprawdź dane produktu i ponów aktualizację.",
    },
    {
        "kind": "ftp_failure",
        "severity": "error",
        "event_type": "ftp.transfer_failed",
        "summary": "Transfer plików przez FTP nie powiódł się",
        "recommended_action": "Sprawdź połączenie FTP i ponów transfer.",
        "exception_type": "OSError",
        "traceback_text": (
            "Traceback (most recent call last):\n"
            '  File "picsyncra/ftp_transfer.py", line 42, in upload\n'
            "OSError: Symulowany błąd transferu FTP"
        ),
    },
    {
        "kind": "photo_location_unavailable",
        "severity": "error",
        "event_type": "photo.location_unavailable",
        "summary": "Lokalizacja zdjęć jest niedostępna",
        "recommended_action": "Sprawdź dostępność lokalizacji źródłowej zdjęć.",
    },
    {
        "kind": "backend_exception",
        "severity": "critical",
        "event_type": "backend.exception",
        "summary": "Backend zgłosił nieobsłużony wyjątek",
        "recommended_action": "Sprawdź diagnostykę backendu i stan zadania.",
        "exception_type": "RuntimeError",
        "traceback_text": (
            "Traceback (most recent call last):\n"
            '  File "picsyncra/backend.py", line 87, in process_job\n'
            "RuntimeError: Symulowany wyjątek backendu"
        ),
    },
    {
        "kind": "entra_secret_expiry",
        "severity": "critical",
        "event_type": "entra.client_secret_expiry",
        "summary": "Client Secret Microsoft Entra wygaśnie za 7 dni",
        "recommended_action": "Odnów Client Secret Microsoft Entra przed upływem 7 dni.",
    },
)

_TEST_SIMULATION_NOTICE = (
    "[TEST][SYMULACJA] To jest bezpieczna symulacja; "
    "nie utworzono zdarzenia ani incydentu."
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _parse_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text(value: object, limit: int = 2_000) -> str:
    return str(value or "").strip()[:limit]


def _header_text(value: object, limit: int = 300) -> str:
    return " ".join(_text(value, limit).splitlines())[:limit]


def _daily_summary_due_end(now: datetime, schedule: object) -> str:
    """Return the latest configured Warsaw run slot, or an empty value before it."""

    text = _text(schedule, 5)
    if len(text) != 5 or text[2] != ":" or not (text[:2] + text[3:]).isdigit():
        return ""
    hour, minute = int(text[:2]), int(text[3:])
    if hour > 23 or minute > 59:
        return ""
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    local = current.astimezone(DAILY_SUMMARY_TIME_ZONE)
    # A fall-back hour occurs twice; fold=0 makes the daily wall-clock slot
    # stable, so the second occurrence cannot create a duplicate report.
    scheduled = local.replace(
        hour=hour, minute=minute, second=0, microsecond=0, fold=0
    )
    if local < scheduled:
        return ""
    return _iso_utc(scheduled)


def _daily_change_sources(record: Mapping[str, object]) -> list[Mapping[str, object]]:
    details = record.get("details")
    if not isinstance(details, Mapping):
        return []
    change_set = details.get("change_set")
    if not isinstance(change_set, Mapping):
        return []
    sources: list[Mapping[str, object]] = [change_set]
    pimcore = change_set.get("pimcore")
    if isinstance(pimcore, Mapping):
        sources.append(pimcore)
    return sources


def _compact_daily_change_rows(
    history: list[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Project history into user-facing EAN rows without operational evidence."""

    grouped: dict[str, dict[str, object]] = {}
    for record in history:
        ean = _text(record.get("ean"), 128)
        if not ean or ean == "BRAK-EAN":
            continue
        sources = _daily_change_sources(record)
        if not sources:
            continue
        row = grouped.setdefault(
            ean, {"ean": ean, "created": False, "fields": set(), "slots": set()}
        )
        for source in sources:
            created_source = _text(source.get("kind")).lower() == "created"
            if created_source:
                row["created"] = True
            raw_fields = source.get("fields")
            if not created_source and isinstance(raw_fields, list):
                fields = row["fields"]
                if isinstance(fields, set):
                    for item in raw_fields:
                        if isinstance(item, Mapping):
                            label = _text(item.get("label") or item.get("key"), 200)
                            if label:
                                fields.add(label)
            raw_files = source.get("files")
            if isinstance(raw_files, list):
                slots = row["slots"]
                if isinstance(slots, set):
                    for item in raw_files:
                        if isinstance(item, Mapping):
                            slot = _text(item.get("slot") or item.get("prefix"), 40)
                            if slot:
                                slots.add(slot)
    rows: list[dict[str, object]] = []
    for ean in sorted(grouped):
        row = grouped[ean]
        fields = sorted(row["fields"]) if isinstance(row["fields"], set) else []
        slots = sorted(row["slots"]) if isinstance(row["slots"], set) else []
        if bool(row["created"]) or fields or slots:
            rows.append({"ean": ean, "created": bool(row["created"]), "fields": fields, "slots": slots})
    return rows


def _daily_summary_message(
    rows: list[Mapping[str, object]], *, window_start: str, window_end: str
) -> dict[str, str]:
    lines: list[str] = []
    html_items: list[str] = []
    for row in rows:
        parts: list[str] = []
        if bool(row.get("created")):
            parts.append("utworzono nowy wpis")
        fields = row.get("fields")
        if isinstance(fields, list) and fields:
            parts.append("zaktualizowano dane PIMcore: " + ", ".join(_text(value, 200) for value in fields))
        slots = row.get("slots")
        if isinstance(slots, list) and slots:
            parts.append("zaktualizowano zdjęcia: sloty " + ", ".join(_text(value, 40) for value in slots))
        line = f"{_text(row.get('ean'), 128)} — " + "; ".join(parts)
        lines.append("• " + line)
        html_items.append(f"<li>{html.escape(line)}</li>")
    start = _text(window_start, 40)
    end = _text(window_end, 40)
    heading = "Dzienne podsumowanie zmian produktów"
    text_body = f"{heading}\nOkres: {start} — {end}\n\n" + "\n".join(lines)
    return {
        "message_id": f"daily-change-summary-{_text(window_end, 40)}",
        "subject": "[PicSyncra] Dzienne podsumowanie zmian",
        "text_body": text_body,
        "html_body": (
            f"<h2>{html.escape(heading)}</h2><p>Okres: {html.escape(start)} — "
            f"{html.escape(end)}</p><ul>{''.join(html_items)}</ul>"
        ),
    }


def _default_settings_loader() -> dict[str, object]:
    from . import config

    configured = config.load_config(interactive=False)
    return normalize_email_settings(configured.get(EMAIL_SETTINGS_KEY, {}))


def _default_time_zone_loader() -> str:
    from . import config

    configured = config.load_config(interactive=False)
    display = config.normalize_web_display_settings(configured.get("web_display"))
    return str(display.get("time_zone") or "UTC")


def _default_user_lookup(username: str) -> dict[str, object] | None:
    from .web_data import find_user

    return find_user(username)


def _default_event_emitter(**kwargs: object) -> object:
    from .observability import emit_event

    return emit_event(**kwargs)


def resolve_recipients(
    event: Mapping[str, object],
    settings: Mapping[str, object],
    user_lookup: Callable[[str], Mapping[str, object] | None],
    *,
    tolerate_lookup_errors: bool = True,
) -> list[str]:
    """Resolve, validate and case-insensitively deduplicate one severity rule."""

    severity = _text(event.get("severity")).lower()
    rules = settings.get("rules")
    rule = rules.get(severity) if isinstance(rules, Mapping) else None
    if not isinstance(rule, Mapping) or not bool(rule.get("enabled")):
        return []

    raw_recipients = rule.get("recipients", [])
    if isinstance(raw_recipients, str):
        candidates: list[object] = raw_recipients.split(",")
    elif isinstance(raw_recipients, (list, tuple, set)):
        candidates = list(raw_recipients)
    else:
        candidates = []

    if bool(rule.get("include_actor")):
        username = _text(event.get("username"))
        try:
            user = user_lookup(username) if username else None
        except Exception:
            if not tolerate_lookup_errors:
                raise
            user = None
        if isinstance(user, Mapping):
            candidates.append(user.get("email", ""))

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            address = normalize_email_address(candidate)
        except ValueError:
            continue
        identity = address.casefold()
        if not address or identity in seen:
            continue
        seen.add(identity)
        result.append(address)
    return result


_MAIL_CONTEXT_BLOCKED_KEY = re.compile(
    r"traceback|config|authorization|cookie|headers?|request_body|raw_content",
    re.IGNORECASE,
)


def _project_mail_context(
    value: object, *, list_limit: int | None = 50
) -> object:
    if isinstance(value, dict):
        return {
            str(key): _project_mail_context(item, list_limit=list_limit)
            for key, item in value.items()
            if not _MAIL_CONTEXT_BLOCKED_KEY.search(str(key))
        }
    if isinstance(value, list):
        items = value if list_limit is None else value[:list_limit]
        return [_project_mail_context(item, list_limit=list_limit) for item in items]
    return value


def _safe_technical_value(value: object) -> object:
    from .observability import redact_value

    return _project_mail_context(redact_value(value), list_limit=None)


def _resolved_mail_time_zone(time_zone_name: object) -> tuple[object, str]:
    requested_name = _text(time_zone_name, 128) or "UTC"
    try:
        return ZoneInfo(requested_name), requested_name
    except Exception:
        return timezone.utc, "UTC"


def _format_attachment_timestamp(value: object, time_zone_name: object) -> object:
    if not isinstance(value, str):
        return value
    original = _text(value)
    if not original:
        return ""
    try:
        timestamp = datetime.fromisoformat(original.replace("Z", "+00:00"))
    except ValueError:
        return original
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    target_zone, requested_name = _resolved_mail_time_zone(time_zone_name)
    return (
        f"{timestamp.astimezone(target_zone).isoformat(timespec='milliseconds')} "
        f"[{requested_name}]"
    )


def _localize_attachment_timestamps(value: object, time_zone_name: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): (
                _format_attachment_timestamp(item, time_zone_name)
                if str(key).endswith("_at")
                else _localize_attachment_timestamps(item, time_zone_name)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_localize_attachment_timestamps(item, time_zone_name) for item in value]
    return value


def _incident_details_attachment_payload(
    event: Mapping[str, object],
    incident: Mapping[str, object],
    *,
    time_zone_name: object = "UTC",
) -> dict[str, str] | None:
    details = _safe_technical_value(event.get("details", {}))
    context = _safe_technical_value(incident.get("context", {}))
    if not isinstance(details, dict):
        details = {}
    if not isinstance(context, dict):
        context = {}
    if not details and not context:
        return None
    event_data = {
        key: _text(event.get(key))
        for key in (
            "id",
            "created_at",
            "severity",
            "event_type",
            "module",
            "stage",
            "username",
            "ean",
            "product_id",
            "slot",
            "job_id",
            "correlation_id",
        )
        if _text(event.get(key))
    }
    event_data["details"] = details
    incident_data = {
        key: _text(incident.get(key))
        for key in (
            "id",
            "event_type",
            "severity",
            "status",
            "first_seen_at",
            "last_seen_at",
            "occurrence_count",
        )
        if _text(incident.get(key))
    }
    incident_data["context"] = context
    _target_zone, resolved_time_zone_name = _resolved_mail_time_zone(time_zone_name)
    document = _localize_attachment_timestamps(
        {
            "notice": "Sensitive values have been redacted.",
            "display_time_zone": resolved_time_zone_name,
            "event": event_data,
            "incident": incident_data,
        },
        resolved_time_zone_name,
    )
    return {
        "filename": _INCIDENT_DETAILS_ATTACHMENT_FILENAME,
        "content_type": "application/json",
        "content": json.dumps(document, ensure_ascii=False, indent=2),
    }


def _resource_alert_rows(event: Mapping[str, object]) -> list[tuple[str, str]]:
    details = event.get("details")
    trigger = details.get("trigger") if isinstance(details, Mapping) else None
    if not isinstance(trigger, Mapping):
        return []
    metric = str(trigger.get("metric") or "")
    metrics = {
        "cpu_percent": ("CPU", 1.0, "%"),
        "memory_percent": ("RAM", 1.0, "%"),
        "disk_io_bytes_per_second": ("Dysk I/O", 1024 * 1024, "MiB/s"),
    }
    description = metrics.get(metric)
    if description is None:
        return []
    label, scale, unit = description

    def formatted(value: object) -> str:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return ""
        return f"{float(value) / scale:.2f} {unit}"

    rows = [("Przekroczona metryka", label)]
    value = formatted(trigger.get("value"))
    threshold = formatted(trigger.get("threshold"))
    if value:
        rows.append(("Wartość", value))
    if threshold:
        rows.append(("Próg", threshold))
    if trigger.get("test_mode") == "real":
        rows.append(("Tryb", "test rzeczywisty"))
    return rows


def _sanitize_exception_attachment(value: object) -> str:
    text = sanitize_free_text(value, limit=_EXCEPTION_ATTACHMENT_LIMIT)
    safe = _EXCEPTION_SECRET_RE.sub(r"\g<prefix>[REDACTED]", text)
    return sanitize_free_text(safe, limit=_EXCEPTION_ATTACHMENT_LIMIT)


def _exception_attachment_payload(
    event: Mapping[str, object],
) -> dict[str, str] | None:
    if _text(event.get("severity")).lower() not in {"error", "critical"}:
        return None
    exception_type = str(event.get("exception_type") or "").strip()
    traceback_text = str(event.get("traceback_text") or "").strip()
    if not exception_type and not traceback_text:
        return None
    lines = ["Uwaga: dane wrażliwe w załączniku zostały zredagowane."]
    if exception_type:
        lines.extend(("", f"Typ wyjątku: {exception_type}"))
    if traceback_text:
        lines.extend(("", "Ślad stosu:", traceback_text))
    return {
        "filename": _EXCEPTION_ATTACHMENT_FILENAME,
        "content_type": "text/plain",
        "content": _sanitize_exception_attachment("\n".join(lines)),
    }


def _format_mail_event_time(value: object, time_zone_name: object) -> str:
    original = _text(value)
    if not original:
        return ""
    try:
        timestamp = datetime.fromisoformat(original.replace("Z", "+00:00"))
    except ValueError:
        return original
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    target_zone, requested_name = _resolved_mail_time_zone(time_zone_name)
    local_time = timestamp.astimezone(target_zone)
    abbreviation = local_time.tzname() or requested_name
    return f"{local_time:%Y-%m-%d %H:%M:%S} {abbreviation} ({requested_name})"


def _message_payload(
    event: Mapping[str, object],
    incident: Mapping[str, object],
    message_id: str,
    *,
    time_zone_name: object = "UTC",
) -> dict[str, object]:
    severity = _text(event.get("severity")).upper()
    summary = _text(event.get("summary")) or "Zdarzenie wymaga uwagi"
    subject = _header_text(f"[PicSyncra][{severity}] {summary}")
    try:
        occurrence_count = max(1, int(incident.get("occurrence_count") or 1))
    except (TypeError, ValueError):
        occurrence_count = 1
    rows = [
        ("Poziom", severity),
        ("Typ", _text(event.get("event_type"))),
        ("Czas", _format_mail_event_time(event.get("created_at"), time_zone_name)),
        ("Incydent", _text(incident.get("id"))),
        ("Liczba wystąpień", str(occurrence_count)),
        ("Zadanie", _text(event.get("job_id"))),
        ("EAN", _text(event.get("ean"))),
        ("Użytkownik", _text(event.get("username"))),
        ("Podsumowanie", summary),
        *_resource_alert_rows(event),
        ("Zalecane działanie", _text(event.get("recommended_action"))),
    ]
    attachments: list[dict[str, str]] = []
    details_attachment = _incident_details_attachment_payload(
        event, incident, time_zone_name=time_zone_name
    )
    if details_attachment is not None:
        attachments.append(details_attachment)
        rows.append(
            (
                "Szczegóły techniczne",
                "Pełne dane techniczne znajdują się w załączniku.",
            )
        )
    populated = [(label, value) for label, value in rows if value]
    text_body = "\n".join(f"{label}: {value}" for label, value in populated)
    html_rows = "".join(
        "<tr><th style=\"text-align:left;vertical-align:top\">"
        f"{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
        for label, value in populated
    )
    payload: dict[str, object] = {
        "message_id": message_id,
        "subject": subject,
        "text_body": text_body,
        "html_body": f"<h2>Incydent PicSyncra</h2><table>{html_rows}</table>",
    }
    exception_attachment = _exception_attachment_payload(event)
    if exception_attachment is not None:
        attachments.append(exception_attachment)
    if attachments:
        payload["attachments"] = attachments
    return payload


def _test_suite_message(
    scenario: Mapping[str, object],
    message_id: str,
    now: datetime,
    *,
    time_zone_name: object = "UTC",
) -> dict[str, object]:
    created_at = _iso_utc(now)
    event: dict[str, object] = {
        "id": f"test-event-{message_id}",
        "created_at": created_at,
        "severity": _text(scenario.get("severity")).lower(),
        "event_type": _text(scenario.get("event_type")),
        "module": "notification_test_suite",
        "stage": "simulation",
        "username": "",
        "summary": _text(scenario.get("summary")),
        "recommended_action": _text(scenario.get("recommended_action")),
        "details": {"simulation": True},
    }
    for key in ("exception_type", "traceback_text"):
        value = scenario.get(key)
        if isinstance(value, str) and value.strip():
            event[key] = value
    incident = {
        "id": f"test-incident-{message_id}",
        "event_type": event["event_type"],
        "severity": event["severity"],
        "occurrence_count": 1,
        "first_seen_at": created_at,
        "last_seen_at": created_at,
        "context": {"simulation": True},
    }
    payload = _message_payload(
        event, incident, message_id, time_zone_name=time_zone_name
    )
    payload["subject"] = _header_text(
        f"{_TEST_SIMULATION_NOTICE} — {_text(payload.get('subject'))}"
    )
    payload["text_body"] = (
        f"{_TEST_SIMULATION_NOTICE}\n{_text(payload.get('text_body'), 10_000)}"
    )
    payload["html_body"] = (
        f"{html.escape(_TEST_SIMULATION_NOTICE)}<br>"
        f"{_text(payload.get('html_body'), 20_000)}"
    )
    return payload


def _runtime_context_lines(
    context: Mapping[str, object],
) -> list[tuple[str, list[str]]]:
    from .observability import redact_value

    sections: list[tuple[str, list[str]]] = []
    for key, label, cap in (
        ("before", "Przed", 3),
        ("problem", "Problem", 5),
        ("after", "Po", 3),
    ):
        raw_items = context.get(key)
        items = raw_items if isinstance(raw_items, list) else []
        lines: list[str] = []
        for raw in items[:cap]:
            safe = redact_value(raw)
            if not isinstance(safe, Mapping):
                continue
            parts = [
                _text(safe.get("created_at"), 40),
                _text(safe.get("severity"), 20).upper(),
                _text(safe.get("summary"), 500),
            ]
            details = safe.get("details")
            if isinstance(details, Mapping):
                projected = _project_mail_context(dict(details))
                if projected:
                    parts.append(
                        json.dumps(
                            projected,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(", ", ": "),
                        )[:1_000]
                    )
            line = " | ".join(part for part in parts if part)
            if line:
                lines.append(line)
        sections.append((label, lines))
    return sections


def _escape_html_bounded(value: object, budget: int) -> str:
    pieces: list[str] = []
    used = 0
    for character in str(value or ""):
        escaped = html.escape(character)
        if used + len(escaped) > max(0, budget):
            break
        pieces.append(escaped)
        used += len(escaped)
    return "".join(pieces)


def _html_context_section(label: str, lines: list[str], budget: int) -> str:
    opening = f"<section><h3>{html.escape(label)}</h3>"
    closing = "</section>"
    empty = "<p>Brak zdarzeń.</p>"
    if not lines:
        return opening + empty + closing
    list_open, list_close = "<ul>", "</ul>"
    fixed_size = len(opening) + len(list_open) + len(list_close) + len(closing)
    remaining = max(0, budget - fixed_size)
    items: list[str] = []
    for index, line in enumerate(lines):
        item_tags_size = len("<li></li>")
        if remaining <= item_tags_size:
            break
        remaining_items = max(1, len(lines) - index)
        text_budget = max(0, remaining // remaining_items - item_tags_size)
        escaped = _escape_html_bounded(line, text_budget)
        item = f"<li>{escaped}</li>"
        if len(item) > remaining:
            break
        items.append(item)
        remaining -= len(item)
    if not items:
        return opening + empty + closing
    return opening + list_open + "".join(items) + list_close + closing


def _text_context_section(label: str, lines: list[str], budget: int) -> str:
    heading = f"{label}:"
    if not lines:
        return f"{heading} Brak zdarzeń."
    remaining = max(0, budget - len(heading) - 1)
    items: list[str] = []
    for index, line in enumerate(lines):
        prefix = "- "
        separator_size = 1 if items else 0
        if remaining <= len(prefix) + separator_size:
            break
        remaining_items = max(1, len(lines) - index)
        line_budget = max(
            0,
            (remaining - separator_size) // remaining_items - len(prefix),
        )
        item = prefix + str(line or "")[:line_budget]
        consumed = separator_size + len(item)
        if consumed > remaining:
            break
        items.append(item)
        remaining -= consumed
    if not items:
        return f"{heading} Brak zdarzeń."
    return heading + "\n" + "\n".join(items)


def _append_runtime_context(
    message: Mapping[str, object], context: Mapping[str, object]
) -> dict[str, object]:
    text_body = _text(message.get("text_body"), 10_000)
    html_body = _text(message.get("html_body"), 20_000)
    enriched: dict[str, object] = {
        "message_id": _text(message.get("message_id")),
        "subject": _text(message.get("subject"), 300),
        "text_body": text_body,
        "html_body": html_body,
    }
    attachment = message.get("exception_attachment")
    if isinstance(attachment, Mapping):
        enriched["exception_attachment"] = dict(attachment)
    attachments = message.get("attachments")
    if isinstance(attachments, list):
        enriched["attachments"] = [
            dict(attachment)
            for attachment in attachments
            if isinstance(attachment, Mapping)
        ]
    sections = _runtime_context_lines(context)
    text_sections = []
    html_sections = []
    text_section_budgets = {"Przed": 1_200, "Problem": 2_400, "Po": 1_200}
    section_budgets = {"Przed": 1_800, "Problem": 3_200, "Po": 1_800}
    for label, lines in sections:
        text_sections.append(
            _text_context_section(label, lines, text_section_budgets[label])
        )
        html_sections.append(
            _html_context_section(label, lines, section_budgets[label])
        )
    text_context = "\n\nKontekst zdarzeń\n" + "\n\n".join(text_sections)
    html_context = (
        "<div><h2>Kontekst zdarzeń</h2>"
        + "".join(html_sections)
        + "</div>"
    )
    text_base_budget = max(0, 10_000 - len(text_context))
    enriched["text_body"] = text_body[:text_base_budget] + text_context
    html_base_budget = max(0, 20_000 - len(html_context))
    html_base = html_body
    if len(html_base) > html_base_budget:
        pre_open, pre_close = "<pre>", "</pre>"
        excerpt_budget = max(0, html_base_budget - len(pre_open) - len(pre_close))
        html_base = (
            pre_open
            + _escape_html_bounded(html_base, excerpt_budget)
            + pre_close
        )
    enriched["html_body"] = html_base + html_context
    return enriched


def _channel_sender(
    channel: str, settings: Mapping[str, object]
) -> tuple[str, str]:
    channel_settings = settings.get(channel)
    values = channel_settings if isinstance(channel_settings, Mapping) else {}
    address = _text(values.get("from_address"))
    if channel == "smtp" and not address:
        address = _text(values.get("username"))
    name = _text(values.get("from_name")) or "PicSyncra"
    return address, name


def _safe_attempt(channel: str, result: Mapping[str, object]) -> dict[str, object]:
    status = _text(result.get("status")).lower()
    if status not in {"sent", "partial", "refused"}:
        status = "sent"
    attempt: dict[str, object] = {"channel": channel, "status": status}
    for key in ("status_code", "elapsed_ms"):
        value = result.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            attempt[key] = max(0, value)
    if status in {"partial", "refused"}:
        for key in ("accepted_count", "refused_count"):
            value = result.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                attempt[key] = max(0, value)
        raw_codes = result.get("refusal_codes")
        if isinstance(raw_codes, (list, tuple, set)):
            attempt["refusal_codes"] = sorted(
                {
                    max(0, value)
                    for value in raw_codes
                    if isinstance(value, int) and not isinstance(value, bool)
                }
            )[:20]
    return attempt


def _failure_attempt(
    channel: str, *, code: str, category: str, message: str
) -> dict[str, object]:
    return {
        "channel": channel,
        "status": "error",
        "code": code,
        "category": category,
        "message": message,
    }


def _verified_refused_recipients(
    message: MailMessage,
    result: Mapping[str, object],
) -> list[str] | None:
    """Return a verified refused subset or None when routing is ambiguous."""

    if result.get("routing_known") is not True:
        return None
    original = [_text(address) for address in message.recipients]
    identities = [address.casefold() for address in original]
    if not original or any(not identity for identity in identities):
        return None
    if len(set(identities)) != len(identities):
        return None
    allowed = dict(zip(identities, original))
    raw_refused = result.get("refused_recipients")
    if not isinstance(raw_refused, list) or not raw_refused:
        return None
    refused: list[str] = []
    seen: set[str] = set()
    for raw_address in raw_refused:
        if not isinstance(raw_address, str):
            return None
        identity = _text(raw_address).casefold()
        address = allowed.get(identity)
        if not address or identity in seen:
            return None
        seen.add(identity)
        refused.append(address)
    accepted_count = result.get("accepted_count")
    refused_count = result.get("refused_count")
    if (
        not isinstance(accepted_count, int)
        or isinstance(accepted_count, bool)
        or not isinstance(refused_count, int)
        or isinstance(refused_count, bool)
    ):
        return None
    if refused_count != len(refused):
        return None
    if accepted_count != len(original) - refused_count:
        return None
    status = _text(result.get("status")).lower()
    if status == "partial" and not (0 < refused_count < len(original)):
        return None
    if status == "refused" and not (
        refused_count == len(original) and accepted_count == 0
    ):
        return None
    return refused if status in {"partial", "refused"} else None


class NotificationService:
    """Coordinate durable queue state without exposing transport secrets."""

    def __init__(
        self,
        *,
        store: object,
        transport_factory: Callable[[str, Mapping[str, object]], MailTransport] = build_transport,
        settings_loader: Callable[[], Mapping[str, object]] = _default_settings_loader,
        time_zone_loader: Callable[[], object] = _default_time_zone_loader,
        user_lookup: Callable[[str], Mapping[str, object] | None] = _default_user_lookup,
        event_emitter: Callable[..., object] = _default_event_emitter,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.store = store
        self.transport_factory = transport_factory
        self.settings_loader = settings_loader
        self.time_zone_loader = time_zone_loader
        self.user_lookup = user_lookup
        self.event_emitter = event_emitter
        self.now = now

    def _settings(self) -> dict[str, object]:
        return normalize_email_settings(self.settings_loader())

    def _time_zone_name(self) -> str:
        try:
            return _text(self.time_zone_loader(), 128) or "UTC"
        except Exception:
            return "UTC"

    def queue_incident_notification(
        self, event: Mapping[str, object], incident: Mapping[str, object]
    ) -> dict[str, object] | None:
        if not bool(incident.get("notification_due")):
            return None
        details = event.get("details")
        if isinstance(details, Mapping) and bool(details.get("suppress_notifications")):
            return None
        severity = _text(event.get("severity")).lower()
        if severity not in {"warning", "error", "critical"}:
            return None

        settings = self._settings()
        recipients = resolve_recipients(event, settings, self.user_lookup)
        created_at = _iso_utc(self.now())
        delivery_id = f"delivery-{uuid.uuid4().hex}"
        message_id = f"{_text(incident.get('id')) or 'incident'}-{uuid.uuid4().hex}"
        message = _message_payload(
            event, incident, message_id, time_zone_name=self._time_zone_name()
        )
        record: dict[str, object] = {
            "id": delivery_id,
            "incident_id": _text(incident.get("id")),
            "event_id": _text(event.get("id")),
            "severity": severity,
            "status": "pending" if recipients else "skipped",
            "primary_channel": _text(settings.get("primary_channel")).lower(),
            "used_channel": "",
            "recipients": recipients,
            "message": message,
            "attempts": [],
            "created_at": created_at,
            "updated_at": created_at,
            "next_attempt_at": "",
        }
        return self.store.enqueue_notification_delivery(record)

    def process_notification_intent(self, intent_id: str) -> bool:
        """Materialize one durable outbox intent, leaving transient failures pending."""

        try:
            context = self.store.notification_intent_context(_text(intent_id))
            if not isinstance(context, Mapping):
                return False
            event = context.get("event")
            incident = context.get("incident")
            if not isinstance(event, Mapping):
                return False
            incident_values = incident if isinstance(incident, Mapping) else {}
            severity = _text(event.get("severity")).lower()
            # Releases made before daily summaries existed may still contain
            # informational intents. Complete them without sending stale spam.
            if severity == "info":
                self.store.materialize_notification_intent(
                    _text(intent_id), delivery=None, completed_at=_iso_utc(self.now())
                )
                return True
            settings = self._settings()
            recipients = resolve_recipients(
                event,
                settings,
                self.user_lookup,
                tolerate_lookup_errors=False,
            )
            completed_at = _iso_utc(self.now())
            event_id = _text(event.get("id"))
            message_id = f"notify-{event_id}"
            delivery_id = f"delivery-{event_id}"
            delivery: dict[str, object] = {
                "id": delivery_id,
                "incident_id": _text(incident_values.get("id")),
                "event_id": event_id,
                "severity": severity,
                "status": "pending" if recipients else "skipped",
                "primary_channel": _text(settings.get("primary_channel")).lower(),
                "used_channel": "",
                "recipients": recipients,
                "message": _message_payload(
                    event,
                    incident_values,
                    message_id,
                    time_zone_name=self._time_zone_name(),
                ),
                "attempts": [],
                "created_at": completed_at,
                "updated_at": completed_at,
                "next_attempt_at": "",
            }
            self.store.materialize_notification_intent(
                _text(intent_id), delivery=delivery, completed_at=completed_at
            )
            return True
        except Exception:
            # The source intent remains pending; diagnostics here would recurse.
            return False

    def process_notification_intents(self, limit: int = WORKER_BATCH_LIMIT) -> int:
        processed = 0
        try:
            intents = self.store.pending_notification_intents(limit=limit)
        except Exception:
            return 0
        for intent in intents:
            if isinstance(intent, Mapping) and self.process_notification_intent(
                _text(intent.get("id"))
            ):
                processed += 1
        return processed

    def process_due_daily_change_summary(self) -> dict[str, object]:
        """Send exactly one compact daily report for the current Warsaw slot."""

        settings = self._settings()
        window_end = _daily_summary_due_end(
            self.now(), settings.get("daily_summary_time", "16:00")
        )
        if not window_end:
            return {"status": "not_due", "product_count": 0}
        recipients = resolve_recipients(
            {"severity": "info", "username": ""}, settings, self.user_lookup
        )
        if not recipients:
            return {"status": "not_configured", "product_count": 0}
        claim = self.store.claim_daily_change_summary(
            window_end, claimed_at=_iso_utc(self.now())
        )
        if not isinstance(claim, Mapping):
            return {"status": "already_processed", "product_count": 0}
        report_end = _text(claim.get("window_end"), 40)
        claim_token = _text(claim.get("claim_token"), 128)
        if not report_end or not claim_token:
            return {"status": "error", "product_count": 0}
        start = _text(claim.get("window_start"), 40)
        try:
            history = self.store.daily_change_history(
                window_start=start, window_end=report_end
            )
            records = [item for item in history if isinstance(item, Mapping)]
            rows = _compact_daily_change_rows(records)
        except Exception:
            self.store.finalize_daily_change_summary(
                report_end,
                status="pending",
                claim_token=claim_token,
                next_attempt_at=_iso_utc(self.now() + DAILY_SUMMARY_RETRY_DELAY),
            )
            return {"status": "error", "product_count": 0}
        if not rows:
            self.store.finalize_daily_change_summary(
                report_end, status="sent", claim_token=claim_token
            )
            return {"status": "skipped", "product_count": 0}
        delivery = {
            "id": f"daily-summary-{report_end}",
            "primary_channel": _text(settings.get("primary_channel")).lower(),
            "recipients": recipients,
            "message": _daily_summary_message(
                rows, window_start=start, window_end=report_end
            ),
        }
        status, _channel, _attempts = self._deliver_claimed(
            delivery, settings, allow_fallback=bool(settings.get("fallback_enabled"))
        )
        final_status = "sent" if status != "error" else "pending"
        self.store.finalize_daily_change_summary(
            report_end,
            status=final_status,
            claim_token=claim_token,
            next_attempt_at=(
                _iso_utc(self.now() + DAILY_SUMMARY_RETRY_DELAY)
                if final_status == "pending"
                else ""
            ),
        )
        return {"status": status, "product_count": len(rows)}

    def recover_daily_change_summaries(self) -> int:
        """Release only report sends abandoned longer than the claim timeout."""

        recover = getattr(self.store, "recover_daily_change_summaries", None)
        if not callable(recover):
            return 0
        return max(
            0,
            int(
                recover(
                    stale_before=_iso_utc(
                        self.now() - DAILY_SUMMARY_STALE_CLAIM_AFTER
                    )
                )
                or 0
            ),
        )

    def _mail_message(
        self,
        delivery: Mapping[str, object],
        channel: str,
        settings: Mapping[str, object],
    ) -> MailMessage:
        payload = delivery.get("message")
        message = payload if isinstance(payload, Mapping) else {}
        sender_address, sender_name = _channel_sender(channel, settings)
        recipients = delivery.get("recipients")
        attachments: list[MailAttachment] = []
        raw_attachments = message.get("attachments")
        attachment_values = raw_attachments if isinstance(raw_attachments, list) else []
        for raw_attachment in attachment_values:
            if not isinstance(raw_attachment, Mapping):
                continue
            filename = raw_attachment.get("filename")
            content_type = raw_attachment.get("content_type")
            content = raw_attachment.get("content")
            if (
                filename == _INCIDENT_DETAILS_ATTACHMENT_FILENAME
                and content_type == "application/json"
                and isinstance(content, str)
            ):
                try:
                    parsed_content = json.loads(content)
                except (TypeError, ValueError):
                    continue
                attachments.append(
                    MailAttachment(
                        filename=_INCIDENT_DETAILS_ATTACHMENT_FILENAME,
                        content_type="application/json",
                        content=json.dumps(
                            _safe_technical_value(parsed_content),
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                )
            elif (
                filename == _EXCEPTION_ATTACHMENT_FILENAME
                and content_type == "text/plain"
                and isinstance(content, str)
            ):
                attachments.append(
                    MailAttachment(
                        filename=_EXCEPTION_ATTACHMENT_FILENAME,
                        content_type="text/plain",
                        content=_sanitize_exception_attachment(content),
                    )
                )
        if not attachments:
            raw_attachment = message.get("exception_attachment")
            if isinstance(raw_attachment, Mapping):
                filename = raw_attachment.get("filename")
                content_type = raw_attachment.get("content_type")
                content = raw_attachment.get("content")
                if (
                    filename == _EXCEPTION_ATTACHMENT_FILENAME
                    and content_type == "text/plain"
                    and isinstance(content, str)
                ):
                    attachments.append(
                        MailAttachment(
                            filename=_EXCEPTION_ATTACHMENT_FILENAME,
                            content_type="text/plain",
                            content=_sanitize_exception_attachment(content),
                        )
                    )
        return MailMessage(
            message_id=_text(message.get("message_id")),
            subject=_text(message.get("subject"), 300),
            text_body=_text(message.get("text_body"), 10_000),
            html_body=_text(message.get("html_body"), 20_000),
            sender_address=sender_address,
            sender_name=sender_name,
            recipients=list(recipients) if isinstance(recipients, list) else [],
            attachments=tuple(attachments),
        )

    def _with_delivery_context(
        self, delivery: Mapping[str, object]
    ) -> Mapping[str, object]:
        try:
            context = self.store.query_incident_context(
                _text(delivery.get("incident_id")),
                problem_limit=5,
                before_limit=3,
                after_limit=3,
            )
        except Exception:
            return delivery
        safe_context = context if isinstance(context, Mapping) else {}
        payload = delivery.get("message")
        message = payload if isinstance(payload, Mapping) else {}
        enriched = dict(delivery)
        enriched["message"] = _append_runtime_context(message, safe_context)
        return enriched

    def _send_channel(
        self,
        delivery: Mapping[str, object],
        channel: str,
        settings: Mapping[str, object],
    ) -> tuple[dict[str, object], bool, list[str], bool]:
        try:
            channel_settings = settings.get(channel)
            transport = self.transport_factory(
                channel,
                channel_settings if isinstance(channel_settings, Mapping) else {},
            )
        except Exception:
            return _failure_attempt(
                channel,
                code="transport_unavailable",
                category="transport",
                message="Nie można przygotować kanału wysyłki.",
            ), False, [], True
        try:
            message = self._mail_message(delivery, channel, settings)
        except Exception:
            return _failure_attempt(
                channel,
                code="message_invalid",
                category="message",
                message="Nie można przygotować wiadomości.",
            ), False, [], True
        try:
            result = transport.send(message)
            safe_result = result if isinstance(result, Mapping) else {}
            attempt = _safe_attempt(channel, safe_result)
            status = _text(safe_result.get("status")).lower()
            if status in {"partial", "refused", "routing_unknown"}:
                refused = _verified_refused_recipients(message, safe_result)
                if refused is not None:
                    return attempt, False, refused, True
                return _failure_attempt(
                    channel,
                    code="partial_routing_unknown",
                    category="delivery",
                    message=(
                        "Nie można bezpiecznie ustalić odrzuconych odbiorców."
                    ),
                ), False, [], False
            return attempt, True, [], False
        except Exception:
            return _failure_attempt(
                channel,
                code="delivery_failed",
                category="delivery",
                message="Kanał nie wysłał wiadomości.",
            ), False, [], True

    def _deliver_claimed(
        self,
        claimed: Mapping[str, object],
        settings: Mapping[str, object],
        *,
        allow_fallback: bool,
    ) -> tuple[str, str, list[dict[str, object]]]:
        primary = _text(claimed.get("primary_channel")).lower()
        attempts: list[dict[str, object]] = []
        attempt, success, refused, fallback_safe = self._send_channel(
            claimed, primary, settings
        )
        attempts.append(attempt)
        if success:
            return "sent", primary, attempts
        if allow_fallback and fallback_safe:
            fallback = "smtp" if primary == "entra" else "entra"
            fallback_delivery = claimed
            if refused:
                fallback_delivery = dict(claimed)
                fallback_delivery["recipients"] = refused
            attempt, success, _fallback_refused, _fallback_safe = self._send_channel(
                fallback_delivery, fallback, settings
            )
            attempts.append(attempt)
            if success:
                return "fallback", fallback, attempts
            return "error", fallback, attempts
        return "error", primary, attempts

    def process_delivery(self, delivery_id: str) -> dict[str, object]:
        claimed = self.store.update_notification_delivery(
            _text(delivery_id), status="sending", updated_at=_iso_utc(self.now())
        )
        if not claimed:
            return {}
        primary = _text(claimed.get("primary_channel")).lower()
        try:
            settings = self._settings()
        except Exception:
            status = "error"
            used_channel = primary
            attempts = [
                _failure_attempt(
                    primary,
                    code="settings_unavailable",
                    category="configuration",
                    message="Nie można wczytać konfiguracji poczty.",
                )
            ]
        else:
            try:
                delivery_for_send = self._with_delivery_context(claimed)
                status, used_channel, attempts = self._deliver_claimed(
                    delivery_for_send,
                    settings,
                    allow_fallback=bool(settings.get("fallback_enabled")),
                )
            except Exception:
                status = "error"
                used_channel = primary
                attempts = [
                    _failure_attempt(
                        primary,
                        code="processing_failed",
                        category="internal",
                        message="Nie można zakończyć obsługi powiadomienia.",
                    )
                ]
        completed = self.store.update_notification_delivery(
            _text(delivery_id),
            status=status,
            used_channel=used_channel,
            attempts=attempts,
            updated_at=_iso_utc(self.now()),
        )
        try:
            self.event_emitter(
                severity="info" if status != "error" else "error",
                event_type=(
                    "notification.sent" if status != "error" else "notification.failed"
                ),
                module="notifications",
                stage="delivery",
                summary=(
                    "Powiadomienie e-mail wysłane."
                    if status != "error"
                    else "Nie udało się wysłać powiadomienia e-mail."
                ),
                details={
                    "delivery_id": _text(delivery_id),
                    "incident_id": _text(claimed.get("incident_id")),
                    "used_channel": used_channel,
                    "suppress_notifications": True,
                },
            )
        except Exception:
            pass
        return completed

    def recover_stale_deliveries(self) -> int:
        threshold = self.now() - STALE_SENDING_AFTER
        recovered = 0
        cursor = ""
        seen: set[str] = set()
        while True:
            page = self.store.query_notification_deliveries(cursor=cursor, limit=100)
            for delivery in page.get("items", []):
                if not isinstance(delivery, dict) or delivery.get("status") != "sending":
                    continue
                updated_at = _parse_utc(delivery.get("updated_at"))
                if updated_at is None or updated_at > threshold:
                    continue
                result = self.store.update_notification_delivery(
                    _text(delivery.get("id")),
                    status="pending",
                    updated_at=_iso_utc(self.now()),
                    next_attempt_at="",
                )
                recovered += bool(result)
            next_cursor = _text(page.get("next_cursor"))
            if not next_cursor or next_cursor in seen:
                break
            seen.add(next_cursor)
            cursor = next_cursor
        return recovered

    def process_pending_batch(self, limit: int = WORKER_BATCH_LIMIT) -> int:
        try:
            self.process_due_daily_change_summary()
        except Exception:
            # Daily reports are isolated from incident delivery and are retryable.
            pass
        self.process_notification_intents(limit=limit)
        processed = 0
        for delivery in self.store.pending_notification_deliveries(limit=limit):
            if self.process_delivery(_text(delivery.get("id"))):
                processed += 1
        try:
            self.store.prune_done_notification_intents(
                _iso_utc(self.now() - OUTBOX_DONE_RETENTION)
            )
        except Exception:
            pass
        return processed

    def send_test_message(
        self, *, channel: str, recipient: str, use_fallback: bool = False
    ) -> dict[str, object]:
        selected = _text(channel).lower()
        if selected not in {"entra", "smtp"}:
            raise ValueError("Niepoprawny kanał wysyłki.")
        address = normalize_email_address(recipient)
        if not address:
            raise ValueError("Niepoprawny adres e-mail.")
        try:
            settings = self._settings()
        except Exception:
            return {
                "status": "error",
                "used_channel": selected,
                "attempts": [
                    _failure_attempt(
                        selected,
                        code="settings_unavailable",
                        category="configuration",
                        message="Nie można wczytać konfiguracji poczty.",
                    )
                ],
                "message_id": "",
            }
        try:
            now = _iso_utc(self.now())
            message_id = f"test-{uuid.uuid4().hex}"
            delivery = {
                "id": f"test-{uuid.uuid4().hex}",
                "incident_id": "",
                "primary_channel": selected,
                "recipients": [address],
                "message": {
                    "message_id": message_id,
                    "subject": "[TEST] PicSyncra — wiadomość testowa",
                    "text_body": f"To jest wiadomość testowa. Czas: {now}",
                    "html_body": (
                        "<h2>Wiadomość testowa PicSyncra</h2>"
                        f"<p>Czas: {html.escape(now)}</p>"
                    ),
                },
            }
        except Exception:
            return {
                "status": "error",
                "used_channel": selected,
                "attempts": [
                    _failure_attempt(
                        selected,
                        code="message_invalid",
                        category="message",
                        message="Nie można przygotować wiadomości testowej.",
                    )
                ],
                "message_id": "",
            }
        status, used_channel, attempts = self._deliver_claimed(
            delivery,
            settings,
            allow_fallback=(
                use_fallback and bool(settings.get("fallback_enabled"))
            ),
        )
        return {
            "status": status,
            "used_channel": used_channel,
            "attempts": attempts,
            "message_id": message_id,
        }

    def send_test_notification_suite(
        self, *, channel: str, use_fallback: bool = False
    ) -> dict[str, object]:
        """Send five direct test messages without recording any operational state."""

        selected = _text(channel).lower()
        if selected not in {"entra", "smtp"}:
            raise ValueError("Niepoprawny kanał wysyłki.")
        try:
            settings = self._settings()
        except Exception:
            settings = None

        results: list[dict[str, object]] = []
        for scenario in _TEST_NOTIFICATION_SCENARIOS:
            kind = _text(scenario.get("kind"))
            severity = _text(scenario.get("severity")).lower()
            result: dict[str, object] = {
                "kind": kind,
                "severity": severity,
                "status": "error",
                "used_channel": selected,
                "recipient_count": 0,
                "attempts": [],
            }
            if settings is None:
                result["attempts"] = [
                    _failure_attempt(
                        selected,
                        code="settings_unavailable",
                        category="configuration",
                        message="Nie można wczytać konfiguracji poczty.",
                    )
                ]
                results.append(result)
                continue

            event = {"severity": severity, "username": ""}
            recipients = resolve_recipients(event, settings, self.user_lookup)
            result["recipient_count"] = len(recipients)
            if not recipients:
                result["status"] = "skipped"
                results.append(result)
                continue

            message_id = f"test-suite-{uuid.uuid4().hex}"
            delivery = {
                "id": f"test-suite-{uuid.uuid4().hex}",
                "incident_id": "",
                "primary_channel": selected,
                "recipients": recipients,
                "message": _test_suite_message(
                    scenario,
                    message_id,
                    self.now(),
                    time_zone_name=self._time_zone_name(),
                ),
            }
            try:
                status, used_channel, attempts = self._deliver_claimed(
                    delivery,
                    settings,
                    allow_fallback=(
                        use_fallback and bool(settings.get("fallback_enabled"))
                    ),
                )
            except Exception:
                status, used_channel, attempts = (
                    "error",
                    selected,
                    [
                        _failure_attempt(
                            selected,
                            code="test_failed",
                            category="internal",
                            message="Nie można zakończyć testu wysyłki.",
                        )
                    ],
                )
            result.update(
                status=status,
                used_channel=used_channel,
                attempts=attempts,
                message_id=message_id,
            )
            results.append(result)
        return {"scenarios": results}


def _default_service() -> NotificationService:
    from .observability import observability_store

    return NotificationService(store=observability_store())


def queue_incident_notification(
    event: Mapping[str, object], incident: Mapping[str, object]
) -> dict[str, object] | None:
    return _default_service().queue_incident_notification(event, incident)


def process_delivery(delivery_id: str) -> dict[str, object]:
    return _default_service().process_delivery(delivery_id)


def send_test_message(
    *, channel: str, recipient: str, use_fallback: bool = False
) -> dict[str, object]:
    return _default_service().send_test_message(
        channel=channel, recipient=recipient, use_fallback=use_fallback
    )


def send_test_notification_suite(
    *, channel: str, use_fallback: bool = False
) -> dict[str, object]:
    return _default_service().send_test_notification_suite(
        channel=channel, use_fallback=use_fallback
    )


_WORKER_LOCK = threading.Lock()
_WORKER_STOP: threading.Event | None = None
_WORKER_THREAD: threading.Thread | None = None
_WORKER_SERVICE: NotificationService | None = None
_WORKER_OBSERVED_AT = ""
_WORKER_LAST_ENTRA_MONITOR_AT: datetime | None = None
_WORKER_SCHEDULER = WakeableDeadlineScheduler(
    max_idle_seconds=WORKER_MAX_IDLE_SECONDS
)


def wake_notification_worker() -> None:
    """Wake the worker so it can re-read durable notification state."""

    _WORKER_SCHEDULER.wake()


def _next_daily_summary_at(
    service: NotificationService, now: datetime
) -> datetime | None:
    try:
        schedule = _text(service._settings().get("daily_summary_time", "16:00"), 5)
    except Exception:
        return None
    if (
        len(schedule) != 5
        or schedule[2] != ":"
        or not (schedule[:2] + schedule[3:]).isdigit()
    ):
        return None
    hour, minute = int(schedule[:2]), int(schedule[3:])
    if hour > 23 or minute > 59:
        return None
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    local = current.astimezone(DAILY_SUMMARY_TIME_ZONE)
    scheduled = local.replace(
        hour=hour, minute=minute, second=0, microsecond=0, fold=0
    )
    if local >= scheduled:
        scheduled += timedelta(days=1)
    return scheduled.astimezone(timezone.utc)


def _worker_delay_seconds(
    service: NotificationService,
    *,
    now: datetime,
    next_prune_at: datetime,
) -> float:
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    deadlines = [next_prune_at]
    try:
        due_at = _parse_utc(service.store.next_notification_due_at())
    except Exception:
        due_at = None
    if due_at is not None:
        deadlines.append(due_at)
    daily_at = _next_daily_summary_at(service, current)
    if daily_at is not None:
        deadlines.append(daily_at)
    return max(0.0, min((deadline - current).total_seconds() for deadline in deadlines))


def _worker_loop(service: NotificationService, stop_event: threading.Event) -> None:
    global _WORKER_LAST_ENTRA_MONITOR_AT
    while not stop_event.is_set():
        monitor_now = _utc_now()
        if (
            _WORKER_LAST_ENTRA_MONITOR_AT is None
            or monitor_now - _WORKER_LAST_ENTRA_MONITOR_AT >= timedelta(hours=24)
        ):
            try:
                process_due_entra_secret_reminders()
            except Exception:
                # Monitoring must never delay or stop notification delivery.
                pass
            finally:
                _WORKER_LAST_ENTRA_MONITOR_AT = monitor_now
        try:
            service.process_pending_batch(limit=WORKER_BATCH_LIMIT)
        except Exception:
            # Queue processing is isolated from the web/product request paths.
            pass
        wait_generation = _WORKER_SCHEDULER.capture_generation()
        cycle_finished_at = _utc_now()
        delay = _worker_delay_seconds(
            service,
            now=cycle_finished_at,
            next_prune_at=cycle_finished_at + WORKER_PRUNE_INTERVAL,
        )
        if (
            _WORKER_SCHEDULER.wait(
                stop_event,
                delay,
                since_generation=wait_generation,
            )
            == "stop"
        ):
            break


def start_notification_worker() -> None:
    """Recover stale claims and start one bounded daemon queue worker."""

    global _WORKER_LAST_ENTRA_MONITOR_AT, _WORKER_OBSERVED_AT, _WORKER_SERVICE, _WORKER_STOP, _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return
        _WORKER_THREAD = None
        _WORKER_SERVICE = None
        _WORKER_STOP = None
        try:
            service = _default_service()
        except Exception:
            return
        try:
            service.recover_stale_deliveries()
        except Exception:
            pass
        try:
            service.recover_daily_change_summaries()
        except Exception:
            pass
        stop_event = threading.Event()
        _WORKER_SERVICE = service
        _WORKER_STOP = stop_event
        _WORKER_LAST_ENTRA_MONITOR_AT = None
        _WORKER_THREAD = threading.Thread(
            target=_worker_loop,
            args=(service, stop_event),
            name="picsyncra-notification-worker",
            daemon=True,
        )
        _WORKER_THREAD.start()
        _WORKER_OBSERVED_AT = _iso_utc(_utc_now())


def stop_notification_worker() -> None:
    """Stop and join the current notification worker."""

    global _WORKER_OBSERVED_AT, _WORKER_SERVICE, _WORKER_STOP, _WORKER_THREAD
    with _WORKER_LOCK:
        thread = _WORKER_THREAD
        stop_event = _WORKER_STOP
        if stop_event is not None:
            stop_event.set()
            wake_notification_worker()
    if thread is not None and thread.is_alive():
        thread.join(timeout=WORKER_STOP_TIMEOUT_SECONDS)
    with _WORKER_LOCK:
        if _WORKER_THREAD is not thread:
            return
        if thread is not None and thread.is_alive():
            return
        _WORKER_THREAD = None
        _WORKER_SERVICE = None
        _WORKER_STOP = None
        _WORKER_OBSERVED_AT = _iso_utc(_utc_now())


def notification_worker_health() -> dict[str, str]:
    """Return current worker state without constructing or starting a worker."""

    with _WORKER_LOCK:
        thread = _WORKER_THREAD
        return {
            "status": "online" if thread is not None and thread.is_alive() else "critical",
            "observed_at": _WORKER_OBSERVED_AT,
        }
