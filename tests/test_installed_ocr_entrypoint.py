"""The OCR executable translates its existing pipeline result into IPC diagnostics."""

from __future__ import annotations

from picsyncra.installation.ocr_entrypoint import run_ocr_job
from picsyncra.services.image_dimensions import OcrTextBox
from picsyncra.services.ocr_pipeline import OcrPipelineReport


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
