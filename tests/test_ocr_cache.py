from picsyncra.services.image_dimensions import (
    ImageOcrDiagnostics,
    OcrDiagnosticCandidate,
)
from picsyncra.services.ocr_cache import (
    collect_image_values,
    enqueue_ocr_fast_image_job,
    image_content_hash,
    restore_crop_bbox,
)
from picsyncra.services.ocr_cache import enqueue_ocr_crop_jobs
from picsyncra.sqlite_store import SqliteStore


def test_collect_image_values_persists_only_numeric_candidates(tmp_path):
    image = tmp_path / "slot.png"
    image.write_bytes(b"image-content")
    store = SqliteStore(str(tmp_path / "ocr.sqlite"))
    diagnostics = ImageOcrDiagnostics(
        available=True,
        dimensions={},
        candidates=[
            OcrDiagnosticCandidate("120/140", 0.91, (1, 2, 30, 20), None, "120?140", True),
            OcrDiagnosticCandidate("tekst", 0.98, (2, 4, 20, 18), None, "", False),
        ],
    )

    result = collect_image_values(str(image), store=store, analyze=lambda _path: diagnostics)

    cached = store.get_ocr_scan(result.image_hash)
    assert result.state == "completed"
    assert cached is not None
    assert cached["state"] == "completed"
    assert cached["values"] == [
        {
            "text": "120/140",
            "comparison": "120?140",
            "confidence": 0.91,
            "bbox": [1, 2, 30, 20],
        }
    ]


def test_collect_image_values_reuses_completed_hash_without_new_ocr(tmp_path):
    image = tmp_path / "slot.png"
    image.write_bytes(b"image-content")
    store = SqliteStore(str(tmp_path / "ocr.sqlite"))
    first = collect_image_values(
        str(image),
        store=store,
        analyze=lambda _path: ImageOcrDiagnostics(True, {}, []),
    )

    second = collect_image_values(
        str(image),
        store=store,
        analyze=lambda _path: (_ for _ in ()).throw(AssertionError("OCR should not run")),
    )

    assert second.image_hash == first.image_hash
    assert second.reused is True


def test_enqueue_ocr_crop_jobs_persists_a_real_crop_for_each_numeric_value(tmp_path):
    from PIL import Image

    image = tmp_path / "slot.png"
    Image.new("RGB", (80, 60), "white").save(image)
    store = SqliteStore(str(tmp_path / "ocr.sqlite"))
    diagnostics = ImageOcrDiagnostics(
        available=True,
        dimensions={},
        candidates=[
            OcrDiagnosticCandidate("120/140", 0.91, (10, 12, 40, 30), None, "120?140", True),
            OcrDiagnosticCandidate("4", 0.93, (0, 0, 4, 5), None, "4", True),
            OcrDiagnosticCandidate("tekst", 0.98, (42, 12, 70, 30), None, "", False),
        ],
    )

    job_ids = enqueue_ocr_crop_jobs(
        str(image),
        image_hash="a" * 64,
        diagnostics=diagnostics,
        store=store,
        crop_dir=str(tmp_path / "ocr-crops"),
    )

    jobs = store.list_ocr_crop_jobs()
    assert len(job_ids) == 2
    assert jobs[0]["image_hash"] == "a" * 64
    assert jobs[0]["bbox"] == [2, 4, 48, 38]
    assert jobs[1]["bbox"] == [0, 0, 12, 13]
    with Image.open(tmp_path / "ocr-crops" / f"{job_ids[0]}.png") as crop:
        assert crop.size == (184, 136)
    with Image.open(tmp_path / "ocr-crops" / f"{job_ids[1]}.png") as crop:
        assert crop.size == (48, 52)


