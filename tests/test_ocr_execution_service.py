from picsyncra.services.ocr_execution_service import OcrExecutionService
from picsyncra.services.ocr_progress import OcrProgressRegistry
from picsyncra.services.ocr_resource_policy import ResourceTelemetry


class _FakeWorker:
    def __init__(self) -> None:
        self.started = False
        self.alive = True
        self.exit_code: int | None = None
        self.submissions: list[dict[str, object]] = []
        self.events: list[dict[str, object]] = []
        self.cancelled: list[str] = []
        self.cpu_limits: list[int] = []
        self.telemetry = []

    def start(self) -> None:
        self.started = True

    def stop(self, **kwargs):
        self.alive = False

    def submit(self, **payload: object) -> None:
        self.submissions.append(payload)

    def poll_events(self) -> list[dict[str, object]]:
        events, self.events = self.events, []
        return events

    def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)

    def update_limits(self, *, cpu_percent: int) -> None:
        self.cpu_limits.append(cpu_percent)

    def update_telemetry(self, telemetry: ResourceTelemetry) -> None:
        self.telemetry.append(telemetry)

    def status(self) -> dict[str, object]:
        return {"pid": 4321, "alive": self.alive, "exit_code": self.exit_code}


def _telemetry(cpu: float = 10) -> ResourceTelemetry:
    return ResourceTelemetry(cpu, 2_000, 10_000, 10)


def test_first_installed_ocr_job_returns_and_can_be_polled_during_slow_start():
    import threading
    import time
    from picsyncra.installation.ocr_runtime import LazyInstalledOcrWorker
    entered, release = threading.Event(), threading.Event()
    target = _FakeWorker()
    def factory():
        entered.set(); assert release.wait(3); return target
    worker = LazyInstalledOcrWorker(factory)
    registry = OcrProgressRegistry()
    service = OcrExecutionService(worker=worker, registry=registry,
        settings=lambda: {'model_profiles': ['fast']}, telemetry=_telemetry)
    started = time.monotonic()
    run_id = service.submit_test(path='image.png')
    try:
        assert time.monotonic() - started < 0.3
        assert entered.wait(1)
        assert service.snapshot(run_id).state == 'running'
        service.cancel(run_id)
    finally: release.set()
    for _ in range(100):
        if registry.snapshot(run_id).state == 'cancelled': break
        time.sleep(0.01)
    assert target.submissions == []
    assert registry.snapshot(run_id).state == 'cancelled'


def test_failed_lazy_start_is_reported_to_polling_and_next_job_can_retry():
    import time
    from picsyncra.installation.ocr_runtime import LazyInstalledOcrWorker
    calls = []
    def factory():
        calls.append('verify')
        raise RuntimeError('OCR handshake timed out')
    registry = OcrProgressRegistry()
    service = OcrExecutionService(worker=LazyInstalledOcrWorker(factory), registry=registry,
        settings=lambda: {'model_profiles': ['fast']}, telemetry=_telemetry)
    for _ in range(2):
        run_id = service.submit_test(path='image.png')
        for _ in range(100):
            snapshot = service.snapshot(run_id)
            if snapshot.state == 'error': break
            time.sleep(0.01)
        assert snapshot.state == 'error' and snapshot.error == 'OCR handshake timed out'
    assert calls == ['verify', 'verify']


def test_lazy_retry_finishes_old_generation_and_preserves_new_job():
    import time
    from picsyncra.installation.ocr_runtime import LazyInstalledOcrWorker
    workers = [_FakeWorker(), _FakeWorker()]
    remaining = iter(workers)
    service = OcrExecutionService(worker=LazyInstalledOcrWorker(lambda: next(remaining)), registry=OcrProgressRegistry(),
        settings=lambda: {'model_profiles': ['fast']}, telemetry=_telemetry)
    first = service.submit_test(path='one.png')
    for _ in range(100):
        if workers[0].submissions: break
        time.sleep(0.01)
    workers[0].alive = False
    second = service.submit_test(path='two.png')
    for _ in range(100):
        if workers[1].submissions: break
        time.sleep(0.01)
    assert service.snapshot(first).state == 'error'
    assert service.snapshot(second).state == 'running'


def test_execution_service_submits_selected_profiles_and_forwards_live_events():
    worker = _FakeWorker()
    service = OcrExecutionService(
        worker=worker,
        registry=OcrProgressRegistry(),
        settings=lambda: {"model_profiles": ["accurate", "fast"], "pause_cpu_percent": 85},
        telemetry=lambda: _telemetry(),
    )
    service.start()

    run_id = service.submit_test(path="C:/cache/test.png")
    worker.events = [
        {"kind": "stage_started", "run_id": run_id, "stage": "fast_full_image"},
        {
            "kind": "result",
            "run_id": run_id,
            "diagnostics": {"available": True, "candidates": []},
        },
    ]
    service.pump()

    assert worker.started is True
    assert worker.submissions == [
        {
            "run_id": run_id,
            "path": "C:/cache/test.png",
            "profile_ids": ["accurate", "fast"],
            "resource_settings": {"model_profiles": ["accurate", "fast"], "pause_cpu_percent": 85},
        }
    ]
    assert worker.cpu_limits == [35]
    snapshot = service.snapshot(run_id)
    assert snapshot.state == "completed"
    assert [(event.kind, event.payload["stage"]) for event in snapshot.events[:2]] == [
        ("queued", "waiting_for_worker"),
        ("stage_started", "fast_full_image"),
    ]


