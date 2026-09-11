"""Process-job query routes with explicit application dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .process_queue import OwnerQueueLimit, ProcessQueueFull


@dataclass(frozen=True)
class ProcessApiDependencies:
    current_user: Callable[[Request], str]
    queue: Any = None
    stage_form: Callable[[Request], Awaitable[Any]] | None = None
    cache_scope: Callable[[Request, str], str] | None = None
    job_store: Callable[..., dict[str, Any]] | None = None
    job_completion: Callable[[str], Any | None] | None = None
    job_snapshot: Callable[[str], dict[str, Any]] | None = None
    jobs_for_user: Callable[[str, int], list[dict[str, Any]]] | None = None
    active_jobs: Callable[[], dict[str, Any]] | None = None
    job_for_user: Callable[[str, str], dict[str, Any] | None] | None = None
    cancel_job: Callable[[str, str], dict[str, Any] | None] | None = None


def _reserve_process_capacity(queue: Any, cache_scope: str) -> Any:
    try:
        return queue.reserve(cache_scope)
    except (ProcessQueueFull, OwnerQueueLimit) as exc:
        retry_after = getattr(exc, "retry_after_seconds", None)
        if retry_after is None:
            limits = getattr(queue, "limits", None)
            retry_after = getattr(limits, "retry_after_seconds", 2)
        raise HTTPException(
            status_code=429,
            detail="Kolejka przetwarzania jest pelna. Sprobuj ponownie za chwile.",
            headers={"Retry-After": str(max(1, int(retry_after or 2)))},
        ) from exc


def build_process_router(dependencies: ProcessApiDependencies) -> APIRouter:
    router = APIRouter()

    async def queue_process_upload(
        request: Request,
        *,
        persist_as_running: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        if not all(
            (
                dependencies.queue is not None,
                dependencies.stage_form is not None,
                dependencies.cache_scope is not None,
                dependencies.job_store is not None,
            )
        ):
            raise RuntimeError("Brak zaleznosci kolejkowania przetwarzania.")
        username = dependencies.current_user(request)
        cache_scope = dependencies.cache_scope(request, username)
        reservation = _reserve_process_capacity(dependencies.queue, cache_scope)
        try:
            form = await dependencies.stage_form(request)
        except Exception:
            reservation.release()
            raise
        try:
            job = dependencies.job_store(
                username=username,
                cache_scope=cache_scope,
                form=form,
                reservation=reservation,
                persist_as_running=persist_as_running,
            )
        except Exception:
            reservation.release()
            raise
        return username, job

    @router.get("/api/process-jobs")
    def process_jobs(request: Request, limit: int = 20) -> dict[str, Any]:
        if dependencies.jobs_for_user is None:
            raise RuntimeError("Brak magazynu zadan przetwarzania.")
        return {"jobs": dependencies.jobs_for_user(dependencies.current_user(request), limit)}

    @router.get("/api/process-jobs/active")
    def active_process_jobs(request: Request) -> dict[str, Any]:
        dependencies.current_user(request)
        if dependencies.active_jobs is None:
            raise RuntimeError("Brak magazynu zadan przetwarzania.")
        return dependencies.active_jobs()

    @router.get("/api/process-jobs/{job_id}")
    def process_job(request: Request, job_id: str) -> dict[str, Any]:
        if dependencies.job_for_user is None:
            raise RuntimeError("Brak magazynu zadan przetwarzania.")
        job = dependencies.job_for_user(job_id, dependencies.current_user(request))
        if not job:
            raise HTTPException(status_code=404, detail="Nie znaleziono zadania.")
        return job

    @router.delete("/api/process-jobs/{job_id}")
    def cancel_process_job(request: Request, job_id: str) -> dict[str, Any]:
        if dependencies.cancel_job is None:
            raise RuntimeError("Brak magazynu zadan przetwarzania.")
        job = dependencies.cancel_job(job_id, dependencies.current_user(request))
        if not job:
            raise HTTPException(
                status_code=409,
                detail="Zadanie nie oczekuje juz w kolejce ani nie jest uruchomione.",
            )
        return {"cancelled": True, "job": job}

    @router.post("/api/process/background")
    async def process_uploads_background(request: Request) -> JSONResponse:
        _username, job = await queue_process_upload(request)
        return JSONResponse({"queued": True, "job": job})

    @router.post("/api/process")
    async def process_uploads(request: Request) -> JSONResponse:
        _username, queued = await queue_process_upload(request, persist_as_running=True)
        job_id = str(queued["job_id"])
        if dependencies.job_completion is None or dependencies.job_snapshot is None:
            raise RuntimeError("Brak magazynu zadan przetwarzania.")
        completion = dependencies.job_completion(job_id)
        if completion is None:
            raise HTTPException(status_code=500, detail="Nie znaleziono zadania kolejki.")
        await run_in_threadpool(completion.wait)
        job = dependencies.job_snapshot(job_id)
        if job.get("status") == "cancelled":
            raise HTTPException(status_code=409, detail="Zadanie zostalo anulowane.")
        if job.get("status") == "failed":
            status_code = max(400, int(job.get("error_status_code") or 500))
            if status_code >= 500:
                raise RuntimeError("process job failed")
            raise HTTPException(
                status_code=status_code,
                detail=str(job.get("error") or "Przetwarzanie zakonczone bledem."),
            )
        payload = job.get("result")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="Brak wyniku zadania kolejki.")
        return JSONResponse(payload)

    return router
