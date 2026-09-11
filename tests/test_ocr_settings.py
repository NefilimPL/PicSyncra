from picsyncra.ocr_settings import normalize_ocr_settings
from picsyncra.services.ocr_profiles import available_ocr_profiles


def test_normalize_ocr_settings_bounds_idle_and_cpu_limits():
    assert normalize_ocr_settings(
        {"idle_seconds": -1, "max_cpu_percent": 101}
    ) == {
        "enabled_slots": [],
        "background_enabled": False,
        "background_queue_visible_to_users": False,
        "idle_seconds": 0,
        "max_cpu_percent": 100,
        "pause_cpu_percent": 100,
        "max_memory_mode": "percent",
        "max_memory_percent": 30,
        "max_memory_gb": 4.0,
        "max_disk_busy_percent": 80,
        "queue_lease_minutes": 60,
        "queue_success_extension_minutes": 30,
        "model_profiles": ["fast"],
        "accurate_confidence_threshold": 99,
    }


def test_normalize_ocr_settings_removes_duplicate_and_empty_slots():
    assert normalize_ocr_settings({"enabled_slots": ["15", "", "15", 16]})[
        "enabled_slots"
    ] == ["15", "16"]


def test_normalize_ocr_settings_keeps_background_queue_visibility_flag():
    assert normalize_ocr_settings({"background_queue_visible_to_users": True})[
        "background_queue_visible_to_users"
    ] is True


def test_normalize_ocr_settings_keeps_known_profiles_in_requested_order():
    assert normalize_ocr_settings(
        {"model_profiles": ["accurate", "fast", "unknown", "accurate"]}
    )["model_profiles"] == ["accurate", "fast"]


def test_normalize_ocr_settings_bounds_accurate_confidence_threshold():
    assert normalize_ocr_settings({})["accurate_confidence_threshold"] == 99
    assert normalize_ocr_settings({"accurate_confidence_threshold": -1})[
        "accurate_confidence_threshold"
    ] == 0
    assert normalize_ocr_settings({"accurate_confidence_threshold": 101})[
        "accurate_confidence_threshold"
    ] == 100


def test_normalize_ocr_settings_keeps_usage_limits_with_safe_defaults():
    settings = normalize_ocr_settings(
        {
            "max_memory_mode": "gigabytes",
            "max_memory_percent": 0,
            "max_memory_gb": "4.5",
            "max_disk_busy_percent": 101,
        }
    )

    assert settings["max_memory_mode"] == "gigabytes"
    assert settings["max_memory_percent"] == 1
    assert settings["max_memory_gb"] == 4.5
    assert settings["max_disk_busy_percent"] == 100


def test_normalize_ocr_settings_falls_back_from_invalid_memory_limits():
    settings = normalize_ocr_settings(
        {
            "max_memory_mode": "capacity",
            "max_memory_percent": "not-a-number",
            "max_memory_gb": -2,
            "max_disk_busy_percent": -1,
        }
    )

    assert settings["max_memory_mode"] == "percent"
    assert settings["max_memory_percent"] == 30
    assert settings["max_memory_gb"] == 4.0
    assert settings["max_disk_busy_percent"] == 0


def test_local_ocr_profiles_describe_mobile_and_server_engines():
    profiles = {profile.id: profile for profile in available_ocr_profiles()}

    assert profiles["fast"].recognizer_model == "PP-OCRv5_mobile_rec"
    assert profiles["accurate"].recognizer_model == "PP-OCRv5_server_rec"
