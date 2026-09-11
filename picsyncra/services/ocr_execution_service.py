"""One dispatch path for live OCR tester work and persistent OCR jobs."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Protocol

from .ocr_progress import OcrProgressRegistry, OcrRunSnapshot
from .ocr_resource_policy import OcrResourcePolicy, ResourceTelemetry


class OcrWorker(Protocol):
    def start(self) -> None: ...

    def submit(
        self,
        *,
        run_id: str,
        path: str,
        profile_ids: list[object],
        resource_settings: dict[str, object] | None = None,
    ) -> None: ...

    def update_telemetry(self, telemetry: ResourceTelemetry) -> None: ...

    def poll_events(self) -> list[dict[str, object]]: ...

    def cancel(self, run_id: str) -> None: ...

    def update_limits(self, *, cpu_percent: int) -> None: ...

    def status(self) -> dict[str, object]: ...


class OcrExecutionService:
    """Translate worker messages into browser-safe ordered OCR snapshots."""

    def __init__(
        self,
        *,
        worker: OcrWorker,
        registry: OcrProgressRegistry,
        settings: Callable[[], dict[str, object]],
        telemetry: Callable[[], ResourceTelemetry],
        on_worker_ready: Callable[[int], None] | None = None,
    ) -> None:
        self._worker = worker
        self._registry = registry
        self._settings = settings
        self._telemetry = telemetry
        self._on_worker_ready = on_worker_ready
        self._inflight_run_ids: set[str] = set()

    def start(self) -> None:
        self._worker.start()

    def submit_test(self, *, path: str) -> str:
        return self._submit(kind="test", job_id=None, path=path)

    def submit_queue(
        self,
        *,
        job_id: str,
        path: str,
        profile_ids: list[object] | None = None,
    ) -> str:
        """Submit a persisted crop through the exact same controlled pipeline."""

        return self._submit(
            kind="queue",
            job_id=job_id,
            path=path,
            profile_ids=profile_ids,
        )

    def _submit(
        self,
        *,
        kind: str,
        job_id: str | None,
        path: str,
        profile_ids: list[object] | None = None,
    ) -> str:
        settings = self._settings()
        run_id = self._registry.create_run(kind=kind, job_id=job_id)
        telemetry = self._telemetry()
        self._worker.update_telemetry(telemetry)
        try:
            self._worker.update_limits(
                cpu_percent=int(settings.get("max_cpu_percent") or 35)
            )
        except (TypeError, ValueError):
            self._worker.update_limits(cpu_percent=35)
        decision = OcrResourcePolicy(settings).before_stage(telemetry)
        if decision.action == "defer":
            self._registry.publish(
                run_id,
                "paused",
                reason=decision.reason,
                retry_after_seconds=decision.retry_after_seconds,
            )
            self._registry.finalize(run_id, state="paused")
            return run_id
        profiles = profile_ids if isinstance(profile_ids, list) else settings.get("model_profiles")
        selected = [str(item) for item in profiles] if isinstance(profiles, list) else []
        if not selected:
            self._registry.publish(run_id, "error", message="No OCR profile selected.")
            self._registry.finalize(run_id, state="error", error="No OCR profile selected.")
            return run_id
        self._registry.publish(run_id, "queued", stage="waiting_for_worker")
        self._inflight_run_ids.add(run_id)
        self._worker.submit(
            run_id=run_id,
            path=str(path),
            profile_ids=selected,
            resource_settings=settings,
        )
        return run_id

    def pump(self) -> None:
        """Move all currently available child-process messages into the registry."""

        self._worker.update_telemetry(self._telemetry())
        for event in self._worker.poll_events():
            run_id = str(event.get("run_id") or "")
            kind = str(event.get("kind") or "")
            if kind == "ready" and self._on_worker_ready is not None:
                try:
                    self._on_worker_ready(int(event.get("pid") or 0))
                except (TypeError, ValueError):
                    pass
            if not run_id or not kind:
                continue
            payload = {
                str(key): value
                for key, value in event.items()
                if key not in {"kind", "run_id"}
            }
            try:
                self._registry.publish(run_id, kind, **payload)
                if kind == "result":
                    self._inflight_run_ids.discard(run_id)
                    diagnostics = payload.get("diagnostics")
                    result = diagnostics if isinstance(diagnostics, dict) else {}
                    self._registry.finalize(run_id, state="completed", result=result)
                elif kind == "error":
                    self._inflight_run_ids.discard(run_id)
                    self._registry.finalize(
                        run_id, state="error", error=str(payload.get("message") or "OCR error")
                    )
            except KeyError:
                continue
        self._finalize_runs_for_stopped_worker()

    def snapshot(self, run_id: str, *, after_sequence: int = 0) -> OcrRunSnapshot:
        self.pump()
        return self._registry.snapshot(run_id, after_sequence=after_sequence)

    def wait_for_terminal(self, run_id: str, *, timeout_seconds: float) -> OcrRunSnapshot:
        """Wait in a queue thread while the isolated worker continues independently."""

        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        while True:
            snapshot = self.snapshot(run_id)
            if snapshot.state in {"completed", "error", "cancelled", "paused"}:
                return snapshot
            if time.monotonic() >= deadline:
                raise TimeoutError("OCR worker did not finish before queue timeout.")
            time.sleep(0.1)

    def cancel(self, run_id: str) -> None:
        self._registry.request_cancel(run_id)
        self._worker.cancel(run_id)

    def _finalize_runs_for_stopped_worker(self) -> None:
        status_method = getattr(self._worker, "status", None)
        if not callable(status_method):
            return
        try:
            status = status_method()
        except Exception:
            return
        if not isinstance(status, dict) or status.get("alive") is not False:
            return
        exit_code = status.get("exit_code")
        suffix = f" (kod {exit_code})." if isinstance(exit_code, int) else "."
        message = "Proces OCR zakonczyl sie przed rozpoczeciem zadania" + suffix
        for run_id in tuple(self._inflight_run_ids):
            try:
                self._registry.publish(run_id, "error", message=message)
                self._registry.finalize(run_id, state="error", error=message)
            except KeyError:
                pass
            finally:
                self._inflight_run_ids.discard(run_id)
