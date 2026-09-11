"""Build structured product, file, and integration history change sets."""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable, Mapping


def _comparison_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, str):
        return unicodedata.normalize("NFKC", value).strip().casefold()
    return value


def field_changes(
    before: Mapping[str, object] | None,
    after: Mapping[str, object],
    labels: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Return changed fields while retaining their original display values."""

    previous = before or {}
    display_labels = labels or {}
    keys = set(after) if before is None else set(previous) | set(after)
    changes: list[dict[str, object]] = []
    for key in sorted(keys):
        old = None if before is None else previous.get(key)
        new = after.get(key)
        if before is not None and _comparison_value(old) == _comparison_value(new):
            continue
        changes.append(
            {
                "key": key,
                "label": display_labels.get(key, key),
                "before": old,
                "after": new,
            }
        )
    return changes


def _slot(item: Mapping[str, object]) -> str:
    return str(item.get("prefix") or item.get("slot") or "").strip()


def _name(item: Mapping[str, object]) -> str | None:
    for key in ("filename", "ftp_filename", "sql_value"):
        value = str(item.get(key) or "").strip()
        if value:
            return os.path.basename(value)
    path = str(item.get("path") or item.get("local_path") or "").strip()
    return os.path.basename(path) if path else None


def _size(item: Mapping[str, object], key: str = "size_bytes") -> int | None:
    value = item.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0:
        return int(value)
    return None


def _saved_change(
    slot: str,
    operation: str,
    previous: Mapping[str, object],
    saved: Mapping[str, object],
) -> dict[str, object]:
    change: dict[str, object] = {
        "slot": slot,
        "operation": operation,
        "before_name": _name(previous),
        "after_name": _name(saved),
        "source_name": str(saved.get("source_name") or "").strip() or None,
        "before_size_bytes": _size(previous),
        "source_size_bytes": _size(saved, "source_size_bytes"),
        "after_size_bytes": _size(saved),
        "elapsed_ms": _size(saved, "elapsed_ms"),
        "processing_operation": str(saved.get("operation") or "").strip() or None,
        "content_fit": bool(saved.get("content_fit")),
    }
    if "preprocessed" in saved:
        change["preprocessed"] = bool(saved.get("preprocessed"))
    return change


def file_changes(
    existing_photos: Iterable[Mapping[str, object]],
    saved_files: Iterable[Mapping[str, object]],
    delete_requests: Iterable[Mapping[str, object]],
    migrated_prefixes: Iterable[object],
) -> list[dict[str, object]]:
    """Describe added, replaced, deleted, and migrated file slots."""

    existing = {_slot(item): item for item in existing_photos if _slot(item)}
    saved = {_slot(item): item for item in saved_files if _slot(item)}
    deleted = {_slot(item): item for item in delete_requests if _slot(item)}
    migrated = {str(prefix).strip() for prefix in migrated_prefixes if str(prefix).strip()}
    changes: list[dict[str, object]] = []
    for slot in sorted(set(saved) | set(deleted)):
        if slot in saved:
            operation = (
                "migrated"
                if slot in migrated
                else "replaced"
                if slot in existing or slot in deleted
                else "added"
            )
            previous = existing.get(slot, deleted.get(slot, {}))
            changes.append(_saved_change(slot, operation, previous, saved[slot]))
            continue
        previous = existing.get(slot, deleted[slot])
        changes.append(
            {
                "slot": slot,
                "operation": "deleted",
                "before_name": _name(previous),
                "before_size_bytes": _size(previous),
            }
        )
    return changes


def history_change_set(
    *,
    existing_entry: Mapping[str, object] | None,
    saved_entry: Mapping[str, object],
    existing_photos: Iterable[Mapping[str, object]],
    saved_files: Iterable[Mapping[str, object]],
    delete_requests: Iterable[Mapping[str, object]],
    migrated_prefixes: Iterable[object],
    integrations: object,
    pimcore: object = None,
) -> dict[str, object]:
    """Build the common history payload for a product operation."""

    comparable_existing = (
        {key: existing_entry.get(key) for key in saved_entry}
        if existing_entry is not None
        else None
    )
    fields = field_changes(comparable_existing, saved_entry)
    files = file_changes(
        existing_photos,
        saved_files,
        delete_requests,
        migrated_prefixes,
    )
    integration_payload = integrations if isinstance(integrations, Mapping) else {}
    evidence_by_slot: dict[str, dict[str, object]] = {}
    for integration_name in ("local", "ftp", "sql"):
        integration = integration_payload.get(integration_name)
        if not isinstance(integration, Mapping):
            continue
        slot_results = integration.get("slot_results")
        if not isinstance(slot_results, list):
            continue
        for item in slot_results:
            if not isinstance(item, Mapping):
                continue
            slot = _slot(item)
            if slot:
                slot_evidence = evidence_by_slot.setdefault(slot, {})
                current = slot_evidence.get(integration_name)
                candidate = dict(item)
                if current is None:
                    slot_evidence[integration_name] = candidate
                elif isinstance(current, list):
                    current.append(candidate)
                else:
                    slot_evidence[integration_name] = [current, candidate]
    for file_change in files:
        slot_evidence = evidence_by_slot.get(str(file_change.get("slot") or ""))
        if slot_evidence:
            file_change["evidence"] = slot_evidence
    kind = "created" if existing_entry is None else "updated" if fields or files else "synchronized"
    return {
        "kind": kind,
        "fields": fields,
        "files": files,
        "integrations": integrations,
        "pimcore": pimcore or {},
    }
