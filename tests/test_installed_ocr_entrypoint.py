"""The OCR executable translates its existing pipeline result into IPC diagnostics."""

from __future__ import annotations

from picsyncra.installation.ocr_entrypoint import run_ocr_job
from picsyncra.services.image_dimensions import OcrTextBox
from picsyncra.services.ocr_pipeline import OcrPipelineRegion, OcrPipelineReport


def test_ocr_entrypoint_returns_the_existing_pipeline_diagnostics_shape() -> None:
    """Catches a separate runtime returning a result incompatible with WEB progress."""

    report = OcrPipelineReport(
        regions=(),
        all_boxes=(OcrTextBox("32,8", 0.93, (1, 2, 30, 20)),),
        total_elapsed_ms=17,
    )
    received: dict[str, object] = {}

    result = run_ocr_job(
        {
            "kind": "job",
            "run_id": "run-1",
            "path": "C:/work/image.png",
            "work_root": "C:/work",
            "profile_ids": ["fast"],
        },
        pipeline=lambda path, *, profile_ids: received.update(
            {"path": path, "profile_ids": profile_ids}
        )
        or report,
    )

    assert received == {"path": "C:/work/image.png", "profile_ids": ["fast"]}
    assert result["available"] is True
    assert result["candidates"] == [
        {
            "text": "32,8",
            "confidence": 0.93,
            "bbox": [1, 2, 30, 20],
            "dimension": None,
            "value": "32.8",
            "accepted": True,
            "reason": "Wykryto wartosc liczbowa.",
            "selected": False,
        }
    ]
    assert result["timings_ms"] == {"total": 17}


def test_ocr_entrypoint_preserves_pipeline_regions_for_the_existing_web_client() -> None:
    """Catches installed OCR dropping the detailed fast/accurate pipeline result."""

    report = OcrPipelineReport(
        regions=(
            OcrPipelineRegion(
                region_id="region-1",
                fast_box=OcrTextBox("32,8", 0.93, (1, 2, 30, 20)),
                source_bbox=(1, 2, 30, 20),
                crop_bbox=(0, 0, 35, 25),
                accurate_boxes=(OcrTextBox("32.8", 0.99, (2, 3, 28, 19)),),
                status="completed",
                reason="",
                fast_elapsed_ms=4,
                crop_elapsed_ms=2,
                accurate_elapsed_ms=8,
            ),
        ),
        all_boxes=(),
        total_elapsed_ms=17,
    )

    result = run_ocr_job(
        {"path": "C:/work/image.png", "profile_ids": ["fast", "accurate"]},
        pipeline=lambda _path, *, profile_ids: report,
    )

    assert result["regions"] == [
        {
            "region_id": "region-1",
            "fast": {
                "text": "32,8",
                "value": "32.8",
                "confidence": 0.93,
                "bbox": [1, 2, 30, 20],
            },
            "source_bbox": [1, 2, 30, 20],
            "crop_bbox": [0, 0, 35, 25],
            "accurate": [
                {
                    "text": "32.8",
                    "value": "32.8",
                    "confidence": 0.99,
                    "bbox": [2, 3, 28, 19],
                }
            ],
            "status": "completed",
            "reason": "",
            "timings_ms": {"fast": 4, "crop": 2, "accurate": 8},
        }
    ]
