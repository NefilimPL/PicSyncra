"""Authenticated WEB API for installed-only updates and remote restart."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ..installation.contracts import OperationRequest


@dataclass(frozen=True)
class InstallationApiDependencies:
    is_installed: Callable[[], bool]
    require_admin: Callable[[Request], dict[str, Any]]
    require_user: Callable[[Request], str]
    require_csrf: Callable[[Request], None]
    installation_status: Callable[[], dict[str, Any]]
    list_releases: Callable[[str], list[dict[str, Any]]]
    submit_operation: Callable[[OperationRequest, str], dict[str, Any]]
    read_operation: Callable[[str], dict[str, Any] | None]
    force_operation: Callable[[str], dict[str, Any] | None]
    change_channel: Callable[[str], dict[str, Any]]
    set_autostart: Callable[[bool], dict[str, Any]]
    heartbeat: Callable[[str, str], dict[str, Any]]
    public_status: Callable[[], dict[str, Any]]


def _require_installed(dependencies: InstallationApiDependencies) -> None:
    if not dependencies.is_installed():
        raise HTTPException(status_code=404, detail="Ta funkcja jest dostepna tylko w zainstalowanej aplikacji.")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise HTTPException(status_code=400, detail=f"Niepoprawne pole {field}.")
    return value.strip()


def _operation(payload: object) -> OperationRequest:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Niepoprawne dane operacji.")
    allowed = {"request_id", "action", "release_id", "restore_backup_id", "acknowledge_data_loss"}
    if not set(payload).issubset(allowed):
        raise HTTPException(status_code=400, detail="Niepoprawne dane operacji.")
    request_id = _text(payload.get("request_id"), "request_id")
    action = payload.get("action")
    release_id = payload.get("release_id")
    restore_backup_id = payload.get("restore_backup_id")
    acknowledged = payload.get("acknowledge_data_loss", False)
    if action not in {"update", "downgrade", "install_ocr", "restart"}:
        raise HTTPException(status_code=400, detail="Niepoprawny rodzaj operacji.")
    if release_id is not None and (isinstance(release_id, bool) or not isinstance(release_id, int) or release_id <= 0):
        raise HTTPException(status_code=400, detail="Niepoprawne wydanie.")
    if restore_backup_id is not None:
        restore_backup_id = _text(restore_backup_id, "restore_backup_id")
    if not isinstance(acknowledged, bool):
        raise HTTPException(status_code=400, detail="Niepoprawne potwierdzenie danych.")
    return OperationRequest(request_id, action, release_id, restore_backup_id, acknowledged)  # type: ignore[arg-type]


def build_installation_router(dependencies: InstallationApiDependencies) -> APIRouter:
    """Build installed-update routes without coupling portable WEB to updates."""
    router = APIRouter()

    @router.get("/api/installation")
    def installation_status(request: Request) -> dict[str, Any]:
        _require_installed(dependencies)
        dependencies.require_admin(request)
        return dependencies.installation_status()

    @router.get("/api/installation/releases")
    def installation_releases(request: Request, channel: str = "stable") -> dict[str, Any]:
        _require_installed(dependencies)
        dependencies.require_admin(request)
        if channel not in {"stable", "dev"}:
            raise HTTPException(status_code=400, detail="Niepoprawny kanal wydan.")
        return {"releases": dependencies.list_releases(channel)}

    @router.post("/api/installation/operations")
    async def installation_operation(request: Request) -> JSONResponse:
        _require_installed(dependencies)
        admin = dependencies.require_admin(request)
        dependencies.require_csrf(request)
        try:
            result = dependencies.submit_operation(
                _operation(await request.json()), str(admin.get("id") or admin.get("username") or "")
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(result, status_code=202)

    @router.get("/api/installation/operations/{operation_id}")
    def installation_operation_status(request: Request, operation_id: str) -> dict[str, Any]:
        _require_installed(dependencies)
        dependencies.require_admin(request)
        result = dependencies.read_operation(_text(operation_id, "operation_id"))
        if result is None:
            raise HTTPException(status_code=404, detail="Nie znaleziono operacji.")
        return result

    @router.post("/api/installation/operations/{operation_id}/force")
    def installation_force(request: Request, operation_id: str) -> JSONResponse:
        _require_installed(dependencies)
        dependencies.require_admin(request)
        dependencies.require_csrf(request)
        result = dependencies.force_operation(_text(operation_id, "operation_id"))
        if result is None:
            raise HTTPException(status_code=409, detail="Operacja nie moze zostac wymuszona.")
        return JSONResponse(result, status_code=202)

    @router.post("/api/installation/channel")
    async def installation_channel(request: Request) -> dict[str, Any]:
        _require_installed(dependencies)
        dependencies.require_admin(request)
        dependencies.require_csrf(request)
        payload = await request.json()
        channel = payload.get("channel") if isinstance(payload, dict) else None
        if channel not in {"stable", "dev"}:
            raise HTTPException(status_code=400, detail="Niepoprawny kanal wydan.")
        return dependencies.change_channel(channel)

    @router.post("/api/installation/autostart")
    async def installation_autostart(request: Request) -> dict[str, Any]:
        _require_installed(dependencies)
        dependencies.require_admin(request)
        dependencies.require_csrf(request)
        payload = await request.json()
        enabled = payload.get("enabled") if isinstance(payload, dict) else None
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=400, detail="Niepoprawna wartosc autostartu.")
        return dependencies.set_autostart(enabled)

    @router.get("/api/installation/presence")
    def installation_presence(request: Request, session_id: str) -> dict[str, Any]:
        _require_installed(dependencies)
        return dependencies.heartbeat(dependencies.require_user(request), _text(session_id, "session_id"))

    @router.get("/api/installation/public-status")
    def installation_public_status() -> dict[str, Any]:
        _require_installed(dependencies)
        return dependencies.public_status()

    return router


__all__ = ["InstallationApiDependencies", "build_installation_router"]
