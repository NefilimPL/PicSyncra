"""Shared configuration contract for product form fields."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


PRODUCT_FIELDS_KEY = "product_fields"
LEGACY_COLOR_FIELD_LABELS_KEY = "color_field_labels"
PRODUCT_FIELD_KEYS = (
    "name",
    "type",
    "model",
    "color1",
    "color2",
    "color3",
    "extra",
    "ean",
)
PRODUCT_FIELD_VALUE_KEYS = {
    "name": "name",
    "type": "type_name",
    "model": "model",
    "color1": "color1",
    "color2": "color2",
    "color3": "color3",
    "extra": "extra",
    "ean": "ean",
}
DEFAULT_PRODUCT_FIELD_LABELS = {
    "name": "Nazwa",
    "type": "Typ",
    "model": "Model",
    "color1": "Kolor 1",
    "color2": "Kolor 2",
    "color3": "Kolor 3",
    "extra": "Dodatek",
    "ean": "EAN",
}
DEFAULT_REQUIRED_FIELDS = frozenset({"name", "type", "model", "color1"})


def _clean_label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().rstrip(":*").strip()


def _bool_value(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def default_product_fields() -> dict[str, dict[str, object]]:
    return {
        key: {
            "label": "",
            "enabled": True,
            "required": key in DEFAULT_REQUIRED_FIELDS,
        }
        for key in PRODUCT_FIELD_KEYS
    }


def normalize_product_fields(
    raw_settings: object,
    *,
    legacy_color_labels: object = None,
) -> dict[str, dict[str, object]]:
    raw = raw_settings if isinstance(raw_settings, Mapping) else {}
    legacy = legacy_color_labels if isinstance(legacy_color_labels, Mapping) else {}
    normalized = default_product_fields()
    for key in PRODUCT_FIELD_KEYS:
        item = raw.get(key)
        item = item if isinstance(item, Mapping) else {}
        if "label" in item:
            label = _clean_label(item.get("label"))
        elif key in {"color1", "color2", "color3"}:
            label = _clean_label(legacy.get(key))
        else:
            label = ""
        enabled = _bool_value(item.get("enabled"), True)
        required = enabled and _bool_value(
            item.get("required"),
            key in DEFAULT_REQUIRED_FIELDS,
        )
        normalized[key] = {
            "label": label,
            "enabled": enabled,
            "required": required,
        }
    return normalized


def effective_product_values(
    raw_values: Mapping[str, Any],
    raw_settings: object,
) -> dict[str, Any]:
    values = dict(raw_values)
    settings = normalize_product_fields(raw_settings)
    for key, value_key in PRODUCT_FIELD_VALUE_KEYS.items():
        if not settings[key]["enabled"]:
            values[value_key] = ""
    return values


def effective_field_label(key: str, raw_settings: object) -> str:
    settings = normalize_product_fields(raw_settings)
    return str(settings[key]["label"] or DEFAULT_PRODUCT_FIELD_LABELS[key])


def missing_required_fields(
    raw_values: Mapping[str, Any],
    raw_settings: object,
) -> list[tuple[str, str]]:
    settings = normalize_product_fields(raw_settings)
    values = effective_product_values(raw_values, settings)
    missing = []
    for key, value_key in PRODUCT_FIELD_VALUE_KEYS.items():
        if settings[key]["required"] and not str(values.get(value_key) or "").strip():
            missing.append((key, effective_field_label(key, settings)))
    return missing
