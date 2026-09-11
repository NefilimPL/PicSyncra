from PIL import Image

from picsyncra.services.image_dimensions import (
    ImageOcrDiagnostics,
    OcrDiagnosticCandidate,
)
from picsyncra.services.ocr_cache import enqueue_ocr_fast_image_job
from picsyncra.services.ocr_slot_queue import process_slot_ocr_queue_job
from picsyncra.sqlite_store import SqliteStore


def test_fast_slot_queue_job_scans_original_once_then_queues_only_eligible_crops(tmp_path):
    image = tmp_path / "slot.png"
    Image.new("RGB", (80, 60), "white").save(image)
    store = SqliteStore(str(tmp_path / "ocr.sqlite"))
    store.upsert_ocr_scan("a" * 64, [], "queued")
    enqueue_ocr_fast_image_job(
        str(image),
        image_hash="a" * 64,
        store=store,
        crop_dir=str(tmp_path / "ocr-crops"),
    )
    job = store.claim_ocr_crop_job()
    assert job is not None
    diagnostics = ImageOcrDiagnostics(
        available=True,
        dimensions={},
        candidates=[
            OcrDiagnosticCandidate("97", 0.97, (10, 12, 30, 28), None, "97", True),
            OcrDiagnosticCandidate("99", 0.99, (40, 30, 60, 48), None, "99", True),
        ],
    )
    calls = []

    def analyze(path, profile_ids):
        scan = store.get_ocr_scan("a" * 64)
        assert scan is not None
        assert scan["state"] == "scanning"
        calls.append((path, profile_ids))
        return diagnostics

    def enqueue_crops(path, *, image_hash, diagnostics, store, crop_dir, accurate_confidence_threshold):
        assert path == str(image)
        assert image_hash == "a" * 64
        assert diagnostics.candidates[0].value == "97"
        assert accurate_confidence_threshold == 98
        return ["accurate-97"]

    result = process_slot_ocr_queue_job(
        job,
        store=store,
        analyze=analyze,
        enqueue_crops=enqueue_crops,
        crop_dir=str(tmp_path / "ocr-crops"),
        settings={"model_profiles": ["fast", "accurate"], "accurate_confidence_threshold": 98},
    )

    assert calls == [(str(image), ["fast"])]
    assert result.state == "refining"
    assert result.created_crop_ids == ["accurate-97"]
    assert store.list_ocr_crop_jobs()[0]["status"] == "completed"
    scan = store.get_ocr_scan("a" * 64)
    assert scan is not None
    assert scan["state"] == "refining"
    assert scan["values"] == [
        {"text": "97", "comparison": "97", "confidence": 0.97, "bbox": [10, 12, 30, 28]},
        {"text": "99", "comparison": "99", "confidence": 0.99, "bbox": [40, 30, 60, 48]},
    ]


def test_accurate_slot_jobs_keep_the_scan_refining_until_the_last_crop_finishes(tmp_path):
    image = tmp_path / "crop.png"
    Image.new("RGB", (80, 60), "white").save(image)
    store = SqliteStore(str(tmp_path / "ocr.sqlite"))
    image_hash = "b" * 64
    store.upsert_ocr_scan(
        image_hash,
        [{"text": "97", "comparison": "97", "confidence": 0.97, "bbox": [10, 12, 30, 28]}],
        "refining",
    )
    for identifier in ("accurate-1", "accurate-2"):
        store.enqueue_ocr_crop_job(
            {
                "id": identifier,
                "image_hash": image_hash,
                "bbox": [30, 20, 60, 50],
                "thumbnail_path": str(image),
                "kind": "accurate",
            }
        )
    diagnostics = ImageOcrDiagnostics(
        available=True,
        dimensions={},
        candidates=[
            OcrDiagnosticCandidate("123", 0.96, (2, 3, 12, 13), None, "123", True),
        ],
    )

    def analyze(_path, profile_ids):
        assert profile_ids == ["accurate"]
        return diagnostics

    first = store.claim_ocr_crop_job()
    assert first is not None
    first_result = process_slot_ocr_queue_job(
        first,
        store=store,
        analyze=analyze,
        enqueue_crops=lambda *_args, **_kwargs: [],
        crop_dir=str(tmp_path / "ocr-crops"),
        settings={"model_profiles": ["fast", "accurate"]},
    )

    assert first_result.state == "refining"
    first_scan = store.get_ocr_scan(image_hash)
    assert first_scan is not None
    assert first_scan["state"] == "refining"
    assert first_scan["values"][-1]["bbox"] == [30, 21, 33, 23]

    second = store.claim_ocr_crop_job()
    assert second is not None
    second_result = process_slot_ocr_queue_job(
        second,
        store=store,
        analyze=analyze,
        enqueue_crops=lambda *_args, **_kwargs: [],
        crop_dir=str(tmp_path / "ocr-crops"),
        settings={"model_profiles": ["fast", "accurate"]},
    )

    assert second_result.state == "completed"
    assert store.get_ocr_scan(image_hash)["state"] == "completed"
