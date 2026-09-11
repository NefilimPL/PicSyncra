"""Deterministic responsiveness benchmark for queued image processing."""

from __future__ import annotations

import math
from pathlib import Path
import threading
import time
import tracemalloc
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from picsyncra.image_pipeline import ImagePipelineOptions, process_image
from picsyncra.web import app as web_app
from picsyncra.web.process_queue import ProcessQueueService, QueueLimits


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _write_representative_images(directory: Path) -> list[Path]:
    sources: list[Path] = []
    for index in range(26):
        width = 480 + (index % 4) * 80
        height = 320 + (index % 3) * 80
        source = directory / f"slot-{index:02d}.jpg"
        Image.effect_noise((width, height), 80 + (index % 5) * 8).convert("RGB").save(
            source,
            format="JPEG",
            quality=95,
        )
        sources.append(source)
    return sources


@pytest.mark.performance
def test_queued_26_image_pipeline_keeps_health_responsive(
    tmp_path, monkeypatch
) -> None:
    """Catches image work returning to the API thread or unbounded JPEG re-encoding."""
    source_dir = tmp_path / "sources"
    output_dir = tmp_path / "output"
    job_root = tmp_path / "jobs"
    staging = job_root / "job-benchmark"
    source_dir.mkdir()
    output_dir.mkdir()
    staging.mkdir(parents=True)
    sources = _write_representative_images(source_dir)
    queue = ProcessQueueService(QueueLimits(workers=1, max_pending=8, max_per_owner=2))
    jobs: dict[str, dict[str, object]] = {}
    completions: dict[str, threading.Event] = {}
    started = threading.Event()
    encode_attempts: list[int] = []
    health_samples: list[float] = []
    queue_depth_samples: list[int] = []
    form = web_app._ProcessFormSnapshot(temp_dir=str(staging))

    def process(**_kwargs):
        started.set()
        for index, source in enumerate(sources):
            result = process_image(
                str(source),
                str(output_dir / f"processed-{index:02d}.jpg"),
                ImagePipelineOptions(
                    target_format="JPEG",
                    max_dimensions=(640, 640),
                    compress_enabled=True,
                    compress_quality=92,
                    max_bytes=50_000,
                ),
            )
            encode_attempts.append(result.encode_attempts)
            time.sleep(0.005)
        return {
            "timing": {"stages": []},
            "ftp": {},
            "sql": {},
            "local_delete": {},
            "skipped_slots": [],
        }

    monkeypatch.setattr(web_app, "_PROCESS_JOB_ROOT", job_root)
    monkeypatch.setattr(web_app, "_PROCESS_QUEUE", queue)
    monkeypatch.setattr(web_app, "_PROCESS_JOBS", jobs)
    monkeypatch.setattr(web_app, "_PROCESS_JOB_COMPLETIONS", completions)
    tracemalloc.start()
    try:
        with (
            patch.object(web_app, "_process_upload_snapshot", side_effect=process),
            patch.object(web_app, "record_job"),
            patch.object(web_app, "emit_event"),
            patch.object(web_app, "notification_worker_health", return_value={"status": "online", "observed_at": ""}),
        ):
            queued = web_app._queue_process_job(
                username="benchmark",
                cache_scope="benchmark-scope",
                form=form,
                reservation=queue.reserve("benchmark-scope"),
            )
            job_id = str(queued["job_id"])
            assert started.wait(timeout=5)

            client = TestClient(web_app.app)
            assert client.get("/api/health").status_code == 200
            while True:
                sample_started = time.perf_counter()
                response = client.get("/api/health")
                health_samples.append(time.perf_counter() - sample_started)
                assert response.status_code == 200
                queue_depth_samples.append(web_app._active_process_jobs_snapshot()["active_count"])
                if completions[job_id].wait(timeout=0.01):
                    break

        _current, peak_bytes = tracemalloc.get_traced_memory()
        health_p95 = _p95(health_samples)

        assert health_p95 < 0.250
        assert peak_bytes > 0
        assert max(queue_depth_samples) <= 8
        assert len(encode_attempts) == 26
        assert all(attempts <= 6 for attempts in encode_attempts)
        assert jobs[job_id]["status"] == "completed"
        assert not staging.exists()
    finally:
        tracemalloc.stop()
        queue.shutdown()
