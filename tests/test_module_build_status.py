from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path


def test_build_manifest_includes_registered_ocr_and_generator_modules(monkeypatch, tmp_path):
    module_build_status = importlib.import_module(
        "picsyncra.services.module_build_status"
    )
    monkeypatch.setattr(
        module_build_status,
        "_git",
        lambda *_args: "abc123|2026-08-27T10:00:00+00:00",
    )

    manifest = module_build_status.build_manifest(
        tmp_path,
        build_variant="web-ocr",
        now=datetime(2026, 8, 27, tzinfo=UTC),
    )

    assert manifest["schema_version"] == 1
    assert manifest["build_variant"] == "web-ocr"
    assert {
        "slots",
        "ocr",
        "ocr_tester",
        "pimcore",
        "settings",
        "generator_local",
        "generator_web",
    } <= {item["id"] for item in manifest["modules"]}
    assert all(
        set(item) == {"id", "label", "commit", "committed_at"}
        for item in manifest["modules"]
    )


def test_snapshot_marks_changed_module_for_rebuild(monkeypatch, tmp_path):
    module_build_status = importlib.import_module(
        "picsyncra.services.module_build_status"
    )
    manifest = {
        "schema_version": 1,
        "modules": [
            {
                "id": "ocr",
                "label": "OCR",
                "commit": "old",
                "committed_at": "2026-08-01T00:00:00+00:00",
            }
        ],
    }
    monkeypatch.setattr(module_build_status, "_find_repo_root", lambda *_args: tmp_path, raising=False)
    monkeypatch.setattr(
        module_build_status,
        "_module_git_state",
        lambda *_args: ("new", "2026-08-27T00:00:00+00:00", False),
        raising=False,
    )

    row = module_build_status.module_status_snapshot(manifest, tmp_path, {})["modules"][0]

    assert row["status"] == "rebuild_required"


def test_snapshot_keeps_embedded_data_when_repository_is_unavailable():
    module_build_status = importlib.import_module(
        "picsyncra.services.module_build_status"
    )
    manifest = {
        "schema_version": 1,
        "build_variant": "web",
        "repository_commit": "abc123",
        "modules": [],
    }

    snapshot = module_build_status.module_status_snapshot(manifest, Path("C:/"), {})

    assert snapshot["repository_status"] == "unavailable"
    assert snapshot["build"]["build_variant"] == "web"
    assert snapshot["build"]["repository_commit"] == "abc123"


def test_snapshot_prioritizes_uncommitted_changes(monkeypatch, tmp_path):
    module_build_status = importlib.import_module(
        "picsyncra.services.module_build_status"
    )
    manifest = {
        "schema_version": 1,
        "modules": [
            {
                "id": "ocr",
                "label": "OCR",
                "commit": "same",
                "committed_at": "2026-08-01T00:00:00+00:00",
            }
        ],
    }
    monkeypatch.setattr(module_build_status, "_find_repo_root", lambda *_args: tmp_path)
    monkeypatch.setattr(
        module_build_status,
        "_module_git_state",
        lambda *_args: ("same", "2026-08-01T00:00:00+00:00", True),
    )

    row = module_build_status.module_status_snapshot(manifest, tmp_path, {})["modules"][0]

    assert row["status"] == "uncommitted_changes"


def test_load_packaged_manifest_reads_the_embedded_json(monkeypatch, tmp_path):
    module_build_status = importlib.import_module(
        "picsyncra.services.module_build_status"
    )
    package_root = tmp_path / "picsyncra"
    (package_root / "services").mkdir(parents=True)
    (package_root / "module_build_manifest.json").write_text(
        json.dumps({"schema_version": 1, "modules": []}), encoding="utf-8"
    )
    monkeypatch.setattr(
        module_build_status,
        "__file__",
        str(package_root / "services" / "module_build_status.py"),
    )

    assert module_build_status.load_packaged_module_manifest() == {
        "schema_version": 1,
        "modules": [],
    }
