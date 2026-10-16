"""Failures specific to the installed OCR boundary, without loading large models."""

import json
import os
from io import StringIO
from pathlib import Path
import sys
import types

import pytest

from picsyncra.installation.ocr_entrypoint import run_ocr_job
from picsyncra.installation import ocr_runtime
from picsyncra.installation.ocr_runtime import InstalledOcrWorker, serve_ocr_runtime
from picsyncra.services import image_dimensions
from picsyncra.services.image_dimensions import OcrTextBox
from picsyncra.services.ocr_pipeline import OcrPipelineReport
from tests.test_ocr_runtime_protocol import _Process


def test_installed_ocr_returns_a_detailed_result_larger_than_eight_kib(tmp_path):
    image = tmp_path / "input.png"
    image.write_bytes(b"image")
    boxes = tuple(OcrTextBox(str(100 + i), .95, (i, 10, i + 10, 20)) for i in range(100))
    report = OcrPipelineReport(regions=(), all_boxes=boxes, total_elapsed_ms=17)
    commands = StringIO(json.dumps({
        "kind": "job", "run_id": "large-result", "path": str(image),
        "work_root": str(tmp_path), "profile_ids": ["fast"],
    }) + '\n' + json.dumps({"kind": "stop"}) + '\n')
    responses = StringIO()
    serve_ocr_runtime(commands, responses, build_id="build", component_id="ocr",
                      run_job=lambda job: run_ocr_job(job, pipeline=lambda *_a, **_kw: report))
    lines = responses.getvalue().splitlines()
    result = json.loads(lines[-1])
    assert result["kind"] == "result", result
    assert len(lines[-1].encode("utf-8")) > 8192
    assert len(result["diagnostics"]["candidates"]) == 100

    # Exercise the other end of the same IPC channel as well as its serializer.
    process = _Process([line + '\n' for line in lines])
    worker = InstalledOcrWorker(executable=tmp_path / "ocr.exe", build_id="build",
                                component_id="ocr", process_factory=lambda _args: process)
    # The synchronous reader makes delivery deterministic without sleeps/threads.
    worker._process = process
    worker._read_events(process)
    received = worker.poll()
    assert received[-1] == result


def test_installed_ocr_reports_the_failure_reason_instead_of_a_generic_error(tmp_path):
    image = tmp_path / "input.png"
    image.write_bytes(b"image")
    commands = StringIO(json.dumps({
        "kind": "job", "run_id": "failed-run", "path": str(image),
        "work_root": str(tmp_path), "profile_ids": ["fast"],
    }) + '\n')
    responses = StringIO()
    def fail(_job):
        raise PermissionError("OCR cache is read-only")
    serve_ocr_runtime(commands, responses, build_id="build", component_id="ocr", run_job=fail)
    result = json.loads(responses.getvalue().splitlines()[-1])
    assert result["kind"] == "error"
    assert result["run_id"] == "failed-run"
    assert "PermissionError" in result.get("message", "")
    assert "cache is read-only" in result.get("message", "")


def test_runtime_reader_tolerates_bounded_library_output_before_the_result(tmp_path):
    result = {"kind": "result", "run_id": "one", "diagnostics": {"available": True}}
    process = _Process(["library initialization note\n", json.dumps(result) + '\n'])
    worker = InstalledOcrWorker(executable=tmp_path / "ocr.exe", build_id="build",
                                component_id="ocr", process_factory=lambda _args: process)
    worker._process = process
    worker._read_events(process)
    assert worker.poll()[-1] == result
    assert process.terminated is False


def test_installed_ocr_preserves_pipeline_dependency_cause(tmp_path):
    image = tmp_path / "input.png"
    image.write_bytes(b"image")
    commands = StringIO(json.dumps({
        "kind": "job", "run_id": "dependency-error", "path": str(image),
        "work_root": str(tmp_path), "profile_ids": ["fast"],
    }) + '\n')
    responses = StringIO()

    def fail(_job):
        try:
            raise ModuleNotFoundError("No module named 'ocr_engine'")
        except ImportError as exc:
            raise RuntimeError("A dependency error occurred during pipeline creation.") from exc

    serve_ocr_runtime(commands, responses, build_id="build", component_id="ocr", run_job=fail)
    result = json.loads(responses.getvalue().splitlines()[-1])
    assert "ocr_engine" in result["message"]
    assert "pipeline creation" in result["message"]


