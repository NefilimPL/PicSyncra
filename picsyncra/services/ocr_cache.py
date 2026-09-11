"""Persistent OCR-value collection for immutable image content."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable, Protocol
import uuid

from PIL import Image, ImageEnhance

from .image_dimensions import ImageOcrDiagnostics


class OcrScanStore(Protocol):
    def get_ocr_scan(self, image_hash: str) -> dict[str, object] | None: ...

    def upsert_ocr_scan(
        self, image_hash: str, values: list[dict[str, object]], state: str
    ) -> None: ...

    def enqueue_ocr_crop_job(self, payload: dict[str, object]) -> str: ...


@dataclass(frozen=True)
class OcrCacheResult:
    image_hash: str
    state: str
    reused: bool
    values: list[dict[str, object]]


def image_content_hash(path: str) -> str:
    """Hash image bytes in bounded chunks, independent from its slot or filename."""

    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def restore_crop_bbox(
    bbox: list[int] | tuple[int, int, int, int],
    crop_bbox: list[int] | tuple[int, int, int, int],
    *,
    upscale_factor: int = 4,
) -> list[int]:
    """Map a bounding box from an enlarged crop back to source-image pixels."""

    factor = max(1, int(upscale_factor))
    crop_left, crop_top, crop_right, crop_bottom = (int(value) for value in crop_bbox)
    left, top, right, bottom = (int(value) for value in bbox)
    restored = [
        crop_left + round(left / factor),
        crop_top + round(top / factor),
        crop_left + round(right / factor),
        crop_top + round(bottom / factor),
    ]
    return [
        max(crop_left, min(crop_right, restored[0])),
        max(crop_top, min(crop_bottom, restored[1])),
        max(crop_left, min(crop_right, restored[2])),
        max(crop_top, min(crop_bottom, restored[3])),
    ]


def collect_image_values(
    path: str,
    *,
    store: OcrScanStore,
    analyze: Callable[[str], ImageOcrDiagnostics],
    enqueue_crops: Callable[[str, ImageOcrDiagnostics], None] | None = None,
    start_fast_scan: Callable[[str], str | None] | None = None,
    finish_fast_scan: Callable[[str, list[dict[str, object]], str], None] | None = None,
) -> OcrCacheResult:
    """Run OCR once for new image content and persist every numeric candidate."""

    image_hash = image_content_hash(path)
    existing = store.get_ocr_scan(image_hash)
    if isinstance(existing, dict) and str(existing.get("state") or "") == "completed":
        values = list(existing.get("values") or [])
        return OcrCacheResult(image_hash, "completed", True, values)

    fast_stage_id = str(start_fast_scan(image_hash) or "") if start_fast_scan else ""
    values: list[dict[str, object]] = []
    state = "error"
    try:
        store.upsert_ocr_scan(image_hash, [], "scanning")
        diagnostics = analyze(path)
        if enqueue_crops is not None and diagnostics.available:
            enqueue_crops(image_hash, diagnostics)
        values = [
            {
                "text": str(candidate.text),
                "comparison": str(candidate.value),
                "confidence": float(candidate.confidence),
                "bbox": list(candidate.bbox),
            }
            for candidate in diagnostics.candidates
            if candidate.accepted and str(candidate.value).strip()
        ]
        state = "completed" if diagnostics.available else "error"
        store.upsert_ocr_scan(image_hash, values, state)
        return OcrCacheResult(image_hash, state, False, values)
    finally:
        if fast_stage_id and finish_fast_scan is not None:
            finish_fast_scan(fast_stage_id, values, state)


def enqueue_ocr_fast_image_job(
    path: str,
    *,
    image_hash: str,
    store: OcrScanStore,
    crop_dir: str,
) -> str:
    """Persist a bounded full-image preview while the fast OCR stage runs."""

    target_dir = Path(crop_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    job_id = f"ocr-{uuid.uuid4().hex}"
    preview_path = target_dir / f"{job_id}.png"
    with Image.open(path) as source:
        source = source.convert("RGB")
        width, height = source.size
        preview = source.copy()
        preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        preview.save(preview_path, format="PNG", optimize=True)
    store.enqueue_ocr_crop_job(
        {
            "id": job_id,
            "image_hash": image_hash,
            "bbox": [0, 0, width, height],
            "thumbnail_path": str(preview_path),
            "source_path": str(path),
            "kind": "fast",
            "status": "pending",
        }
    )
    return job_id


def enqueue_ocr_crop_jobs(
    path: str,
    *,
    image_hash: str,
    diagnostics: ImageOcrDiagnostics,
    store: OcrScanStore,
    crop_dir: str,
    accurate_confidence_threshold: int = 100,
) -> list[str]:
    """Persist enlarged, sharpened numeric crops for idle-time refinement."""

    if not diagnostics.available:
        return []
    target_dir = Path(crop_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    threshold = max(0, min(100, int(accurate_confidence_threshold)))
    job_ids: list[str] = []
    with Image.open(path) as source:
        for candidate in diagnostics.candidates:
            if not candidate.accepted or not str(candidate.value).strip():
                continue
            if float(candidate.confidence) * 100 > threshold:
                continue
            left, top, right, bottom = (int(value) for value in candidate.bbox)
            left = max(0, min(source.width, left))
            top = max(0, min(source.height, top))
            right = max(left + 1, min(source.width, right))
            bottom = max(top + 1, min(source.height, bottom))
            crop_left = max(0, left - 8)
            crop_top = max(0, top - 8)
            crop_right = min(source.width, right + 8)
            crop_bottom = min(source.height, bottom + 8)
            crop = source.crop((crop_left, crop_top, crop_right, crop_bottom)).convert("RGB")
            crop = crop.resize((crop.width * 4, crop.height * 4), Image.Resampling.LANCZOS)
            crop = ImageEnhance.Sharpness(crop).enhance(1.8)
            job_id = f"ocr-{uuid.uuid4().hex}"
            crop_path = target_dir / f"{job_id}.png"
            crop.save(crop_path, format="PNG", optimize=True)
            store.enqueue_ocr_crop_job(
                {
                    "id": job_id,
                    "image_hash": image_hash,
                    "bbox": [crop_left, crop_top, crop_right, crop_bottom],
                    "thumbnail_path": str(crop_path),
                    "kind": "accurate",
                }
            )
            job_ids.append(job_id)
    return job_ids
