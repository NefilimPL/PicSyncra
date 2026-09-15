"""Standalone entry point for the separately bundled OCR runtime."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import sys

from .ocr_runtime import serve_ocr_runtime
from ..services.image_dimensions import diagnostics_for_boxes
from ..services.ocr_pipeline import OcrPipelineReport, run_ocr_pipeline_report
from ..services.ocr_values import comparison_key


def _serialize_box(box: object) -> dict[str, object]:
    return {
        "text": str(getattr(box, "text")),
        "value": comparison_key(str(getattr(box, "text"))),
        "confidence": float(getattr(box, "confidence")),
        "bbox": [int(value) for value in getattr(box, "bbox")],
    }


def run_ocr_job(
    job: Mapping[str, object],
    *,
    pipeline: Callable[..., OcrPipelineReport] = run_ocr_pipeline_report,
) -> dict[str, object]:
    """Run the existing pipeline while preserving the WEB diagnostics schema."""

    report = pipeline(str(job["path"]), profile_ids=list(job["profile_ids"]))
    diagnostics = diagnostics_for_boxes(report.all_boxes)
    return {
        "available": diagnostics.available,
        "dimensions": dict(diagnostics.dimensions),
        "message": diagnostics.message,
        "candidates": [
            {
                "text": candidate.text,
                "confidence": candidate.confidence,
                "bbox": list(candidate.bbox),
                "dimension": candidate.dimension,
                "value": candidate.value,
                "accepted": candidate.accepted,
                "reason": candidate.reason,
                "selected": candidate.selected,
            }
            for candidate in diagnostics.candidates
        ],
        "regions": [
            {
                "region_id": region.region_id,
                "fast": _serialize_box(region.fast_box),
                "source_bbox": list(region.source_bbox),
                "crop_bbox": list(region.crop_bbox) if region.crop_bbox else None,
                "accurate": [_serialize_box(box) for box in region.accurate_boxes],
                "status": region.status,
                "reason": region.reason,
                "timings_ms": {
                    "fast": region.fast_elapsed_ms,
                    "crop": region.crop_elapsed_ms,
                    "accurate": region.accurate_elapsed_ms,
                },
            }
            for region in report.regions
        ],
        "timings_ms": {"total": report.total_elapsed_ms},
    }


def main(argv: list[str] | None = None) -> int:
    """Serve one component identity from explicit non-secret build metadata."""

    parser = argparse.ArgumentParser(prog="PicSyncra-OCR")
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--component-id", required=True)
    args = parser.parse_args(argv)
    return serve_ocr_runtime(
        sys.stdin,
        sys.stdout,
        build_id=args.build_id,
        component_id=args.component_id,
        run_job=run_ocr_job,
    )


__all__ = ["main", "run_ocr_job"]
