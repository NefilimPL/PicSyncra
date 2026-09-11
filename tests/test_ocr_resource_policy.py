from picsyncra.services.ocr_resource_policy import (
    OcrResourcePolicy,
    ResourceTelemetry,
)


def _settings(**overrides: object) -> dict[str, object]:
    return {
        "max_cpu_percent": 35,
        "pause_cpu_percent": 85,
        "max_memory_mode": "percent",
        "max_memory_percent": 30,
        "max_memory_gb": 4.0,
        "max_disk_busy_percent": 80,
        **overrides,
    }


def test_defers_a_new_stage_when_host_cpu_exceeds_admission_gate():
    decision = OcrResourcePolicy(_settings()).before_stage(
        ResourceTelemetry(
            cpu_percent=85,
            memory_used_bytes=2_000,
            memory_total_bytes=10_000,
            disk_busy_percent=10,
        )
    )

    assert decision.action == "defer"
    assert decision.reason == "host_cpu_admission"


def test_throttles_between_stages_when_memory_usage_exceeds_percent_target():
    decision = OcrResourcePolicy(_settings()).before_stage(
        ResourceTelemetry(
            cpu_percent=20,
            memory_used_bytes=3_001,
            memory_total_bytes=10_000,
            disk_busy_percent=10,
        )
    )

    assert decision.action == "throttle"
    assert decision.reason == "memory_usage"
    assert decision.retry_after_seconds > 0


def test_throttles_between_stages_when_disk_busy_target_is_exceeded():
    decision = OcrResourcePolicy(_settings()).before_stage(
        ResourceTelemetry(
            cpu_percent=20,
            memory_used_bytes=2_000,
            memory_total_bytes=10_000,
            disk_busy_percent=81,
        )
    )

    assert decision.action == "throttle"
    assert decision.reason == "disk_busy"


def test_allows_stage_when_admission_and_soft_usage_targets_are_met():
    decision = OcrResourcePolicy(_settings()).before_stage(
        ResourceTelemetry(
            cpu_percent=20,
            memory_used_bytes=3_000,
            memory_total_bytes=10_000,
            disk_busy_percent=80,
        )
    )

    assert decision.action == "run"
    assert decision.reason is None


def test_memory_limit_in_gigabytes_uses_current_usage_not_disk_capacity():
    decision = OcrResourcePolicy(
        _settings(max_memory_mode="gigabytes", max_memory_gb=4.5)
    ).before_stage(
        ResourceTelemetry(
            cpu_percent=20,
            memory_used_bytes=4_500_000_001,
            memory_total_bytes=32_000_000_000,
            disk_busy_percent=10,
        )
    )

    assert decision.action == "throttle"
    assert decision.reason == "memory_usage"
