from pathlib import Path

import pytest
from PIL import Image

from picsyncra.services.image_dimensions import OcrTextBox
from picsyncra.services.ocr_pipeline import (
    run_ocr_pipeline,
    run_ocr_pipeline_report,
)
from picsyncra.services.ocr_resource_policy import ResourceDecision


def test_both_profiles_send_only_fast_regions_to_accurate_model_and_translate_boxes(tmp_path):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (80, 60), "white").save(image_path)
    calls: list[tuple[str, str]] = []
    events: list[dict[str, object]] = []

    class _Recognizer:
        def __init__(self, profile_id: str) -> None:
            self.profile_id = profile_id

        def detect(self, path: str) -> list[OcrTextBox]:
            calls.append((self.profile_id, Path(path).name))
            if self.profile_id == "fast":
                return [OcrTextBox("20 kg", 0.8, (10, 12, 30, 22))]
            return [OcrTextBox("20kg", 0.95, (1, 2, 11, 7))]

    report = run_ocr_pipeline_report(
        str(image_path),
        profile_ids=["fast", "accurate"],
        recognizer_factory=_Recognizer,
        on_event=lambda kind, **payload: events.append({"kind": kind, **payload}),
    )

    assert calls[0] == ("fast", "source.png")
    assert calls[1][0] == "accurate"
    assert calls[1][1] != "source.png"
    assert report.all_boxes[-1] == OcrTextBox("20kg", 0.95, (3, 6, 13, 11))
    assert report.regions[0].region_id == "region-1"
    assert report.regions[0].accurate_boxes == (
        OcrTextBox("20kg", 0.95, (3, 6, 13, 11)),
    )
    assert report.regions[0].fast_elapsed_ms >= 0
    assert report.regions[0].crop_elapsed_ms >= 0
    assert report.regions[0].accurate_elapsed_ms >= 0
    assert report.total_elapsed_ms >= 0
    assert {event["kind"] for event in events} >= {"candidate_regions", "crop_started"}
    candidate_regions = next(event for event in events if event["kind"] == "candidate_regions")
    assert candidate_regions["regions"] == [
        {
            "region_id": "region-1",
            "text": "20 kg",
            "value": "20",
            "confidence": 0.8,
            "bbox": [10, 12, 30, 22],
        }
    ]
    crop_started = next(event for event in events if event["kind"] == "crop_started")
    assert crop_started["region_id"] == "region-1"
    assert crop_started["source_bbox"] == [
        10,
        12,
        30,
        22,
    ]
    assert crop_started["bbox"] == [2, 4, 38, 30]


def test_high_confidence_fast_region_is_skipped_with_explicit_reason(tmp_path):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (80, 60), "white").save(image_path)
    calls: list[str] = []
    events: list[dict[str, object]] = []

    class _Recognizer:
        def __init__(self, profile_id: str) -> None:
            self.profile_id = profile_id

        def detect(self, _path: str) -> list[OcrTextBox]:
            calls.append(self.profile_id)
            return [OcrTextBox("100", 1.0, (10, 12, 30, 22))]

    report = run_ocr_pipeline_report(
        str(image_path),
        profile_ids=["fast", "accurate"],
        accurate_confidence_threshold=99,
        recognizer_factory=_Recognizer,
        on_event=lambda kind, **payload: events.append({"kind": kind, **payload}),
    )

    assert calls == ["fast"]
    assert report.regions[0].status == "skipped_threshold"
    assert "100% > 99%" in report.regions[0].reason
    assert any(event["kind"] == "crop_skipped" for event in events)


def test_crop_margin_is_symmetric_and_clipped_to_image_edge(tmp_path):
    image_path = tmp_path / "edge.png"
    Image.new("RGB", (30, 20), "white").save(image_path)

    class _Recognizer:
        def __init__(self, profile_id: str) -> None:
            self.profile_id = profile_id

        def detect(self, _path: str) -> list[OcrTextBox]:
            if self.profile_id == "fast":
                return [OcrTextBox("12", 0.8, (2, 2, 22, 12))]
            return []

    report = run_ocr_pipeline_report(
        str(image_path),
        profile_ids=["fast", "accurate"],
        accurate_confidence_threshold=100,
        recognizer_factory=_Recognizer,
    )

    assert report.regions[0].source_bbox == (2, 2, 22, 12)
    assert report.regions[0].crop_bbox == (0, 0, 30, 20)


@pytest.mark.parametrize(
    ("profiles", "expected_calls"),
    [(["fast"], ["fast"]), (["accurate"], ["accurate"])],
)
def test_single_profile_runs_one_full_image_stage(tmp_path, profiles, expected_calls):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (80, 60), "white").save(image_path)
    calls: list[str] = []

    class _Recognizer:
        def __init__(self, profile_id: str) -> None:
            self.profile_id = profile_id

        def detect(self, _path: str) -> list[OcrTextBox]:
            calls.append(self.profile_id)
            return []

    assert run_ocr_pipeline(
        str(image_path), profile_ids=profiles, recognizer_factory=_Recognizer
    ) == []
    assert calls == expected_calls


def test_explicit_empty_profile_selection_is_rejected():
    with pytest.raises(ValueError, match="profile"):
        run_ocr_pipeline("source.png", profile_ids=[])


def test_pipeline_throttles_between_fast_stage_and_accurate_crop(tmp_path):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (80, 60), "white").save(image_path)
    checks = iter(
        [
            ResourceDecision("run"),
            ResourceDecision("throttle", "memory_usage", 0.25),
            ResourceDecision("run"),
        ]
    )
    events: list[str] = []
    waits: list[float] = []

    class _Recognizer:
        def __init__(self, profile_id: str) -> None:
            self.profile_id = profile_id

        def detect(self, _path: str) -> list[OcrTextBox]:
            return [OcrTextBox("12", 0.9, (10, 10, 20, 20))] if self.profile_id == "fast" else []

    run_ocr_pipeline(
        str(image_path),
        profile_ids=["fast", "accurate"],
        recognizer_factory=_Recognizer,
        before_stage=lambda _stage: next(checks),
        on_event=lambda kind, **_payload: events.append(kind),
        sleeper=waits.append,
    )

    assert waits == [0.25]
    assert "throttled" in events
