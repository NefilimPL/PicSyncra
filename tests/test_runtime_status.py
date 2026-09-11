"""Contract tests for the consolidated runtime status endpoint."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from picsyncra.web import app as web_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(web_app.app)


def _provider_patches(*, role: str = "admin"):
    return [
        patch.object(
            web_app,
            "_current_user_payload",
            return_value={"username": role, "role": role},
        ),
        patch.object(web_app, "_health_payload", return_value={"ok": True}),
        patch.object(
            web_app,
            "file_index_status",
            return_value={"generated_at": "index-1", "state": "ready"},
        ),
        patch.object(
            web_app,
            "_runtime_process_queue_summary",
            return_value={"generation": "queue-1", "active_count": 0},
        ),
        patch.object(
            web_app,
            "_runtime_active_clients_summary",
            return_value={"generation": "clients-1", "count": 0},
        ),
    ]


def _payload_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(_payload_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(_payload_keys(item))
        return keys
    return set()


def test_runtime_status_contains_summaries_not_detail_lists(
    client: TestClient,
) -> None:
    patches = _provider_patches()
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        response = client.get("/api/runtime-status")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"observed_at", "health", "versions", "summary"}
    assert "jobs" not in payload
    assert "users" not in payload
    assert "events" not in payload


def test_runtime_status_service_has_an_injected_summary_only_contract() -> None:
    from picsyncra.web.runtime_status import RuntimeStatusService

    service = RuntimeStatusService(
        health_provider=lambda: {
            "ok": True,
            "status": "online",
            "events": [{"traceback": "private"}],
        },
        file_index_provider=lambda: {
            "generated_at": "index-1",
            "state": "ready",
            "files": ["secret.jpg"],
        },
        process_queue_provider=lambda: {
            "generation": "queue-1",
            "active_count": 0,
            "jobs": [{"username": "alice"}],
        },
        active_clients_provider=lambda: {
            "generation": "clients-1",
            "count": 2,
            "users": ["alice", "bob"],
        },
        clock=lambda: "2026-07-27T10:00:00Z",
    )

    assert service.snapshot({"username": "admin", "role": "admin"}) == {
        "observed_at": "2026-07-27T10:00:00Z",
        "health": {"ok": True, "status": "online"},
        "versions": {
            "file_index": "index-1:ready",
            "process_queue": "queue-1",
            "active_clients": "clients-1",
        },
        "summary": {
            "file_index_state": "ready",
            "process_active": 0,
            "active_users_enabled": True,
            "active_users_count": 2,
        },
    }


def test_runtime_status_hides_presence_from_non_admin(
    client: TestClient,
) -> None:
    patches = _provider_patches(role="operator")
    with patches[0], patches[1], patches[2], patches[3], patches[4] as active_provider:
        response = client.get("/api/runtime-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["versions"]["active_clients"] == "unknown"
    assert payload["summary"]["active_users_enabled"] is False
    assert "active_users_count" not in payload["summary"]
    assert "users" not in _payload_keys(payload)
    active_provider.assert_not_called()


def test_runtime_status_admin_gets_presence_count_without_names(
    client: TestClient,
) -> None:
    patches = _provider_patches()
    patches[-1] = patch.object(
        web_app,
        "_runtime_active_clients_summary",
        return_value={
            "generation": 23,
            "count": 2,
            "users": ["alice", "bob"],
        },
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        response = client.get("/api/runtime-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["versions"]["active_clients"] == 23
    assert payload["summary"]["active_users_enabled"] is True
    assert payload["summary"]["active_users_count"] == 2
    assert "alice" not in response.text
    assert "bob" not in response.text
    assert "users" not in _payload_keys(payload)


def test_runtime_status_returns_unknown_when_one_provider_fails(
    client: TestClient,
) -> None:
    patches = _provider_patches()
    patches[2] = patch.object(
        web_app,
        "file_index_status",
        side_effect=RuntimeError("private traceback marker"),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        response = client.get("/api/runtime-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["versions"]["file_index"] == "unknown"
    assert payload["summary"]["file_index_state"] == "unknown"
    assert payload["versions"]["process_queue"] == "queue-1"
    assert "traceback" not in response.text.lower()
    assert "private traceback marker" not in response.text


def test_process_queue_generation_is_stable_until_queue_state_changes() -> None:
    job_id = "runtime-status-generation"
    job = {"id": job_id, "status": "running", "progress": 1}
    with web_app._PROCESS_JOBS_LOCK:
        web_app._PROCESS_JOBS[job_id] = job
    try:
        before = web_app._runtime_process_queue_summary()
        unchanged = web_app._runtime_process_queue_summary()
        web_app._set_process_job_progress(job_id, 2, "Working")
        changed = web_app._runtime_process_queue_summary()
    finally:
        with web_app._PROCESS_JOBS_LOCK:
            web_app._PROCESS_JOBS.pop(job_id, None)

    assert unchanged["generation"] == before["generation"]
    assert changed["generation"] > before["generation"]
    assert changed["active_count"] == before["active_count"]


def test_process_queue_runtime_summary_does_not_build_detailed_snapshot() -> None:
    with web_app._PROCESS_JOBS_LOCK:
        original = dict(web_app._PROCESS_JOBS)
        web_app._PROCESS_JOBS.clear()
        web_app._PROCESS_JOBS.update(
            {
                "queued": {"status": "queued"},
                "running": {"status": "running"},
                "completed": {"status": "completed"},
            }
        )
        expected_generation = web_app._PROCESS_QUEUE_GENERATION
    try:
        with (
            patch.object(
                web_app,
                "_active_process_jobs_snapshot",
                side_effect=AssertionError("detailed snapshot was constructed"),
            ),
            patch.object(
                web_app,
                "_cleanup_process_jobs",
                side_effect=AssertionError("runtime polling performed cleanup"),
            ),
        ):
            summary = web_app._runtime_process_queue_summary()
    finally:
        with web_app._PROCESS_JOBS_LOCK:
            web_app._PROCESS_JOBS.clear()
            web_app._PROCESS_JOBS.update(original)

    assert summary == {
        "generation": expected_generation,
        "active_count": 2,
    }


def test_runtime_active_client_summary_uses_atomic_registry_projection() -> None:
    registry = Mock()
    registry.closed = False
    registry.runtime_summary.return_value = {
        "generation": 41,
        "active_user_count": 131,
    }
    registry.snapshot.side_effect = AssertionError("capped client snapshot was used")

    with patch.object(web_app, "_ACTIVE_CLIENT_REGISTRY", registry):
        summary = web_app._runtime_active_clients_summary()

    assert summary == {"generation": 41, "count": 131}
    registry.runtime_summary.assert_called_once_with()
    registry.snapshot.assert_not_called()
    registry.schedule_flush.assert_called_once_with()


def test_runtime_status_checks_file_index_without_starting_refresh(
    client: TestClient,
) -> None:
    patches = _provider_patches()
    patches[2] = patch.object(
        web_app,
        "file_index_status",
        return_value={"generated_at": "index-1", "state": "ready"},
    )
    with (
        patches[0],
        patches[1],
        patches[2] as file_index_provider,
        patches[3],
        patches[4],
    ):
        response = client.get("/api/runtime-status")

    assert response.status_code == 200
    file_index_provider.assert_called_once_with(start=False)


def test_runtime_status_is_excluded_from_active_client_tracking() -> None:
    registry = Mock()
    request = SimpleNamespace(
        url=SimpleNamespace(path="/api/runtime-status"),
        client=SimpleNamespace(host="127.0.0.1", port=12345),
        headers={"user-agent": "test"},
        method="GET",
    )

    with (
        patch.object(web_app, "_ACTIVE_CLIENT_REGISTRY", registry),
        patch.object(web_app, "_current_user") as current_user,
    ):
        web_app._record_active_client(request, 200)

    current_user.assert_not_called()
    registry.record.assert_not_called()
    registry.schedule_flush.assert_not_called()