def test_enqueue_ocr_crop_jobs_respects_the_accurate_confidence_threshold(tmp_path):
    from PIL import Image

    image = tmp_path / "slot.png"
    Image.new("RGB", (100, 80), "white").save(image)
    diagnostics = ImageOcrDiagnostics(
        available=True,
        dimensions={},
        candidates=[
            OcrDiagnosticCandidate("99", 0.99, (10, 12, 30, 28), None, "99", True),
            OcrDiagnosticCandidate("95", 0.95, (40, 30, 60, 48), None, "95", True),
        ],
    )
    store = SqliteStore(str(tmp_path / "ocr.sqlite"))

    job_ids = enqueue_ocr_crop_jobs(
        str(image),
        image_hash="a" * 64,
        diagnostics=diagnostics,
        store=store,
        crop_dir=str(tmp_path / "ocr-crops"),
        accurate_confidence_threshold=95,
    )

    assert len(job_ids) == 1
    assert store.list_ocr_crop_jobs()[0]["bbox"] == [32, 22, 68, 56]


def test_fast_ocr_queue_job_keeps_the_full_image_before_its_crops(tmp_path):
    from PIL import Image

    image = tmp_path / "slot.png"
    Image.new("RGB", (80, 60), "white").save(image)
    store = SqliteStore(str(tmp_path / "ocr.sqlite"))

    fast_job_id = enqueue_ocr_fast_image_job(
        str(image),
        image_hash="f" * 64,
        store=store,
        crop_dir=str(tmp_path / "ocr-crops"),
    )
    crop_job_id = store.enqueue_ocr_crop_job(
        {
            "id": "accurate-crop",
            "image_hash": "f" * 64,
            "bbox": [10, 12, 40, 30],
            "kind": "accurate",
        }
    )

    jobs = store.list_ocr_crop_jobs()
    assert [job["id"] for job in jobs] == [fast_job_id, crop_job_id]
    assert jobs[0]["kind"] == "fast"
    assert jobs[0]["status"] == "pending"
    assert jobs[0]["bbox"] == [0, 0, 80, 60]
    assert jobs[0]["source_path"] == str(image)
    assert (tmp_path / "ocr-crops" / f"{fast_job_id}.png").is_file()
    assert jobs[1]["kind"] == "accurate"


def test_collect_image_values_wraps_fast_ocr_with_queue_stage_callbacks(tmp_path):
    image = tmp_path / "slot.png"
    image.write_bytes(b"image-content")
    store = SqliteStore(str(tmp_path / "ocr.sqlite"))
    expected_hash = image_content_hash(str(image))
    events = []
    diagnostics = ImageOcrDiagnostics(
        available=True,
        dimensions={},
        candidates=[OcrDiagnosticCandidate("23,4", 0.97, (1, 2, 30, 20), None, "23.4", True)],
    )

    def start_fast_scan(image_hash):
        events.append(("started", image_hash))
        return "fast-stage"

    def analyze(_path):
        assert events == [("started", expected_hash)]
        return diagnostics

    def finish_fast_scan(stage_id, values, state):
        events.append(("finished", stage_id, values, state))

    collect_image_values(
        str(image),
        store=store,
        analyze=analyze,
        start_fast_scan=start_fast_scan,
        finish_fast_scan=finish_fast_scan,
    )

    assert events == [
        ("started", expected_hash),
        (
            "finished",
            "fast-stage",
            [{"text": "23,4", "comparison": "23.4", "confidence": 0.97, "bbox": [1, 2, 30, 20]}],
            "completed",
        ),
    ]


def test_collect_image_values_passes_fresh_diagnostics_to_crop_queue_callback(tmp_path):
    image = tmp_path / "slot.png"
    image.write_bytes(b"image-content")
    store = SqliteStore(str(tmp_path / "ocr.sqlite"))
    diagnostics = ImageOcrDiagnostics(True, {}, [])
    queued = []

    collect_image_values(
        str(image),
        store=store,
        analyze=lambda _path: diagnostics,
        enqueue_crops=lambda image_hash, result: queued.append((image_hash, result)),
    )

    assert queued == [(image_content_hash(str(image)), diagnostics)]


def test_restore_crop_bbox_maps_upscaled_refinement_coordinates_to_source_image():
    assert restore_crop_bbox(
        [4, 8, 80, 40],
        [10, 12, 40, 30],
    ) == [11, 14, 30, 22]
