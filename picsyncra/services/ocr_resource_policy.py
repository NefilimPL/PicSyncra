"""Pure resource-limit decisions made between OCR inference stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GIGABYTE_BYTES = 1_000_000_000


@dataclass(frozen=True)
class ResourceTelemetry:
    """Current host usage relevant to admission and soft OCR limits."""

    cpu_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    disk_busy_percent: float


@dataclass(frozen=True)
class ResourceDecision:
    """A safe-boundary OCR action; active inference is never interrupted."""

    action: Literal["run", "throttle", "defer"]
    reason: str | None = None
    retry_after_seconds: float = 0.0


def memory_limit_bytes(settings: dict[str, object], total_memory_bytes: int) -> int:
    """Resolve the configured RAM usage target to bytes."""

    if settings.get("max_memory_mode") == "gigabytes":
        try:
            return max(0, int(float(settings.get("max_memory_gb", 4.0)) * GIGABYTE_BYTES))
        except (TypeError, ValueError):
            return 4 * GIGABYTE_BYTES
    try:
        percent = float(settings.get("max_memory_percent", 30))
    except (TypeError, ValueError):
        percent = 30.0
    return max(0, int(max(0.0, min(100.0, percent)) * max(0, total_memory_bytes) / 100))


class OcrResourcePolicy:
    """Decide whether a future OCR stage may begin or should wait."""

    def __init__(self, settings: dict[str, object]) -> None:
        self._settings = settings

    def before_stage(self, telemetry: ResourceTelemetry) -> ResourceDecision:
        """Return a decision for a stage that has not started yet."""

        if telemetry.cpu_percent >= self._number("pause_cpu_percent", 100.0):
            return ResourceDecision("defer", "host_cpu_admission", 2.0)

        memory_limit = memory_limit_bytes(self._settings, telemetry.memory_total_bytes)
        if memory_limit and telemetry.memory_used_bytes > memory_limit:
            return ResourceDecision("throttle", "memory_usage", 2.0)

        if telemetry.disk_busy_percent > self._number("max_disk_busy_percent", 100.0):
            return ResourceDecision("throttle", "disk_busy", 1.0)

        return ResourceDecision("run")

    def _number(self, key: str, default: float) -> float:
        try:
            return float(self._settings.get(key, default))
        except (TypeError, ValueError):
            return default
