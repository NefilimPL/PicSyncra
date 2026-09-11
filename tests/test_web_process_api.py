from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, Mock


def test_process_router_delegates_job_queries_and_cancellation() -> None:
    from picsyncra.web.process_api import ProcessApiDependencies, build_process_router

    app = FastAPI()
    app.include_router(
        build_process_router(
            ProcessApiDependencies(
                current_user=lambda _request: "alice",
                jobs_for_user=lambda username, limit: [{"id": "one", "owner": username, "limit": limit}],
                active_jobs=lambda: {"jobs": [{"id": "one"}]},
                job_for_user=lambda job_id, username: {"id": job_id, "owner": username},
                cancel_job=lambda job_id, username: {"id": job_id, "owner": username},
            )
        )
    )
    client = TestClient(app)

    assert client.get("/api/process-jobs?limit=5").json() == {
        "jobs": [{"id": "one", "owner": "alice", "limit": 5}]
    }
    assert client.get("/api/process-jobs/active").json() == {"jobs": [{"id": "one"}]}
    assert client.get("/api/process-jobs/one").json() == {"id": "one", "owner": "alice"}
    assert client.delete("/api/process-jobs/one").json() == {
        "cancelled": True,
        "job": {"id": "one", "owner": "alice"},
    }


def test_process_router_reserves_capacity_before_staging_a_background_upload() -> None:
    """Catches extracted upload routes that stage files before reserving queue capacity."""
    from picsyncra.web.process_api import ProcessApiDependencies, build_process_router

    reservation = Mock()
    queue = Mock()
    queue.reserve.return_value = reservation
    stage_form = AsyncMock(return_value=Mock())
    job_store = Mock(return_value={"job_id": "job-1"})
    app = FastAPI()
    app.include_router(
        build_process_router(
            ProcessApiDependencies(
                queue=queue,
                stage_form=stage_form,
                current_user=lambda _request: "alice",
                cache_scope=lambda _request, _username: "scope-a",
                job_store=job_store,
            )
        )
    )

    response = TestClient(app).post(
        "/api/process/background",
        data={"ean": "5901234567890", "name": "ALFA"},
        files={"slot_1": ("photo.jpg", b"photo", "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json() == {"queued": True, "job": {"job_id": "job-1"}}
    queue.reserve.assert_called_once_with("scope-a")
