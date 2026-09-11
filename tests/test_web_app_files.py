"""Tests for web API file token and local deletion helpers."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from picsyncra import web_data
from picsyncra import common
from picsyncra.similar_product_files import SimilarFileCandidate
from picsyncra.web import active_clients
from picsyncra.web import app as web_app
from picsyncra.web.process_queue import (
    OwnerQueueLimit,
    ProcessQueueFull,
    ProcessQueueService,
    QueueLimits,
)

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional test dependency
    Image = None


def _workspace_temp(name: str) -> Path:
    root = Path(__file__).resolve().parents[1] / "tmp_test" / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def _similar_product_payload() -> dict[str, str]:
    return {
        "name": "MAGGIORE",
        "type_name": "KOMODA",
        "model": "M1",
        "color1": "WHITE",
        "color2": "",
        "color3": "",
        "extra": "NO-LED",
    }


def test_similar_settings_round_trip_removes_unknown_slots(monkeypatch) -> None:
    """Catches selected suggestion slots surviving after their definition is removed."""

    cfg = json.loads(json.dumps(common.DEFAULT_CONFIG))
    cfg[common.SLOT_DEFS_KEY] = [{"prefix": "01", "label": "Instrukcja"}]
    with (
        patch.object(web_data.config, "CONFIG", cfg),
        patch.object(web_data, "save_config"),
        patch.object(web_data.config, "initialize_config", return_value=cfg),
        patch.object(web_data, "load_users", return_value=[]),
    ):
        snapshot = web_data.update_settings(
            {
                common.SIMILAR_FILE_DETECTION_KEY: {
                    "enabled": True,
                    "slot_prefixes": ["01", "99"],
                }
            }
        )

    assert snapshot[common.SIMILAR_FILE_DETECTION_KEY] == {
        "enabled": True,
        "slot_prefixes": ["01"],
    }


def test_similar_file_lookup_does_not_start_or_refresh_the_local_index() -> None:
    """Catches a read-only suggestion request starting the persistent local index."""

    cfg = json.loads(json.dumps(common.DEFAULT_CONFIG))
    cfg[common.SIMILAR_FILE_DETECTION_KEY] = {
        "enabled": True,
        "slot_prefixes": ["01"],
    }

    def loaded_index_only(*, start: bool = False):
        assert start is False
        return None

    with (
        patch.object(web_data.config, "CONFIG", cfg),
        patch.object(web_data, "_get_file_index", side_effect=loaded_index_only),
        patch.object(web_data, "find_similar_file_candidates", return_value=[]),
    ):
        assert web_data.find_web_similar_file_candidates(_similar_product_payload()) == []


def test_similar_file_lookup_reserves_currently_occupied_slots() -> None:
    """Catches web lookup ignoring a loaded or manually selected target slot."""

    captured: dict[str, object] = {}

    def capture_lookup(*_args, **kwargs):
        captured.update(kwargs)
        return []

    with (
        patch.object(web_data, "_get_file_index", return_value=None),
        patch.object(web_data, "find_similar_file_candidates", side_effect=capture_lookup),
    ):
        web_data.find_web_similar_file_candidates(
            {**_similar_product_payload(), "occupied_prefixes": ["01", "02"]}
        )

    assert captured["occupied_prefixes"] == ["01", "02"]


def test_web_similar_lookup_coalesces_identical_requests(monkeypatch) -> None:
    """Catches repeated identical form lookups rediscovering the same files."""

    calls = 0

    def discover(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(web_data, "find_similar_file_candidates", discover)
    web_data.reset_similar_file_lookup_cache()

    assert web_data.find_web_similar_file_candidates(_similar_product_payload()) == []
    assert web_data.find_web_similar_file_candidates(_similar_product_payload()) == []
    assert calls == 1


def test_web_similar_lookup_key_changes_with_extra_and_occupied_slots(monkeypatch) -> None:
    """Catches cache keys that omit strict extra or occupied target slots."""

    calls = []
    monkeypatch.setattr(
        web_data, "find_similar_file_candidates", lambda *_a, **kw: calls.append(kw) or []
    )
    web_data.reset_similar_file_lookup_cache()

    web_data.find_web_similar_file_candidates(_similar_product_payload())
    web_data.find_web_similar_file_candidates({**_similar_product_payload(), "extra": "LED"})
    web_data.find_web_similar_file_candidates(
        {**_similar_product_payload(), "occupied_prefixes": ["01"]}
    )

    assert len(calls) == 3


def test_web_similar_lookup_coalesces_simultaneous_identical_requests(monkeypatch) -> None:
    """Catches a waiter starting a duplicate discovery while the owner is blocked."""

    calls = 0
    owner_started = threading.Event()
    release_owner = threading.Event()
    results: list[list[SimilarFileCandidate]] = []
    created_flights = []
    original_event = threading.Event

    class TrackingEvent:
        def __init__(self) -> None:
            self._event = original_event()
            self.wait_started = original_event()

        def set(self) -> None:
            self._event.set()

        def wait(self, timeout=None) -> bool:
            self.wait_started.set()
            return self._event.wait(timeout)

    def discover(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        owner_started.set()
        assert release_owner.wait(timeout=2)
        return []

    monkeypatch.setattr(web_data, "find_similar_file_candidates", discover)
    web_data.reset_similar_file_lookup_cache()
    payload = _similar_product_payload()
    owner = threading.Thread(
        target=lambda: results.append(web_data.find_web_similar_file_candidates(payload))
    )
    waiter = threading.Thread(
        target=lambda: results.append(web_data.find_web_similar_file_candidates(payload))
    )
    monkeypatch.setattr(
        web_data.threading, "Event", lambda: created_flights.append(TrackingEvent()) or created_flights[-1]
    )

    owner.start()
    assert owner_started.wait(timeout=2)
    waiter.start()
    assert created_flights[0].wait_started.wait(timeout=2)
    release_owner.set()
    owner.join(timeout=2)
    waiter.join(timeout=2)

    assert not owner.is_alive()
    assert not waiter.is_alive()
    assert results == [[], []]
    assert calls == 1


def test_web_similar_lookup_owner_error_wakes_waiter_and_allows_retry(monkeypatch) -> None:
    """Catches failed owners stranding waiters or leaving a stale in-flight lookup."""

    calls = 0
    owner_started = threading.Event()
    release_owner = threading.Event()
    owner_errors: list[Exception] = []
    waiter_results: list[list[SimilarFileCandidate]] = []
    created_flights = []
    original_event = threading.Event

    class TrackingEvent:
        def __init__(self) -> None:
            self._event = original_event()
            self.wait_started = original_event()

        def set(self) -> None:
            self._event.set()

        def wait(self, timeout=None) -> bool:
            self.wait_started.set()
            return self._event.wait(timeout)

    def discover(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            owner_started.set()
            assert release_owner.wait(timeout=2)
            raise RuntimeError("discovery failed")
        return []

    def run_owner() -> None:
        try:
            web_data.find_web_similar_file_candidates(payload)
        except RuntimeError as error:
            owner_errors.append(error)

    monkeypatch.setattr(web_data, "find_similar_file_candidates", discover)
    web_data.reset_similar_file_lookup_cache()
    payload = _similar_product_payload()
    owner = threading.Thread(target=run_owner)
    waiter = threading.Thread(
        target=lambda: waiter_results.append(web_data.find_web_similar_file_candidates(payload))
    )
    monkeypatch.setattr(
        web_data.threading, "Event", lambda: created_flights.append(TrackingEvent()) or created_flights[-1]
    )

    owner.start()
    assert owner_started.wait(timeout=2)
    waiter.start()
    assert created_flights[0].wait_started.wait(timeout=2)
    release_owner.set()
    owner.join(timeout=2)
    waiter.join(timeout=2)

    assert not owner.is_alive()
    assert not waiter.is_alive()
    assert [str(error) for error in owner_errors] == ["discovery failed"]
    assert waiter_results == [[]]
    assert calls == 2
    assert not web_data._SIMILAR_LOOKUP_IN_FLIGHT


def test_file_token_allows_a_resolved_equivalent_of_the_photos_root(monkeypatch) -> None:
    """Catches preview tokens failing when a mapped photo root resolves elsewhere."""

    configured_root = r"Z:\photos"
    resolved_root = r"\\server\share\photos"
    source = rf"{resolved_root}\BLACK\NO-LED\5901234567890_01.jpg"
    original_realpath = web_app.os.path.realpath

    def resolve_path(path: str) -> str:
        normalized = original_realpath(path)
        if normalized.casefold() == configured_root.casefold():
            return resolved_root
        return normalized

    monkeypatch.setattr(web_app.settings, "l", configured_root)
    with (
        patch.object(web_app.os.path, "realpath", side_effect=resolve_path),
        patch.object(web_app.os.path, "isfile", return_value=True),
    ):
        assert web_app._path_from_file_token(web_app._file_token(source)) == source


def test_file_token_allows_case_variant_of_a_resolved_photos_root(monkeypatch) -> None:
    """Catches Windows path casing rejecting a signed file inside the photos root."""

    configured_root = r"C:\Photos"
    source = r"c:\photos\BLACK\NO-LED\5901234567890_01.jpg"

    def common_path(paths: list[str]) -> str:
        if configured_root in paths:
            return r"c:\photos"
        return r"C:\outside"

    monkeypatch.setattr(web_app.settings, "l", configured_root)
    with (
        patch.object(web_app.os.path, "realpath", side_effect=lambda path: path),
        patch.object(web_app.os.path, "commonpath", side_effect=common_path),
        patch.object(web_app.os.path, "isfile", return_value=True),
    ):
        assert web_app._path_from_file_token(web_app._file_token(source)) == source


def test_delete_local_files_skips_path_outside_trusted_roots(tmp_path, monkeypatch) -> None:
    """A direct caller cannot turn local cleanup into an arbitrary-file delete."""
    photos = tmp_path / "photos"
    outside = tmp_path / "outside.jpg"
    photos.mkdir()
    outside.write_bytes(b"keep")
    monkeypatch.setattr(web_app.settings, "l", str(photos))

    result = web_app._delete_local_files([{"local_path": str(outside)}], set())

    assert result["deleted"] == 0
    assert outside.exists()


def test_file_token_rejects_signed_symlink_escaping_photos_root(tmp_path, monkeypatch) -> None:
    """A valid signature cannot authorize a path that escapes through a link."""
    photos = tmp_path / "photos"
    outside = tmp_path / "outside"
    photos.mkdir()
    outside.mkdir()
    secret = outside / "secret.jpg"
    secret.write_bytes(b"secret")
    try:
        (photos / "escape").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")
    monkeypatch.setattr(web_app.settings, "l", str(photos))

    with pytest.raises(HTTPException) as error:
        web_app._path_from_file_token(web_app._file_token(str(photos / "escape" / secret.name)))

    assert error.value.status_code == 403


def test_similar_files_endpoint_requires_login_and_hides_source_path(monkeypatch) -> None:
    """Catches a suggestions response that leaks a local filename path or skips auth."""

    monkeypatch.setenv("PICSYNCRA_WEB_AUTH", "1")
    with TestClient(web_app.app) as client:
        assert client.post("/api/similar-files", json=_similar_product_payload()).status_code == 401

    candidate = SimilarFileCandidate(
        candidate_id="candidate-1",
        source_prefix="01",
        target_prefix="01",
        source_path="C:/photos/BLACK/NO-LED/1_01.pdf",
        filename="1_01.pdf",
        source_color_segment="BLACK",
        size_bytes=12,
        sha256="digest",
        is_pdf=True,
    )
    with (
        patch.object(web_app, "_require_user", return_value="operator"),
        patch.object(web_app, "find_web_similar_file_candidates", return_value=[candidate]),
        patch.object(web_app, "_enrich_photo_payload", wraps=web_app._enrich_photo_payload),
        patch.object(web_app.settings, "l", "C:/photos"),
    ):
        response = TestClient(web_app.app).post(
            "/api/similar-files", json=_similar_product_payload()
        )

    assert response.status_code == 200
    item = response.json()["candidates"][0]
    assert item["url"].startswith("/api/file?token=")
    assert set(item) == {
        "id",
        "source_prefix",
        "target_prefix",
        "filename",
        "source_color",
        "size_bytes",
        "is_pdf",
        "token",
        "url",
        "thumb_url",
    }
    assert "path" not in item and "C:/" not in json.dumps(item)


def test_similar_lookup_returns_submit_ready_token_but_does_not_schedule_a_slot(
    tmp_path, monkeypatch
) -> None:
    """Catches a lookup request reaching process, cache, or job-history boundaries."""

    source = tmp_path / "photos" / "BLACK" / "NO-LED" / "5901234567890_01.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4\n")
    candidate = SimilarFileCandidate(
        candidate_id="candidate-1",
        source_prefix="01",
        target_prefix="01",
        source_path=str(source),
        filename=source.name,
        source_color_segment="BLACK",
        size_bytes=source.stat().st_size,
        sha256="digest",
        is_pdf=True,
    )
    monkeypatch.setattr(
        web_app, "find_web_similar_file_candidates", lambda _payload: [candidate]
    )
    monkeypatch.setattr(web_app, "_require_user", lambda _request: "operator")

    def unexpected_side_effect(*_args, **_kwargs):
        raise AssertionError("a read-only similar-file lookup must not cause a side effect")

    with (
        TestClient(web_app.app) as client,
        patch.object(web_app, "_materialize_process_form", side_effect=unexpected_side_effect),
        patch.object(web_app, "_queue_process_job", side_effect=unexpected_side_effect),
        patch.object(web_app, "_save_upload_cache_entry", side_effect=unexpected_side_effect),
        patch.object(web_app, "record_job", side_effect=unexpected_side_effect),
        patch.object(web_app, "emit_event", side_effect=unexpected_side_effect),
        patch.object(web_app, "_write_web_event", side_effect=unexpected_side_effect),
    ):
        monkeypatch.setattr(web_app.settings, "l", str(tmp_path / "photos"))
        response = client.post("/api/similar-files", json=_similar_product_payload())
        item = response.json()["candidates"][0]
        assert web_app._path_from_file_token(item["token"]) == str(source)

    assert response.status_code == 200


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_terminal_process_jobs_cleanup_staging_and_release_reservation(
    tmp_path, monkeypatch, outcome: str
) -> None:
    """Catches terminal jobs that retain a staging directory or owner queue slot."""
    root = tmp_path / "jobs"
    root.mkdir()
    staging = root / "job-terminal"
    staging.mkdir()
    (staging / "upload.jpg").write_bytes(b"staged")
    queue = ProcessQueueService(QueueLimits(workers=1, max_pending=1, max_per_owner=1))
    jobs: dict[str, dict[str, object]] = {}
    completions: dict[str, threading.Event] = {}
    started = threading.Event()
    form = web_app._ProcessFormSnapshot(temp_dir=str(staging))
    result = {
        "timing": {"stages": []},
        "ftp": {},
        "sql": {},
        "local_delete": {},
        "skipped_slots": [],
    }

    def process(**kwargs):
        started.set()
        if outcome == "failed":
            raise RuntimeError("expected worker failure")
        if outcome == "cancelled":
            assert kwargs["cancel_event"].wait(timeout=5)
            raise web_app._ProcessJobCancelled()
        return result

    monkeypatch.setattr(web_app, "_PROCESS_JOB_ROOT", root)
    monkeypatch.setattr(web_app, "_PROCESS_QUEUE", queue)
    monkeypatch.setattr(web_app, "_PROCESS_JOBS", jobs)
    monkeypatch.setattr(web_app, "_PROCESS_JOB_COMPLETIONS", completions)
    try:
        with (
            patch.object(web_app, "_process_upload_snapshot", side_effect=process),
            patch.object(web_app, "record_job"),
            patch.object(web_app, "emit_event"),
            patch.object(web_app, "_write_web_event"),
        ):
            queued = web_app._queue_process_job(
                username="operator",
                cache_scope="scope",
                form=form,
                reservation=queue.reserve("scope"),
            )
            job_id = str(queued["job_id"])
            assert started.wait(timeout=5)
            if outcome == "cancelled":
                cancelled = web_app._cancel_process_job_for_user(job_id, "operator")
                assert cancelled is not None
            assert completions[job_id].wait(timeout=5)

        assert not staging.exists()
        assert web_app._process_job_for_user(job_id, "operator")["status"] == outcome
        deadline = time.monotonic() + 5
        while True:
            try:
                replacement = queue.reserve("scope")
                break
            except OwnerQueueLimit:
                assert time.monotonic() < deadline
                time.sleep(0.01)
        replacement.release()
    finally:
        queue.shutdown()


def test_cancel_process_endpoint_cleans_waiting_job(tmp_path, monkeypatch) -> None:
    """Catches a cancel endpoint that leaves queued staging or capacity behind."""
    root = tmp_path / "jobs"
    root.mkdir()
    staging = root / "job-waiting"
    staging.mkdir()
    (staging / "upload.jpg").write_bytes(b"staged")
    queue = ProcessQueueService(
        QueueLimits(workers=1, max_pending=1, max_per_owner=1),
        start_workers=False,
    )
    jobs: dict[str, dict[str, object]] = {}
    completions: dict[str, threading.Event] = {}
    monkeypatch.setattr(web_app, "_PROCESS_JOB_ROOT", root)
    monkeypatch.setattr(web_app, "_PROCESS_QUEUE", queue)
    monkeypatch.setattr(web_app, "_PROCESS_JOBS", jobs)
    monkeypatch.setattr(web_app, "_PROCESS_JOB_COMPLETIONS", completions)
    try:
        with patch.object(web_app, "record_job"):
            queued = web_app._queue_process_job(
                username="operator",
                cache_scope="scope",
                form=web_app._ProcessFormSnapshot(temp_dir=str(staging)),
                reservation=queue.reserve("scope"),
            )
        job_id = str(queued["job_id"])
        with patch.object(web_app, "_require_user", return_value="operator"):
            response = TestClient(web_app.app).delete(f"/api/process-jobs/{job_id}")

        assert response.status_code == 200
        assert response.json()["job"]["status"] == "cancelled"
        assert not staging.exists()
        replacement = queue.reserve("scope")
        replacement.release()
    finally:
        queue.shutdown()


def test_process_snapshot_stops_before_validation_when_cancelled() -> None:
    """Catches a cancellation token that is ignored until after validation starts."""
    cancel_event = threading.Event()
    cancel_event.set()

    with (
        patch.object(web_app, "slot_definitions_from_config", return_value=[]),
        patch.object(
            web_app,
            "validate_product_form",
            side_effect=AssertionError("validation must not run after cancellation"),
        ),
        pytest.raises(web_app._ProcessJobCancelled),
    ):
        web_app._process_upload_snapshot(
            username="operator",
            cache_scope="scope",
            form=web_app._ProcessFormSnapshot(),
            cancel_event=cancel_event,
        )


class _MemoryUpload:
    def __init__(self, filename: str, chunks: list[bytes], content_type: str = "image/jpeg") -> None:
        self.filename = filename
        self.content_type = content_type
        self._chunks = list(chunks)
        self.closed = False

    async def read(self, _size: int = -1) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    async def close(self) -> None:
        self.closed = True


class WebAppFileTests(unittest.TestCase):
    def test_latest_request_asset_precedes_app(self) -> None:
        workspace = Path(__file__).resolve().parents[1]
        index_source = (
            workspace / "picsyncra" / "web" / "static" / "index.html"
        ).read_text(encoding="utf-8")

        latest_request_asset = '<script src="/static/latest-request.js'
        app_asset = '<script src="/static/app.js'
        self.assertIn(latest_request_asset, index_source)
        self.assertLess(
            index_source.index(latest_request_asset), index_source.index(app_asset)
        )

    def test_ocr_diagnostics_asset_precedes_app(self) -> None:
        workspace = Path(__file__).resolve().parents[1]
        index_source = (
            workspace / "picsyncra" / "web" / "static" / "index.html"
        ).read_text(encoding="utf-8")
        diagnostics_source = (
            workspace / "picsyncra" / "web" / "static" / "ocr-diagnostics.js"
        ).read_text(encoding="utf-8")

        diagnostics_asset = '<script src="/static/ocr-diagnostics.js'
        app_asset = '<script src="/static/app.js'
        self.assertIn(diagnostics_asset, index_source)
        self.assertLess(index_source.index(diagnostics_asset), index_source.index(app_asset))
        self.assertIn("root.OcrDiagnostics", diagnostics_source)

    def test_runtime_status_asset_precedes_app_and_replaces_named_runtime_pollers(
        self,
    ) -> None:
        workspace = Path(__file__).resolve().parents[1]
        index_source = (
            workspace / "picsyncra" / "web" / "static" / "index.html"
        ).read_text(encoding="utf-8")
        app_source = (
            workspace / "picsyncra" / "web" / "static" / "app.js"
        ).read_text(encoding="utf-8")

        runtime_asset = '<script src="/static/runtime-status.js'
        app_asset = '<script src="/static/app.js'
        self.assertIn(runtime_asset, index_source)
        self.assertLess(index_source.index(runtime_asset), index_source.index(app_asset))
        self.assertEqual(app_source.count("new PicSyncra.RuntimeStatusPoller("), 1)
        self.assertNotIn('createPoller("fileIndex"', app_source)
        self.assertNotIn('createPoller("processQueue"', app_source)
        self.assertNotIn('createPoller("activeUsers"', app_source)
        self.assertIn(
            "if (state.observability.stream && state.observability.streamConnected)",
            app_source,
        )

    def test_product_query_endpoints_clamp_limit_before_store_delegation(self) -> None:
        """Requests above 100 must not widen the delegated product queries."""

        client = TestClient(web_app.app)
        store = Mock()
        store.mode = "sqlite"
        store.search_product_entries.return_value = []
        store.suggest_product_field.return_value = []
        with (
            patch.object(web_app, "_require_user", return_value="operator"),
            patch.object(web_data, "get_active_store", return_value=store),
            patch.object(web_data, "_get_file_index", return_value=None),
            patch.object(web_app, "search_entries", web_data.search_entries),
            patch.object(web_app, "field_suggestions", web_data.field_suggestions),
            patch.object(web_app, "file_index_status", return_value={}),
        ):
            search_response = client.get("/api/entries/search?ean=5901&limit=999")
            suggestion_response = client.get("/api/suggestions?field=name&name=al&limit=999")

        self.assertEqual(search_response.status_code, 200)
        self.assertEqual(suggestion_response.status_code, 200)
        self.assertEqual(store.search_product_entries.call_args.kwargs["limit"], 100)
        self.assertEqual(store.suggest_product_field.call_args.kwargs["limit"], 100)

    def test_process_job_progress_coalesces_percent_only_snapshots(self) -> None:
        """Persisting every progress tick would make this test exceed three writes."""
        job_id = "progress-gate-100-updates"
        job = web_app._new_process_job(
            username="alice",
            cache_scope="scope",
            form=web_app._ProcessFormSnapshot(),
            status="running",
        )
        job["id"] = job_id
        with web_app._PROCESS_JOBS_LOCK:
            web_app._PROCESS_JOBS[job_id] = job

        try:
            with (
                patch.object(web_app, "_persist_process_job") as persist,
                patch.object(
                    web_app.time,
                    "monotonic",
                    side_effect=[index / 100 for index in range(100)],
                ),
            ):
                for percent in range(1, 101):
                    web_app._set_process_job_progress(
                        job_id,
                        percent,
                        "Przetwarzanie obrazow",
                        current_stage={"key": "images", "label": "Obrazy"},
                    )

            with web_app._PROCESS_JOBS_LOCK:
                current = dict(web_app._PROCESS_JOBS[job_id])
            self.assertEqual(current["progress"], 100)
            self.assertEqual(current["progress_label"], "Przetwarzanie obrazow")
            self.assertLessEqual(persist.call_count, 3)
        finally:
            with web_app._PROCESS_JOBS_LOCK:
                web_app._PROCESS_JOBS.pop(job_id, None)
            gate = getattr(web_app, "_PROCESS_PROGRESS_GATE", None)
            if gate is not None:
                gate.forget(job_id)

    def test_application_lifecycle_starts_and_stops_notification_worker(self) -> None:
        source = inspect.getsource(web_app.create_app)

        self.assertIn("start_notification_worker()", source)
        self.assertIn("stop_notification_worker()", source)
        self.assertIn("_start_backup_scheduler()", source)
        self.assertIn("_stop_backup_scheduler()", source)

    def test_process_job_persists_correlated_result(self) -> None:
        form = web_app._ProcessFormSnapshot(
            fields={"ean": "5901234567890", "name": "Test product"}
        )
        queue = Mock()
        queue.submit.return_value = 1
        reservation = Mock()
        result = {
            "timing": {"stages": [{"key": "prepare", "elapsed_ms": 12}]},
            "ftp": {},
            "sql": {},
            "local_delete": {},
            "skipped_slots": [],
        }

        with (
            patch.object(web_app, "_PROCESS_QUEUE", queue),
            patch.object(web_app, "_process_upload_snapshot", return_value=result) as process,
            patch.object(web_app, "record_job") as record_job,
            patch.object(web_app, "emit_event") as emit_event,
        ):
            queued = web_app._queue_process_job(
                username="alice", cache_scope="scope", form=form, reservation=reservation
            )
            web_app._run_process_job(queued["job_id"])

        process.assert_called_once()
        self.assertEqual(process.call_args.kwargs["job_id"], queued["job_id"])
        states = [call.args[0]["status"] for call in record_job.call_args_list]
        self.assertEqual(states, ["queued", "running", "completed"])
        self.assertTrue(
            all(call.args[0]["id"] == queued["job_id"] for call in record_job.call_args_list)
        )
        completed = record_job.call_args_list[-1].args[0]
        self.assertEqual(completed["stages"], result["timing"]["stages"])
        self.assertEqual(emit_event.call_args.kwargs["severity"], "info")
        self.assertEqual(emit_event.call_args.kwargs["job_id"], queued["job_id"])

    def test_process_job_persists_critical_unexpected_failure(self) -> None:
        form = web_app._ProcessFormSnapshot(fields={"ean": "5901234567890"})
        queue = Mock()
        queue.submit.return_value = 1
        reservation = Mock()

        with (
            patch.object(web_app, "_PROCESS_QUEUE", queue),
            patch.object(
                web_app,
                "_process_upload_snapshot",
                side_effect=RuntimeError("database password=secret"),
            ),
            patch.object(web_app, "record_job") as record_job,
            patch.object(web_app, "emit_event") as emit_event,
        ):
            queued = web_app._queue_process_job(
                username="alice", cache_scope="scope", form=form, reservation=reservation
            )
            web_app._run_process_job(queued["job_id"])

        failed = record_job.call_args_list[-1].args[0]
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["id"], queued["job_id"])
        self.assertEqual(emit_event.call_args.kwargs["severity"], "critical")
        self.assertIsInstance(emit_event.call_args.kwargs["exception"], RuntimeError)
        self.assertEqual(emit_event.call_args.kwargs["job_id"], queued["job_id"])

    def test_failed_process_job_persists_the_active_stage(self) -> None:
        form = web_app._ProcessFormSnapshot(fields={"ean": "5901234567890"})
        queue = Mock()
        queue.submit.return_value = 1
        reservation = Mock()

        def fail_during_stage(*, progress, **_kwargs):
            progress(
                45,
                "FTP upload",
                [{"key": "prepare", "elapsed_ms": 10}],
                {
                    "key": "ftp",
                    "label": "FTP upload",
                    "started_at": time.time() - 0.05,
                    "elapsed_ms": 0,
                    "running": True,
                },
            )
            raise RuntimeError("FTP crashed")

        with (
            patch.object(web_app, "_PROCESS_QUEUE", queue),
            patch.object(web_app, "_process_upload_snapshot", side_effect=fail_during_stage),
            patch.object(web_app, "record_job") as record_job,
            patch.object(web_app, "emit_event"),
        ):
            queued = web_app._queue_process_job(
                username="alice", cache_scope="scope", form=form, reservation=reservation
            )
            web_app._run_process_job(queued["job_id"])

        failed = record_job.call_args_list[-1].args[0]
        self.assertEqual(failed["status"], "failed")
        self.assertEqual([stage["key"] for stage in failed["stages"]], ["prepare", "ftp"])
        failing_stage = failed["stages"][-1]
        self.assertGreaterEqual(failing_stage["elapsed_ms"], 40)
        self.assertIs(failing_stage["running"], False)
        self.assertIs(failing_stage["failed"], True)
        self.assertEqual(failing_stage["error"], "FTP crashed")

    def test_process_result_severity_distinguishes_blocking_and_skipped_results(self) -> None:
        self.assertEqual(
            web_app._result_severity(
                {"ftp": {"error": "offline"}, "sql": {}, "local_delete": {}}
            ),
            "error",
        )
        self.assertEqual(
            web_app._result_severity(
                {"ftp": {}, "sql": {}, "local_delete": {}, "skipped_slots": ["01"]}
            ),
            "warning",
        )
        self.assertEqual(
            web_app._result_severity(
                {"ftp": {}, "sql": {}, "local_delete": {}, "skipped_slots": []}
            ),
            "info",
        )

    def test_process_snapshot_emits_correlated_stage_and_validation_events(self) -> None:
        form = web_app._ProcessFormSnapshot()
        with (
            patch.object(web_app, "slot_definitions_from_config", return_value=[]),
            patch.object(web_app, "_active_product_field_settings", return_value={}),
            patch.object(
                web_app,
                "effective_product_form",
                side_effect=lambda product, _settings: product,
            ),
            patch.object(web_app, "validate_product_form", return_value=["Missing EAN"]),
            patch.object(web_app, "emit_event") as emit_event,
        ):
            with self.assertRaises(HTTPException) as caught:
                web_app._process_upload_snapshot(
                    username="alice",
                    cache_scope="scope",
                    form=form,
                    job_id="job-correlated",
                )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(
            [call.kwargs["severity"] for call in emit_event.call_args_list],
            ["info", "warning"],
        )
        self.assertEqual(
            [call.kwargs["event_type"] for call in emit_event.call_args_list],
            ["process.stage_started", "process.validation_rejected"],
        )
        self.assertTrue(
            all(
                call.kwargs["job_id"] == "job-correlated"
                for call in emit_event.call_args_list
            )
        )
        stage_events = [
            call.kwargs
            for call in emit_event.call_args_list
            if call.kwargs["event_type"] == "process.stage_started"
        ]
        stage_keys = [
            (event["job_id"], event["stage"]) for event in stage_events
        ]
        self.assertEqual(len(stage_keys), len(set(stage_keys)))

    def test_process_stage_started_once_for_repeated_stage(self) -> None:
        emitted_stages: set[str] = set()

        with patch.object(web_app, "emit_event") as emit_event:
            for percent in (4, 8):
                web_app._emit_process_stage_started_once(
                    emitted_stages,
                    current_key="prepare",
                    current_label="Przygotowanie",
                    percent=percent,
                    label="Przygotowanie danych",
                    username="alice",
                    job_id="job-repeat",
                )

        emit_event.assert_called_once()
        self.assertEqual(emit_event.call_args.kwargs["job_id"], "job-repeat")
        self.assertEqual(emit_event.call_args.kwargs["stage"], "prepare")

    def test_existing_photo_snapshot_captures_size_before_local_mutation(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            photo = Path(temp_dir) / "old.jpg"
            photo.write_bytes(b"old-photo")

            snapshot = web_app._snapshot_existing_photos(
                [
                    {
                        "prefix": "03",
                        "filename": photo.name,
                        "path": str(photo),
                        "ftp_filename": "5901234567890_03.jpg",
                    },
                    {
                        "prefix": "04",
                        "path": "",
                        "ftp_filename": "5901234567890_04.jpg",
                    },
                ]
            )
            photo.unlink()

        self.assertEqual(snapshot[0]["size_bytes"], 9)
        self.assertEqual(snapshot[0]["filename"], "old.jpg")
        self.assertEqual(snapshot[1]["ftp_filename"], "5901234567890_04.jpg")
        self.assertIsNone(snapshot[1]["size_bytes"])

    def test_process_integration_events_reuse_results_and_job_id(self) -> None:
        with patch.object(web_app, "emit_event") as emit_event:
            web_app._emit_process_integration_events(
                username="alice",
                job_id="job-123",
                ean="5901234567890",
                ftp_result={
                    "enabled": True,
                    "uploaded": 2,
                    "deleted": 1,
                    "elapsed_ms": 14,
                    "error": "",
                },
                sql_result={
                    "enabled": True,
                    "updated": 0,
                    "cleared": 0,
                    "rows": 0,
                    "elapsed_ms": 6,
                    "error": "database unavailable",
                },
            )

        self.assertEqual(emit_event.call_count, 2)
        ftp_event, sql_event = emit_event.call_args_list
        self.assertEqual(ftp_event.kwargs["severity"], "info")
        self.assertEqual(ftp_event.kwargs["event_type"], "integration.ftp.completed")
        self.assertEqual(ftp_event.kwargs["details"]["uploaded"], 2)
        self.assertEqual(sql_event.kwargs["severity"], "error")
        self.assertEqual(sql_event.kwargs["event_type"], "integration.sql.completed")
        self.assertTrue(all(call.kwargs["job_id"] == "job-123" for call in emit_event.call_args_list))

    def _image_bytes(self, image_format: str, mode: str = "RGB") -> bytes:
        if Image is None:
            self.skipTest("Pillow unavailable")
        buffer = io.BytesIO()
        color = 1 if mode == "1" else 255 if mode == "L" else "white"
        Image.new(mode, (16, 16), color).save(buffer, format=image_format)
        return buffer.getvalue()

    def _optional_image_bytes(self, image_format: str, mode: str = "RGB") -> bytes | None:
        try:
            return self._image_bytes(image_format, mode)
        except Exception:
            return None

    def _ftyp_payload(self, brand: bytes) -> bytes:
        return b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x00\x00" + brand + b"mif1"

    def test_output_identity_ignores_disabled_product_fields(self) -> None:
        first = web_app.WebProductForm(
            name="MAGGIORE",
            type_name="KOMODA",
            model="MA03",
            color1="BIALY",
            ean="5901234567890",
        )
        second = web_app.WebProductForm(
            name="MAGGIORE",
            type_name="STOL",
            model="MA03",
            color1="BIALY",
            ean="5901234567890",
        )

        with (
            patch.object(
                web_app.config,
                "CONFIG",
                {"product_fields": {"type": {"enabled": False}}},
            ),
            patch.object(web_app.settings, "l", "C:\\processed"),
        ):
            self.assertEqual(
                web_app._output_identity(first),
                web_app._output_identity(second),
            )

    def test_delete_token_can_be_resolved_after_file_disappears(self) -> None:
        temp_dir = _workspace_temp("web_app_delete_token")
        try:
            processed = temp_dir / "processed"
            processed.mkdir()
            target = processed / "old.jpg"
            target.write_bytes(b"old")
            with (
                patch.object(web_app.settings, "l", str(processed)),
                patch.object(web_app.settings, "AC", str(temp_dir)),
            ):
                token = web_app._file_token(str(target))
                target.unlink()
                self.assertEqual(
                    Path(web_app._path_from_file_token(token, require_exists=False)),
                    target,
                )
                with self.assertRaises(HTTPException):
                    web_app._path_from_file_token(token)
        finally:
            shutil.rmtree(temp_dir)

    def test_upload_cache_token_can_be_resolved(self) -> None:
        temp_dir = _workspace_temp("web_app_upload_cache_token")
        try:
            processed = temp_dir / "processed"
            upload_cache = temp_dir / "web_upload_cache" / "session"
            processed.mkdir()
            upload_cache.mkdir(parents=True)
            target = upload_cache / "01_cached.jpg"
            target.write_bytes(b"cached")
            with (
                patch.object(web_app.settings, "l", str(processed)),
                patch.object(web_app.settings, "AC", str(temp_dir)),
            ):
                token = web_app._file_token(str(target))
                self.assertEqual(Path(web_app._path_from_file_token(token)), target)
        finally:
            shutil.rmtree(temp_dir)

    def test_delete_upload_cache_files_only_removes_upload_cache_paths(self) -> None:
        temp_dir = _workspace_temp("web_app_upload_cache_cleanup")
        try:
            upload_cache = temp_dir / "web_upload_cache" / "session"
            processed = temp_dir / "processed"
            upload_cache.mkdir(parents=True)
            processed.mkdir()
            cached = upload_cache / "01_cached.jpg"
            processed_file = processed / "keep.jpg"
            cached.write_bytes(b"cached")
            processed_file.write_bytes(b"keep")

            with patch.object(web_app.settings, "AC", str(temp_dir)):
                with patch.object(web_app.os, "walk", side_effect=AssertionError("os.walk")):
                    result = web_app._delete_upload_cache_files([str(cached), str(processed_file)])

            self.assertEqual(result["deleted"], 1)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["errors"], [])
            self.assertFalse(cached.exists())
            self.assertTrue(processed_file.exists())
        finally:
            shutil.rmtree(temp_dir)

    def test_save_process_upload_rejects_oversized_file_and_removes_partial(self) -> None:
        temp_dir = _workspace_temp("web_app_process_upload_limit")
        try:
            upload = _MemoryUpload("large.jpg", [b"x" * (1024 * 1024), b"y"])
            with (
                patch.object(web_app.settings, "AC", str(temp_dir)),
                patch.object(
                    web_app.config,
                    "CONFIG",
                    {
                        web_app.PROCESSING_SETTINGS_KEY: {
                            "max_upload_mb": 1,
                            "max_upload_pixels": 25_000_000,
                        }
                    },
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(web_app._save_upload(upload, str(temp_dir), "01"))

            self.assertEqual(caught.exception.status_code, 413)
            self.assertEqual(list(temp_dir.iterdir()), [])
            self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_process_upload_rejects_executable_extension(self) -> None:
        temp_dir = _workspace_temp("web_app_process_upload_executable")
        try:
            upload = _MemoryUpload("payload.exe", [b"MZ"])
            with (
                patch.object(web_app.settings, "AC", str(temp_dir)),
                patch.object(
                    web_app.config,
                    "CONFIG",
                    {
                        web_app.SECURITY_SETTINGS_KEY: {
                            "allowed_upload_extensions": ["jpg", "exe"],
                            "blocked_upload_extensions": [],
                            "block_executable_uploads": True,
                        }
                    },
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(web_app._save_upload(upload, str(temp_dir), "01"))

            self.assertEqual(caught.exception.status_code, 400)
            self.assertEqual(list(temp_dir.iterdir()), [])
            self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_upload_cache_rejects_extension_outside_allow_list(self) -> None:
        temp_dir = _workspace_temp("web_app_upload_extension_limit")
        try:
            upload = _MemoryUpload("document.pdf", [b"%PDF"])
            with (
                patch.object(web_app.settings, "AC", str(temp_dir)),
                patch.object(
                    web_app.config,
                    "CONFIG",
                    {
                        web_app.SECURITY_SETTINGS_KEY: {
                            "allowed_upload_extensions": ["jpg", "png"],
                            "blocked_upload_extensions": [],
                            "block_executable_uploads": True,
                        }
                    },
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(web_app._save_upload_cache(upload, "session", "01"))

            self.assertEqual(caught.exception.status_code, 400)
            self.assertEqual(caught.exception.detail, "Typ pliku .pdf nie jest dozwolony.")
            cache_root = temp_dir / "web_upload_cache"
            cached_files = list(cache_root.rglob("*")) if cache_root.exists() else []
            self.assertEqual([path for path in cached_files if path.is_file()], [])
            self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_upload_cache_rejects_image_above_pixel_limit_and_removes_file(self) -> None:
        if Image is None:
            self.skipTest("Pillow unavailable")
        temp_dir = _workspace_temp("web_app_upload_pixel_limit")
        try:
            buffer = io.BytesIO()
            Image.new("RGB", (10, 10), "white").save(buffer, format="PNG")
            upload = _MemoryUpload("large.png", [buffer.getvalue()], "image/png")
            with (
                patch.object(web_app.settings, "AC", str(temp_dir)),
                patch.object(
                    web_app.config,
                    "CONFIG",
                    {
                        web_app.PROCESSING_SETTINGS_KEY: {
                            "max_upload_mb": 50,
                            "max_upload_pixels": 50,
                        }
                    },
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(web_app._save_upload_cache(upload, "session", "01"))

            self.assertEqual(caught.exception.status_code, 413)
            cache_root = temp_dir / "web_upload_cache"
            cached_files = list(cache_root.rglob("*")) if cache_root.exists() else []
            self.assertEqual([path for path in cached_files if path.is_file()], [])
            self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_upload_cache_rejects_html_content_named_as_jpg(self) -> None:
        temp_dir = _workspace_temp("web_app_upload_magic_mismatch")
        try:
            upload = _MemoryUpload("photo.jpg", [b"<!doctype html><script>alert(1)</script>"], "image/jpeg")
            with (
                patch.object(web_app.settings, "AC", str(temp_dir)),
                patch.object(
                    web_app.config,
                    "CONFIG",
                    {
                        web_app.SECURITY_SETTINGS_KEY: {
                            "allowed_upload_extensions": ["jpg", "png"],
                            "blocked_upload_extensions": [],
                            "block_executable_uploads": True,
                        }
                    },
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(web_app._save_upload_cache(upload, "session", "01"))

            self.assertEqual(caught.exception.status_code, 400)
            self.assertIn("HTML/XML/SVG", caught.exception.detail)
            cache_root = temp_dir / "web_upload_cache"
            cached_files = list(cache_root.rglob("*")) if cache_root.exists() else []
            self.assertEqual([path for path in cached_files if path.is_file()], [])
            self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_upload_cache_strips_jpeg_exif_metadata(self) -> None:
        if Image is None:
            self.skipTest("Pillow unavailable")
        temp_dir = _workspace_temp("web_app_upload_metadata_strip")
        try:
            buffer = io.BytesIO()
            image = Image.new("RGB", (16, 16), "white")
            exif = image.getexif()
            exif[0x010E] = "private description"
            image.save(buffer, format="JPEG", exif=exif.tobytes())
            upload = _MemoryUpload("photo.jpg", [buffer.getvalue()], "image/jpeg")
            with patch.object(web_app.settings, "AC", str(temp_dir)):
                path, _size = asyncio.run(web_app._save_upload_cache(upload, "session", "01"))

            with Image.open(path) as saved:
                self.assertEqual(dict(saved.getexif()), {})
            self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_upload_cache_accepts_jfif_jpeg_when_allowed(self) -> None:
        if Image is None:
            self.skipTest("Pillow unavailable")
        temp_dir = _workspace_temp("web_app_upload_jfif")
        try:
            buffer = io.BytesIO()
            Image.new("RGB", (16, 16), "white").save(buffer, format="JPEG")
            upload = _MemoryUpload("photo.jfif", [buffer.getvalue()], "image/jpeg")
            with (
                patch.object(web_app.settings, "AC", str(temp_dir)),
                patch.object(
                    web_app.config,
                    "CONFIG",
                    {
                        web_app.SECURITY_SETTINGS_KEY: {
                            "allowed_upload_extensions": ["jfif"],
                            "blocked_upload_extensions": [],
                            "block_executable_uploads": True,
                        }
                    },
                ),
            ):
                path, _size = asyncio.run(web_app._save_upload_cache(upload, "session", "01"))

            self.assertTrue(path.endswith(".jfif"))
            with Image.open(path) as image:
                self.assertEqual(image.format, "JPEG")
            self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_upload_cache_accepts_additional_image_formats_when_allowed(self) -> None:
        if Image is None:
            self.skipTest("Pillow unavailable")
        temp_dir = _workspace_temp("web_app_upload_additional_image_formats")
        cases = [
            ("photo.jpe", "image/jpeg", self._image_bytes("JPEG")),
            ("photo.peg", "image/jpeg", self._image_bytes("JPEG")),
            ("photo.apng", "image/apng", self._image_bytes("PNG")),
            ("photo.dib", "image/bmp", self._image_bytes("DIB")),
            ("photo.ico", "image/x-icon", self._image_bytes("ICO", "RGBA")),
            ("photo.tga", "image/x-tga", self._image_bytes("TGA")),
            ("photo.ppm", "image/x-portable-pixmap", self._image_bytes("PPM")),
            ("photo.pgm", "image/x-portable-graymap", self._image_bytes("PPM", "L")),
            ("photo.pbm", "image/x-portable-bitmap", self._image_bytes("PPM", "1")),
            ("photo.pnm", "image/x-portable-anymap", self._image_bytes("PPM")),
            ("photo.pcx", "image/x-pcx", self._image_bytes("PCX")),
        ]
        avif_payload = self._optional_image_bytes("AVIF")
        if avif_payload is not None:
            cases.append(("photo.avifs", "image/avif-sequence", avif_payload))
        jpeg2000_payload = self._optional_image_bytes("JPEG2000")
        if jpeg2000_payload is not None:
            cases.extend(
                [
                    ("photo.jp2", "image/jp2", jpeg2000_payload),
                    ("photo.j2k", "image/jp2", jpeg2000_payload),
                    ("photo.jpc", "image/jp2", jpeg2000_payload),
                    ("photo.jpx", "image/jpx", jpeg2000_payload),
                ]
            )

        try:
            for filename, content_type, payload in cases:
                with self.subTest(filename=filename):
                    extension = filename.rsplit(".", 1)[1]
                    upload = _MemoryUpload(filename, [payload], content_type)
                    with (
                        patch.object(web_app.settings, "AC", str(temp_dir)),
                        patch.object(
                            web_app.config,
                            "CONFIG",
                            {
                                web_app.SECURITY_SETTINGS_KEY: {
                                    "allowed_upload_extensions": [extension],
                                    "blocked_upload_extensions": [],
                                    "block_executable_uploads": True,
                                }
                            },
                        ),
                    ):
                        path, _size = asyncio.run(web_app._save_upload_cache(upload, "session", "01"))

                    self.assertTrue(path.endswith(f".{extension}"))
                    self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_upload_cache_accepts_heif_family_and_cursor_passthrough_when_allowed(self) -> None:
        temp_dir = _workspace_temp("web_app_upload_heif_passthrough")
        cases = [
            ("photo.heic", "image/heic", self._ftyp_payload(b"heic")),
            ("photo.heif", "image/heif", self._ftyp_payload(b"mif1")),
            ("photo.hif", "image/heif", self._ftyp_payload(b"heic")),
            ("photo.cur", "image/x-icon", b"\x00\x00\x02\x00\x01\x00" + b"\x00" * 64),
        ]
        try:
            for filename, content_type, payload in cases:
                with self.subTest(filename=filename):
                    extension = filename.rsplit(".", 1)[1]
                    upload = _MemoryUpload(filename, [payload], content_type)
                    with (
                        patch.object(web_app.settings, "AC", str(temp_dir)),
                        patch.object(
                            web_app.config,
                            "CONFIG",
                            {
                                web_app.SECURITY_SETTINGS_KEY: {
                                    "allowed_upload_extensions": [extension],
                                    "blocked_upload_extensions": [],
                                    "block_executable_uploads": True,
                                }
                            },
                        ),
                    ):
                        path, _size = asyncio.run(web_app._save_upload_cache(upload, "session", "01"))

                    self.assertTrue(path.endswith(f".{extension}"))
                    self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_upload_cache_entry_normalizes_browser_extension_webp_named_jpg(self) -> None:
        if Image is None:
            self.skipTest("Pillow unavailable")
        temp_dir = _workspace_temp("web_app_upload_normalize_webp_extension")
        try:
            buffer = io.BytesIO()
            try:
                Image.new("RGB", (16, 16), "white").save(buffer, format="WEBP")
            except Exception:
                self.skipTest("Pillow WebP support unavailable")
            upload = _MemoryUpload("product.jpg", [buffer.getvalue()], "image/jpeg")
            with (
                patch.object(web_app.settings, "AC", str(temp_dir)),
                patch.object(
                    web_app.config,
                    "CONFIG",
                    {
                        web_app.SECURITY_SETTINGS_KEY: {
                            "allowed_upload_extensions": ["jpg", "webp"],
                            "blocked_upload_extensions": [],
                            "block_executable_uploads": True,
                        }
                    },
                ),
            ):
                saved = asyncio.run(
                    web_app._save_upload_cache_entry(
                        upload,
                        "session",
                        "web",
                        normalize_extension=True,
                    )
                )

            self.assertTrue(saved.path.endswith(".webp"))
            self.assertEqual(saved.name, "product.webp")
            with Image.open(saved.path) as image:
                self.assertEqual(image.format, "WEBP")
            self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_upload_cache_normalizes_misnamed_jfif_to_detected_image_format(self) -> None:
        if Image is None:
            self.skipTest("Pillow unavailable")
        temp_dir = _workspace_temp("web_app_upload_normalize_jfif_extension")
        try:
            buffer = io.BytesIO()
            try:
                Image.new("RGB", (16, 16), "white").save(buffer, format="WEBP")
            except Exception:
                self.skipTest("Pillow WebP support unavailable")
            upload = _MemoryUpload("product.jfif", [buffer.getvalue()], "image/jpeg")
            with (
                patch.object(web_app.settings, "AC", str(temp_dir)),
                patch.object(
                    web_app.config,
                    "CONFIG",
                    {
                        web_app.SECURITY_SETTINGS_KEY: {
                            "allowed_upload_extensions": ["jfif", "webp"],
                            "blocked_upload_extensions": [],
                            "block_executable_uploads": True,
                        }
                    },
                ),
            ):
                path, _size = asyncio.run(web_app._save_upload_cache(upload, "session", "01"))

            self.assertTrue(path.endswith(".webp"))
            with Image.open(path) as image:
                self.assertEqual(image.format, "WEBP")
            self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_upload_cache_entry_returns_detected_name_for_misnamed_jfif(self) -> None:
        if Image is None:
            self.skipTest("Pillow unavailable")
        temp_dir = _workspace_temp("web_app_upload_normalize_jfif_name")
        try:
            buffer = io.BytesIO()
            try:
                Image.new("RGB", (16, 16), "white").save(buffer, format="WEBP")
            except Exception:
                self.skipTest("Pillow WebP support unavailable")
            upload = _MemoryUpload("product.jfif", [buffer.getvalue()], "image/jpeg")
            with (
                patch.object(web_app.settings, "AC", str(temp_dir)),
                patch.object(
                    web_app.config,
                    "CONFIG",
                    {
                        web_app.SECURITY_SETTINGS_KEY: {
                            "allowed_upload_extensions": ["jfif", "webp"],
                            "blocked_upload_extensions": [],
                            "block_executable_uploads": True,
                        }
                    },
                ),
            ):
                saved = asyncio.run(
                    web_app._save_upload_cache_entry(
                        upload,
                        "session",
                        "01",
                        normalize_extension=True,
                    )
                )

            self.assertTrue(saved.path.endswith(".webp"))
            self.assertEqual(saved.name, "product.webp")
            self.assertTrue(upload.closed)
        finally:
            shutil.rmtree(temp_dir)

    def test_save_upload_cache_runs_optional_antivirus_scan(self) -> None:
        if Image is None:
            self.skipTest("Pillow unavailable")
        temp_dir = _workspace_temp("web_app_upload_antivirus")
        try:
            buffer = io.BytesIO()
            Image.new("RGB", (10, 10), "white").save(buffer, format="JPEG")
            upload = _MemoryUpload("photo.jpg", [buffer.getvalue()], "image/jpeg")
            with (
                patch.object(web_app.settings, "AC", str(temp_dir)),
                patch.object(
                    web_app.config,
                    "CONFIG",
                    {
                        web_app.SECURITY_SETTINGS_KEY: {
                            "antivirus_scan_uploads": True,
                        }
                    },
                ),
                patch.object(web_app, "_defender_scan_executable", return_value="MpCmdRun.exe"),
                patch.object(
                    web_app.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0, stdout="clean", stderr=""),
                ) as scan,
            ):
                path, _size = asyncio.run(web_app._save_upload_cache(upload, "session", "01"))

            scan.assert_called_once()
            scan_result = web_app._upload_scan_result(path)
            self.assertTrue(scan_result["enabled"])
            self.assertTrue(scan_result["scanned"])
            self.assertEqual(scan_result["scanner"], "Microsoft Defender")
        finally:
            shutil.rmtree(temp_dir)

    def test_delete_local_files_is_idempotent_and_preserves_saved_paths(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            root = Path(temp_dir)
            delete_file = root / "delete.jpg"
            saved_file = root / "saved.jpg"
            missing_file = root / "missing.jpg"
            delete_file.write_bytes(b"delete")
            saved_file.write_bytes(b"saved")

            with patch.object(web_app.settings, "l", str(root)):
                result = web_app._delete_local_files(
                    [
                        {"prefix": "03", "local_path": str(delete_file)},
                        {"prefix": "04", "local_path": str(saved_file)},
                        {"prefix": "05", "local_path": str(missing_file)},
                    ],
                    {str(saved_file)},
                )

            self.assertEqual(result["deleted"], 1)
            self.assertEqual(result["skipped"], 2)
            self.assertEqual(result["errors"], [])
            self.assertEqual(
                [(item["slot"], item["status"]) for item in result["slot_results"]],
                [("03", "deleted"), ("04", "skipped"), ("05", "skipped")],
            )
            self.assertTrue(all(item["elapsed_ms"] >= 0 for item in result["slot_results"]))
            self.assertFalse(delete_file.exists())
            self.assertTrue(saved_file.exists())

    def test_ftp_sync_skips_upload_for_backfilled_prefixes(self) -> None:
        result = SimpleNamespace(
            output_dir="processed",
            saved_files=[
                SimpleNamespace(
                    prefix="03",
                    filename="5901234567890_03_DETAIL_MAGGIORE.jpg",
                )
            ],
        )

        with (
            patch.dict(web_app.config.CONFIG, {web_app.ft: True, web_app.H: {}}, clear=False),
            patch.object(
                web_app,
                "sync_remote_files",
                return_value={"uploaded": 0, "deleted": 0, "elapsed_ms": 1, "error": ""},
            ) as sync_remote,
        ):
            payload = web_app._sync_result_to_ftp(
                result,
                [],
                skip_upload_prefixes={"03"},
            )

        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["uploaded"], 0)
        self.assertEqual(
            payload["slot_results"],
            [
                {
                    "slot": "03",
                    "upload_status": "skipped",
                    "delete_status": "not_requested",
                    "elapsed_ms": 0,
                }
            ],
        )
        sync_remote.assert_not_called()

    def test_ftp_sync_derives_slot_specific_statuses_from_requested_and_provider_result(self) -> None:
        result = SimpleNamespace(
            output_dir="processed",
            saved_files=[
                SimpleNamespace(prefix="03", filename="5901234567890_03_NEW.jpg"),
                SimpleNamespace(prefix="04", filename="5901234567890_04_NEW.jpg"),
            ],
        )
        with (
            patch.dict(web_app.config.CONFIG, {web_app.ft: True, web_app.H: {}}, clear=False),
            patch.object(
                web_app,
                "sync_remote_files",
                return_value={"uploaded": 1, "deleted": 1, "elapsed_ms": 25, "error": "network"},
            ),
        ):
            payload = web_app._sync_result_to_ftp(
                result,
                ["5901234567890_05_OLD.jpg"],
            )

        assert payload["slot_results"] == [
            {
                "slot": "03",
                "upload_status": "partial",
                "delete_status": "not_requested",
                "elapsed_ms": 25,
                "upload_count": 1,
                "upload_requested": 2,
                "provider_error": True,
            },
            {
                "slot": "04",
                "upload_status": "partial",
                "delete_status": "not_requested",
                "elapsed_ms": 25,
                "upload_count": 1,
                "upload_requested": 2,
                "provider_error": True,
            },
            {"slot": "05", "upload_status": "not_requested", "delete_status": "deleted", "elapsed_ms": 25},
        ]

    def test_existing_local_photos_are_migrated_when_product_path_changes(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            root = Path(temp_dir)
            processed = root / "processed"
            old_file = processed / "MAGGIORE" / "KOMODA" / "MA03" / "BIALY" / "NO-LED"
            old_file.mkdir(parents=True)
            photo_path = old_file / "5901234567890_03_DETAIL_MAGGIORE_KOMODA_MA03_BIALY_NO-LED.jpg"
            photo_path.write_bytes(b"old")
            uploaded_slots = []
            delete_requests = []
            existing_entry = {
                "product_id": "PRD-1",
                "ean": "5901234567890",
                "name": "MAGGIORE",
                "type_name": "KOMODA",
                "model": "MA03",
                "color1": "BIALY",
                "color2": "",
                "color3": "",
                "extra": "NO-LED",
            }
            product = web_app.WebProductForm(
                product_id="PRD-1",
                ean="5901234567890",
                name="MAGGIORE",
                type_name="KOMODA",
                model="MA03",
                color1="BIALY",
                color2="DAB",
                extra="NO-LED",
            )

            with (
                patch.object(web_app.settings, "l", str(processed)),
                patch.object(
                    web_app,
                    "find_product_photos",
                    return_value=[
                        {
                            "prefix": "03",
                            "path": str(photo_path),
                            "filename": photo_path.name,
                            "ftp": True,
                            "ftp_filename": "5901234567890_03.jpg",
                        }
                    ],
                ),
            ):
                migrated = web_app._append_existing_photo_migrations(
                    existing_entry=existing_entry,
                    product=product,
                    uploaded_slots=uploaded_slots,
                    delete_requests=delete_requests,
                    slot_by_prefix={"03": {"prefix": "03", "label": "DETAIL_pic"}},
                )

            self.assertEqual(migrated, ["03"])
            self.assertEqual(uploaded_slots[0].prefix, "03")
            self.assertEqual(uploaded_slots[0].source_path, str(photo_path))
            self.assertEqual(uploaded_slots[0].original_filename, photo_path.name)
            self.assertEqual(delete_requests[0]["local_path"], str(photo_path))

    def test_ftp_only_photos_are_downloaded_when_local_file_is_missing(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            root = Path(temp_dir)
            processed = root / "processed"
            cache_file = root / "cache" / "5901234567890_03.jpg"
            cache_file.parent.mkdir(parents=True)
            cache_file.write_bytes(b"ftp")
            uploaded_slots = []
            delete_requests = []
            existing_entry = {
                "product_id": "PRD-1",
                "ean": "5901234567890",
                "name": "MAGGIORE",
                "type_name": "KOMODA",
                "model": "MA03",
                "color1": "BIALY",
                "extra": "NO-LED",
            }
            product = web_app.WebProductForm(
                product_id="PRD-1",
                ean="5901234567890",
                name="MAGGIORE",
                type_name="KOMODA",
                model="MA03",
                color1="BIALY",
                extra="NO-LED",
            )

            with (
                patch.object(web_app.settings, "l", str(processed)),
                patch.object(
                    web_app,
                    "find_product_photos",
                    return_value=[
                        {
                            "ean": "5901234567890",
                            "prefix": "03",
                            "path": "",
                            "ftp_filename": "5901234567890_03.jpg",
                        }
                    ],
                ),
                patch.object(web_app, "cache_ftp_preview", return_value=str(cache_file)) as cache_ftp,
            ):
                appended = web_app._append_existing_photo_migrations(
                    existing_entry=existing_entry,
                    product=product,
                    uploaded_slots=uploaded_slots,
                    delete_requests=delete_requests,
                    slot_by_prefix={"03": {"prefix": "03", "label": "DETAIL_pic"}},
                )

            self.assertEqual(appended, ["03"])
            cache_ftp.assert_called_once_with(
                "5901234567890",
                "5901234567890_03.jpg",
                cache_scope="",
            )
            self.assertEqual(uploaded_slots[0].source_path, str(cache_file))
            self.assertEqual(delete_requests[0]["local_path"], "")
            self.assertEqual(delete_requests[0]["ftp_filename"], "5901234567890_03.jpg")
            self.assertTrue(delete_requests[0]["ftp_backfill"])

    def test_local_only_photos_are_appended_for_missing_ftp_upload(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            root = Path(temp_dir)
            processed = root / "processed"
            local_dir = processed / "MAGGIORE" / "KOMODA" / "MA03" / "BIALY" / "NO-LED"
            local_dir.mkdir(parents=True)
            photo_path = local_dir / "5901234567890_03_DETAIL_MAGGIORE_KOMODA_MA03_BIALY_NO-LED.jpg"
            photo_path.write_bytes(b"local")
            uploaded_slots = []
            delete_requests = []
            product = web_app.WebProductForm(
                product_id="PRD-1",
                ean="5901234567890",
                name="MAGGIORE",
                type_name="KOMODA",
                model="MA03",
                color1="BIALY",
                extra="NO-LED",
            )

            with (
                patch.object(web_app.settings, "l", str(processed)),
                patch.dict(web_app.config.CONFIG, {web_app.ft: True}, clear=False),
                patch.object(
                    web_app,
                    "find_product_photos",
                    return_value=[
                        {
                            "ean": "5901234567890",
                            "prefix": "03",
                            "path": str(photo_path),
                            "filename": photo_path.name,
                            "ftp_filename": "",
                        }
                    ],
                ),
            ):
                appended = web_app._append_existing_photo_migrations(
                    existing_entry={"ean": "5901234567890"},
                    product=product,
                    uploaded_slots=uploaded_slots,
                    delete_requests=delete_requests,
                    slot_by_prefix={"03": {"prefix": "03", "label": "DETAIL_pic"}},
                )

            self.assertEqual(appended, ["03"])
            self.assertEqual(uploaded_slots[0].source_path, str(photo_path))
            self.assertEqual(delete_requests[0]["ftp_filename"], "")
            self.assertFalse(delete_requests[0]["ftp_backfill"])

    def test_local_photo_is_appended_for_missing_sql_without_delete_request(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            root = Path(temp_dir)
            processed = root / "processed"
            local_dir = processed / "MAGGIORE" / "KOMODA" / "MA03" / "BIALY" / "NO-LED"
            local_dir.mkdir(parents=True)
            photo_path = local_dir / "5901234567890_03_DETAIL_MAGGIORE_KOMODA_MA03_BIALY_NO-LED.jpg"
            photo_path.write_bytes(b"local")
            uploaded_slots = []
            delete_requests = []
            product = web_app.WebProductForm(
                product_id="PRD-1",
                ean="5901234567890",
                name="MAGGIORE",
                type_name="KOMODA",
                model="MA03",
                color1="BIALY",
                extra="NO-LED",
            )

            with (
                patch.object(web_app.settings, "l", str(processed)),
                patch.object(
                    web_app,
                    "find_product_photos",
                    return_value=[
                        {
                            "ean": "5901234567890",
                            "prefix": "03",
                            "path": str(photo_path),
                            "filename": photo_path.name,
                            "ftp": True,
                            "ftp_filename": "5901234567890_03.jpg",
                            "sql": False,
                            "sql_checked": True,
                        }
                    ],
                ) as find_photos,
            ):
                appended = web_app._append_existing_photo_migrations(
                    existing_entry={
                        "product_id": "PRD-1",
                        "ean": "5901234567890",
                        "name": "MAGGIORE",
                        "type_name": "KOMODA",
                        "model": "MA03",
                        "color1": "BIALY",
                        "color2": "",
                        "color3": "",
                        "extra": "NO-LED",
                    },
                    product=product,
                    uploaded_slots=uploaded_slots,
                    delete_requests=delete_requests,
                    slot_by_prefix={"03": {"prefix": "03", "label": "DETAIL_pic"}},
                )

            self.assertEqual(appended, ["03"])
            self.assertEqual(uploaded_slots[0].source_path, str(photo_path))
            self.assertEqual(delete_requests, [])
            self.assertTrue(find_photos.call_args.kwargs["include_sql"])

    def test_existing_photo_migration_uses_preloaded_photos(self) -> None:
        uploaded_slots = []
        delete_requests = []
        product = web_app.WebProductForm(
            product_id="PRD-1",
            ean="5901234567890",
            name="MAGGIORE",
            type_name="KOMODA",
            model="MA03",
            color1="BIALY",
            extra="NO-LED",
        )
        existing_photos = [
            {
                "ean": "5901234567890",
                "prefix": "03",
                "path": str(Path(__file__)),
                "filename": Path(__file__).name,
                "local": True,
                "ftp": True,
                "ftp_filename": "5901234567890_03.jpg",
                "sql": True,
                "sql_checked": True,
            }
        ]

        with patch.object(web_app, "find_product_photos") as find_photos:
            appended = web_app._append_existing_photo_migrations(
                existing_entry={
                    "product_id": "PRD-1",
                    "ean": "5901234567890",
                    "name": "MAGGIORE",
                    "type_name": "KOMODA",
                    "model": "MA03",
                    "color1": "BIALY",
                    "color2": "",
                    "color3": "",
                    "extra": "NO-LED",
                },
                product=product,
                uploaded_slots=uploaded_slots,
                delete_requests=delete_requests,
                slot_by_prefix={"03": {"prefix": "03", "label": "DETAIL_pic"}},
                existing_photos=existing_photos,
            )

        self.assertEqual(appended, [])
        find_photos.assert_not_called()

    def test_ftp_upload_is_skipped_for_sql_only_repair_with_existing_remote(self) -> None:
        result = SimpleNamespace(
            saved_files=[
                SimpleNamespace(
                    prefix="03",
                    filename="5901234567890_03_DETAIL_MAGGIORE.jpg",
                )
            ],
        )

        skipped = web_app._ftp_skip_upload_prefixes(
            result,
            [{"prefix": "03", "ftp": True}],
            explicit_prefixes=set(),
            migrated_prefixes=set(),
            ftp_backfill_prefixes=set(),
        )

        self.assertEqual(skipped, {"03"})

    def test_ftp_upload_is_skipped_for_existing_remote_even_when_local_file_exists(self) -> None:
        result = SimpleNamespace(
            saved_files=[
                SimpleNamespace(
                    prefix="03",
                    filename="5901234567890_03_DETAIL_MAGGIORE.jpg",
                )
            ],
        )

        skipped = web_app._ftp_skip_upload_prefixes(
            result,
            [{"prefix": "03", "local": True, "ftp": True}],
            explicit_prefixes=set(),
            migrated_prefixes=set(),
            ftp_backfill_prefixes=set(),
        )

        self.assertEqual(skipped, {"03"})

    def test_sql_sync_skips_updates_when_product_row_is_missing(self) -> None:
        result = SimpleNamespace(
            ean="5901234567890",
            saved_files=[
                SimpleNamespace(
                    prefix="03",
                    filename="5901234567890_03_DETAIL_MAGGIORE.jpg",
                )
            ],
        )

        class Cursor:
            rowcount = -1

            def __init__(self) -> None:
                self.queries = []

            def execute(self, query):
                self.queries.append(query)

            def fetchone(self):
                return None

            def close(self):
                return None

        class Connection:
            def __init__(self) -> None:
                self.cursor_obj = Cursor()
                self.committed = False

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                self.committed = True

            def rollback(self):
                return None

            def close(self):
                return None

        conn = Connection()
        with (
            patch.dict(
                web_app.config.CONFIG,
                {
                    web_app.u: True,
                    web_app.p: web_app.K,
                    web_app.w: "UPDATE object_query_1 SET {col} = '{filename}' WHERE EAN = '{ean}'",
                    web_app.SQL_COLUMN_MAP_KEY: {"03": "img_03"},
                },
                clear=False,
            ),
            patch.object(web_app, "connect_db", return_value=conn),
        ):
            payload = web_app._sync_result_to_sql(result)

        self.assertTrue(payload["skipped"])
        self.assertEqual(payload["updated"], 0)
        self.assertEqual(payload["rows"], 0)
        self.assertEqual(len(conn.cursor_obj.queries), 1)
        self.assertIn("SELECT 1", conn.cursor_obj.queries[0])
        self.assertFalse(conn.committed)
        self.assertEqual(
            payload["slot_results"],
            [{"slot": "03", "operation": "update", "status": "skipped", "elapsed_ms": payload["elapsed_ms"]}],
        )

    def test_sql_sync_does_not_count_zero_row_updates(self) -> None:
        result = SimpleNamespace(
            ean="5901234567890",
            saved_files=[
                SimpleNamespace(
                    prefix="03",
                    filename="5901234567890_03_DETAIL_MAGGIORE.jpg",
                )
            ],
        )

        class Cursor:
            rowcount = -1

            def __init__(self) -> None:
                self.queries = []

            def execute(self, query):
                self.queries.append(query)
                self.rowcount = 0 if str(query).lstrip().upper().startswith("UPDATE") else -1

            def fetchone(self):
                return (1,)

            def close(self):
                return None

        class Connection:
            def __init__(self) -> None:
                self.cursor_obj = Cursor()
                self.committed = False

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                self.committed = True

            def rollback(self):
                return None

            def close(self):
                return None

        conn = Connection()
        with (
            patch.dict(
                web_app.config.CONFIG,
                {
                    web_app.u: True,
                    web_app.p: web_app.K,
                    web_app.w: "UPDATE object_query_1 SET {col} = '{filename}' WHERE EAN = '{ean}'",
                    web_app.SQL_COLUMN_MAP_KEY: {"03": "img_03"},
                },
                clear=False,
            ),
            patch.object(web_app, "connect_db", return_value=conn),
        ):
            payload = web_app._sync_result_to_sql(result)

        self.assertFalse(payload["skipped"])
        self.assertEqual(payload["updated"], 0)
        self.assertEqual(payload["rows"], 0)
        self.assertEqual(len(conn.cursor_obj.queries), 2)
        self.assertFalse(conn.committed)

    def test_sql_sync_rolls_back_success_evidence_when_later_slot_fails(self) -> None:
        result = SimpleNamespace(
            ean="5901234567890",
            saved_files=[
                SimpleNamespace(prefix="03", filename="5901234567890_03_NEW.jpg"),
                SimpleNamespace(prefix="04", filename="5901234567890_04_NEW.jpg"),
                SimpleNamespace(prefix="05", filename="5901234567890_05_NEW.jpg"),
            ],
        )

        class Cursor:
            rowcount = -1

            def execute(self, query):
                if "img_04" in str(query):
                    raise RuntimeError("second slot failed")
                self.rowcount = 1 if str(query).lstrip().upper().startswith("UPDATE") else -1

            def fetchone(self):
                return (1,)

            def close(self):
                return None

        class Connection:
            def __init__(self):
                self.cursor_obj = Cursor()
                self.committed = False
                self.rolled_back = False

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                self.committed = True

            def rollback(self):
                self.rolled_back = True

            def close(self):
                return None

        conn = Connection()
        with (
            patch.dict(
                web_app.config.CONFIG,
                {
                    web_app.u: True,
                    web_app.p: web_app.K,
                    web_app.w: "UPDATE object_query_1 SET {col} = '{filename}' WHERE EAN = '{ean}'",
                    web_app.SQL_COLUMN_MAP_KEY: {
                        "03": "img_03",
                        "04": "img_04",
                        "05": "img_05",
                    },
                },
                clear=False,
            ),
            patch.object(web_app, "connect_db", return_value=conn),
        ):
            payload = web_app._sync_result_to_sql(result)

        assert payload["error"] == "second slot failed"
        assert payload["updated"] == 0
        assert payload["rows"] == 0
        assert payload["rolled_back"] is True
        assert conn.rolled_back is True
        assert conn.committed is False
        assert payload["slot_results"] == [
            {
                "slot": "03",
                "operation": "update",
                "status": "error",
                "elapsed_ms": payload["elapsed_ms"],
                "provider": "sql",
                "reason": "second slot failed",
                "attempted": True,
                "rolled_back": True,
            },
            {
                "slot": "04",
                "operation": "update",
                "status": "error",
                "elapsed_ms": payload["elapsed_ms"],
                "provider": "sql",
                "reason": "second slot failed",
                "attempted": True,
                "rolled_back": False,
            },
            {
                "slot": "05",
                "operation": "update",
                "status": "error",
                "elapsed_ms": payload["elapsed_ms"],
                "provider": "sql",
                "reason": "second slot failed",
                "attempted": False,
                "rolled_back": False,
            },
        ]

    def test_sql_sync_connect_failure_marks_every_requested_slot_as_error(self) -> None:
        result = SimpleNamespace(
            ean="5901234567890",
            saved_files=[
                SimpleNamespace(prefix="03", filename="5901234567890_03_NEW.jpg")
            ],
        )

        with (
            patch.dict(
                web_app.config.CONFIG,
                {
                    web_app.u: True,
                    web_app.p: web_app.K,
                    web_app.w: "UPDATE object_query_1 SET {col} = '{filename}' WHERE EAN = '{ean}'",
                    web_app.SQL_COLUMN_MAP_KEY: {"03": "img_03", "04": "img_04"},
                },
                clear=False,
            ),
            patch.object(web_app, "connect_db", side_effect=RuntimeError("sql offline")),
        ):
            payload = web_app._sync_result_to_sql(result, clear_prefixes={"04"})

        assert payload["error"] == "sql offline"
        assert payload["updated"] == 0
        assert payload["cleared"] == 0
        assert payload["rows"] == 0
        assert payload["rolled_back"] is False
        assert payload["slot_results"] == [
            {
                "slot": "03",
                "operation": "update",
                "status": "error",
                "elapsed_ms": payload["elapsed_ms"],
                "provider": "sql",
                "reason": "sql offline",
                "attempted": False,
                "rolled_back": False,
            },
            {
                "slot": "04",
                "operation": "clear",
                "status": "error",
                "elapsed_ms": payload["elapsed_ms"],
                "provider": "sql",
                "reason": "sql offline",
                "attempted": False,
                "rolled_back": False,
            },
        ]

    def test_local_slot_results_preserve_save_and_delete_evidence_for_same_slot(self) -> None:
        result = web_app._local_slot_results(
            [{"prefix": "03", "elapsed_ms": 12}],
            {
                "slot_results": [
                    {"slot": "03", "status": "error", "elapsed_ms": 4}
                ]
            },
        )

        assert result == [
            {"slot": "03", "operation": "save", "status": "saved", "elapsed_ms": 12},
            {"slot": "03", "operation": "delete", "status": "error", "elapsed_ms": 4},
        ]

    def test_complete_existing_photo_is_not_appended_without_missing_sources(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            root = Path(temp_dir)
            processed = root / "processed"
            local_dir = processed / "MAGGIORE" / "KOMODA" / "MA03" / "BIALY" / "NO-LED"
            local_dir.mkdir(parents=True)
            photo_path = local_dir / "5901234567890_03_DETAIL_MAGGIORE_KOMODA_MA03_BIALY_NO-LED.jpg"
            photo_path.write_bytes(b"local")
            uploaded_slots = []
            delete_requests = []
            product = web_app.WebProductForm(
                product_id="PRD-1",
                ean="5901234567890",
                name="MAGGIORE",
                type_name="KOMODA",
                model="MA03",
                color1="BIALY",
                extra="NO-LED",
            )

            with (
                patch.object(web_app.settings, "l", str(processed)),
                patch.dict(web_app.config.CONFIG, {web_app.ft: True}, clear=False),
                patch.object(
                    web_app,
                    "find_product_photos",
                    return_value=[
                        {
                            "ean": "5901234567890",
                            "prefix": "03",
                            "path": str(photo_path),
                            "filename": photo_path.name,
                            "local": True,
                            "ftp": True,
                            "ftp_filename": "5901234567890_03.jpg",
                            "sql": True,
                            "sql_checked": True,
                        }
                    ],
                ),
            ):
                appended = web_app._append_existing_photo_migrations(
                    existing_entry={
                        "product_id": "PRD-1",
                        "ean": "5901234567890",
                        "name": "MAGGIORE",
                        "type_name": "KOMODA",
                        "model": "MA03",
                        "color1": "BIALY",
                        "color2": "",
                        "color3": "",
                        "extra": "NO-LED",
                    },
                    product=product,
                    uploaded_slots=uploaded_slots,
                    delete_requests=delete_requests,
                    slot_by_prefix={"03": {"prefix": "03", "label": "DETAIL_pic"}},
                )

            self.assertEqual(appended, [])
            self.assertEqual(uploaded_slots, [])
            self.assertEqual(delete_requests, [])

    def test_enriched_local_photo_urls_include_file_version(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            photo_path = Path(temp_dir) / "5901234567890_03.jpg"
            photo_path.write_bytes(b"first")
            with patch.object(web_app.settings, "l", temp_dir):
                first = web_app._enrich_photo_payload([{"prefix": "03", "path": str(photo_path)}])[0]
                photo_path.write_bytes(b"changed-content")
                second = web_app._enrich_photo_payload([{"prefix": "03", "path": str(photo_path)}])[0]

        self.assertIn("&v=", first["url"])
        self.assertIn("&v=", first["thumb_url"])
        self.assertNotEqual(first["file_version"], second["file_version"])
        self.assertNotEqual(first["thumb_url"], second["thumb_url"])

    def test_ftp_upload_is_kept_for_explicitly_changed_slot(self) -> None:
        result = SimpleNamespace(
            saved_files=[
                SimpleNamespace(
                    prefix="03",
                    filename="5901234567890_03_DETAIL_MAGGIORE.jpg",
                )
            ],
        )

        skipped = web_app._ftp_skip_upload_prefixes(
            result,
            [{"prefix": "03", "ftp": True}],
            explicit_prefixes={"03"},
            migrated_prefixes=set(),
            ftp_backfill_prefixes=set(),
        )

        self.assertEqual(skipped, set())

    def test_explicit_slot_replacement_deletes_old_remote_when_extension_changes(self) -> None:
        result = SimpleNamespace(
            saved_files=[
                SimpleNamespace(
                    prefix="03",
                    filename="5901234567890_03_DETAIL_MAGGIORE.png",
                )
            ],
        )

        deletes = web_app._ftp_replacement_delete_candidates(
            result,
            [{"prefix": "03", "ftp_filename": "5901234567890_03.jpg"}],
            explicit_prefixes={"03"},
        )

        self.assertEqual(deletes, ["5901234567890_03.jpg"])

    def test_explicit_slot_replacement_keeps_same_remote_name_for_overwrite(self) -> None:
        result = SimpleNamespace(
            saved_files=[
                SimpleNamespace(
                    prefix="03",
                    filename="5901234567890_03_DETAIL_MAGGIORE.jpg",
                )
            ],
        )

        deletes = web_app._ftp_replacement_delete_candidates(
            result,
            [{"prefix": "03", "ftp_filename": "5901234567890_03.jpg"}],
            explicit_prefixes={"03"},
        )

        self.assertEqual(deletes, [])

    def test_deleted_ftp_only_slot_is_not_downloaded_again(self) -> None:
        product = web_app.WebProductForm(
            product_id="PRD-1",
            ean="5901234567890",
            name="MAGGIORE",
            type_name="KOMODA",
            model="MA03",
            color1="BIALY",
        )
        delete_requests = [{"prefix": "03", "ftp_filename": "5901234567890_03.jpg"}]

        with (
            patch.object(
                web_app,
                "find_product_photos",
                return_value=[
                    {
                        "ean": "5901234567890",
                        "prefix": "03",
                        "path": "",
                        "ftp_filename": "5901234567890_03.jpg",
                    }
                ],
            ),
            patch.object(web_app, "cache_ftp_preview") as cache_ftp,
        ):
            appended = web_app._append_existing_photo_migrations(
                existing_entry={"ean": "5901234567890"},
                product=product,
                uploaded_slots=[],
                delete_requests=delete_requests,
                slot_by_prefix={"03": {"prefix": "03", "label": "DETAIL_pic"}},
            )

        self.assertEqual(appended, [])
        cache_ftp.assert_not_called()

    def test_pending_ftp_slot_can_replace_deleted_target_prefix(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            cache_file = Path(temp_dir) / "5901234567890_02.jpg"
            cache_file.write_bytes(b"ftp")
            product = web_app.WebProductForm(
                product_id="PRD-1",
                ean="5901234567890",
                name="MAGGIORE",
                type_name="KOMODA",
                model="MA03",
                color1="BIALY",
            )
            uploaded_slots = []
            delete_requests = [
                {
                    "prefix": "03",
                    "label": "DETAIL_pic",
                    "local_path": "",
                    "ftp_filename": "5901234567890_03.jpg",
                    "sql": False,
                }
            ]
            pending_ftp_slots = [
                {
                    "prefix": "03",
                    "label": "DETAIL_pic",
                    "filename": "5901234567890_02.jpg",
                    "ean": "5901234567890",
                    "content_fit": True,
                }
            ]

            with patch.object(web_app, "cache_ftp_preview", return_value=str(cache_file)) as cache_ftp:
                appended = web_app._append_pending_ftp_slots(
                    product=product,
                    pending_ftp_slots=pending_ftp_slots,
                    uploaded_slots=uploaded_slots,
                    delete_requests=delete_requests,
                )

            self.assertEqual(appended, ["03"])
            cache_ftp.assert_called_once_with(
                "5901234567890",
                "5901234567890_02.jpg",
                cache_scope="",
            )
            self.assertEqual(uploaded_slots[0].prefix, "03")
            self.assertEqual(uploaded_slots[0].source_path, str(cache_file))
            self.assertTrue(uploaded_slots[0].content_fit)
            self.assertEqual(
                [item["ftp_filename"] for item in delete_requests],
                ["5901234567890_03.jpg", "5901234567890_02.jpg"],
            )

    def test_ftp_only_existing_photos_backfill_unoccupied_slots(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            uploaded_source = Path(temp_dir) / "new-14.jpg"
            cache_file = Path(temp_dir) / "5901234567890_15.jpg"
            uploaded_source.write_bytes(b"new")
            cache_file.write_bytes(b"ftp")
            product = web_app.WebProductForm(
                ean="5901234567890",
                name="MAGGIORE",
                type_name="KOMODA",
                model="MA03",
                color1="BIALY",
            )
            uploaded_slots = [
                web_app.WebUploadedSlot(
                    prefix="14",
                    label="DETAIL_pic",
                    source_path=str(uploaded_source),
                    original_filename="new-14.jpg",
                )
            ]
            delete_requests = []
            existing_photos = [
                {"ean": "5901234567890", "prefix": "14", "ftp": True, "ftp_filename": "5901234567890_14.jpg"},
                {"ean": "5901234567890", "prefix": "15", "ftp": True, "ftp_filename": "5901234567890_15.jpg"},
            ]

            with patch.object(web_app, "cache_ftp_preview", return_value=str(cache_file)) as cache_ftp:
                appended = web_app._append_existing_photo_migrations(
                    existing_entry=None,
                    product=product,
                    uploaded_slots=uploaded_slots,
                    delete_requests=delete_requests,
                    slot_by_prefix={
                        "14": {"prefix": "14", "label": "DETAIL_pic"},
                        "15": {"prefix": "15", "label": "DETAIL_pic"},
                    },
                    existing_photos=existing_photos,
                )

            self.assertEqual(appended, ["15"])
            self.assertEqual([slot.prefix for slot in uploaded_slots], ["14", "15"])
            self.assertEqual(uploaded_slots[0].source_path, str(uploaded_source))
            self.assertEqual(uploaded_slots[1].source_path, str(cache_file))
            self.assertEqual(delete_requests[0]["prefix"], "15")
            self.assertTrue(delete_requests[0]["ftp_backfill"])
            cache_ftp.assert_called_once_with(
                "5901234567890",
                "5901234567890_15.jpg",
                cache_scope="",
            )

    def test_log_parser_groups_traceback_into_one_critical_event(self) -> None:
        events = web_app._parse_log_events(
            {
                "key": "errors",
                "label": "Bledy",
                "path": "errors.log",
                "lines": [
                    "[2026-05-11 14:14:11] [USER: user] [PC: pc] ERROR: WEB POST /api/ftp-preview: boom",
                    "Traceback (most recent call last):",
                    "  File \"app.py\", line 1, in handler",
                    "RuntimeError: boom",
                    "[2026-05-11 14:15:00] [USER: user] [PC: pc] ERROR: Brak dostepu",
                ],
            }
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["severity"], "critical")
        self.assertEqual(len(events[0]["lines"]), 4)
        self.assertEqual(events[1]["severity"], "warning")

    def test_log_parser_splits_plain_lines_and_strips_control_sequences(self) -> None:
        events = web_app._parse_log_events(
            {
                "key": "web_out",
                "label": "Web stdout",
                "path": "out.log",
                "lines": [
                    '\x1b[32mINFO\x1b[0m:     127.0.0.1:1 - "GET /ok HTTP/1.1" 200 OK',
                    'INFO:     127.0.0.1:2 - "GET /missing HTTP/1.1" 404 Not Found',
                ],
            }
        )

        self.assertEqual(len(events), 2)
        self.assertNotIn("\x1b", events[0]["summary"])
        self.assertEqual(events[0]["severity"], "info")
        self.assertEqual(events[1]["severity"], "warning")

    def test_web_event_info_details_with_error_keys_stay_info(self) -> None:
        events = web_app._parse_log_events(
            {
                "key": "web_events",
                "label": "Zdarzenia web",
                "path": "events.log",
                "lines": [
                    "[2026-05-12 12:54:30] [USER: admin] INFO: PROCESS_COMPLETED - Zapisano 0 plikow, usunieto lokalnie 0.",
                    'details: {"ftp": {"error": ""}, "sql": {"error": ""}}',
                ],
            }
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "info")

    def test_user_cache_scope_is_session_specific(self) -> None:
        first = web_app._user_cache_scope(
            SimpleNamespace(cookies={web_app.SESSION_COOKIE: "session-one"}),
            "admin",
        )
        second = web_app._user_cache_scope(
            SimpleNamespace(cookies={web_app.SESSION_COOKIE: "session-two"}),
            "admin",
        )
        other_user = web_app._user_cache_scope(
            SimpleNamespace(cookies={web_app.SESSION_COOKIE: "session-one"}),
            "operator",
        )

        self.assertNotEqual(first, second)
        self.assertNotEqual(first, other_user)
        self.assertTrue(first.startswith("admin-"))

    def test_user_cache_scope_without_session_uses_client_context(self) -> None:
        first = web_app._user_cache_scope(
            SimpleNamespace(
                cookies={},
                client=SimpleNamespace(host="192.0.2.10"),
                headers={"user-agent": "browser-a"},
            ),
            "admin",
        )
        second = web_app._user_cache_scope(
            SimpleNamespace(
                cookies={},
                client=SimpleNamespace(host="192.0.2.11"),
                headers={"user-agent": "browser-a"},
            ),
            "admin",
        )

        self.assertNotEqual(first, second)

    def test_log_payloads_are_newest_first_and_hide_successful_access_logs(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            log_path = Path(temp_dir) / "picsyncra_web_out.log"
            log_path.write_text(
                "\n".join(
                    [
                        "INFO:     Custom maintenance event.",
                        'INFO:     127.0.0.1:1 - "GET /api/logs?limit=120 HTTP/1.1" 200 OK',
                        'INFO:     127.0.0.1:2 - "GET /crash HTTP/1.1" 500 Internal Server Error',
                    ]
                ),
                encoding="utf-8",
            )
            targets = [{"key": "web_out", "label": "Web stdout", "path": log_path}]

            with patch.object(web_app, "_log_targets", return_value=targets):
                payload = web_app._log_payloads(20)[0]

            summaries = [event["summary"] for event in payload["events"]]
            self.assertEqual(len(summaries), 2)
            self.assertIn("/crash", summaries[0])
            self.assertEqual(summaries[1], "Custom maintenance event.")

    def test_runtime_logs_hide_uvicorn_startup_and_400_access_noise(self) -> None:
        startup_event = {
            "source": "web_err",
            "lines": ["INFO:     Uvicorn running on http://0.0.0.0:8010 (Press CTRL+C to quit)"],
        }
        bad_request_event = {
            "source": "web_out",
            "lines": ['INFO:     127.0.0.1:1 - "POST /api/process HTTP/1.1" 400 Bad Request'],
        }
        server_error_event = {
            "source": "web_out",
            "lines": ['INFO:     127.0.0.1:1 - "POST /api/process HTTP/1.1" 500 Internal Server Error'],
        }

        self.assertFalse(web_app._is_visible_log_event(startup_event))
        self.assertFalse(web_app._is_visible_log_event(bad_request_event))
        self.assertTrue(web_app._is_visible_log_event(server_error_event))

    def test_background_process_routes_are_registered(self) -> None:
        route_paths = {getattr(route, "path", "") for route in web_app.app.routes}

        self.assertIn("/api/process/background", route_paths)
        self.assertIn("/api/process-jobs", route_paths)
        self.assertIn("/api/process-jobs/active", route_paths)
        self.assertIn("/api/process-jobs/{job_id}", route_paths)

    def test_background_process_rejects_before_materializing_when_queue_is_full(
        self,
    ) -> None:
        """Catches a saturated queue that still stages an upload before rejecting it."""
        client = TestClient(web_app.app)
        full_queue = Mock()
        full_queue.reserve.side_effect = ProcessQueueFull(retry_after_seconds=2)
        snapshot = web_app._ProcessFormSnapshot()

        with (
            patch.object(web_app, "_require_user", return_value="operator"),
            patch.object(web_app, "_PROCESS_QUEUE", full_queue, create=True),
            patch.object(
                web_app,
                "_materialize_process_form",
                return_value=snapshot,
            ) as materialize,
            patch.object(web_app, "_queue_process_job", return_value={"job_id": "job-1"}),
        ):
            response = client.post(
                "/api/process/background",
                data={
                    "ean": "5901234567890",
                    "name": "ALFA",
                    "type_name": "STOL",
                    "model": "A1",
                },
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "2")
        materialize.assert_not_awaited()

    def test_background_process_owner_limit_uses_configured_retry_after(self) -> None:
        """Catches the process-router proxy losing configured owner-limit retry delays."""
        queue = ProcessQueueService(
            QueueLimits(workers=1, max_pending=3, max_per_owner=1, retry_after_seconds=17),
            start_workers=False,
        )
        scope = "operator-" + hashlib.sha1(b"scope-token").hexdigest()[:12]
        reservation = queue.reserve(scope)
        client = TestClient(web_app.app)
        client.cookies.set(web_app.SESSION_COOKIE, "scope-token")
        try:
            with (
                patch.object(web_app, "_require_user", return_value="operator"),
                patch.object(web_app, "_PROCESS_QUEUE", queue),
            ):
                response = client.post(
                    "/api/process/background",
                    data={"ean": "5901234567890"},
                    headers={
                        web_app.CSRF_HEADER: web_app._csrf_token_for_session("scope-token")
                    },
                )
        finally:
            reservation.release()
            queue.shutdown()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "17")

    def test_foreground_and_background_share_the_owner_queue_limit(self) -> None:
        """Catches separate endpoint queues that let one owner exceed two active jobs."""
        queue = ProcessQueueService(
            QueueLimits(workers=1, max_pending=3, max_per_owner=2),
        )
        original_submit = queue.submit
        second_submitted = threading.Event()
        first_started = threading.Event()
        release_first = threading.Event()
        foreground_done = threading.Event()
        foreground_result: dict[str, object] = {}
        submit_count = 0
        submit_lock = threading.Lock()
        materialize_calls = 0
        materialize_lock = threading.Lock()
        snapshot = web_app._ProcessFormSnapshot()
        result = {"timing": {"stages": []}, "ftp": {}, "sql": {}, "local_delete": {}}

        def track_submit(*args, **kwargs):
            nonlocal submit_count
            position = original_submit(*args, **kwargs)
            with submit_lock:
                submit_count += 1
                if submit_count == 2:
                    second_submitted.set()
            return position

        async def materialize(_form, _temp_dir):
            nonlocal materialize_calls
            with materialize_lock:
                materialize_calls += 1
            return snapshot

        def process(**_kwargs):
            if not first_started.is_set():
                first_started.set()
                assert release_first.wait(timeout=5)
            return result

        def run_foreground() -> None:
            try:
                foreground_result["response"] = TestClient(web_app.app).post(
                    "/api/process",
                    data={"ean": "5901234567890"},
                )
            except BaseException as exc:  # pragma: no cover - reported by the assertion below
                foreground_result["error"] = exc
            finally:
                foreground_done.set()

        background_client = TestClient(web_app.app)
        try:
            with (
                patch.object(web_app, "_require_user", return_value="operator"),
                patch.object(web_app, "_PROCESS_QUEUE", queue),
                patch.object(web_app, "_materialize_process_form", side_effect=materialize),
                patch.object(web_app, "_process_upload_snapshot", side_effect=process),
                patch.object(web_app, "record_job"),
                patch.object(web_app, "emit_event"),
            ):
                queue.submit = track_submit
                background = background_client.post(
                    "/api/process/background",
                    data={"ean": "5901234567890"},
                )
                self.assertEqual(background.status_code, 200)
                self.assertTrue(first_started.wait(timeout=5))

                foreground_thread = threading.Thread(target=run_foreground)
                foreground_thread.start()
                self.assertTrue(second_submitted.wait(timeout=5))

                rejected = background_client.post(
                    "/api/process/background",
                    data={"ean": "5901234567890"},
                )
                self.assertEqual(rejected.status_code, 429)
                self.assertEqual(rejected.headers["Retry-After"], "2")
                self.assertEqual(materialize_calls, 2)

                release_first.set()
                self.assertTrue(foreground_done.wait(timeout=5))
                foreground_thread.join(timeout=1)
                self.assertNotIn("error", foreground_result)
                self.assertEqual(foreground_result["response"].status_code, 200)
                self.assertEqual(foreground_result["response"].json(), result)
        finally:
            release_first.set()
            queue.shutdown()
            with web_app._PROCESS_JOBS_LOCK:
                for job_id, job in list(web_app._PROCESS_JOBS.items()):
                    if job.get("form") is snapshot or job.get("username") == "operator":
                        web_app._PROCESS_JOBS.pop(job_id, None)
                        web_app._PROCESS_JOB_COMPLETIONS.pop(job_id, None)

    def test_process_warning_messages_are_user_visible(self) -> None:
        payload = {
            "ftp": {"error": "brak polaczenia"},
            "sql": {"error": "brak wiersza"},
            "local_delete": {"errors": ["03: odmowa dostepu"]},
            "skipped_slots": ["04"],
        }

        messages = web_app._process_warning_messages(payload)

        self.assertIn("FTP: brak polaczenia", messages)
        self.assertIn("SQL: brak wiersza", messages)
        self.assertTrue(any("03: odmowa dostepu" in item for item in messages))
        self.assertTrue(any("04" in item for item in messages))

    def test_process_job_payload_hides_internal_form_snapshot(self) -> None:
        job = {
            "id": "abc",
            "status": "queued",
            "form": object(),
            "entry": {"ean": "5901234567890", "name": "MAGGIORE"},
            "entry_label": "MAGGIORE - 5901234567890",
        }

        payload = web_app._process_job_payload(job)

        self.assertNotIn("form", payload)
        self.assertEqual(payload["job_id"], "abc")
        self.assertEqual(payload["entry"]["ean"], "5901234567890")

    def test_active_process_jobs_snapshot_is_global_and_ordered(self) -> None:
        with web_app._PROCESS_JOBS_LOCK:
            original = dict(web_app._PROCESS_JOBS)
            web_app._PROCESS_JOBS.clear()
            web_app._PROCESS_JOBS.update(
                {
                    "running": {
                        "id": "running",
                        "status": "running",
                        "username": "user1",
                        "created_at": 1.0,
                        "started_at": 3.0,
                        "entry": {"name": "RUN"},
                        "entry_label": "RUN",
                        "progress": 34,
                        "progress_label": "Zapis wpisu",
                    },
                    "queued": {
                        "id": "queued",
                        "status": "queued",
                        "username": "user2",
                        "created_at": 2.0,
                        "entry": {"name": "WAIT"},
                        "entry_label": "WAIT",
                        "progress": 0,
                        "progress_label": "Oczekuje w kolejce",
                    },
                }
            )
        try:
            snapshot = web_app._active_process_jobs_snapshot()
        finally:
            with web_app._PROCESS_JOBS_LOCK:
                web_app._PROCESS_JOBS.clear()
                web_app._PROCESS_JOBS.update(original)

        self.assertEqual(snapshot["active_count"], 2)
        self.assertEqual(snapshot["queued_count"], 1)
        self.assertEqual(snapshot["jobs"][0]["job_id"], "running")
        self.assertEqual(snapshot["jobs"][0]["progress"], 34)
        self.assertEqual(snapshot["jobs"][1]["username"], "user2")
        self.assertEqual(snapshot["jobs"][1]["queue_position"], 1)

    def test_active_presence_payload_is_disabled_by_default(self) -> None:
        with patch.object(web_app.config, "CONFIG", {}):
            payload = web_app._active_presence_payload(
                [
                    {
                        "username": "admin",
                        "last_seen": "2026-06-30 10:00:00",
                        "last_seen_epoch": 20,
                    },
                ]
            )

        self.assertEqual(payload, {"enabled": False, "users": []})

    def test_active_presence_payload_sanitizes_and_deduplicates_users(self) -> None:
        clients = [
            {
                "username": "admin",
                "client_id": "client-a",
                "remote_address": "10.0.0.1",
                "path": "/api/bootstrap",
                "last_seen": "old",
                "last_seen_epoch": 10,
            },
            {
                "username": "operator",
                "client_id": "client-b",
                "user_agent": "browser",
                "last_seen": "now",
                "last_seen_epoch": 30,
            },
            {
                "username": "admin",
                "client_id": "client-a",
                "remote_port": 1234,
                "last_seen": "new",
                "last_seen_epoch": 40,
            },
            {
                "username": "niezalogowany",
                "last_seen": "anon",
                "last_seen_epoch": 50,
            },
            {
                "username": "",
                "last_seen": "blank",
                "last_seen_epoch": 60,
            },
        ]
        with patch.object(
            web_app.config,
            "CONFIG",
            {web_app.SECURITY_SETTINGS_KEY: {"show_active_web_users": True}},
        ):
            payload = web_app._active_presence_payload(clients, now=40)

        self.assertTrue(payload["enabled"])
        self.assertEqual(
            payload["users"],
            [
                {"username": "admin", "last_seen_epoch": 40.0},
                {"username": "operator", "last_seen_epoch": 30.0},
            ],
        )

    def test_active_presence_payload_requires_browser_client_id(self) -> None:
        clients = [
            {
                "username": "admin",
                "last_seen": "html request",
                "last_seen_epoch": 100,
            },
            {
                "username": "operator",
                "client_id": "client-a",
                "last_seen": "browser poll",
                "last_seen_epoch": 100,
            },
        ]
        with patch.object(
            web_app.config,
            "CONFIG",
            {web_app.SECURITY_SETTINGS_KEY: {"show_active_web_users": True}},
        ):
            payload = web_app._active_presence_payload(clients, now=100)

        self.assertEqual(
            payload["users"],
            [
                {
                    "username": "operator",
                    "last_seen_epoch": 100.0,
                }
            ],
        )

    def test_active_client_key_prefers_browser_client_id(self) -> None:
        first = {
            "username": "admin",
            "client_id": "client-a",
            "remote_address": "10.0.0.1",
            "user_agent": "browser-a",
        }
        same_client_new_connection = {
            "username": "admin",
            "client_id": "client-a",
            "remote_address": "10.0.0.2",
            "user_agent": "browser-b",
        }
        other_client = {
            "username": "admin",
            "client_id": "client-b",
            "remote_address": "10.0.0.1",
            "user_agent": "browser-a",
        }

        self.assertEqual(
            web_app._active_client_key(first),
            web_app._active_client_key(same_client_new_connection),
        )
        self.assertNotEqual(
            web_app._active_client_key(first),
            web_app._active_client_key(other_client),
        )

    def test_remove_active_client_removes_only_matching_browser_client(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = web_app.ActiveClientRegistry(Path(temp_dir) / "active.json")
            first = {
                "username": "admin",
                "client_id": "client-a",
                "last_seen_epoch": 100.0,
            }
            second = {
                "username": "admin",
                "client_id": "client-b",
                "last_seen_epoch": 100.0,
            }
            other_user = {
                "username": "operator",
                "client_id": "client-a",
                "last_seen_epoch": 100.0,
            }
            registry.record(first)
            registry.record(second)
            registry.record(other_user)
            try:
                with patch.object(web_app, "_ACTIVE_CLIENT_REGISTRY", registry):
                    removed = web_app._remove_active_client("admin", "client-a", now=100.0)
                    snapshot = web_app._active_clients_snapshot(now=100.0)
            finally:
                registry.close(timeout=5.0)

        self.assertEqual(removed, 1)
        self.assertEqual(
            {(item.get("username"), item.get("client_id")) for item in snapshot},
            {("admin", "client-b"), ("operator", "client-a")},
        )

    def test_active_client_leave_does_not_wait_for_blocked_writer(self) -> None:
        writer_started = threading.Event()
        release_writer = threading.Event()
        leave_finished = threading.Event()
        record_finished = threading.Event()
        leave_results = []
        errors = []
        serialized_payloads = []

        def serializer(payload):
            serialized_payloads.append(payload)
            if len(serialized_payloads) == 1:
                writer_started.set()
                self.assertTrue(release_writer.wait(timeout=5.0))
            return json.dumps(payload)

        request = SimpleNamespace(
            url=SimpleNamespace(path="/api/bootstrap"),
            client=SimpleNamespace(host="127.0.0.1", port=12345),
            headers={"user-agent": "test", web_app.PRESENCE_CLIENT_ID_HEADER: "client-b"},
            method="GET",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "active.json"
            registry = web_app.ActiveClientRegistry(path, serializer=serializer)
            registry.record(
                {
                    "username": "admin",
                    "client_id": "client-a",
                    "last_seen_epoch": time.time(),
                }
            )

            def leave():
                try:
                    leave_results.append(
                        web_app._remove_active_client("admin", "client-a", now=time.time())
                    )
                except Exception as exc:
                    errors.append(exc)
                finally:
                    leave_finished.set()

            def record():
                try:
                    web_app._record_active_client(request, 200)
                except Exception as exc:
                    errors.append(exc)
                finally:
                    record_finished.set()

            try:
                with (
                    patch.object(web_app, "_ACTIVE_CLIENT_REGISTRY", registry),
                    patch.object(web_app, "_current_user", return_value="admin"),
                ):
                    leave_thread = threading.Thread(target=leave)
                    leave_thread.start()
                    self.assertTrue(writer_started.wait(timeout=5.0))

                    record_thread = threading.Thread(target=record)
                    record_thread.start()
                    leave_returned_before_writer_release = leave_finished.wait(timeout=0.2)
                    record_returned_before_writer_release = record_finished.wait(timeout=0.2)

                    release_writer.set()
                    leave_thread.join(timeout=5.0)
                    record_thread.join(timeout=5.0)
                    self.assertFalse(leave_thread.is_alive())
                    self.assertFalse(record_thread.is_alive())
                    registry.flush(force=True)
            finally:
                release_writer.set()
                registry.close(timeout=5.0)

            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(leave_returned_before_writer_release)
        self.assertTrue(record_returned_before_writer_release)
        self.assertEqual(leave_results, [1])
        self.assertEqual(errors, [])
        self.assertEqual(
            {(item["username"], item["client_id"]) for item in payload},
            {("admin", "client-b")},
        )

    def test_record_active_client_only_records_and_schedules_writer(self) -> None:
        write_started = threading.Event()
        release_write = threading.Event()

        def serializer(payload):
            write_started.set()
            self.assertTrue(release_write.wait(timeout=5.0))
            return "[]"

        request = SimpleNamespace(
            url=SimpleNamespace(path="/api/bootstrap"),
            client=SimpleNamespace(host="127.0.0.1", port=12345),
            headers={"user-agent": "test", web_app.PRESENCE_CLIENT_ID_HEADER: "client-a"},
            method="GET",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = web_app.ActiveClientRegistry(
                Path(temp_dir) / "active.json",
                serializer=serializer,
            )
            try:
                with (
                    patch.object(web_app, "_ACTIVE_CLIENT_REGISTRY", registry),
                    patch.object(web_app, "_current_user", return_value="admin"),
                ):
                    web_app._record_active_client(request, 200)
                    self.assertTrue(write_started.wait(timeout=5.0))
                    self.assertEqual(registry.generation, 1)
            finally:
                release_write.set()
                registry.close(timeout=5.0)

    def test_shutdown_closes_active_client_registry_with_five_second_bound(self) -> None:
        shutdown = next(
            handler
            for handler in web_app.app.router.on_shutdown
            if handler.__name__ == "_shutdown"
        )
        registry = Mock()
        with (
            patch.object(web_app, "_ACTIVE_CLIENT_REGISTRY", registry),
            patch.object(web_app._RESOURCE_MONITOR, "stop"),
            patch.object(web_app, "stop_notification_worker"),
            patch.object(web_app, "_stop_backup_scheduler"),
            patch.object(web_app.data_store, "reset_active_store_cache"),
        ):
            shutdown()

        registry.close.assert_called_once_with(timeout=5.0)

    def test_later_app_startup_replaces_active_client_registry_closed_by_prior_shutdown(
        self,
    ) -> None:
        first_app = web_app.create_app()
        later_app = web_app.create_app()
        shutdown = next(
            handler for handler in first_app.router.on_shutdown if handler.__name__ == "_shutdown"
        )
        startup = next(
            handler for handler in later_app.router.on_startup if handler.__name__ == "_startup"
        )
        request = SimpleNamespace(
            url=SimpleNamespace(path="/api/bootstrap"),
            client=SimpleNamespace(host="127.0.0.1", port=12345),
            headers={"user-agent": "test", web_app.PRESENCE_CLIENT_ID_HEADER: "client-a"},
            method="GET",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "active.json"
            initial_registry = web_app.ActiveClientRegistry(path)
            initial_registry.record(
                {
                    "username": "prior-user",
                    "client_id": "prior-client",
                    "last_seen_epoch": time.time(),
                }
            )
            replacement_registry = initial_registry
            try:
                with (
                    patch.object(web_app, "_ACTIVE_CLIENT_REGISTRY", initial_registry),
                    patch.object(web_app, "_active_clients_log_path", return_value=path),
                    patch.object(web_app._RESOURCE_MONITOR, "start"),
                    patch.object(web_app._RESOURCE_MONITOR, "stop"),
                    patch.object(web_app, "initialize_application_runtime", return_value={}),
                    patch.object(web_app, "cleanup_web_ftp_cache"),
                    patch.object(web_app, "cleanup_web_upload_cache"),
                    patch.object(web_app, "_prune_live_events_if_due"),
                    patch.object(web_app, "_start_backup_scheduler"),
                    patch.object(web_app, "_stop_backup_scheduler"),
                    patch.object(web_app, "start_notification_worker"),
                    patch.object(web_app, "stop_notification_worker"),
                    patch.object(web_app.data_store, "reset_active_store_cache"),
                    patch.object(web_app, "_current_user", return_value="admin"),
                ):
                    shutdown()
                    startup()
                    replacement_registry = web_app._ACTIVE_CLIENT_REGISTRY
                    web_app._record_active_client(request, 200)
                    replacement_registry.flush(force=True)
            finally:
                replacement_registry.close(timeout=5.0)

            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertIsNot(replacement_registry, initial_registry)
        self.assertEqual(
            {item["username"] for item in payload},
            {"admin", "prior-user"},
        )

    def test_startup_waits_for_timed_out_active_client_writer_handoff(self) -> None:
        old_write_started = threading.Event()
        release_old_write = threading.Event()
        old_replace_finished = threading.Event()
        replacement_ready = threading.Event()
        replacement_holder = {}
        renewal_errors = []
        real_replace = active_clients.os.replace
        old_writer_ident = []

        def serializer(payload):
            old_writer_ident.append(threading.get_ident())
            old_write_started.set()
            self.assertTrue(release_old_write.wait(timeout=5.0))
            return json.dumps(payload)

        def replace(source, destination):
            real_replace(source, destination)
            if old_writer_ident and threading.get_ident() == old_writer_ident[0]:
                old_replace_finished.set()

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "active.json"
            old_registry = web_app.ActiveClientRegistry(path, serializer=serializer)
            old_registry.record(
                {
                    "username": "prior-user",
                    "client_id": "prior-client",
                    "last_seen_epoch": time.time(),
                }
            )
            old_registry.schedule_flush(force=True)
            self.assertTrue(old_write_started.wait(timeout=5.0))
            self.assertFalse(old_registry.close(timeout=0.01))

            def renew_registry():
                try:
                    replacement_holder["registry"] = web_app._ensure_active_client_registry()
                except Exception as exc:
                    renewal_errors.append(exc)
                finally:
                    replacement_ready.set()

            try:
                with (
                    patch.object(web_app, "_ACTIVE_CLIENT_REGISTRY", old_registry),
                    patch.object(web_app, "_active_clients_log_path", return_value=path),
                    patch.object(active_clients.os, "replace", replace),
                ):
                    renewal_thread = threading.Thread(target=renew_registry)
                    renewal_thread.start()
                    replacement_returned_while_old_writer_blocked = replacement_ready.wait(
                        timeout=0.2
                    )
                    release_old_write.set()
                    self.assertTrue(old_replace_finished.wait(timeout=5.0))
                    renewal_thread.join(timeout=5.0)
                    self.assertFalse(renewal_thread.is_alive())
                    self.assertEqual(renewal_errors, [])

                    replacement = replacement_holder["registry"]
                    replacement.record(
                        {
                            "username": "later-user",
                            "client_id": "later-client",
                            "last_seen_epoch": time.time(),
                        }
                    )
                    replacement.flush(force=True)
                    replacement.close(timeout=5.0)
            finally:
                release_old_write.set()

            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertFalse(replacement_returned_while_old_writer_blocked)
        self.assertEqual(
            {item["username"] for item in payload},
            {"later-user", "prior-user"},
        )

    def test_active_client_record_lazily_renews_closed_registry_without_startup(self) -> None:
        request = SimpleNamespace(
            url=SimpleNamespace(path="/api/bootstrap"),
            client=SimpleNamespace(host="127.0.0.1", port=12345),
            headers={"user-agent": "test", web_app.PRESENCE_CLIENT_ID_HEADER: "client-a"},
            method="GET",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "active.json"
            closed_registry = web_app.ActiveClientRegistry(path)
            closed_registry.close(timeout=5.0)
            renewed_registry = closed_registry
            try:
                with (
                    patch.object(web_app, "_ACTIVE_CLIENT_REGISTRY", closed_registry),
                    patch.object(web_app, "_active_clients_log_path", return_value=path),
                    patch.object(web_app, "_current_user", return_value="admin"),
                ):
                    web_app._record_active_client(request, 200)
                    renewed_registry = web_app._ACTIVE_CLIENT_REGISTRY
                    renewed_registry.flush(force=True)
            finally:
                renewed_registry.close(timeout=5.0)

            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertIsNot(renewed_registry, closed_registry)
        self.assertEqual(payload[0]["username"], "admin")

    def test_active_presence_payload_hides_stale_browser_clients_quickly(self) -> None:
        now = 200.0
        clients = [
            {
                "username": "admin",
                "client_id": "client-a",
                "last_seen": "stale",
                "last_seen_epoch": now - web_app.PRESENCE_CLIENT_MAX_AGE_SECONDS - 1,
            },
            {
                "username": "operator",
                "client_id": "client-b",
                "last_seen": "fresh",
                "last_seen_epoch": now,
            },
        ]
        with patch.object(
            web_app.config,
            "CONFIG",
            {web_app.SECURITY_SETTINGS_KEY: {"show_active_web_users": True}},
        ):
            payload = web_app._active_presence_payload(clients, now=now)

        self.assertEqual(
            payload["users"],
            [{"username": "operator", "last_seen_epoch": now}],
        )

    def test_existing_photo_conflicts_detect_unloaded_replacement(self) -> None:
        upload = web_app.WebUploadedSlot(
            prefix="03",
            label="DETAIL_pic",
            source_path="new.jpg",
            original_filename="new.jpg",
        )
        conflicts = web_app._existing_photo_conflicts(
            [{"prefix": "03", "local": True, "path": "old.jpg", "filename": "old.jpg"}],
            [upload],
            [],
        )

        self.assertEqual(conflicts[0]["prefix"], "03")
        self.assertEqual(conflicts[0]["sources"], ["LOCAL"])

    def test_existing_photo_conflicts_ignores_explicit_ftp_source(self) -> None:
        upload = web_app.WebUploadedSlot(
            prefix="03",
            label="DETAIL_pic",
            source_path="cache.jpg",
            original_filename="5901234567890_03.jpg",
        )
        conflicts = web_app._existing_photo_conflicts(
            [{"prefix": "03", "ftp": True, "ftp_filename": "5901234567890_03.jpg"}],
            [upload],
            [],
        )

        self.assertEqual(conflicts, [])

    def test_existing_photo_conflicts_allows_upload_to_replace_ftp_only_slot(self) -> None:
        upload = web_app.WebUploadedSlot(
            prefix="03",
            label="DETAIL_pic",
            source_path="new.jpg",
            original_filename="new.jpg",
        )
        conflicts = web_app._existing_photo_conflicts(
            [{"prefix": "03", "ftp": True, "ftp_filename": "5901234567890_03.jpg"}],
            [upload],
            [],
        )

        self.assertEqual(conflicts, [])

    def test_existing_photo_conflicts_ignore_sql_only_presence(self) -> None:
        upload = web_app.WebUploadedSlot(
            prefix="03",
            label="DETAIL_pic",
            source_path="new.jpg",
            original_filename="new.jpg",
        )
        conflicts = web_app._existing_photo_conflicts(
            [{"prefix": "03", "sql": True, "sql_checked": True, "sql_value": ""}],
            [upload],
            [],
        )

        self.assertEqual(conflicts, [])

    def test_system_change_filter_hides_product_and_photo_entries(self) -> None:
        settings_event = {
            "source": "changes",
            "lines": ["[2026-05-12 10:00:00] [USER: user] Settings saved (images/FTP/SQL)."],
        }
        image_event = {
            "source": "changes",
            "lines": ["[2026-05-12 10:01:00] [USER: user] Added/modified image 123.jpg"],
        }
        entry_event = {
            "source": "changes",
            "lines": ["[2026-05-12 10:02:00] [USER: user] Updated Excel entry for EAN 5901234567890."],
        }

        self.assertTrue(web_app._is_system_change_event(settings_event))
        self.assertFalse(web_app._is_system_change_event(image_event))
        self.assertFalse(web_app._is_system_change_event(entry_event))

    def test_clear_log_files_truncates_configured_targets(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            root = Path(temp_dir)
            error_log = root / "error_log.txt"
            changes_log = root / "changes_log.txt"
            error_log.write_text("error\n", encoding="utf-8")
            changes_log.write_text("change\n", encoding="utf-8")
            targets = [
                {"key": "errors", "label": "Bledy", "path": error_log},
                {"key": "changes", "label": "Zmiany", "path": changes_log},
            ]

            with patch.object(web_app, "_log_targets", return_value=targets):
                result = web_app._clear_log_files()

            self.assertEqual(result["errors"], [])
            self.assertEqual(error_log.read_text(encoding="utf-8"), "")
            self.assertEqual(changes_log.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