def test_execution_service_pauses_tester_at_admission_gate_without_submitting_or_queueing():
    worker = _FakeWorker()
    service = OcrExecutionService(
        worker=worker,
        registry=OcrProgressRegistry(),
        settings=lambda: {"model_profiles": ["fast"], "pause_cpu_percent": 85},
        telemetry=lambda: _telemetry(cpu=90),
    )

    run_id = service.submit_test(path="C:/cache/test.png")

    assert worker.submissions == []
    snapshot = service.snapshot(run_id)
    assert snapshot.state == "paused"
    assert snapshot.events[-1].kind == "paused"


def test_execution_service_requests_safe_boundary_cancellation():
    worker = _FakeWorker()
    service = OcrExecutionService(
        worker=worker,
        registry=OcrProgressRegistry(),
        settings=lambda: {"model_profiles": ["fast"], "pause_cpu_percent": 85},
        telemetry=lambda: _telemetry(),
    )
    run_id = service.submit_test(path="C:/cache/test.png")

    service.cancel(run_id)

    assert worker.cancelled == [run_id]
    assert service.snapshot(run_id).cancel_requested is True


def test_execution_service_registers_worker_pid_from_ready_event():
    worker = _FakeWorker()
    registered: list[int] = []
    service = OcrExecutionService(
        worker=worker,
        registry=OcrProgressRegistry(),
        settings=lambda: {"model_profiles": ["fast"], "pause_cpu_percent": 85},
        telemetry=lambda: _telemetry(),
        on_worker_ready=registered.append,
    )
    worker.events = [{"kind": "ready", "pid": 4321}]

    service.pump()

    assert registered == [4321]


def test_execution_service_fails_a_run_when_the_ocr_worker_exits_before_it_starts():
    worker = _FakeWorker()
    worker.alive = False
    worker.exit_code = 23
    service = OcrExecutionService(
        worker=worker,
        registry=OcrProgressRegistry(),
        settings=lambda: {"model_profiles": ["fast"], "pause_cpu_percent": 85},
        telemetry=lambda: _telemetry(),
    )

    run_id = service.submit_test(path="C:/cache/test.png")

    snapshot = service.snapshot(run_id)

    assert snapshot.state == "error"
    assert snapshot.error == "Proces OCR zakonczyl sie przed rozpoczeciem zadania (kod 23)."


def test_execution_service_uses_the_same_worker_pipeline_for_background_job():
    worker = _FakeWorker()
    service = OcrExecutionService(
        worker=worker,
        registry=OcrProgressRegistry(),
        settings=lambda: {"model_profiles": ["fast"], "pause_cpu_percent": 85},
        telemetry=lambda: _telemetry(),
    )

    run_id = service.submit_queue(job_id="ocr-1", path="C:/cache/crop.png")

    assert worker.submissions[0]["run_id"] == run_id
    assert worker.submissions[0]["path"] == "C:/cache/crop.png"
    assert service.snapshot(run_id).kind == "queue"


def test_execution_service_can_limit_a_queue_job_to_the_fast_profile():
    worker = _FakeWorker()
    service = OcrExecutionService(
        worker=worker,
        registry=OcrProgressRegistry(),
        settings=lambda: {"model_profiles": ["fast", "accurate"], "pause_cpu_percent": 85},
        telemetry=lambda: _telemetry(),
    )

    service.submit_queue(
        job_id="ocr-full-image",
        path="C:/cache/slot.png",
        profile_ids=["fast"],
    )

    assert worker.submissions[0]["profile_ids"] == ["fast"]


def test_execution_service_keeps_ocr_in_maintenance_drain_and_cancels_it_when_forced():
    from picsyncra.installation.maintenance import MaintenanceGate

    worker = _FakeWorker()
    gate = MaintenanceGate()
    service = OcrExecutionService(
        worker=worker,
        registry=OcrProgressRegistry(),
        settings=lambda: {"model_profiles": ["fast"]},
        telemetry=lambda: _telemetry(),
        maintenance_gate=gate,
    )

    run_id = service.submit_test(path="C:/cache/test.png")
    assert gate.snapshot()["active_by_kind"] == {"ocr": 1}

    gate.begin("update-1", initiator_id="admin-1")
    gate.request_force_cancel()
    assert worker.cancelled == [run_id]

    worker.events = [{"kind": "result", "run_id": run_id, "diagnostics": {}}]
    service.pump()
    assert gate.snapshot()["active_tasks"] == 0