def test_multi_profile_failure_keeps_the_underlying_dependency_error():
    def fail(_profile):
        try:
            raise ModuleNotFoundError("missing OCR dependency")
        except ImportError as exc:
            raise RuntimeError("pipeline creation failed") from exc

    recognizer = image_dimensions.MultiProfileImageDimensionRecognizer(["fast"], recognizer_factory=fail)
    with pytest.raises(image_dimensions.ImageDimensionUnavailable, match="missing OCR dependency"):
        recognizer.detect("input.png")


@pytest.mark.parametrize("frame_bytes", [16384, 65536], ids=["at-limit", "oversized"])
def test_result_reader_enforces_its_frame_limit_with_a_size_respecting_stream(tmp_path, monkeypatch, frame_bytes):
    monkeypatch.setattr(ocr_runtime, "MAX_OCR_EVENT_BYTES", 16384)
    result = {"kind": "result", "run_id": "one", "diagnostics": {"message": ""}}
    overhead = len(json.dumps(result, separators=(",", ":")).encode("utf-8"))
    result["diagnostics"]["message"] = "x" * (frame_bytes - overhead)
    encoded = json.dumps(result, separators=(",", ":"))
    process = _Process([])
    process.stdout = StringIO(encoded + '\n')
    worker = InstalledOcrWorker(executable=tmp_path / "ocr.exe", build_id="build",
                                component_id="ocr", process_factory=lambda _args: process)
    worker._process = process
    worker._read_events(process)
    events = worker.poll()
    assert process.stdout.tell() <= 16385
    if frame_bytes == 16384:
        assert events == [result]
        assert process.terminated is False
    else:
        assert process.terminated is True
        assert events[-1] == {"kind": "error", "code": "runtime_exited"}


@pytest.mark.parametrize("source", ["bundled", "installed"])
def test_packaged_models_are_read_from_explicit_paths_with_a_separate_writable_cache(tmp_path, monkeypatch, source):
    models = tmp_path / "program" / "ocr_models"
    for name in ("PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec"):
        directory = models / "official_models" / name
        directory.mkdir(parents=True)
        (directory / "model.bin").write_bytes(b"model")
    monkeypatch.setattr(sys, "_MEIPASS", str(models.parent) if source == "bundled" else "", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "writable"))
    monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(models))
    monkeypatch.delenv("PICSYNCRA_OCR_MODEL_ROOT", raising=False)
    if source == "installed":
        monkeypatch.setenv("PICSYNCRA_OCR_MODEL_ROOT", str(models))
    monkeypatch.delenv("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", raising=False)
    monkeypatch.setitem(sys.modules, "cv2", types.ModuleType("cv2"))
    captured = {}
    class PaddleModule(types.ModuleType):
        def __getattr__(self, name):
            if name != "PaddleOCR":
                raise AttributeError(name)
            # PaddleX initializes temp/lock directories during import.
            cache = Path(os.environ["PADDLE_PDX_CACHE_HOME"])
            assert not cache.is_relative_to(models.parent)
            assert os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] == "True"
            (cache / "temp").mkdir(parents=True, exist_ok=True)
            return lambda **kwargs: captured.update(kwargs)
    monkeypatch.setitem(sys.modules, "paddleocr", PaddleModule("paddleocr"))

    image_dimensions.PaddleImageDimensionRecognizer("fast")
    assert captured["text_detection_model_dir"] == str(models / "official_models" / "PP-OCRv5_mobile_det")
    assert captured["text_recognition_model_dir"] == str(models / "official_models" / "PP-OCRv5_mobile_rec")
    assert image_dimensions.ocr_model_cache_path() == str(models)
    assert not (models / "temp").exists()
