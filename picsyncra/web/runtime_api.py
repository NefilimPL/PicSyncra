"""Runtime, file-index, and presence routes with explicit dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request


@dataclass(frozen=True)
class RuntimeApiDependencies:
    current_user_payload: Callable[[Request], dict[str, Any]]
    require_user: Callable[[Request], str]
    require_admin: Callable[[Request], Any]
    runtime_status: Callable[[dict[str, Any]], dict[str, Any]]
    file_index_status: Callable[[], dict[str, Any]]
    refresh_file_index: Callable[[], dict[str, Any]]
    active_clients: Callable[[], list[dict[str, Any]]]
    presence_payload: Callable[[list[dict[str, Any]]], dict[str, Any]]
    request_client_id: Callable[[Request], str]
    remove_active_client: Callable[[str, str], bool]


def build_runtime_router(dependencies: RuntimeApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/api/runtime-status")
    def runtime_status(request: Request) -> dict[str, Any]:
        return dependencies.runtime_status(dependencies.current_user_payload(request))

    @router.get("/api/file-index/status")
    def file_index_status(request: Request) -> dict[str, Any]:
        dependencies.require_user(request)
        return dependencies.file_index_status()

    @router.get("/api/server/active-users")
    def active_users(request: Request) -> dict[str, Any]:
        dependencies.require_admin(request)
        return {"clients": dependencies.active_clients()}

    @router.get("/api/server/presence")
    def active_presence(request: Request) -> dict[str, Any]:
        dependencies.require_user(request)
        return dependencies.presence_payload(dependencies.active_clients())

    @router.post("/api/server/presence/leave")
    def leave_active_presence(request: Request) -> dict[str, Any]:
        username = dependencies.require_user(request)
        removed = dependencies.remove_active_client(
            username, dependencies.request_client_id(request)
        )
        return {"ok": True, "removed": removed}

    @router.post("/api/file-index/refresh")
    def refresh_file_index(request: Request) -> dict[str, Any]:
        dependencies.require_admin(request)
        return dependencies.refresh_file_index()

    return router
