import time

from picsyncra.services.image_dimensions import OcrTextBox, diagnostics_for_boxes
from picsyncra.services.ocr_pipeline import OcrPipelineRegion, OcrPipelineReport
from picsyncra.services.ocr_worker_process import OcrWorkerProcess, _serialize_report
from picsyncra.services.windows_job_limits import WindowsJobLimits


class _FakeWindowsJobApi:
    def __init__(self) -> None:
        self.assigned: list[tuple[int, int]] = []
        self.cpu_rates: list[tuple[int, int]] = []
        self.closed: list[int] = []

    def create_job(self) -> int:
        return 101

    def assign_process(self, job_handle: int, pid: int) -> None:
        self.assigned.append((job_handle, pid))

    def set_cpu_hard_cap(self, job_handle: int, cpu_rate: int) -> None:
        self.cpu_rates.append((job_handle, cpu_rate))

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)


def test_windows_job_limits_assigns_worker_and_applies_continuous_cpu_hard_cap():
    api = _FakeWindowsJobApi()
    limits = WindowsJobLimits(api=api)

    capability = limits.apply_to_process(pid=4321, cpu_percent=35)

    assert capability.available is True
    assert capability.cpu_percent == 35
    assert api.assigned == [(101, 4321)]
    assert api.cpu_rates == [(101, 3_500)]


def test_windows_job_limits_reports_unavailable_without_breaking_ocr_when_api_fails():
    class _FailingApi:
        def create_job(self) -> int:
            raise OSError("unsupported")

    capability = WindowsJobLimits(api=_FailingApi()).apply_to_process(
        pid=4321, cpu_percent=35
    )

    assert capability.available is False
    assert "unsupported" in capability.message


def test_windows_job_limits_keeps_handle_until_worker_shutdown():
    api = _FakeWindowsJobApi()
    limits = WindowsJobLimits(api=api)
    limits.apply_to_process(pid=4321, cpu_percent=35)

    limits.close()

    assert api.closed == [101]


def test_worker_process_reports_ready_and_stops_without_loading_an_ocr_model():
    worker = OcrWorkerProcess(cpu_percent=35)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        events: list[dict[str, object]] = []
        while time.monotonic() < deadline and not events:
            events.extend(worker.poll_events())
            time.sleep(0.02)
    finally:
        worker.stop(timeout=5)

    assert events[0]["kind"] == "ready"
    assert isinstance(events[0]["pid"], int)


def test_worker_process_forwards_a_serializable_job_result():
    worker = OcrWorkerProcess(cpu_percent=35)
    worker.start()
    try:
        worker.submit(run_id="run-1", path="missing-image.png", profile_ids=["fast"])
        deadline = time.monotonic() + 5
        events: list[dict[str, object]] = []
        while time.monotonic() < deadline:
            events.extend(worker.poll_events())
            if any(event["kind"] == "result" for event in events):
                break
            time.sleep(0.02)
    finally:
        worker.stop(timeout=5)

    started = next(event for event in events if event["kind"] == "stage_started")
    assert isinstance(started["worker_pid"], int)
    result = next(event for event in events if event["kind"] == "result")
    assert result["run_id"] == "run-1"
    assert result["diagnostics"]["available"] is False


def test_worker_serializes_region_pairing_and_timings():
    fast = OcrTextBox("32,8", 0.93, (10, 10, 40, 25))
    accurate = OcrTextBox("32.8", 0.98, (11, 11, 41, 26))
    report = OcrPipelineReport(
        regions=(
            OcrPipelineRegion(
                region_id="region-1",
                fast_box=fast,
                source_bbox=(10, 10, 40, 25),
                crop_bbox=(2, 2, 48, 33),
                accurate_boxes=(accurate,),
                status="completed",
                reason="",
                fast_elapsed_ms=14,
                crop_elapsed_ms=3,
                accurate_elapsed_ms=28,
            ),
        ),
        all_boxes=(fast, accurate),
        total_elapsed_ms=45,
    )

    payload = _serialize_report(report, diagnostics_for_boxes(report.all_boxes))

    assert payload["regions"] == [
        {
            "region_id": "region-1",
            "fast": {
                "text": "32,8",
                "value": "32.8",
                "confidence": 0.93,
                "bbox": [10, 10, 40, 25],
            },
            "source_bbox": [10, 10, 40, 25],
            "crop_bbox": [2, 2, 48, 33],
            "accurate": [
                {
                    "text": "32.8",
                    "value": "32.8",
                    "confidence": 0.98,
                    "bbox": [11, 11, 41, 26],
                }
            ],
            "status": "completed",
            "reason": "",
            "timings_ms": {"fast": 14, "crop": 3, "accurate": 28},
        }
    ]
    assert payload["timings_ms"] == {"total": 45}
    assert payload["candidates"][0]["value"] == "32.8"
