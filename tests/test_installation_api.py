from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request


class RequestStub:
    def __init__(self, payload=None, *, csrf: str = "") -> None:
        self._payload = payload
        self.headers = {"x-picsyncra-csrf": csrf}

    async def json(self):
        return self._payload


def app_with_dependencies(*, installed: bool = True):
    from picsyncra.web.installation_api import InstallationApiDependencies, build_installation_router

    calls: list[object] = []

    def require_admin(_request: Request):
        return {"id": "admin-1", "username": "admin", "role": "admin"}

    def require_user(_request: Request):
        return "operator-1"

    def require_csrf(request: Request):
        if request.headers.get("x-picsyncra-csrf") != "valid":
            raise HTTPException(status_code=403, detail="csrf")

    def submit(payload, actor_id: str):
        calls.append((payload, actor_id))
        return {"operation_id": "op-1", "state": "downloading"}

    router = build_installation_router(InstallationApiDependencies(
        is_installed=lambda: installed,
        require_admin=require_admin,
        require_user=require_user,
        require_csrf=require_csrf,
        installation_status=lambda: {"channel": "stable", "build": "41"},
        list_releases=lambda channel: [{"release_id": 42, "channel": channel}],
        submit_operation=submit,
        read_operation=lambda operation_id: {"operation_id": operation_id, "state": "draining"},
        force_operation=lambda operation_id: {"operation_id": operation_id, "state": "draining", "force_allowed": True},
        change_channel=lambda channel: {"channel": channel},
        set_autostart=lambda enabled: {"autostart": enabled},
        heartbeat=lambda user_id, session_id: {"user": user_id, "session": session_id},
        public_status=lambda: {"state": "countdown", "deadline_utc": "2026-09-16T12:00:00Z"},
    ))
    return {route.path: route.endpoint for route in router.routes}, calls


def test_portable_runtime_does_not_expose_installed_update_endpoints() -> None:
    routes, _calls = app_with_dependencies(installed=False)
    with pytest.raises(HTTPException) as error:
        routes["/api/installation"](RequestStub())
    assert error.value.status_code == 404


def test_installation_status_and_release_channel_require_admin() -> None:
    routes, _calls = app_with_dependencies()
    assert routes["/api/installation"](RequestStub()) == {"channel": "stable", "build": "41"}
    assert routes["/api/installation/releases"](RequestStub(), "dev") == {"releases": [{"release_id": 42, "channel": "dev"}]}
    with pytest.raises(HTTPException) as error:
        routes["/api/installation/releases"](RequestStub(), "preview")
    assert error.value.status_code == 400


def test_operation_submission_requires_csrf_and_uses_server_actor_identity() -> None:
    routes, calls = app_with_dependencies()
    payload = {"request_id": "request-1", "action": "restart", "release_id": None,
               "restore_backup_id": None, "acknowledge_data_loss": False}
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes["/api/installation/operations"](RequestStub(payload)))
    assert error.value.status_code == 403
    accepted = asyncio.run(routes["/api/installation/operations"](RequestStub(payload, csrf="valid")))
    assert accepted.status_code == 202
    assert b'"operation_id":"op-1"' in accepted.body
    assert calls[0][1] == "admin-1"
    assert not hasattr(calls[0][0], "actor_id")


def test_force_channel_and_autostart_are_csrf_protected_admin_mutations() -> None:
    routes, _calls = app_with_dependencies()
    request = RequestStub(csrf="valid")
    assert routes["/api/installation/operations/{operation_id}/force"](request, "op-1").status_code == 202
    assert asyncio.run(routes["/api/installation/channel"](RequestStub({"channel": "dev"}, csrf="valid"))) == {"channel": "dev"}
    assert asyncio.run(routes["/api/installation/autostart"](RequestStub({"enabled": True}, csrf="valid"))) == {"autostart": True}


def test_presence_requires_logged_in_user_but_public_status_needs_no_session() -> None:
    routes, _calls = app_with_dependencies()
    assert routes["/api/installation/public-status"]() == {"state": "countdown", "deadline_utc": "2026-09-16T12:00:00Z"}
    assert routes["/api/installation/presence"](RequestStub(), "tab-1") == {"user": "operator-1", "session": "tab-1"}
