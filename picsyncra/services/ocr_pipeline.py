"""Stage-aware local OCR orchestration for fast and accurate profiles."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from typing import Protocol

from PIL import Image

from .image_dimensions import ImageDimensionRecognizer, OcrTextBox, PaddleImageDimensionRecognizer
from .ocr_profiles import normalize_ocr_profile_ids
from .ocr_values import comparison_key


ProgressCallback = Callable[..., None]
StagePolicy = Callable[[str], object]


@dataclass(frozen=True)
class OcrPipelineRegion:
    """One fast-model region and its optional accurate-model crop result."""

    region_id: str
    fast_box: OcrTextBox
    source_bbox: tuple[int, int, int, int]
    crop_bbox: tuple[int, int, int, int] | None
    accurate_boxes: tuple[OcrTextBox, ...]
    status: str
    reason: str
    fast_elapsed_ms: int
    crop_elapsed_ms: int
    accurate_elapsed_ms: int


@dataclass(frozen=True)
class OcrPipelineReport:
    """Structured OCR output retaining the relationship between both models."""

    regions: tuple[OcrPipelineRegion, ...]
    all_boxes: tuple[OcrTextBox, ...]
    total_elapsed_ms: int


def _emit(callback: ProgressCallback | None, kind: str, **payload: object) -> None:
    if callback is not None:
        callback(kind, **payload)


def _wait_for_stage(
    callback: StagePolicy | None,
    stage: str,
    emit: ProgressCallback | None,
    sleeper: Callable[[float], None],
) -> None:
    if callback is None:
        return
    while True:
        decision = callback(stage)
        action = str(getattr(decision, "action", "run"))
        if action == "run":
            return
        reason = str(getattr(decision, "reason", "resource_limit"))
        retry = max(0.05, float(getattr(decision, "retry_after_seconds", 1.0)))
        if action == "throttle":
            _emit(emit, "throttled", stage=stage, resource=reason, retry_after_seconds=retry)
            sleeper(retry)
            continue
        _emit(emit, "paused", stage=stage, reason=reason, retry_after_seconds=retry)
        raise RuntimeError(f"OCR stage deferred: {reason}")


def _merge_boxes(boxes: Iterable[OcrTextBox]) -> list[OcrTextBox]:
    merged: list[OcrTextBox] = []
    indexes: dict[tuple[str, tuple[int, int, int, int]], int] = {}
    for box in boxes:
        key = (str(box.text).strip().casefold(), box.bbox)
        index = indexes.get(key)
        if index is None:
            indexes[key] = len(merged)
            merged.append(box)
        elif box.confidence > merged[index].confidence:
            merged[index] = box
    return merged


def _bounded_bbox(box: OcrTextBox, image: Image.Image) -> tuple[int, int, int, int] | None:
    left, top, right, bottom = (int(value) for value in box.bbox)
    left = max(0, min(image.width, left))
    top = max(0, min(image.height, top))
    right = max(left, min(image.width, right))
    bottom = max(top, min(image.height, bottom))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _expanded_bbox(
    bbox: tuple[int, int, int, int], image: Image.Image
) -> tuple[int, int, int, int]:
    """Add one symmetric context margin before clipping it to the image."""

    left, top, right, bottom = bbox
    longest_side = max(right - left, bottom - top)
    padding = min(64, max(8, round(longest_side * 0.25)))
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(image.width, right + padding),
        min(image.height, bottom + padding),
    )


def _elapsed_ms(clock: Callable[[], float], started_at: float) -> int:
    return max(0, round((clock() - started_at) * 1000))


def _event_box(box: OcrTextBox) -> dict[str, object]:
    return {
        "text": box.text,
        "value": comparison_key(box.text),
        "confidence": box.confidence,
        "bbox": list(box.bbox),
    }


def _translated(box: OcrTextBox, origin: tuple[int, int, int, int]) -> OcrTextBox:
    left, top, _right, _bottom = origin
    box_left, box_top, box_right, box_bottom = box.bbox
    return OcrTextBox(
        box.text,
        box.confidence,
        (left + box_left, top + box_top, left + box_right, top + box_bottom),
        box.hint,
        box.angle,
    )


def run_ocr_pipeline_report(
    path: str,
    *,
    profile_ids: Iterable[object],
    accurate_confidence_threshold: int = 99,
    recognizer_factory: Callable[[object], ImageDimensionRecognizer] | None = None,
    on_event: ProgressCallback | None = None,
    before_stage: StagePolicy | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.perf_counter,
) -> OcrPipelineReport:
    """Run OCR while retaining every fast-region and accurate-crop relationship."""

    profiles = normalize_ocr_profile_ids(list(profile_ids))
    if not profiles:
        raise ValueError("At least one OCR profile must be selected.")
    threshold = max(0, min(100, int(accurate_confidence_threshold)))
    factory = recognizer_factory or PaddleImageDimensionRecognizer
    source_path = str(path)
    total_started_at = clock()
    all_boxes: list[OcrTextBox] = []

    if profiles == ["accurate"]:
        _wait_for_stage(before_stage, "accurate_full_image", on_event, sleeper)
        _emit(on_event, "stage_started", stage="accurate_full_image", model="accurate")
        stage_started_at = clock()
        boxes = factory("accurate").detect(source_path)
        _emit(
            on_event,
            "stage_finished",
            stage="accurate_full_image",
            model="accurate",
            elapsed_ms=_elapsed_ms(clock, stage_started_at),
        )
        return OcrPipelineReport(
            regions=(),
            all_boxes=tuple(_merge_boxes(boxes)),
            total_elapsed_ms=_elapsed_ms(clock, total_started_at),
        )

    _wait_for_stage(before_stage, "fast_full_image", on_event, sleeper)
    _emit(on_event, "stage_started", stage="fast_full_image", model="fast")
    fast_started_at = clock()
    fast_boxes = factory("fast").detect(source_path)
    fast_elapsed_ms = _elapsed_ms(clock, fast_started_at)
    all_boxes.extend(fast_boxes)
    regions = [
        OcrPipelineRegion(
            region_id=f"region-{index}",
            fast_box=box,
            source_bbox=box.bbox,
            crop_bbox=None,
            accurate_boxes=(),
            status="pending",
            reason="Oczekiwanie na decyzje dla modelu dokladnego.",
            fast_elapsed_ms=fast_elapsed_ms,
            crop_elapsed_ms=0,
            accurate_elapsed_ms=0,
        )
        for index, box in enumerate(fast_boxes, start=1)
    ]
    _emit(
        on_event,
        "candidate_regions",
        model="fast",
        regions=[
            {"region_id": region.region_id, **_event_box(region.fast_box)}
            for region in regions
        ],
    )
    _emit(
        on_event,
        "stage_finished",
        stage="fast_full_image",
        model="fast",
        elapsed_ms=fast_elapsed_ms,
    )

    if "accurate" not in profiles:
        return OcrPipelineReport(
            regions=tuple(
                replace(
                    region,
                    status="not_requested",
                    reason="Model dokladny nie jest wlaczony.",
                )
                for region in regions
            ),
            all_boxes=tuple(_merge_boxes(all_boxes)),
            total_elapsed_ms=_elapsed_ms(clock, total_started_at),
        )

    with Image.open(source_path) as source, TemporaryDirectory(prefix="picsyncra-ocr-") as temp_dir:
        source = source.convert("RGB")
        eligible: list[tuple[int, tuple[int, int, int, int]]] = []
        for index, region in enumerate(regions):
            bounded = _bounded_bbox(region.fast_box, source)
            if bounded is None:
                regions[index] = replace(
                    region,
                    status="invalid_region",
                    reason="Wykryty obszar nie miesci sie w obrazie.",
                )
                _emit(
                    on_event,
                    "crop_skipped",
                    region_id=region.region_id,
                    bbox=list(region.source_bbox),
                    reason=regions[index].reason,
                )
            elif region.fast_box.confidence * 100 > threshold:
                reason = (
                    "Pominieto: pewnosc szybkiego "
                    f"{round(region.fast_box.confidence * 100)}% > {threshold}%."
                )
                regions[index] = replace(
                    region,
                    status="skipped_threshold",
                    reason=reason,
                )
                _emit(
                    on_event,
                    "crop_skipped",
                    region_id=region.region_id,
                    bbox=list(bounded),
                    confidence=region.fast_box.confidence,
                    threshold=threshold,
                    reason=reason,
                )
            else:
                eligible.append((index, bounded))

        total = len(eligible)
        for crop_index, (index, source_bbox) in enumerate(eligible, start=1):
            _wait_for_stage(before_stage, "accurate_crop", on_event, sleeper)
            region = regions[index]
            crop_bbox = _expanded_bbox(source_bbox, source)
            _emit(
                on_event,
                "crop_started",
                stage="accurate_crop",
                model="accurate",
                region_id=region.region_id,
                crop_index=crop_index,
                crop_total=total,
                bbox=list(crop_bbox),
                source_bbox=list(source_bbox),
            )
            crop_started_at = clock()
            crop_path = Path(temp_dir) / f"crop-{crop_index}.png"
            source.crop(crop_bbox).save(crop_path, format="PNG", optimize=True)
            crop_elapsed_ms = _elapsed_ms(clock, crop_started_at)
            accurate_started_at = clock()
            accurate_boxes = factory("accurate").detect(str(crop_path))
            accurate_elapsed_ms = _elapsed_ms(clock, accurate_started_at)
            translated_boxes = tuple(
                _translated(box, crop_bbox) for box in accurate_boxes
            )
            all_boxes.extend(translated_boxes)
            status = "completed" if translated_boxes else "empty"
            reason = "" if translated_boxes else "Dokladny model nie wykryl tekstu w wycinku."
            regions[index] = replace(
                region,
                crop_bbox=crop_bbox,
                accurate_boxes=translated_boxes,
                status=status,
                reason=reason,
                crop_elapsed_ms=crop_elapsed_ms,
                accurate_elapsed_ms=accurate_elapsed_ms,
            )
            _emit(
                on_event,
                "crop_finished",
                stage="accurate_crop",
                model="accurate",
                region_id=region.region_id,
                crop_index=crop_index,
                crop_total=total,
                bbox=list(crop_bbox),
                source_bbox=list(source_bbox),
                accurate=[_event_box(box) for box in translated_boxes],
                status=status,
                reason=reason,
                crop_elapsed_ms=crop_elapsed_ms,
                accurate_elapsed_ms=accurate_elapsed_ms,
            )
    return OcrPipelineReport(
        regions=tuple(regions),
        all_boxes=tuple(_merge_boxes(all_boxes)),
        total_elapsed_ms=_elapsed_ms(clock, total_started_at),
    )


def run_ocr_pipeline(
    path: str,
    *,
    profile_ids: Iterable[object],
    recognizer_factory: Callable[[object], ImageDimensionRecognizer] | None = None,
    on_event: ProgressCallback | None = None,
    before_stage: StagePolicy | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[OcrTextBox]:
    """Return the legacy flattened OCR output for existing consumers."""

    return list(
        run_ocr_pipeline_report(
            path,
            profile_ids=profile_ids,
            recognizer_factory=recognizer_factory,
            on_event=on_event,
            before_stage=before_stage,
            sleeper=sleeper,
        ).all_boxes
    )
