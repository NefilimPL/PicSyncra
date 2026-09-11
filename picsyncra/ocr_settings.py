"""Global settings for the optional local OCR value collector."""

from __future__ import annotations

import math

from .services.ocr_profiles import normalize_ocr_profile_ids


OCR_SETTINGS_KEY = "ocr"
DEFAULT_OCR_SETTINGS: dict[str, object] = {
    "enabled_slots": [],
    "background_enabled": False,
    "background_queue_visible_to_users": False,
    "idle_seconds": 5,
    "max_cpu_percent": 35,
    "pause_cpu_percent": 85,
    "max_memory_mode": "percent",
    "max_memory_percent": 30,
    "max_memory_gb": 4.0,
    "max_disk_busy_percent": 80,
    "queue_lease_minutes": 60,
    "queue_success_extension_minutes": 30,
    "model_profiles": ["fast"],
    "accurate_confidence_threshold": 99,
}


def default_ocr_settings() -> dict[str, object]:
    """Return a fresh default settings payload."""

    return dict(DEFAULT_OCR_SETTINGS)


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_float(value: object, default: float, minimum: float) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        parsed = float(value)
        if not math.isfinite(parsed) or parsed < minimum:
            raise ValueError
    except (TypeError, ValueError):
        parsed = default
    return parsed


def normalize_ocr_settings(value: object) -> dict[str, object]:
    """Return bounded, serializable OCR settings from an arbitrary payload."""

    raw = value if isinstance(value, dict) else {}
    raw_slots = raw.get("enabled_slots", [])
    slots: list[str] = []
    if isinstance(raw_slots, list):
        for raw_slot in raw_slots:
            slot = str(raw_slot or "").strip()
            if slot and slot not in slots:
                slots.append(slot)
    idle = _bounded_int(raw.get("idle_seconds"), 5, 0, 3600)
    maximum = _bounded_int(raw.get("max_cpu_percent"), 35, 0, 100)
    pause = max(maximum, _bounded_int(raw.get("pause_cpu_percent"), 85, 0, 100))
    memory_mode = raw.get("max_memory_mode")
    if memory_mode not in {"percent", "gigabytes"}:
        memory_mode = "percent"
    memory_percent = _bounded_int(raw.get("max_memory_percent"), 30, 1, 100)
    memory_gb = _bounded_float(raw.get("max_memory_gb"), 4.0, 0.1)
    disk_busy = _bounded_int(raw.get("max_disk_busy_percent"), 80, 0, 100)
    queue_lease = _bounded_int(raw.get("queue_lease_minutes"), 60, 1, 24 * 60)
    queue_extension = _bounded_int(
        raw.get("queue_success_extension_minutes"), 30, 0, 24 * 60
    )
    accurate_confidence_threshold = _bounded_int(
        raw.get("accurate_confidence_threshold"), 99, 0, 100
    )
    profiles = normalize_ocr_profile_ids(raw.get("model_profiles")) or ["fast"]
    return {
        "enabled_slots": slots,
        "background_enabled": bool(raw.get("background_enabled", False)),
        "background_queue_visible_to_users": bool(
            raw.get("background_queue_visible_to_users", False)
        ),
        "idle_seconds": idle,
        "max_cpu_percent": maximum,
        "pause_cpu_percent": pause,
        "max_memory_mode": memory_mode,
        "max_memory_percent": memory_percent,
        "max_memory_gb": memory_gb,
        "max_disk_busy_percent": disk_busy,
        "queue_lease_minutes": queue_lease,
        "queue_success_extension_minutes": queue_extension,
        "model_profiles": profiles,
        "accurate_confidence_threshold": accurate_confidence_threshold,
    }
