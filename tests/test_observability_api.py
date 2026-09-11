"""Authenticated API coverage for structured observability data."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from picsyncra import data_store, web_data
from picsyncra.resource_monitor import ResourceMonitor
from picsyncra.sqlite_store import SqliteStore
from picsyncra.web import app as web_app


def _event(
    identity: str,
    created_at: str,
    severity: str = "info",
    *,
    event_type: str = "test.event",
    job_id: str = "",
    correlation_id: str = "",
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": identity,
        "created_at": created_at,
        "severity": severity,
        "event_type": event_type,
        "module": "tests",
        "job_id": job_id,
        "correlation_id": correlation_id,
        "summary": identity,
        "details": details or {},
    }


@pytest.fixture
def api_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    previous_auth = os.environ.get("PICSYNCRA_WEB_AUTH")
    os.environ["PICSYNCRA_WEB_AUTH"] = "1"
    with web_app._RATE_LIMITS_LOCK:
        web_app._RATE_LIMITS.clear()
    database_path = tmp_path / "app.sqlite"
    monkeypatch.setattr(web_app.settings, "AC", str(tmp_path))
    monkeypatch.setattr(
        web_app.settings, "LISTS_WORKBOOK_PATH", str(tmp_path / "lists.xlsx")
    )
    monkeypatch.setattr(
        web_app.storage_settings, "resolve_sqlite_path", lambda: str(database_path)
    )
    data_store.reset_active_store_cache()
    store = SqliteStore(str(database_path))
    store.initialize()
    client = TestClient(web_app.app)
    yield client, store
    client.close()
    with web_app._RATE_LIMITS_LOCK:
        web_app._RATE_LIMITS.clear()
    data_store.reset_active_store_cache()
    if previous_auth is None:
        os.environ.pop("PICSYNCRA_WEB_AUTH", None)
    else:
        os.environ["PICSYNCRA_WEB_AUTH"] = previous_auth


def _login(client: TestClient, username: str = "admin", password: str = "admin") -> str:
    response = client.post(
        "/api/login",
        data={"username": username, "password": password},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def test_history_details_requires_login(api_environment) -> None:
    client, _store = api_environment

    assert client.get("/api/history/details?ean=5901").status_code == 401


def test_history_details_returns_one_filtered_group(api_environment) -> None:
    client, _store = api_environment
    _login(client)
    web_data.record_history(
        username="alice",
        action="save",
        ean="5901",
        details={},
    )
    web_data.record_history(
        username="bob",
        action="save",
        ean="5901",
        details={},
    )

    response = client.get("/api/history/details?ean=5901&user=alice")

    assert response.status_code == 200
    assert [item["user"] for item in response.json()["items"]] == ["alice"]
    assert client.get("/api/history/details?ean=missing").status_code == 404


def test_history_details_api_pages_one_ean(api_environment) -> None:
    client, _store = api_environment
    _login(client)
    for _ in range(30):
        web_data.record_history(username="alice", action="save", ean="5901")

    response = client.get("/api/history/details?ean=5901&page=2&page_size=25")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 5
    assert response.json()["total_pages"] == 2


def test_time_zone_catalog_requires_admin(api_environment) -> None:
    client, _store = api_environment

    assert client.get("/api/settings/time-zones").status_code == 401

    web_data.add_user("operator", "secret", "user")
    _login(client, "operator", "secret")
    assert client.get("/api/settings/time-zones").status_code == 403

    _login(client)
    response = client.get("/api/settings/time-zones")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"time_zones"}
    time_zones = payload["time_zones"]
    assert time_zones[0] == "UTC"
    assert time_zones.count("UTC") == 1
    assert time_zones[1:] == sorted(time_zones[1:])
    assert len(time_zones) == len(set(time_zones))
    assert all(isinstance(value, str) and value for value in time_zones)
    assert "Europe/Warsaw" in time_zones


def test_bootstrap_exposes_only_normalized_web_display_shape(api_environment) -> None:
    client, _store = api_environment
    _login(client)
    untrusted_display = {
        "time_zone": " Europe/Warsaw ",
        "password": "must-not-leak",
        "api_token": "must-not-leak",
    }

    with patch.dict(
        web_app.config.CONFIG,
        {"web_display": untrusted_display},
        clear=False,
    ):
        response = client.get("/api/bootstrap")

    assert response.status_code == 200
    assert response.json()["web_display"] == {"time_zone": "Europe/Warsaw"}
    assert "must-not-leak" not in json.dumps(response.json())


def test_settings_api_rejects_invalid_time_zone_without_replacing_saved_value(
    api_environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store = api_environment
    config_payload = json.loads(json.dumps(web_app.config.DEFAULT_CONFIG))
    config_payload["web_display"] = {"time_zone": "Europe/Warsaw"}
    saved_configs: list[dict[str, object]] = []
    monkeypatch.setattr(web_app.config, "CONFIG", config_payload)
    monkeypatch.setattr(
        web_data,
        "save_config",
        lambda payload, **_kwargs: saved_configs.append(json.loads(json.dumps(payload))),
    )
    monkeypatch.setattr(web_data.config, "initialize_config", lambda **_kwargs: config_payload)
    monkeypatch.setattr(
        web_data,
        "settings_snapshot",
        lambda: {"web_display": config_payload["web_display"]},
    )
    monkeypatch.setattr(
        web_app.config,
        "available_display_time_zones",
        lambda: ["UTC", "Europe/Warsaw"],
    )
    csrf = _login(client)

    valid = client.post(
        "/api/settings",
        headers={"X-PicSyncra-CSRF": csrf},
        json={"web_display": {"time_zone": "Europe/Warsaw"}},
    )
    invalid = client.post(
        "/api/settings",
        headers={"X-PicSyncra-CSRF": csrf},
        json={"web_display": {"time_zone": "CEST"}},
    )

    assert valid.status_code == 200, valid.text
    assert invalid.status_code == 400
    assert config_payload["web_display"] == {"time_zone": "Europe/Warsaw"}
    assert len(saved_configs) == 1
    assert saved_configs[0]["web_display"] == {"time_zone": "Europe/Warsaw"}


def test_failed_sqlite_repair_api_preserves_the_cached_store(
    api_environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = api_environment
    cached_store = data_store.get_sqlite_store(store.path)
    monkeypatch.setattr(
        web_app.storage_settings, "resolve_sqlite_path", lambda _payload=None: store.path
    )
    monkeypatch.setattr(
        web_app,
        "repair_sqlite_database",
        lambda *_args: {"ok": False, "warnings": ["integrity_check_failed"]},
    )
    csrf = _login(client)

    response = client.post(
        "/api/settings/sqlite/repair", headers={"X-PicSyncra-CSRF": csrf}
    )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is False
    assert data_store.get_sqlite_store(store.path) is cached_store


def test_successful_sqlite_repair_api_invalidates_the_cached_store(
    api_environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = api_environment
    cached_store = data_store.get_sqlite_store(store.path)
    monkeypatch.setattr(
        web_app.storage_settings, "resolve_sqlite_path", lambda _payload=None: store.path
    )
    monkeypatch.setattr(
        web_app.storage_settings,
        "resolve_backup_dir",
        lambda: str(Path(store.path).parent / "BACKUP"),
    )
    csrf = _login(client)

    response = client.post(
        "/api/settings/sqlite/repair", headers={"X-PicSyncra-CSRF": csrf}
    )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert data_store.get_sqlite_store(store.path) is not cached_store


def test_cleanup_process_jobs_preserves_active_and_keeps_newest_completed() -> None:
    now = 10_000.0
    completed_limit = web_app._PROCESS_JOB_MAX_COMPLETED
    jobs = {
        f"completed-{index}": {
            "id": f"completed-{index}",
            "status": "completed",
            "finished_at": now - index,
        }
        for index in range(completed_limit + 2)
    }
    jobs["expired"] = {
        "id": "expired",
        "status": "failed",
        "finished_at": now - web_app._PROCESS_JOB_RETENTION_SECONDS - 1,
    }
    jobs["queued"] = {"id": "queued", "status": "queued", "created_at": 1.0}
    with web_app._PROCESS_JOBS_LOCK:
        previous = dict(web_app._PROCESS_JOBS)
        web_app._PROCESS_JOBS.clear()
        web_app._PROCESS_JOBS.update(jobs)
    try:
        web_app._cleanup_process_jobs(now=now)

        with web_app._PROCESS_JOBS_LOCK:
            retained = dict(web_app._PROCESS_JOBS)
        completed_ids = {
            job_id for job_id, job in retained.items() if job.get("status") == "completed"
        }
        assert retained["queued"]["status"] == "queued"
        assert "expired" not in retained
        assert len(completed_ids) == completed_limit
        assert "completed-0" in completed_ids
        assert f"completed-{completed_limit + 1}" not in completed_ids
    finally:
        with web_app._PROCESS_JOBS_LOCK:
            web_app._PROCESS_JOBS.clear()
            web_app._PROCESS_JOBS.update(previous)


def test_process_job_completion_transitions_bound_resident_terminal_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed_limit = web_app._PROCESS_JOB_MAX_COMPLETED
    job_count = completed_limit + 4
    jobs = {
        f"job-{index}": {
            "id": f"job-{index}",
            "status": "queued",
            "username": "admin",
            "cache_scope": "scope",
            "form": index,
            "created_at": float(index + 1),
            "started_at": 0.0,
            "finished_at": 0.0,
            "progress": 0,
        }
        for index in range(job_count)
    }
    jobs["still-queued"] = {
        "id": "still-queued",
        "status": "queued",
        "created_at": 0.0,
    }
    ticks = iter(float(value) for value in range(10_000, 20_000))
    monkeypatch.setattr(web_app.time, "time", lambda: next(ticks))

    def process_snapshot(**kwargs):
        if int(kwargs["form"]) % 2:
            raise RuntimeError("expected failure")
        return {}

    monkeypatch.setattr(web_app, "_process_upload_snapshot", process_snapshot)
    monkeypatch.setattr(web_app, "_persist_process_job", lambda _job: None)
    monkeypatch.setattr(web_app, "_emit_process_completed", lambda *_args: None)
    monkeypatch.setattr(web_app, "_emit_process_failed", lambda *_args, **_kwargs: None)
    with web_app._PROCESS_JOBS_LOCK:
        previous = dict(web_app._PROCESS_JOBS)
        web_app._PROCESS_JOBS.clear()
        web_app._PROCESS_JOBS.update(jobs)
    try:
        for index in range(job_count):
            web_app._run_process_job(f"job-{index}")

        with web_app._PROCESS_JOBS_LOCK:
            resident = dict(web_app._PROCESS_JOBS)
        terminal = [
            job
            for job in resident.values()
            if job.get("status") in {"completed", "failed"}
        ]
        assert resident["still-queued"]["status"] == "queued"
        assert len(terminal) <= completed_limit
        assert len(resident) <= completed_limit + 1
        assert {job["status"] for job in terminal} == {"completed", "failed"}
    finally:
        with web_app._PROCESS_JOBS_LOCK:
            web_app._PROCESS_JOBS.clear()
            web_app._PROCESS_JOBS.update(previous)


def test_upload_scan_results_prune_missing_and_expired_entries(tmp_path: Path) -> None:
    now = 20_000.0 + web_app.WEB_UPLOAD_CACHE_MAX_AGE_SECONDS
    fresh_path = tmp_path / "fresh.jpg"
    expired_path = tmp_path / "expired.jpg"
    missing_path = tmp_path / "missing.jpg"
    fresh_path.write_bytes(b"fresh")
    expired_path.write_bytes(b"expired")
    with web_app._UPLOAD_SCAN_RESULTS_LOCK:
        previous = dict(web_app._UPLOAD_SCAN_RESULTS)
        web_app._UPLOAD_SCAN_RESULTS.clear()
        web_app._UPLOAD_SCAN_RESULTS.update(
            {
                str(fresh_path.resolve()): {"scanned": True, "_cached_at": now},
                str(expired_path.resolve()): {
                    "scanned": True,
                    "_cached_at": now - web_app.WEB_UPLOAD_CACHE_MAX_AGE_SECONDS - 1,
                },
                str(missing_path.resolve()): {"scanned": True, "_cached_at": now},
            }
        )
    try:
        web_app._prune_upload_scan_results(now=now)

        with web_app._UPLOAD_SCAN_RESULTS_LOCK:
            retained = dict(web_app._UPLOAD_SCAN_RESULTS)
        assert set(retained) == {str(fresh_path.resolve())}
    finally:
        with web_app._UPLOAD_SCAN_RESULTS_LOCK:
            web_app._UPLOAD_SCAN_RESULTS.clear()
            web_app._UPLOAD_SCAN_RESULTS.update(previous)


def test_upload_scan_result_copy_survives_source_replacement(tmp_path: Path) -> None:
    source_path = tmp_path / "source.jpg"
    target_path = tmp_path / "source_processed.jpg"
    target_path.write_bytes(b"processed")
    with web_app._UPLOAD_SCAN_RESULTS_LOCK:
        previous = dict(web_app._UPLOAD_SCAN_RESULTS)
        web_app._UPLOAD_SCAN_RESULTS.clear()
        web_app._UPLOAD_SCAN_RESULTS[str(source_path.resolve())] = {
            "enabled": True,
            "scanned": True,
            "_cached_at": 1.0,
        }
    try:
        web_app._copy_upload_scan_result(str(source_path), str(target_path))

        result = web_app._upload_scan_result(str(target_path))
        assert result == {"enabled": True, "scanned": True}
        with web_app._UPLOAD_SCAN_RESULTS_LOCK:
            assert str(source_path.resolve()) not in web_app._UPLOAD_SCAN_RESULTS
    finally:
        with web_app._UPLOAD_SCAN_RESULTS_LOCK:
            web_app._UPLOAD_SCAN_RESULTS.clear()
            web_app._UPLOAD_SCAN_RESULTS.update(previous)


def test_preprocess_upload_scan_handoff_survives_prune_between_source_and_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = getattr(web_app, "_preprocess_cached_upload_with_scan_result", None)
    assert callable(handoff)
    source_path = tmp_path / "source.jpg"
    target_path = tmp_path / "source_processed.jpg"
    source_path.write_bytes(b"source")
    source_removed = threading.Event()
    source_pruned = threading.Event()

    def preprocess(path: str, display_name: str, _options):
        assert os.path.abspath(path) == os.path.abspath(source_path)
        target_path.write_bytes(b"processed")
        source_path.unlink()
        source_removed.set()
        assert source_pruned.wait(timeout=2)
        return str(target_path), display_name, True

    monkeypatch.setattr(web_app, "preprocess_cached_upload", preprocess)
    with web_app._UPLOAD_SCAN_RESULTS_LOCK:
        previous = dict(web_app._UPLOAD_SCAN_RESULTS)
        web_app._UPLOAD_SCAN_RESULTS.clear()
        web_app._UPLOAD_SCAN_RESULTS[str(source_path.resolve())] = {
            "enabled": True,
            "scanned": True,
            "scanner": "Microsoft Defender",
            "_cached_at": 1.0,
        }

    def prune_removed_source() -> None:
        assert source_removed.wait(timeout=2)
        web_app._prune_upload_scan_results()
        with web_app._UPLOAD_SCAN_RESULTS_LOCK:
            assert str(source_path.resolve()) not in web_app._UPLOAD_SCAN_RESULTS
        source_pruned.set()

    pruner = threading.Thread(target=prune_removed_source, daemon=True)
    try:
        pruner.start()
        result_path, result_name, preprocessed = asyncio.run(
            handoff(str(source_path), "source.jpg", object())
        )
        pruner.join(timeout=2)

        assert not pruner.is_alive()
        assert (result_path, result_name, preprocessed) == (
            str(target_path),
            "source.jpg",
            True,
        )
        assert web_app._upload_scan_result(str(target_path)) == {
            "enabled": True,
            "scanned": True,
            "scanner": "Microsoft Defender",
        }
        with web_app._UPLOAD_SCAN_RESULTS_LOCK:
            cached = dict(web_app._UPLOAD_SCAN_RESULTS[str(target_path.resolve())])
        assert float(cached["_cached_at"]) > 1.0
    finally:
        source_pruned.set()
        pruner.join(timeout=2)
        with web_app._UPLOAD_SCAN_RESULTS_LOCK:
            web_app._UPLOAD_SCAN_RESULTS.clear()
            web_app._UPLOAD_SCAN_RESULTS.update(previous)


def test_upload_routes_use_preprocess_scan_handoff_for_both_path_families() -> None:
    source = inspect.getsource(web_app.create_app)
    normal_start = source.index("async def upload_cache_api")
    normal_end = source.index("def browser_extension_ping_api", normal_start)
    extension_start = source.index("async def browser_extension_upload_cache_api")
    extension_end = source.index("async def web_images_scan_api", extension_start)

    for body in (
        source[normal_start:normal_end],
        source[extension_start:extension_end],
    ):
        assert "await _preprocess_cached_upload_with_scan_result(" in body
        assert "preprocess_cached_upload," not in body
        assert "_copy_upload_scan_result(" not in body


def test_rate_limit_cleanup_prunes_only_expired_key_lists() -> None:
    now = 30_000.0
    with web_app._RATE_LIMITS_LOCK:
        previous = dict(web_app._RATE_LIMITS)
        web_app._RATE_LIMITS.clear()
        web_app._RATE_LIMITS.update(
            {
                "login|expired": [now - web_app.RATE_LIMIT_LOGIN_WINDOW_SECONDS - 1],
                "login|fresh": [now - 1],
                "upload|expired": [now - web_app.RATE_LIMIT_UPLOAD_WINDOW_SECONDS - 1],
            }
        )
    try:
        web_app._prune_rate_limits(now=now)

        with web_app._RATE_LIMITS_LOCK:
            retained = dict(web_app._RATE_LIMITS)
        assert retained == {"login|fresh": [now - 1]}
    finally:
        with web_app._RATE_LIMITS_LOCK:
            web_app._RATE_LIMITS.clear()
            web_app._RATE_LIMITS.update(previous)


class _MonitorStub:
    def __init__(
        self,
        snapshot: dict[str, object] | None = None,
        *,
        safe_result: dict[str, object] | None = None,
        real_result: dict[str, object] | None = None,
        real_error: Exception | None = None,
        lifecycle_events: list[str] | None = None,
    ) -> None:
        self.snapshot = snapshot or {
            "host": {"available": True},
            "backend": {"available": True},
        }
        self.safe_result = safe_result or {
            "ok": True,
            "test_mode": "safe",
            "resources": self.snapshot,
        }
        self.real_result = real_result or {
            "ok": True,
            "kind": "cpu",
            "status": "detected",
            "timed_out": False,
        }
        self.real_error = real_error
        self.lifecycle_events = lifecycle_events
        self.sample_calls = 0
        self.safe_calls = 0
        self.real_calls: list[str] = []
        self.start_calls = 0
        self.stop_calls = 0

    def latest_public_snapshot(self) -> dict[str, object]:
        return self.snapshot

    def sample_once(self) -> dict[str, object]:
        self.sample_calls += 1
        return self.snapshot

    def record_safe_simulation(self) -> dict[str, object]:
        self.safe_calls += 1
        return dict(self.safe_result)

    def start_real_test(self, kind: str) -> dict[str, object]:
        self.real_calls.append(kind)
        if self.real_error is not None:
            raise self.real_error
        return dict(self.real_result)

    def start(self) -> bool:
        self.start_calls += 1
        if self.lifecycle_events is not None:
            self.lifecycle_events.append("monitor.start")
        return True

    def stop(self) -> None:
        self.stop_calls += 1
        if self.lifecycle_events is not None:
            self.lifecycle_events.append("monitor.stop")


def test_entra_expiry_endpoints_require_admin_csrf_and_return_only_public_status(
    api_environment, monkeypatch
) -> None:
    client, _store = api_environment
    public_status = {
        "tenant_id": "tenant",
        "client_id": "client",
        "status": "ok",
        "expires_at": "2026-08-01T10:00:00.000Z",
        "credential_name": "safe credential",
        "application_name": "safe application",
        "source": "saved",
        "last_checked_at": "2026-07-20T10:00:00.000Z",
        "last_success_at": "2026-07-20T10:00:00.000Z",
        "error_code": "",
        "error_message": "",
    }
    monkeypatch.setattr(web_app, "entra_secret_status", lambda: public_status)
    monkeypatch.setattr(web_app, "refresh_entra_secret_status", lambda force=True: public_status)

    assert client.get("/api/settings/email/entra-expiry").status_code == 401
    csrf = _login(client)
    assert client.post("/api/settings/email/entra-expiry/refresh", json={}).status_code == 403

    get_response = client.get("/api/settings/email/entra-expiry")
    post_response = client.post(
        "/api/settings/email/entra-expiry/refresh",
        headers={"X-PicSyncra-CSRF": csrf},
        json={},
    )

    assert get_response.status_code == 200
    assert post_response.status_code == 200
    assert get_response.json() == public_status
    assert post_response.json() == public_status
    assert "client_secret" not in get_response.text
    assert "credential_key_id" not in post_response.text


def test_direct_entra_test_mail_refreshes_status_only_after_entra_success(
    api_environment, monkeypatch
) -> None:
    client, _store = api_environment
    with web_app._RATE_LIMITS_LOCK:
        web_app._RATE_LIMITS.clear()
    csrf = _login(client)
    refreshes = []
    prior_status = {"status": "ok", "source": "saved", "expires_at": "2026-08-01T10:00:00.000Z"}
    monkeypatch.setattr(web_app, "entra_secret_status", lambda: prior_status)
    monkeypatch.setattr(web_app, "refresh_entra_secret_status", lambda force=True: refreshes.append(force) or prior_status)
    monkeypatch.setattr(
        web_app,
        "send_test_message",
        lambda **_kwargs: {"status": "sent", "used_channel": "entra", "attempts": []},
    )

    success = client.post(
        "/api/settings/email/test",
        headers={"X-PicSyncra-CSRF": csrf},
        json={"channel": "entra", "recipient": "admin@example.com", "use_fallback": False},
    )

    assert success.status_code == 200
    assert refreshes == [True]
    monkeypatch.setattr(
        web_app,
        "send_test_message",
        lambda **_kwargs: {"status": "error", "used_channel": "entra", "attempts": []},
    )
    refreshes.clear()

    failed = client.post(
        "/api/settings/email/test",
        headers={"X-PicSyncra-CSRF": csrf},
        json={"channel": "entra", "recipient": "admin@example.com", "use_fallback": False},
    )

    assert failed.status_code == 502
    assert refreshes == []
    assert client.get("/api/settings/email/entra-expiry").json() == prior_status


def test_notification_test_suite_uses_selected_channel_and_requires_csrf(
    api_environment, monkeypatch
) -> None:
    client, _store = api_environment
    with web_app._RATE_LIMITS_LOCK:
        web_app._RATE_LIMITS.clear()
    csrf = _login(client)
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        web_app,
        "send_test_notification_suite",
        lambda **kwargs: calls.append(kwargs) or {
            "scenarios": [
                {
                    "kind": kind,
                    "severity": severity,
                    "status": "skipped",
                    "used_channel": "smtp",
                    "recipient_count": 0,
                    "attempts": [],
                }
                for kind, severity in (
                    ("pimcore_rejection", "warning"),
                    ("ftp_failure", "error"),
                    ("photo_location_unavailable", "error"),
                    ("backend_exception", "critical"),
                    ("entra_secret_expiry", "critical"),
                )
            ]
        },
    )

    response = client.post(
        "/api/settings/email/test-suite",
        headers={"X-PicSyncra-CSRF": csrf},
        json={"channel": "smtp", "use_fallback": False},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    scenarios = response.json()["scenarios"]
    assert [item["kind"] for item in scenarios] == [
        "pimcore_rejection",
        "ftp_failure",
        "photo_location_unavailable",
        "backend_exception",
        "entra_secret_expiry",
    ]
    assert all(
        set(item)
        == {"kind", "severity", "status", "used_channel", "recipient_count", "attempts"}
        for item in scenarios
    )
    assert all(item["status"] == "skipped" for item in scenarios)
    assert calls == [{"channel": "smtp", "use_fallback": False}]


def test_events_are_admin_only_paginated_filtered_and_validate_cursor(
    api_environment,
) -> None:
    client, store = api_environment
    for index in range(25):
        store.append_operational_event(
            _event(
                f"evt-{index:02d}",
                f"2026-07-16T10:{index:02d}:00.000Z",
                "warning" if index % 2 else "info",
            )
        )
    web_data.add_user("operator", "secret", "user")

    _login(client, "operator", "secret")
    assert client.get("/api/observability/events").status_code == 403

    client = TestClient(web_app.app)
    _login(client)
    first_page = client.get("/api/observability/events")
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 20
    assert first_page.json()["next_cursor"]
    assert first_page.json()["server_time"].endswith("Z")
    assert first_page.json()["unread"]["warning"] == 12

    warning_page = client.get(
        "/api/observability/events", params={"severity": "warning", "limit": 1000}
    )
    assert warning_page.status_code == 200
    assert len(warning_page.json()["items"]) == 12
    assert {item["severity"] for item in warning_page.json()["items"]} == {"warning"}
    assert client.get(
        "/api/observability/events", params={"severity": "verbose"}
    ).status_code == 400
    assert client.get(
        "/api/observability/events", params={"cursor": "not-a-cursor"}
    ).status_code == 400
    assert client.get(
        "/api/observability/events",
        params={"cursor": first_page.json()["next_cursor"] + "!"},
    ).status_code == 400
    assert client.get(
        "/api/observability/events",
        params={"cursor": " " + first_page.json()["next_cursor"]},
    ).status_code == 400
    assert client.get(
        "/api/observability/events",
        params={"cursor": first_page.json()["next_cursor"]},
    ).status_code == 200
    not_a_date = base64.urlsafe_b64encode(
        json.dumps(["not-a-date", "evt-1"]).encode("utf-8")
    ).decode("ascii").rstrip("=")
    assert client.get(
        "/api/observability/events", params={"cursor": not_a_date}
    ).status_code == 400
    for noncanonical_timestamp in (
        "2026-07-16 10:05:00.000+00:00",
        "2026-07-16T12:05:00.000+02:00",
    ):
        noncanonical = base64.urlsafe_b64encode(
            json.dumps([noncanonical_timestamp, "evt-1"]).encode("utf-8")
        ).decode("ascii").rstrip("=")
        assert client.get(
            "/api/observability/events", params={"cursor": noncanonical}
        ).status_code == 400


def test_live_seed_is_admin_only_atomic_and_exposes_only_opaque_marker(
    api_environment,
) -> None:
    client, store = api_environment
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(minutes=5)).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    old = (now - timedelta(hours=25)).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    store.append_operational_event(_event("evt-old", old))
    store.append_operational_event(_event("evt-recent", recent))
    store.append_operational_event(_event("evt-tombstone", recent))
    with sqlite3.connect(store.path) as conn:
        conn.execute("DELETE FROM operational_events WHERE id = ?", ("evt-tombstone",))
    web_data.add_user("operator", "secret", "user")

    assert client.get(
        "/api/observability/events", params={"live_seed": 1}
    ).status_code == 401
    _login(client, "operator", "secret")
    assert client.get(
        "/api/observability/events", params={"live_seed": 1}
    ).status_code == 403

    admin = TestClient(web_app.app)
    _login(admin)
    response = admin.get("/api/observability/events", params={"live_seed": 1})

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == ["evt-recent"]
    assert payload["stream_after_id"] == "evt-tombstone"
    assert payload["next_cursor"] == ""
    assert "sequence" not in json.dumps(payload)
    admin.close()


def test_fresh_live_seed_origin_marker_streams_later_events_without_sentinel_data(
    api_environment,
) -> None:
    client, store = api_environment
    _login(client)

    seed = client.get("/api/observability/events", params={"live_seed": 1})

    assert seed.status_code == 200
    payload = seed.json()
    assert payload["items"] == []
    assert payload["stream_after_id"]
    assert "sequence" not in json.dumps(payload)
    store.append_operational_event(
        _event("evt-after-origin", datetime.now(timezone.utc).isoformat())
    )
    endpoint = next(
        route.endpoint
        for route in web_app.app.routes
        if getattr(route, "path", "") == "/api/observability/stream"
    )

    class RequestStub:
        headers: dict[str, str] = {}

        async def is_disconnected(self) -> bool:
            return False

    async def first_frame() -> str:
        with patch.object(
            web_app,
            "_require_admin",
            return_value={"username": "admin", "role": "admin"},
        ):
            response = await endpoint(
                RequestStub(), after_id=payload["stream_after_id"]
            )
            iterator = response.body_iterator
            frame = await anext(iterator)
            await iterator.aclose()
            return frame

    frame = asyncio.run(first_frame())
    assert frame.startswith("id: evt-after-origin\n")
    assert payload["stream_after_id"] not in frame


def test_incidents_include_only_their_correlated_context(api_environment) -> None:
    client, store = api_environment
    _login(client)
    correlated = [
        _event("evt-before", "2026-07-16T10:00:00.000Z", job_id="job-1"),
        _event(
            "evt-problem",
            "2026-07-16T10:01:00.000Z",
            "error",
            job_id="job-1",
        ),
        _event("evt-after", "2026-07-16T10:02:00.000Z", job_id="job-1"),
        _event(
            "evt-unrelated",
            "2026-07-16T10:01:30.000Z",
            "critical",
            job_id="job-2",
        ),
    ]
    for event in correlated:
        store.append_operational_event(event)
    store.upsert_incident(
        {
            "id": "inc-1",
            "fingerprint": "same-failure",
            "severity": "error",
            "event_type": "test.failure",
            "first_seen_at": "2026-07-16T10:01:00.000Z",
            "last_seen_at": "2026-07-16T10:01:00.000Z",
            "first_event_id": "evt-problem",
            "latest_event_id": "evt-problem",
            "job_id": "job-1",
        }
    )

    response = client.get("/api/observability/incidents", params={"severity": "error"})

    assert response.status_code == 200
    incident = response.json()["items"][0]
    assert "before" not in incident
    assert "problem" not in incident
    assert "after" not in incident
    assert "evt-unrelated" not in response.text

    context = client.get("/api/observability/incidents/inc-1/context")
    assert context.status_code == 200
    assert [item["id"] for item in context.json()["before"]] == ["evt-before"]
    assert [item["id"] for item in context.json()["problem"]] == ["evt-problem"]
    assert [item["id"] for item in context.json()["after"]] == ["evt-after"]
    assert context.json()["problem_next_cursor"] == ""


def test_incident_context_endpoint_is_admin_only_lazy_and_pages_problem(
    api_environment,
) -> None:
    client, store = api_environment
    for index in range(25):
        store.append_operational_event(
            _event(
                f"evt-problem-{index:02d}",
                f"2026-07-16T10:{index:02d}:00.000Z",
                "error",
                job_id="job-context",
                details={"password": "must-not-leak", "safe": index},
            )
        )
    store.upsert_incident(
        {
            "id": "inc-lazy",
            "fingerprint": "lazy",
            "severity": "error",
            "event_type": "test.failure",
            "first_seen_at": "2026-07-16T10:00:00.000Z",
            "last_seen_at": "2026-07-16T10:24:00.000Z",
            "first_event_id": "evt-problem-00",
            "latest_event_id": "evt-problem-24",
            "job_id": "job-context",
        }
    )
    web_data.add_user("operator-context", "secret", "user")

    assert client.get("/api/observability/incidents/inc-lazy/context").status_code == 401
    _login(client, "operator-context", "secret")
    assert client.get("/api/observability/incidents/inc-lazy/context").status_code == 403

    admin = TestClient(web_app.app)
    _login(admin)
    listing = admin.get("/api/observability/incidents", params={"severity": "error"})
    assert listing.status_code == 200
    assert "problem" not in listing.json()["items"][0]
    first = admin.get(
        "/api/observability/incidents/inc-lazy/context", params={"limit": 20}
    )
    assert first.status_code == 200
    assert len(first.json()["problem"]) == 20
    assert first.json()["problem_next_cursor"]
    second = admin.get(
        "/api/observability/incidents/inc-lazy/context",
        params={"cursor": first.json()["problem_next_cursor"], "limit": 20},
    )
    assert [item["id"] for item in second.json()["problem"]] == [
        f"evt-problem-{index:02d}" for index in range(20, 25)
    ]
    serialized = json.dumps([first.json(), second.json()])
    assert "must-not-leak" not in serialized
    assert admin.get("/api/observability/incidents/missing/context").status_code == 404
    assert admin.get(
        "/api/observability/incidents/inc-lazy/context",
        params={"cursor": "not-base64!"},
    ).status_code == 400
    admin.close()


def test_live_api_cursor_reaches_oldest_of_4000_retained_events(
    api_environment,
) -> None:
    client, store = api_environment
    _login(client)
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    with store.connection() as conn:
        for index in range(4000):
            payload = store._normalize_operational_event(
                _event(
                    f"evt-live-{index:04d}",
                    (start + timedelta(seconds=index))
                    .isoformat(timespec="milliseconds")
                    .replace("+00:00", "Z"),
                )
            )
            store._insert_operational_event(conn, payload)

    seed = client.get("/api/observability/events", params={"live_seed": 1})
    assert seed.status_code == 200
    payload = seed.json()
    assert len(payload["items"]) == 200
    assert payload["archive_since"]
    assert payload["next_cursor"]
    reached = {item["id"] for item in payload["items"]}
    cursor = payload["next_cursor"]
    while cursor:
        page = client.get(
            "/api/observability/events",
            params={
                "cursor": cursor,
                "since": payload["archive_since"],
                "limit": 100,
            },
        )
        assert page.status_code == 200
        reached.update(item["id"] for item in page.json()["items"])
        cursor = page.json()["next_cursor"]

    assert len(reached) == 4000
    assert "evt-live-0000" in reached


def test_live_seed_and_older_page_apply_same_literal_substring_filters(
    api_environment,
) -> None:
    client, store = api_environment
    _login(client)
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    with store.connection() as conn:
        for index in range(205):
            payload = store._normalize_operational_event(
                {
                    **_event(
                        f"evt-filter-{index:03d}",
                        (start + timedelta(seconds=index))
                        .isoformat(timespec="milliseconds")
                        .replace("+00:00", "Z"),
                    ),
                    "module": (
                        "ŻÓŁĆ Pimcore"
                        if index
                        else "ŻÓŁĆ%_\\Pimcore"
                    ),
                }
            )
            store._insert_operational_event(conn, payload)
        store._insert_operational_event(
            conn,
            store._normalize_operational_event(
                {
                    **_event(
                        "evt-filter-decoy",
                        (start + timedelta(seconds=100, milliseconds=500))
                        .isoformat(timespec="milliseconds")
                        .replace("+00:00", "Z"),
                    ),
                    "module": "FTP",
                }
            ),
        )

    seed = client.get(
        "/api/observability/events",
        params={"live_seed": 1, "module": "żółć"},
    )
    assert seed.status_code == 200
    payload = seed.json()
    older = client.get(
        "/api/observability/events",
        params={
            "cursor": payload["next_cursor"],
            "since": payload["archive_since"],
            "module": "żółć",
            "limit": 20,
        },
    )
    literal = client.get(
        "/api/observability/events",
        params={"live_seed": 1, "module": "żółć%_\\p"},
    )
    date_seed = client.get(
        "/api/observability/events",
        params={"live_seed": 1, "query": start.strftime("%Y-%m")},
    )
    property_name = client.get(
        "/api/observability/events",
        params={"live_seed": 1, "query": "created_at"},
    )

    assert len(payload["items"]) == 200
    assert {item["module"] for item in payload["items"]} == {"ŻÓŁĆ Pimcore"}
    assert len(older.json()["items"]) == 5
    assert [item["id"] for item in literal.json()["items"]] == ["evt-filter-000"]
    assert len(date_seed.json()["items"]) == 200
    assert date_seed.json()["next_cursor"]
    assert property_name.json()["items"] == []


def test_incidents_include_matching_delivery_status_with_strict_safe_projection(
    api_environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = api_environment
    _login(client)
    store.append_operational_event(
        _event("evt-problem", "2026-07-16T10:01:00.000Z", "error")
    )
    store.upsert_incident(
        {
            "id": "inc-visible",
            "fingerprint": "visible-failure",
            "severity": "error",
            "event_type": "test.failure",
            "first_seen_at": "2026-07-16T10:01:00.000Z",
            "last_seen_at": "2026-07-16T10:01:00.000Z",
            "first_event_id": "evt-problem",
            "latest_event_id": "evt-problem",
        }
    )
    store.enqueue_notification_delivery(
        {
            "id": "delivery-visible",
            "incident_id": "inc-visible",
            "event_id": "evt-problem",
            "severity": "error",
            "status": "error",
            "primary_channel": "entra",
            "used_channel": "smtp",
            "recipients": ["admin@example.com", "operator@example.com"],
            "message": {
                "message_id": "incident-visible",
                "subject": "private subject",
                "text_body": "private body",
            },
            "attempts": [
                {
                    "channel": "smtp",
                    "status": "error",
                    "status_code": 503,
                    "elapsed_ms": 47,
                    "code": "delivery_failed",
                    "category": "delivery",
                    "message": "smtp_password=must-not-leak",
                    "recipients": ["intruder@example.com"],
                    "access_token": "must-not-leak",
                    "unexpected": "must-not-leak",
                }
            ],
            "created_at": "2026-07-16T10:02:00.000Z",
            "updated_at": "2026-07-16T10:03:00.000Z",
            "next_attempt_at": "",
        }
    )
    # More than one global delivery page must not starve the matching older row.
    for index in range(101):
        store.enqueue_notification_delivery(
            {
                "id": f"delivery-decoy-{index:03d}",
                "incident_id": "inc-not-visible",
                "event_id": "evt-decoy",
                "severity": "warning",
                "status": "pending",
                "primary_channel": "entra",
                "used_channel": "",
                "recipients": ["decoy@example.com"],
                "message": {"message_id": f"decoy-{index}"},
                "attempts": [],
                "created_at": f"2026-07-17T10:{index // 60:02d}:{index % 60:02d}.000Z",
                "updated_at": f"2026-07-17T10:{index // 60:02d}:{index % 60:02d}.000Z",
                "next_attempt_at": "",
            }
        )
    monkeypatch.setattr(web_app, "observability_store", lambda: store)

    response = client.get("/api/observability/incidents", params={"severity": "error"})

    assert response.status_code == 200
    delivery = response.json()["items"][0]["deliveries"][0]
    assert delivery == {
        "id": "delivery-visible",
        "status": "error",
        "used_channel": "smtp",
        "recipient_count": 2,
        "created_at": "2026-07-16T10:02:00.000Z",
        "updated_at": "2026-07-16T10:03:00.000Z",
        "attempts": [
            {
                "channel": "smtp",
                "status": "error",
                "status_code": 503,
                "elapsed_ms": 47,
                "code": "delivery_failed",
                "category": "delivery",
                "message": "Kanal nie wyslal wiadomosci.",
            }
        ],
    }
    serialized = json.dumps(response.json(), ensure_ascii=False)
    for private_value in (
        "admin@example.com",
        "operator@example.com",
        "intruder@example.com",
        "private subject",
        "private body",
        "must-not-leak",
    ):
        assert private_value not in serialized


def test_non_admin_cannot_inspect_incident_delivery_status(api_environment) -> None:
    client, _store = api_environment
    web_data.add_user("operator", "secret", "user")
    _login(client, "operator", "secret")

    response = client.get("/api/observability/incidents")

    assert response.status_code == 403
    assert "recipients" not in response.text.lower()
    assert "attempts" not in response.text.lower()


def test_partial_delivery_projection_exposes_only_safe_counts_status_and_codes(
) -> None:
    from picsyncra.web.app import _public_incident_delivery

    projected = _public_incident_delivery(
        {
            "id": "delivery-1",
            "status": "error",
            "used_channel": "smtp",
            "recipients": ["private@example.com", "other@example.com"],
            "created_at": "2026-07-17T12:00:00.000Z",
            "updated_at": "2026-07-17T12:00:01.000Z",
            "attempts": [
                {
                    "channel": "smtp",
                    "status": "partial",
                    "accepted_count": 1,
                    "refused_count": 1,
                    "refusal_codes": [452],
                    "refused_recipients": ["private@example.com"],
                    "server_response": "sensitive",
                }
            ],
        }
    )

    assert projected["attempts"] == [
        {
            "channel": "smtp",
            "status": "partial",
            "accepted_count": 1,
            "refused_count": 1,
            "refusal_codes": [452],
        }
    ]
    assert "private@example.com" not in str(projected)
    assert "sensitive" not in str(projected)

    failed = _public_incident_delivery(
        {
            "id": "delivery-2",
            "status": "error",
            "attempts": [
                {
                    "channel": "smtp",
                    "status": "error",
                    "code": "partial_routing_unknown",
                    "category": "delivery",
                    "message": "private",
                }
            ],
        }
    )
    assert failed["attempts"][0]["code"] == "partial_routing_unknown"


def test_jobs_endpoint_returns_durable_runs_for_admin(api_environment) -> None:
    client, store = api_environment
    _login(client)
    store.upsert_job_run(
        {
            "id": "job-1",
            "username": "admin",
            "status": "completed",
            "summary": "Done",
            "started_at": "2026-07-16T10:00:00.000Z",
        }
    )

    response = client.get("/api/observability/jobs")

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "job-1"
    assert set(response.json()) == {"items", "next_cursor", "unread", "server_time"}


def test_sse_stream_is_admin_only_and_frames_events(api_environment) -> None:
    client, store = api_environment
    web_data.add_user("operator", "secret", "user")
    _login(client, "operator", "secret")
    assert client.get("/api/observability/stream").status_code == 403
    store.append_operational_event(
        _event("evt-sse", "2026-07-16T10:00:00.000Z", "warning")
    )
    endpoint = next(
        route.endpoint
        for route in web_app.app.routes
        if getattr(route, "path", "") == "/api/observability/stream"
    )

    class RequestStub:
        headers: dict[str, str] = {}

        async def is_disconnected(self) -> bool:
            return False

    async def first_frame() -> str:
        with patch.object(
            web_app,
            "_require_admin",
            return_value={"username": "admin", "role": "admin"},
        ):
            response = await endpoint(RequestStub(), after_id="")
            iterator = response.body_iterator
            frame = await anext(iterator)
            await iterator.aclose()
            return frame

    frame = asyncio.run(first_frame())
    assert frame.startswith("id: evt-sse\n")
    assert "data: {" in frame
    assert '"severity": "warning"' in frame
    assert frame.endswith("\n\n")


def test_sse_stream_yields_nothing_when_already_disconnected(api_environment) -> None:
    _client, store = api_environment
    store.append_operational_event(
        _event("evt-snapshot", "2026-07-16T10:00:00.000Z")
    )
    endpoint = next(
        route.endpoint
        for route in web_app.app.routes
        if getattr(route, "path", "") == "/api/observability/stream"
    )

    class RequestStub:
        headers: dict[str, str] = {}

        async def is_disconnected(self) -> bool:
            return True

    async def collect() -> list[str]:
        with patch.object(
            web_app,
            "_require_admin",
            return_value={"username": "admin", "role": "admin"},
        ):
            response = await endpoint(RequestStub(), after_id="")
            return [frame async for frame in response.body_iterator]

    assert asyncio.run(collect()) == []


def test_sse_stream_stops_during_initial_snapshot(api_environment) -> None:
    _client, store = api_environment
    for index in range(3):
        store.append_operational_event(
            _event(f"evt-{index}", f"2026-07-16T10:0{index}:00.000Z")
        )
    endpoint = next(
        route.endpoint
        for route in web_app.app.routes
        if getattr(route, "path", "") == "/api/observability/stream"
    )

    class RequestStub:
        headers: dict[str, str] = {}

        def __init__(self) -> None:
            self.states = iter((False, True))

        async def is_disconnected(self) -> bool:
            return next(self.states, True)

    async def collect() -> list[str]:
        with patch.object(
            web_app,
            "_require_admin",
            return_value={"username": "admin", "role": "admin"},
        ):
            response = await endpoint(RequestStub(), after_id="")
            return [frame async for frame in response.body_iterator]

    frames = asyncio.run(collect())
    assert len(frames) == 1
    assert frames[0].startswith("id: evt-0\n")


def test_sse_stream_reconnect_drains_more_than_one_page_without_duplicates(
    api_environment,
) -> None:
    client, store = api_environment
    _login(client)
    store.append_operational_event(
        _event("evt-marker", "2026-07-16T10:00:00.000Z")
    )
    expected = []
    for index in range(205):
        identity = f"evt-{index:03d}"
        expected.append(identity)
        store.append_operational_event(
            _event(identity, "2026-07-16T10:00:00.000Z")
        )
    endpoint = next(
        route.endpoint
        for route in web_app.app.routes
        if getattr(route, "path", "") == "/api/observability/stream"
    )

    class RequestStub:
        headers: dict[str, str] = {}
        calls = 0

        async def is_disconnected(self) -> bool:
            self.calls += 1
            return self.calls > 1000

    async def event_ids() -> list[str]:
        with (
            patch.object(
                web_app,
                "_require_admin",
                return_value={"username": "admin", "role": "admin"},
            ),
            patch.object(web_app.asyncio, "sleep", return_value=None),
        ):
            response = await endpoint(RequestStub(), after_id="evt-marker")
            iterator = response.body_iterator
            identities = []
            try:
                while len(identities) < len(expected):
                    frame = await anext(iterator)
                    if frame.startswith("id: "):
                        identities.append(frame.splitlines()[0][4:])
            except StopAsyncIteration:
                pass
            await iterator.aclose()
            return identities

    streamed = asyncio.run(event_ids())
    assert streamed == expected
    assert len(streamed) == len(set(streamed))


def test_sse_stream_prefers_standard_last_event_id_header(api_environment) -> None:
    client, store = api_environment
    _login(client)
    for identity in ("evt-query-marker", "evt-replayed", "evt-header-marker", "evt-next"):
        store.append_operational_event(
            _event(identity, "2026-07-16T10:00:00.000Z")
        )
    endpoint = next(
        route.endpoint
        for route in web_app.app.routes
        if getattr(route, "path", "") == "/api/observability/stream"
    )

    class RequestStub:
        headers = {"last-event-id": "evt-header-marker"}

        async def is_disconnected(self) -> bool:
            return False

    async def first_frame() -> str:
        with patch.object(
            web_app,
            "_require_admin",
            return_value={"username": "admin", "role": "admin"},
        ):
            response = await endpoint(RequestStub(), after_id="evt-query-marker")
            iterator = response.body_iterator
            frame = await anext(iterator)
            await iterator.aclose()
            return frame

    frame = asyncio.run(first_frame())
    assert frame.startswith("id: evt-next\n")
    assert "evt-replayed" not in frame


def test_mark_read_state_is_scoped_to_current_authenticated_user(api_environment) -> None:
    client, store = api_environment
    web_data.add_user("operator", "secret", "user")
    web_data.add_user("second-operator", "secret", "user")
    store.append_operational_event(
        _event("evt-warning", "2026-07-16T10:00:00.000Z", "warning")
    )
    anonymous = TestClient(web_app.app)
    assert anonymous.post(
        "/api/observability/read",
        json={
            "severity": "warning",
            "event_id": "evt-warning",
            "created_at": "2026-07-16T10:00:00.000Z",
        },
    ).status_code == 401
    csrf = _login(client, "operator", "secret")

    marked = client.post(
        "/api/observability/read",
        headers={"X-PicSyncra-CSRF": csrf},
        json={
            "severity": "warning",
            "event_id": "evt-warning",
            "created_at": "2026-07-16T10:00:00.000Z",
            "username": "second-operator",
        },
    )

    assert marked.status_code == 200
    assert marked.json()["unread"]["warning"] == 0
    assert store.unread_alert_summary("operator")["warning"] == 0
    assert store.unread_alert_summary("second-operator")["warning"] == 1


def test_clear_logs_clears_operational_tables_but_preserves_audits(
    api_environment,
) -> None:
    client, store = api_environment
    csrf = _login(client)
    store.append_history(
        {"id": "history-1", "created_at": "2026-07-16T09:00:00.000Z"}
    )
    store.append_pimcore_submission(
        {
            "id": "pim-1",
            "operation_type": "create",
            "status": "success",
            "created_at": "2026-07-16T09:30:00.000Z",
        }
    )
    store.append_operational_event(
        _event("evt-1", "2026-07-16T10:00:00.000Z", "error")
    )
    store.upsert_job_run(
        {"id": "job-1", "status": "failed", "started_at": "2026-07-16T10:00:00.000Z"}
    )
    store.upsert_incident(
        {
            "id": "inc-1",
            "fingerprint": "failure",
            "severity": "error",
            "event_type": "test.failure",
            "first_seen_at": "2026-07-16T10:00:00.000Z",
            "last_seen_at": "2026-07-16T10:00:00.000Z",
            "first_event_id": "evt-1",
            "latest_event_id": "evt-1",
        }
    )
    store.mark_alerts_read("admin", "error", "evt-1", "2026-07-16T10:00:00.000Z")

    with patch.object(
        web_app, "_clear_log_files", return_value={"cleared": [], "errors": []}
    ):
        response = client.post(
            "/api/logs/clear",
            headers={"X-PicSyncra-CSRF": csrf},
            json={"password": "admin"},
        )

    assert response.status_code == 200
    assert response.json()["structured_cleared"] == {
        "operational_events": 1,
        "job_runs": 1,
        "incidents": 1,
        "alert_reads": 1,
        "notification_deliveries": 0,
        "notification_outbox": 0,
        "pimcore_integration_contexts": 0,
    }
    assert store.query_operational_events()["items"] == []
    assert store.query_job_runs()["items"] == []
    assert store.query_incidents()["items"] == []
    assert store.load_history()[0]["id"] == "history-1"
    assert store.query_pimcore_submissions()[0]["id"] == "pim-1"


def test_health_reports_local_components_and_last_known_integrations(
    api_environment,
) -> None:
    client, store = api_environment
    store.append_operational_event(
        _event(
            "evt-ftp",
            "2026-07-16T10:00:00.000Z",
            event_type="integration.ftp.completed",
            details={
                "status": "error",
                "error": "password=secret at C:/private/path",
            },
        )
    )
    store.append_operational_event(
        _event(
            "evt-profile",
            "2026-07-16T10:01:00.000Z",
            event_type="integration.sql_profile.completed",
            details={"status": "success", "profile_id": "catalogue"},
        )
    )

    with (
        patch.object(web_app, "test_ftp_connection", side_effect=AssertionError),
        patch.object(web_app, "test_sql_connection", side_effect=AssertionError),
        patch.object(web_app, "test_pimcore_settings", side_effect=AssertionError),
    ):
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload["components"]) >= {"backend", "sqlite", "job_processor"}
    assert payload["components"]["backend"]["status"] == "online"
    assert payload["components"]["sqlite"]["status"] == "online"
    assert payload["integrations"]["ftp"]["status"] == "error"
    assert payload["integrations"]["sql_profiles"] == [
        {
            "profile_id": "catalogue",
            "status": "success",
            "observed_at": "2026-07-16T10:01:00.000Z",
        }
    ]
    assert payload["components"]["sql_profiles"]["observed_at"] == (
        "2026-07-16T10:01:00.000Z"
    )
    assert "password" not in response.text.lower()
    assert "c:/private/path" not in response.text.lower()


def test_health_returns_cached_resource_projection_without_sampling(
    api_environment, monkeypatch
) -> None:
    client, _store = api_environment
    _login(client)
    monitor = _MonitorStub(
        {"host": {"cpu_percent": 60}, "backend": {"cpu_percent": 4}}
    )
    monkeypatch.setattr(web_app, "_RESOURCE_MONITOR", monitor)

    payload = client.get("/api/health").json()

    assert payload["resources"]["backend"]["cpu_percent"] == 4
    assert monitor.sample_calls == 0


def test_health_remains_available_with_cached_unavailable_resource_metrics(
    api_environment, monkeypatch
) -> None:
    client, _store = api_environment
    monitor = _MonitorStub(
        {
            "host": {"available": False, "reason": "counter unavailable"},
            "backend": {"available": False},
        }
    )
    monkeypatch.setattr(web_app, "_RESOURCE_MONITOR", monitor)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["resources"] == monitor.snapshot
    assert monitor.sample_calls == 0


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/resource-monitor/simulate-safe", {}),
        ("/api/resource-monitor/real-test", {"kind": "cpu"}),
    ],
)
def test_resource_monitor_endpoints_require_admin_and_csrf(
    api_environment, monkeypatch, path: str, body: dict[str, object]
) -> None:
    client, _store = api_environment
    monitor = _MonitorStub()
    monkeypatch.setattr(web_app, "_RESOURCE_MONITOR", monitor)

    assert client.post(path, json=body).status_code == 401
    admin_csrf = _login(client)
    assert client.post(path, json=body).status_code == 403
    client.cookies.clear()
    web_data.add_user("operator", "secret", "user")
    operator_csrf = _login(client, "operator", "secret")
    forbidden = client.post(
        path,
        headers={"X-PicSyncra-CSRF": operator_csrf},
        json=body,
    )

    assert forbidden.status_code == 403
    assert admin_csrf
    assert monitor.safe_calls == 0
    assert monitor.real_calls == []


def test_safe_resource_simulation_records_one_labelled_test_event(
    api_environment, monkeypatch
) -> None:
    client, _store = api_environment
    csrf = _login(client)
    events: list[tuple[str, str, dict[str, object]]] = []
    monitor = ResourceMonitor(
        settings_provider=lambda: {},
        context_provider=lambda: {},
        event_emitter=lambda severity, event_type, details: (
            events.append((severity, event_type, details)) or True
        ),
        readers=object(),
    )
    monkeypatch.setattr(web_app, "_RESOURCE_MONITOR", monitor)

    response = client.post(
        "/api/resource-monitor/simulate-safe",
        headers={"X-PicSyncra-CSRF": csrf},
        json={},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"ok", "message", "resources", "test"}
    assert payload["ok"] is True
    assert payload["test"]["test_mode"] == "safe"
    assert len(events) == 1
    assert events[0][0:2] == ("info", "backend.resource_test")
    assert events[0][2]["test_mode"] == "safe"


def test_safe_resource_simulation_reports_web_event_persistence_failure(
    api_environment, monkeypatch
) -> None:
    client, _store = api_environment
    csrf = _login(client)
    emitted: list[dict[str, object]] = []
    monitor = ResourceMonitor(
        settings_provider=lambda: {},
        context_provider=lambda: {},
        event_emitter=web_app._emit_resource_event,
        readers=object(),
    )
    monkeypatch.setattr(web_app, "_RESOURCE_MONITOR", monitor)

    def failing_emit_event(**kwargs: object) -> dict[str, object]:
        emitted.append(dict(kwargs))
        raise OSError("observability store unavailable")

    monkeypatch.setattr(web_app, "emit_event", failing_emit_event)

    response = client.post(
        "/api/resource-monitor/simulate-safe",
        headers={"X-PicSyncra-CSRF": csrf},
        json={},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["test"]["status"] == "persistence_failed"
    assert "trwale zapisac" in payload["message"].lower()
    assert len(emitted) == 1
    assert emitted[0]["strict"] is True


def test_real_resource_worker_failure_is_persisted_and_redacted(monkeypatch) -> None:
    emitted: list[dict[str, object]] = []
    logged: list[str] = []
    monkeypatch.setattr(
        web_app, "emit_event", lambda **kwargs: emitted.append(dict(kwargs)) or {"id": "evt-1"}
    )
    monkeypatch.setattr(web_app, "log_error", lambda message: logged.append(message))

    web_app._report_real_test_worker_failure(
        "disk", "ValueError: password=do-not-leak"
    )

    assert len(emitted) == 1
    event = emitted[0]
    assert event["severity"] == "error"
    assert event["event_type"] == "backend.resource_test_failed"
    assert event["module"] == "resource_monitor"
    assert event["stage"] == "real_test"
    assert event["details"] == {"test_mode": "real", "kind": "disk"}
    assert event["strict"] is True
    assert "do-not-leak" not in str(event["exception"])
    assert "[REDACTED]" in str(event["exception"])
    assert len(logged) == 1
    assert "do-not-leak" not in logged[0]


def test_real_resource_test_returns_monitor_result_without_direct_event(
    api_environment, monkeypatch
) -> None:
    client, _store = api_environment
    csrf = _login(client)
    result = {
        "ok": True,
        "kind": "memory",
        "status": "detected",
        "timed_out": False,
    }
    monitor = _MonitorStub(real_result=result)
    monkeypatch.setattr(web_app, "_RESOURCE_MONITOR", monitor)
    direct_events: list[dict[str, object]] = []
    monkeypatch.setattr(
        web_app, "emit_event", lambda **kwargs: direct_events.append(kwargs)
    )

    response = client.post(
        "/api/resource-monitor/real-test",
        headers={"X-PicSyncra-CSRF": csrf},
        json={"kind": "memory"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"ok", "message", "resources", "test"}
    assert payload["ok"] is True
    assert payload["test"] == result
    assert payload["resources"] == monitor.snapshot
    assert monitor.real_calls == ["memory"]
    assert direct_events == []


def test_real_resource_test_reports_trigger_event_persistence_failure(
    api_environment, monkeypatch
) -> None:
    client, _store = api_environment
    csrf = _login(client)
    result = {
        "ok": False,
        "kind": "memory",
        "status": "persistence_failed",
        "timed_out": False,
    }
    monitor = _MonitorStub(real_result=result)
    monkeypatch.setattr(web_app, "_RESOURCE_MONITOR", monitor)

    response = client.post(
        "/api/resource-monitor/real-test",
        headers={"X-PicSyncra-CSRF": csrf},
        json={"kind": "memory"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["test"] == result
    assert "trwale zapisac" in payload["message"].lower()


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ValueError("unsupported real-test kind"), 400),
        (RuntimeError("a real resource test is already running"), 409),
    ],
)
def test_real_resource_test_maps_monitor_rejections_to_safe_http_statuses(
    api_environment, monkeypatch, error: Exception, expected_status: int
) -> None:
    client, _store = api_environment
    csrf = _login(client)
    monitor = _MonitorStub(real_error=error)
    monkeypatch.setattr(web_app, "_RESOURCE_MONITOR", monitor)

    response = client.post(
        "/api/resource-monitor/real-test",
        headers={"X-PicSyncra-CSRF": csrf},
        json={"kind": "cpu"},
    )

    assert response.status_code == expected_status
    assert monitor.real_calls == ["cpu"]


def test_resource_monitor_lifecycle_runs_once_and_in_runtime_order(
    tmp_path: Path, monkeypatch
) -> None:
    lifecycle_events: list[str] = []
    monitor = _MonitorStub(lifecycle_events=lifecycle_events)
    monkeypatch.setattr(web_app, "_RESOURCE_MONITOR", monitor)
    monkeypatch.setattr(
        web_app,
        "initialize_application_runtime",
        lambda **_kwargs: lifecycle_events.append("runtime.initialize") or {},
    )
    monkeypatch.setattr(web_app, "cleanup_web_ftp_cache", lambda **_kwargs: None)
    monkeypatch.setattr(web_app, "cleanup_web_upload_cache", lambda **_kwargs: None)
    monkeypatch.setattr(web_app, "_prune_live_events_if_due", lambda **_kwargs: None)
    monkeypatch.setattr(web_app, "_start_backup_scheduler", lambda: None)
    monkeypatch.setattr(web_app, "_stop_backup_scheduler", lambda: None)
    monkeypatch.setattr(web_app, "start_notification_worker", lambda: None)
    monkeypatch.setattr(
        web_app,
        "stop_notification_worker",
        lambda: lifecycle_events.append("notification.stop"),
    )
    database_path = str(tmp_path / "shutdown.sqlite")
    cached_store = data_store.get_sqlite_store(database_path)

    with TestClient(web_app.create_app()):
        pass

    assert monitor.start_calls == 1
    assert monitor.stop_calls == 1
    assert lifecycle_events.index("runtime.initialize") < lifecycle_events.index(
        "monitor.start"
    )
    assert lifecycle_events.index("monitor.stop") < lifecycle_events.index(
        "notification.stop"
    )
    assert data_store.get_sqlite_store(database_path) is not cached_store


def test_disabled_ocr_queue_clears_stale_work_during_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StoreProbe:
        def clear_ocr_crop_queue(self):
            store_opened.set()
            return []

    store_opened = threading.Event()
    monkeypatch.setitem(web_app.config.CONFIG, "ocr", {"background_enabled": False})
    monkeypatch.setattr(web_app, "initialize_application_runtime", lambda **_kwargs: {})
    monkeypatch.setattr(web_app, "cleanup_web_ftp_cache", lambda **_kwargs: None)
    monkeypatch.setattr(web_app, "cleanup_web_upload_cache", lambda **_kwargs: None)
    monkeypatch.setattr(web_app, "_prune_live_events_if_due", lambda **_kwargs: None)
    monkeypatch.setattr(web_app, "_start_backup_scheduler", lambda: None)
    monkeypatch.setattr(web_app, "_stop_backup_scheduler", lambda: None)
    monkeypatch.setattr(web_app, "start_notification_worker", lambda: None)
    monkeypatch.setattr(web_app, "stop_notification_worker", lambda: None)
    monkeypatch.setattr(web_app, "observability_store", lambda: _StoreProbe())

    with TestClient(web_app.create_app()):
        store_opened.wait(timeout=0.2)

    assert store_opened.is_set()


def test_health_is_critical_when_job_processor_is_shutdown_even_if_storage_is_online(
    api_environment,
) -> None:
    client, _store = api_environment

    with (
        patch.object(web_app._PROCESS_QUEUE, "_stopping", True),
        patch.object(
            web_app,
            "notification_worker_health",
            return_value={"status": "online", "observed_at": "2026-07-17T08:00:00.000Z"},
        ),
    ):
        payload = client.get("/api/health").json()

    assert payload["ok"] is False
    assert payload["components"]["backend"]["status"] == "online"
    assert payload["components"]["sqlite"]["status"] == "online"
    assert payload["components"]["job_processor"]["status"] == "critical"


def test_health_reports_existing_notification_worker_and_canonical_utc_time(
    api_environment,
) -> None:
    client, _store = api_environment

    with patch.object(
        web_app,
        "notification_worker_health",
        return_value={"status": "critical", "observed_at": "2026-07-17T08:01:02.003Z"},
    ):
        payload = client.get("/api/health").json()

    assert payload["ok"] is False
    assert payload["components"]["notification_worker"] == {
        "status": "critical",
        "observed_at": "2026-07-17T08:01:02.003Z",
    }
    assert payload["time"].endswith("Z")
    datetime.fromisoformat(payload["time"].replace("Z", "+00:00"))


def test_last_known_integration_stops_at_newest_unknown_status(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "app.sqlite"))
    store.append_operational_event(
        _event(
            "evt-known",
            "2026-07-16T10:00:00.000Z",
            event_type="integration.ftp.completed",
            details={"status": "success"},
        )
    )
    store.append_operational_event(
        _event(
            "evt-unknown",
            "2026-07-16T10:01:00.000Z",
            event_type="integration.ftp.completed",
            details={"status": "unexpected-status"},
        )
    )

    result = web_app._last_known_integrations(store)

    assert result["ftp"] == {
        "status": "unknown",
        "observed_at": "2026-07-16T10:01:00.000Z",
    }


def test_operational_clear_invalidates_cached_health_integrations(
    api_environment,
) -> None:
    client, store = api_environment
    csrf = _login(client)
    store.append_operational_event(
        _event(
            "evt-ftp",
            "2026-07-16T10:00:00.000Z",
            event_type="integration.ftp.completed",
            details={"status": "error"},
        )
    )
    with patch.object(web_app, "_HEALTH_INTEGRATION_CACHE_SECONDS", 3600):
        assert client.get("/api/health").json()["integrations"]["ftp"]["status"] == "error"

        with patch.object(
            web_app, "_clear_log_files", return_value={"cleared": [], "errors": []}
        ):
            response = client.post(
                "/api/logs/clear",
                headers={"X-PicSyncra-CSRF": csrf},
                json={"password": "admin"},
            )

        assert response.status_code == 200
        assert client.get("/api/health").json()["integrations"]["ftp"]["status"] == "unknown"
