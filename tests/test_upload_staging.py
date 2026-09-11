from __future__ import annotations

import os
import threading
import time

import pytest
from fastapi import HTTPException

from picsyncra.path_security import PathSecurityError
from picsyncra.web import app as web_app
from picsyncra.web.upload_staging import (
    UploadStagingService,
    cleanup_expired_job_directories,
    cleanup_job_directory,
    scan_uploaded_file,
    validate_image_file,
    validate_upload_signature,
)
from tests.helpers_process_upload import jpeg_bytes, upload_file


@pytest.mark.anyio
async def test_stage_runs_validation_and_scan_off_event_loop(tmp_path) -> None:
    """Catches validation or antivirus work that blocks the request event loop."""
    event_loop_thread = threading.get_ident()
    worker_threads: list[int] = []

    def validate(path: str, filename: object, max_pixels: int) -> tuple[int, int]:
        worker_threads.append(threading.get_ident())
        return 100, 100

    def scan(path: str) -> dict[str, object]:
        worker_threads.append(threading.get_ident())
        return {"status": "clean"}

    service = UploadStagingService(validate_image=validate, scan_file=scan)
    result = await service.stage(
        upload_file("photo.jpg", jpeg_bytes()),
        str(tmp_path),
        "01",
    )

    assert result.path.endswith(".jpg")
    assert result.width == 100
    assert result.height == 100
    assert worker_threads
    assert all(thread_id != event_loop_thread for thread_id in worker_threads)


@pytest.mark.anyio
async def test_stage_rejects_job_directory_outside_managed_root(tmp_path) -> None:
    """Catches staging into a directory that is not owned by the job root."""
    managed_root = tmp_path / "managed"
    outside = tmp_path / "outside"
    managed_root.mkdir()
    outside.mkdir()

    with pytest.raises(PathSecurityError):
        await UploadStagingService().stage(
            upload_file("photo.jpg", jpeg_bytes()),
            str(outside),
            "01",
            managed_root=str(managed_root),
        )


@pytest.mark.anyio
async def test_process_form_staging_keeps_validation_and_scan_off_event_loop(
    tmp_path, monkeypatch
) -> None:
    """Catches the existing process form path running its security checks inline."""
    event_loop_thread = threading.get_ident()
    worker_threads: list[int] = []

    def validate(
        path: str,
        filename: object,
        content_type: object,
        max_pixels: int,
    ) -> tuple[int, int]:
        worker_threads.append(threading.get_ident())
        return 100, 100

    def scan(path: str) -> dict[str, object]:
        worker_threads.append(threading.get_ident())
        return {"status": "clean"}

    monkeypatch.setattr(web_app, "_validate_upload_content", validate)
    monkeypatch.setattr(web_app, "_scan_uploaded_file", scan)
    monkeypatch.setattr(web_app, "_upload_limits", lambda: (1024 * 1024, 25_000_000))

    path = await web_app._save_upload(
        upload_file("photo.jpg", jpeg_bytes()),
        str(tmp_path),
        "01",
    )

    assert path.endswith(".jpg")
    assert worker_threads
    assert all(thread_id != event_loop_thread for thread_id in worker_threads)


def test_raw_staged_path_is_rejected_by_file_token_resolver(tmp_path, monkeypatch) -> None:
    """Catches an endpoint policy that would expose a raw staged upload."""
    raw_dir = tmp_path / "process-job"
    raw_dir.mkdir()
    raw_path = raw_dir / "01_raw.jpg"
    raw_path.write_bytes(b"raw upload bytes with private metadata")
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    cache_root = tmp_path / "cache-root"

    monkeypatch.setattr(web_app.settings, "l", str(processed_dir))
    monkeypatch.setattr(web_app.settings, "AC", str(cache_root))

    with pytest.raises(HTTPException) as error:
        web_app._path_from_file_token(web_app._file_token(str(raw_path)))

    assert error.value.status_code == 403


def test_staging_validator_rejects_image_over_pixel_limit(tmp_path) -> None:
    """Catches a moved image validator that no longer enforces its pixel ceiling."""
    path = tmp_path / "large.jpg"
    path.write_bytes(jpeg_bytes())

    with pytest.raises(HTTPException) as error:
        validate_image_file(str(path), "large.jpg", max_pixels=1)

    assert error.value.status_code == 413


def test_staging_validator_rejects_html_disguised_as_jpeg(tmp_path) -> None:
    """Catches a signature validator that accepts executable HTML as an image."""
    path = tmp_path / "payload.jpg"
    path.write_bytes(b"<!doctype html><script>alert(1)</script>")

    with pytest.raises(HTTPException) as error:
        validate_upload_signature(str(path), "payload.jpg")

    assert error.value.status_code == 400


def test_staging_scanner_reports_disabled_without_starting_process(tmp_path) -> None:
    """Catches a staging scanner that launches Defender despite being disabled."""
    path = tmp_path / "photo.jpg"
    path.write_bytes(jpeg_bytes())

    result = scan_uploaded_file(
        str(path),
        enabled=False,
        scanner_executable="C:/missing/MpCmdRun.exe",
        timeout_seconds=120,
    )

    assert result == {"enabled": False, "scanned": False, "scanner": "", "elapsed_ms": 0}


def test_cleanup_refuses_directory_outside_managed_root(tmp_path) -> None:
    """Catches cleanup that could delete a directory it does not own."""
    managed = tmp_path / "managed"
    managed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    assert cleanup_job_directory(str(outside), managed_root=str(managed)) is False
    assert outside.exists()


def test_expired_cleanup_skips_active_and_non_job_directories(tmp_path) -> None:
    """Catches TTL cleanup that removes active staging or unrelated siblings."""
    managed = tmp_path / "managed"
    managed.mkdir()
    expired = managed / "job-expired"
    active = managed / "job-active"
    unrelated = managed / "upload-cache"
    for directory in (expired, active, unrelated):
        directory.mkdir()
    old = time.time() - 25 * 60 * 60
    for directory in (expired, active, unrelated):
        os.utime(directory, (old, old))

    removed = cleanup_expired_job_directories(
        managed_root=str(managed),
        prefix="job-",
        max_age_seconds=24 * 60 * 60,
        active_paths={str(active)},
    )

    assert removed == 1
    assert not expired.exists()
    assert active.exists()
    assert unrelated.exists()
