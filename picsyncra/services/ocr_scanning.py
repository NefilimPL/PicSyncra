"""Two-stage OCR orchestration with testable local-adapter boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .ocr_values import OcrValue


class OcrDiscoverer(Protocol):
    def discover(self, path: str) -> list[OcrValue]: ...


class OcrRefiner(Protocol):
    def refine(self, path: str, bbox: tuple[int, int, int, int]) -> OcrValue | None: ...


@dataclass(frozen=True)
class ScanResult:
    fast_values: list[OcrValue]
    refined_values: list[OcrValue]
    deferred_bboxes: list[tuple[int, int, int, int]]


def scan_image(
    path: str,
    *,
    discoverer: OcrDiscoverer,
    refiner: OcrRefiner,
    cancel_requested: Callable[[], bool],
) -> ScanResult:
    """Discover quickly, then refine each crop until work is cancelled."""

    fast_values = list(discoverer.discover(path))
    refined_values: list[OcrValue] = []
    deferred_bboxes: list[tuple[int, int, int, int]] = []
    for value in fast_values:
        if cancel_requested():
            deferred_bboxes.append(value.bbox)
            continue
        refined = refiner.refine(path, value.bbox)
        if refined is not None:
            refined_values.append(refined)
    return ScanResult(fast_values, refined_values, deferred_bboxes)
