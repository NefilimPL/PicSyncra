"""Helpers for managing photo slot definitions and SQL column mappings."""

from __future__ import annotations

from typing import Dict, List, Tuple

from .common import DEFAULT_SLOT_DEFS, SQL_COLUMN_MAP_KEY, SLOT_DEFS_KEY


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def normalize_slot_prefix(value, *, width: int = 2) -> str:
    """Return the canonical numeric slot ID used in file names."""

    text = _as_text(value)
    if not text or not text.isdigit():
        return ""
    number = int(text)
    if number <= 0:
        return ""
    return str(number).zfill(max(width, len(str(number))))


def _slot_prefix_key(value) -> str:
    return normalize_slot_prefix(value) or _as_text(value)


def normalize_slot_definitions(raw_defs) -> Tuple[List[Dict[str, str]], List[dict]]:
    """Return a cleaned list of slot definitions and any issues found."""

    issues = []
    slot_defs: List[Dict[str, str]] = []
    seen = set()
    if isinstance(raw_defs, list):
        for entry in raw_defs:
            prefix = ""
            label = ""
            filename_label = ""
            if isinstance(entry, dict):
                prefix = _as_text(
                    entry.get("prefix") or entry.get("filename_id") or entry.get("id")
                )
                label = _as_text(entry.get("label") or entry.get("slot_label"))
                filename_label = _as_text(
                    entry.get("filename_label")
                    or entry.get("file_label")
                    or entry.get("filename")
                )
            elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                prefix = _as_text(entry[0])
                label = _as_text(entry[1])
                if len(entry) >= 3:
                    filename_label = _as_text(entry[2])
            if not prefix or not label:
                if entry:
                    issues.append({"type": "slot_def_invalid", "entry": entry})
                continue
            normalized_prefix = normalize_slot_prefix(prefix) or prefix
            prefix_key = _slot_prefix_key(normalized_prefix).lower()
            if prefix_key in seen:
                issues.append({"type": "slot_def_duplicate", "prefix": prefix})
                continue
            slot = {"prefix": normalized_prefix, "label": label}
            if filename_label:
                slot["filename_label"] = filename_label
            slot_defs.append(slot)
            seen.add(prefix_key)
    if not slot_defs:
        slot_defs = []
        for item in DEFAULT_SLOT_DEFS:
            slot = {
                "prefix": _as_text(item.get("prefix")),
                "label": _as_text(item.get("label")),
            }
            filename_label = _as_text(item.get("filename_label"))
            if filename_label:
                slot["filename_label"] = filename_label
            slot_defs.append(slot)
        if raw_defs:
            issues.append({"type": "slot_def_fallback"})
    return slot_defs, issues


def normalize_sql_column_map(raw_map, slot_defs) -> Tuple[Dict[str, str], List[dict]]:
    """Return a cleaned SQL column map aligned with the provided slot defs."""

    issues = []
    normalized: Dict[str, str] = {}
    if isinstance(raw_map, dict):
        for key, value in raw_map.items():
            prefix = normalize_slot_prefix(key) or _as_text(key)
            if not prefix:
                continue
            normalized[prefix] = _as_text(value)
    prefixes = {slot["prefix"] for slot in slot_defs}
    for prefix in list(normalized):
        if prefix not in prefixes:
            issues.append({"type": "sql_map_extra", "prefix": prefix})
            normalized.pop(prefix, None)
    for slot in slot_defs:
        prefix = slot["prefix"]
        if prefix not in normalized:
            normalized[prefix] = _as_text(slot.get("label"))
    return normalized, issues


def next_slot_prefix(slot_defs) -> str:
    """Return a new numeric prefix that does not collide with existing slots."""

    used = []
    for slot in slot_defs or []:
        prefix = normalize_slot_prefix(slot.get("prefix"))
        if prefix:
            used.append(int(prefix))
    if used:
        next_num = max(used) + 1
    else:
        next_num = 1
    width = max(2, len(str(next_num)))
    return str(next_num).zfill(width)


def slot_config_from_config(config_dict) -> Tuple[List[Dict[str, str]], Dict[str, str], List[dict]]:
    """Load slot definitions and SQL map from the provided config dict."""

    raw_defs = config_dict.get(SLOT_DEFS_KEY)
    slot_defs, slot_issues = normalize_slot_definitions(raw_defs)
    raw_map = config_dict.get(SQL_COLUMN_MAP_KEY)
    sql_map, map_issues = normalize_sql_column_map(raw_map, slot_defs)
    return slot_defs, sql_map, slot_issues + map_issues
