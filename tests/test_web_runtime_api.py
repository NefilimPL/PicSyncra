from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_runtime_router_delegates_status_index_and_presence_operations() -> None:
    from picsyncra.web.runtime_api import RuntimeApiDependencies, build_runtime_router

    app = FastAPI()
    app.include_router(
        build_runtime_router(
            RuntimeApiDependencies(
                current_user_payload=lambda _request: {"username": "alice"},
                require_user=lambda _request: "alice",
                require_admin=lambda _request: {"username": "admin", "role": "admin"},
                runtime_status=lambda user: {"runtime": user["username"]},
                file_index_status=lambda: {"state": "ready"},
                refresh_file_index=lambda: {"refreshed": True},
                active_clients=lambda: [{"username": "alice"}],
                presence_payload=lambda clients: {"users": clients},
                request_client_id=lambda _request: "browser-1",
                remove_active_client=lambda username, client_id: username == "alice" and client_id == "browser-1",
            )
        )
    )
    client = TestClient(app)

    assert client.get("/api/runtime-status").json() == {"runtime": "alice"}
    assert client.get("/api/file-index/status").json() == {"state": "ready"}
    assert client.get("/api/server/active-users").json() == {
        "clients": [{"username": "alice"}]
    }
    assert client.get("/api/server/presence").json() == {
        "users": [{"username": "alice"}]
    }
    assert client.post("/api/server/presence/leave").json() == {
        "ok": True,
        "removed": True,
    }
    assert client.post("/api/file-index/refresh").json() == {"refreshed": True}
