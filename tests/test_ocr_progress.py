from picsyncra.services.ocr_progress import OcrProgressRegistry
from picsyncra.sqlite_store import SqliteStore


def test_progress_snapshot_returns_only_events_after_requested_sequence():
    registry = OcrProgressRegistry(event_limit=10)
    run_id = registry.create_run(kind="test", job_id=None)
    registry.publish(run_id, "stage_started", stage="fast_full_image")
    registry.publish(run_id, "candidate_regions", regions=[{"bbox": [1, 2, 3, 4]}])

    snapshot = registry.snapshot(run_id, after_sequence=1)

    assert snapshot.state == "running"
    assert snapshot.latest_sequence == 2
    assert [(event.sequence, event.kind) for event in snapshot.events] == [
        (2, "candidate_regions")
    ]


def test_progress_registry_keeps_only_the_latest_bounded_events():
    registry = OcrProgressRegistry(event_limit=2)
    run_id = registry.create_run(kind="test", job_id=None)
    registry.publish(run_id, "stage_started", stage="fast_full_image")
    registry.publish(run_id, "candidate_regions", regions=[])
    registry.publish(run_id, "stage_finished", stage="fast_full_image")

    snapshot = registry.snapshot(run_id)

    assert [event.sequence for event in snapshot.events] == [2, 3]


def test_cancel_request_is_visible_to_safe_boundary_code_and_final_snapshot():
    registry = OcrProgressRegistry(event_limit=10)
    run_id = registry.create_run(kind="queue", job_id="ocr-1")

    registry.request_cancel(run_id)
    registry.finalize(run_id, state="cancelled")

    assert registry.is_cancel_requested(run_id) is True
    assert registry.snapshot(run_id).state == "cancelled"


def test_prune_expired_test_runs_keeps_queue_run_for_recovery():
    now = [100.0]
    registry = OcrProgressRegistry(event_limit=10, clock=lambda: now[0])
    test_run = registry.create_run(kind="test", job_id=None)
    queue_run = registry.create_run(kind="queue", job_id="ocr-1")

    now[0] = 1_001.0

    assert registry.prune_expired_test_runs(ttl_seconds=900) == 1
    assert registry.snapshot(queue_run).state == "running"
    try:
        registry.snapshot(test_run)
    except KeyError:
        pass
    else:
        raise AssertionError("expired test run should be removed")


def test_sqlite_store_persists_a_queue_progress_event_without_changing_crop_job_rows(tmp_path):
    store = SqliteStore(str(tmp_path / "ocr.sqlite"))
    store.enqueue_ocr_crop_job(
        {
            "id": "ocr-existing",
            "image_hash": "a" * 64,
            "bbox": [1, 2, 3, 4],
            "thumbnail_path": "",
        }
    )

    store.create_ocr_progress_run("run-1", kind="queue", job_id="ocr-existing")
    store.append_ocr_progress_event(
        "run-1", 1, "stage_started", {"stage": "accurate_crop"}
    )

    assert store.list_ocr_progress_events("run-1", after_sequence=0) == [
        {
            "sequence": 1,
            "kind": "stage_started",
            "payload": {"stage": "accurate_crop"},
        }
    ]
    assert store.list_ocr_crop_jobs()[0]["id"] == "ocr-existing"
