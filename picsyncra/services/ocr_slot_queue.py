"""Process persisted slot OCR stages through the shared OCR worker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .image_dimensions import ImageOcrDiagnostics
from .ocr_cache import restore_crop_bbox


class OcrSlotQueueStore(Protocol):
    def complete_ocr_crop_job(self, job_id: str, values: list[dict[str, object]]) -> None: ...

    def has_active_ocr_crop_jobs(self, image_hash: str) -> bool: ...

    def get_ocr_scan(self, image_hash: str) -> dict[str, object] | None: ...

    def upsert_ocr_scan(
        self, image_hash: str, values: list[dict[str, object]], state: str
    ) -> None: ...


@dataclass(frozen=True)
class OcrSlotQueueResult:
    state: str
    created_crop_ids: list[str]


def _numeric_values(
    diagnostics: ImageOcrDiagnostics,
    *,
    crop_bbox: list[object] | None = None,
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    source_bbox = list(crop_bbox or [])
    for candidate in diagnostics.candidates:
        if not candidate.accepted or not str(candidate.value).strip():
            continue
        bbox = list(candidate.bbox)
        if len(source_bbox) == 4:
            bbox = restore_crop_bbox(bbox, source_bbox)
        values.append(
            {
                "text": str(candidate.text),
                "comparison": str(candidate.value),
                "confidence": float(candidate.confidence),
                "bbox": bbox,
            }
        )
    return values


def _threshold(settings: dict[str, object]) -> int:
    try:
        return max(0, min(100, int(settings.get("accurate_confidence_threshold", 99))))
    except (TypeError, ValueError):
        return 99


def process_slot_ocr_queue_job(
    job: dict[str, object],
    *,
    store: OcrSlotQueueStore,
    analyze: Callable[[str, list[object]], ImageOcrDiagnostics],
    enqueue_crops: Callable[..., list[str]],
    crop_dir: str,
    settings: dict[str, object],
) -> OcrSlotQueueResult:
    """Complete one fast-image or accurate-crop job without bypassing the worker."""

    job_id = str(job.get("id") or "")
    image_hash = str(job.get("image_hash") or "")
    kind = str(job.get("kind") or "accurate").strip().lower()
    if not job_id or not image_hash or kind not in {"fast", "accurate"}:
        raise ValueError("Niepoprawne zadanie OCR kolejki.")
    preview_path = str(job.get("thumbnail_path") or "")
    source_path = str(job.get("source_path") or preview_path)
    if not source_path:
        raise ValueError("Brak obrazu zrodlowego zadania OCR.")

    if kind == "fast":
        existing = store.get_ocr_scan(image_hash)
        current_values = list(existing.get("values") or []) if isinstance(existing, dict) else []
        store.upsert_ocr_scan(image_hash, current_values, "scanning")
    diagnostics = analyze(source_path, [kind])
    if not diagnostics.available:
        raise RuntimeError(diagnostics.message or "Lokalny OCR nie zakonczyl skanowania.")

    if kind == "fast":
        values = _numeric_values(diagnostics)
        store.complete_ocr_crop_job(job_id, values)
        profiles = {str(profile).strip().lower() for profile in settings.get("model_profiles", [])}
        crop_ids: list[str] = []
        if "accurate" in profiles:
            crop_ids = list(
                enqueue_crops(
                    source_path,
                    image_hash=image_hash,
                    diagnostics=diagnostics,
                    store=store,
                    crop_dir=crop_dir,
                    accurate_confidence_threshold=_threshold(settings),
                )
            )
        state = "refining" if crop_ids else "completed"
        store.upsert_ocr_scan(image_hash, values, state)
        return OcrSlotQueueResult(state=state, created_crop_ids=crop_ids)

    values = _numeric_values(diagnostics, crop_bbox=list(job.get("bbox") or []))
    store.complete_ocr_crop_job(job_id, values)
    existing = store.get_ocr_scan(image_hash)
    combined = list(existing.get("values") or []) if isinstance(existing, dict) else []
    state = "refining" if store.has_active_ocr_crop_jobs(image_hash) else "completed"
    store.upsert_ocr_scan(image_hash, combined + values, state)
    return OcrSlotQueueResult(state=state, created_crop_ids=[])
