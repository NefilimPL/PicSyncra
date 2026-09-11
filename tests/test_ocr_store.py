from picsyncra.sqlite_store import SqliteStore


def initialized_store(tmp_path):
    store = SqliteStore(str(tmp_path / "store.sqlite"))
    store.initialize()
    return store


def test_ocr_scan_survives_store_reopen(tmp_path):
    path = tmp_path / "store.sqlite"
    store = SqliteStore(str(path))
    store.initialize()
    store.upsert_ocr_scan(
        "a" * 64,
        [
            {
                "text": "120/140",
                "comparison": "120?140",
                "confidence": 0.91,
                "bbox": [1, 2, 3, 4],
            }
        ],
        "partial",
    )

    reopened = SqliteStore(str(path))
    reopened.initialize()

    assert reopened.get_ocr_scan("a" * 64)["values"][0]["comparison"] == "120?140"


def test_ocr_approval_requires_same_image_hash_set(tmp_path):
    store = initialized_store(tmp_path)
    store.record_ocr_approval("WIDTH", "120", ["hash-a"])

    assert store.has_ocr_approval("WIDTH", "120", ["hash-a"])
    assert not store.has_ocr_approval("WIDTH", "120", ["hash-b"])


def test_ocr_crop_job_is_claimed_once_and_completed(tmp_path):
    store = initialized_store(tmp_path)
    store.enqueue_ocr_crop_job(
        {"image_hash": "hash-a", "bbox": [1, 2, 30, 20], "thumbnail_path": "crop.png"}
    )

    job = store.claim_ocr_crop_job()

    assert job["image_hash"] == "hash-a"
    assert store.claim_ocr_crop_job() is None
    store.complete_ocr_crop_job(job["id"], [{"text": "120", "comparison": "120"}])
    assert store.list_ocr_crop_jobs()[0]["status"] == "completed"


def test_ocr_fast_image_job_is_claimed_by_background_worker(tmp_path):
    store = initialized_store(tmp_path)
    store.enqueue_ocr_crop_job(
        {
            "id": "fast-image",
            "image_hash": "hash-fast",
            "bbox": [0, 0, 800, 600],
            "thumbnail_path": "image.png",
            "kind": "fast",
        }
    )

    job = store.claim_ocr_crop_job()

    assert job is not None
    assert job["id"] == "fast-image"
    assert job["kind"] == "fast"
    assert job["status"] == "processing"


def test_ocr_crop_job_can_return_to_pending_when_user_activity_resumes(tmp_path):
    store = initialized_store(tmp_path)
    job_id = store.enqueue_ocr_crop_job({"image_hash": "a" * 64, "bbox": [1, 2, 3, 4]})

    claimed = store.claim_ocr_crop_job()
    store.requeue_ocr_crop_job(job_id)
    resumed = store.claim_ocr_crop_job()

    assert claimed is not None
    assert resumed is not None
    assert resumed["id"] == job_id


def test_ocr_crop_queue_purges_only_completed_jobs_before_cutoff(tmp_path):
    store = initialized_store(tmp_path)
    completed_id = store.enqueue_ocr_crop_job(
        {"id": "completed", "image_hash": "hash-completed", "thumbnail_path": "old.png"}
    )
    completed = store.claim_ocr_crop_job()
    assert completed is not None
    store.complete_ocr_crop_job(completed_id, [{"text": "20", "comparison": "20"}])
    with store.connection() as conn:
        conn.execute(
            "UPDATE ocr_crop_jobs SET updated_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00.000Z", completed_id),
        )

    store.enqueue_ocr_crop_job(
        {"id": "processing", "image_hash": "hash-processing", "thumbnail_path": "processing.png"}
    )
    processing = store.claim_ocr_crop_job()
    assert processing is not None
    store.enqueue_ocr_crop_job(
        {"id": "pending", "image_hash": "hash-pending", "thumbnail_path": "pending.png"}
    )

    assert store.purge_completed_ocr_crop_jobs("2026-08-25T10:00:00.000Z") == ["old.png"]
    assert [job["status"] for job in store.list_ocr_crop_jobs()] == ["processing", "pending"]


def test_ocr_crop_queue_cancels_only_pending_jobs_for_removed_image(tmp_path):
    store = initialized_store(tmp_path)
    store.enqueue_ocr_crop_job(
        {"id": "processing", "image_hash": "hash-a", "thumbnail_path": "processing.png"}
    )
    processing = store.claim_ocr_crop_job()
    assert processing is not None
    store.enqueue_ocr_crop_job(
        {"id": "pending", "image_hash": "hash-a", "thumbnail_path": "pending.png"}
    )
    store.enqueue_ocr_crop_job(
        {"id": "other", "image_hash": "hash-b", "thumbnail_path": "other.png"}
    )

    assert store.cancel_pending_ocr_crop_jobs("hash-a") == ["pending.png"]
    assert [job["id"] for job in store.list_ocr_crop_jobs()] == ["processing", "other"]
