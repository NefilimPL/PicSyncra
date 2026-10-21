"""Reject incomplete drafts before the UI is allowed to clear them."""

from copy import deepcopy
import asyncio
from io import BytesIO
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from starlette.datastructures import FormData, UploadFile
from starlette.requests import ClientDisconnect, Request

from picsyncra import common
from picsyncra.web import app as web_app
from picsyncra.web.process_queue import ProcessQueueService, QueueLimits


@pytest.fixture
def draft_client(monkeypatch, tmp_path):
    cfg = deepcopy(common.DEFAULT_CONFIG)
    monkeypatch.setattr(web_app.config, "CONFIG", cfg)
    monkeypatch.setattr(web_app, "_require_user", lambda _request: "operator")
    monkeypatch.setattr(web_app, "_PROCESS_JOB_ROOT", tmp_path / "jobs")
    queue = ProcessQueueService(QueueLimits(workers=1, max_pending=1), start_workers=False)
    monkeypatch.setattr(web_app, "_PROCESS_QUEUE", queue)
    enqueue = Mock(return_value={"job_id": "accepted-job"})
    monkeypatch.setattr(web_app, "_queue_process_job", enqueue)
    client = TestClient(web_app.create_app(), raise_server_exceptions=False)
    yield client, enqueue, queue, cfg
    client.close()
    queue.shutdown()


@pytest.mark.parametrize("endpoint", ["/api/process/background", "/api/process"])
@pytest.mark.parametrize("ean", ["", "5901234567890"])
def test_missing_color_is_rejected_before_accepting_a_job(draft_client, endpoint, ean):
    client, enqueue, queue, _cfg = draft_client
    response = client.post(endpoint, data={
        "name": "TEST", "type_name": "TEST", "model": "test", "color1": "  ", "ean": ean,
    })

    assert response.status_code == 400
    assert "Kolor 1" in response.json()["detail"]
    enqueue.assert_not_called()
    # Rejection must release the reservation so correcting the draft can succeed.
    reservation = queue.reserve("another-draft")
    reservation.release()


def test_invalid_ean_is_rejected_before_accepting_a_job(draft_client):
    client, enqueue, _queue, _cfg = draft_client
    response = client.post("/api/process/background", data={
        "name": "TEST", "type_name": "TEST", "model": "test", "color1": "NEW COLOR", "ean": "123",
    })
    assert response.status_code == 400
    assert "13 cyfr" in response.json()["detail"]
    enqueue.assert_not_called()


def test_rejected_draft_keeps_cached_photos_and_cleans_staging(draft_client, tmp_path, monkeypatch):
    client, enqueue, _queue, _cfg = draft_client
    monkeypatch.setattr(web_app.settings, "AC", str(tmp_path))
    photo = tmp_path / "web_upload_cache" / "cached-photo.jpg"
    photo.parent.mkdir()
    photo.write_bytes(b"cached photo")
    token = web_app._file_token(str(photo))
    response = client.post("/api/process/background", data={
        "name": "TEST", "type_name": "TEST", "model": "test",
        "existing_slot_01": token,
    })
    assert response.status_code == 400
    assert photo.read_bytes() == b"cached photo"
    assert web_app._path_from_file_token(token) == str(photo)
    assert list((tmp_path / "jobs").iterdir()) == []
    enqueue.assert_not_called()


def test_rejecting_draft_closes_multipart_upload_handles(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app.config, "CONFIG", deepcopy(common.DEFAULT_CONFIG))
    monkeypatch.setattr(web_app, "_PROCESS_JOB_ROOT", tmp_path / "jobs")
    upload = UploadFile(file=BytesIO(b"photo"), filename="photo.jpg")
    request = Request({"type": "http", "method": "POST", "path": "/api/process/background"})
    request._form = FormData({
        "name": "TEST", "type_name": "TEST", "model": "test", "slot_01": upload,
    })
    with pytest.raises(HTTPException) as caught:
        asyncio.run(web_app._stage_process_form(request))
    assert caught.value.status_code == 400
    assert upload.file.closed


def test_required_fields_use_configured_labels(draft_client):
    client, enqueue, _queue, cfg = draft_client
    cfg["product_fields"] = {"color1": {"label": "Wykonczenie", "required": True}}
    response = client.post("/api/process/background", data={
        "name": "TEST", "type_name": "TEST", "model": "test",
    })
    assert response.status_code == 400
    assert "Wykonczenie" in response.json()["detail"]
    enqueue.assert_not_called()


def test_disabled_fields_do_not_block_a_complete_draft(draft_client):
    client, enqueue, _queue, cfg = draft_client
    cfg["product_fields"] = {"color1": {"enabled": False}, "ean": {"enabled": False}}
    response = client.post("/api/process/background", data={
        "name": "TEST", "type_name": "TEST", "model": "test", "ean": "ignored-invalid-ean",
    })
    assert response.status_code == 200
    enqueue.call_args.kwargs["reservation"].release()


@pytest.mark.parametrize("ean", ["", "5901234567890"])
def test_complete_draft_accepts_a_new_color_and_optional_ean(draft_client, ean):
    client, enqueue, _queue, _cfg = draft_client
    response = client.post("/api/process/background", data={
        "name": "TEST", "type_name": "TEST", "model": "test", "color1": "NEW COLOR", "ean": ean,
    })
    assert response.status_code == 200
    assert response.json()["queued"] is True
    snapshot = enqueue.call_args.kwargs["form"]
    assert snapshot.get("color1") == "NEW COLOR"
    assert snapshot.get("ean") == ean
    enqueue.call_args.kwargs["reservation"].release()


def test_disconnected_similar_lookup_does_not_report_a_critical_error(monkeypatch):
    monkeypatch.setattr(web_app, "_require_user", lambda _request: "operator")
    monkeypatch.setattr(Request, "json", AsyncMock(side_effect=ClientDisconnect()))
    emit = Mock()
    monkeypatch.setattr(web_app, "emit_event", emit)
    client = TestClient(web_app.app, raise_server_exceptions=False)
    response = client.post("/api/similar-files", json={"name": "TEST"})
    client.close()
    assert response.status_code == 499
    assert not any(call.kwargs.get("event_type") == "backend.unhandled_error" for call in emit.call_args_list)
