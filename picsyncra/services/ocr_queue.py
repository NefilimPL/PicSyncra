"""Cooperative idle-time scheduler for persisted OCR crop jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class OcrQueueLease:
    """Keep background OCR alive from user activity, extending after success."""

    def __init__(self, *, last_activity: Callable[[], float]) -> None:
        self._last_activity = last_activity
        self._observed_activity: float | None = None
        self._successful_jobs = 0

    def allows(self, *, now: float, settings: dict[str, object]) -> bool:
        activity = float(self._last_activity())
        if self._observed_activity != activity:
            self._observed_activity = activity
            self._successful_jobs = 0
        base_minutes = self._minutes(settings.get("queue_lease_minutes"), 60)
        extension_minutes = self._minutes(
            settings.get("queue_success_extension_minutes"), 30
        )
        expires_at = activity + (base_minutes + extension_minutes * self._successful_jobs) * 60
        return float(now) <= expires_at

    def record_success(self) -> None:
        self._successful_jobs += 1

    @staticmethod
    def _minutes(value: object, default: int) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return default


class OcrQueueScheduler:
    """Process at most one crop while user activity and CPU allow it."""

    def __init__(
        self,
        *,
        settings: Callable[[], dict[str, object]],
        has_active_requests: Callable[[], bool],
        last_activity: Callable[[], float],
        cpu_percent: Callable[[], float],
        claim_job: Callable[[], dict[str, object] | None],
        process_job: Callable[[dict[str, object]], Any],
        requeue_job: Callable[[dict[str, object]], Any] | None = None,
        lease: OcrQueueLease | None = None,
        now: Callable[[], float],
    ) -> None:
        self._settings = settings
        self._has_active_requests = has_active_requests
        self._last_activity = last_activity
        self._cpu_percent = cpu_percent
        self._claim_job = claim_job
        self._process_job = process_job
        self._requeue_job = requeue_job or (lambda _job: None)
        self._now = now
        self._lease = lease or OcrQueueLease(last_activity=last_activity)

    def run_once(self) -> str:
        settings = self._settings()
        if not bool(settings.get("background_enabled")):
            return "disabled"
        if self._has_active_requests():
            return "busy"
        if self._now() - self._last_activity() < float(settings.get("idle_seconds", 0)):
            return "idle_wait"
        if not self._lease.allows(now=self._now(), settings=settings):
            return "lease_expired"
        cpu_percent = self._cpu_percent()
        if cpu_percent >= float(settings.get("pause_cpu_percent", 100)):
            return "cpu_pause"
        job = self._claim_job()
        if job is None:
            return "empty"
        try:
            self._process_job(job)
        except Exception:
            self._requeue_job(job)
            return "requeued_error"
        if self._has_active_requests():
            self._requeue_job(job)
            return "requeued"
        self._lease.record_success()
        return "processed"
