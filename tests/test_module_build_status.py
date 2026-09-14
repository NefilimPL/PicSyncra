from __future__ import annotations

import importlib
import json
import sys
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
        source_ref="dev",
    )

    assert manifest["schema_version"] == 2
    assert manifest["build_variant"] == "web-ocr"
    assert manifest["source_ref"] == "dev"
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


def test_build_manifest_records_declared_dependencies_and_build_python(monkeypatch):
    module_build_status = importlib.import_module(
        "picsyncra.services.module_build_status"
    )
    monkeypatch.setattr(module_build_status, "_git", lambda *_args: "")
    monkeypatch.setattr(
        module_build_status,
        "_installed_package_version",
        lambda package: {"fastapi": "0.115.6", "pillow": "11.0.0"}.get(package, ""),
        raising=False,
    )

    manifest = module_build_status.build_manifest(
        Path(__file__).resolve().parents[1],
        build_variant="web",
        now=datetime(2026, 9, 14, tzinfo=UTC),
    )
    dependencies = {item["name"]: item for item in manifest["dependencies"]}

    assert manifest["python"] == {
        "version": sys.version.split()[0],
        "implementation": sys.implementation.name,
    }
    assert dependencies["fastapi"] == {
        "name": "fastapi",
        "requirement": "fastapi>=0.115",
        "installed_version": "0.115.6",
        "github_url": "https://github.com/fastapi/fastapi",
    }
    assert dependencies["tkinterdnd2"]["github_url"] == (
        "https://github.com/pmgagne/tkinterdnd2"
    )
    assert sum(item["name"] == "pillow" for item in manifest["dependencies"]) == 1


def test_snapshot_marks_a_legacy_manifest_without_source_ref_as_unavailable():
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
    snapshot = module_build_status.module_status_snapshot(manifest, Path("C:/"), {})

    assert snapshot["repository_status"] == "source_ref_missing"
    assert snapshot["modules"][0]["status"] == "source_ref_missing"


def test_snapshot_marks_a_newer_github_module_commit_as_update_available(monkeypatch):
    module_build_status = importlib.import_module(
        "picsyncra.services.module_build_status"
    )
    manifest = {
        "schema_version": 2,
        "source_ref": "dev",
        "repository_commit": "b" * 40,
        "modules": [
            {
                "id": "ocr",
                "label": "OCR",
                "commit": "o" * 40,
                "committed_at": "2026-08-01T00:00:00Z",
            }
        ],
    }
    monkeypatch.setattr(
        module_build_status,
        "github_branch_module_snapshot",
        lambda *_args, **_kwargs: {
            "available": True,
            "message": "",
            "source_ref": "dev",
            "branch_commit": "n" * 40,
            "relation_to_build": "ahead",
            "modules": {
                "ocr": {
                    "commit": "n" * 40,
                    "committed_at": "2026-09-14T11:22:47Z",
                }
            },
        },
        raising=False,
    )

    snapshot = module_build_status.module_status_snapshot(manifest, Path("C:/"), {})

    assert snapshot["repository_status"] == "github_available"
    assert snapshot["modules"] == [
        {
            "id": "ocr",
            "label": "OCR",
            "build_commit": "o" * 40,
            "build_committed_at": "2026-08-01T00:00:00Z",
            "github_commit": "n" * 40,
            "github_committed_at": "2026-09-14T11:22:47Z",
            "status": "update_available",
        }
    ]


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

    assert snapshot["repository_status"] == "source_ref_missing"
    assert snapshot["build"]["build_variant"] == "web"
    assert snapshot["build"]["repository_commit"] == "abc123"


def test_snapshot_marks_a_build_from_another_history(monkeypatch):
    module_build_status = importlib.import_module(
        "picsyncra.services.module_build_status"
    )
    manifest = {
        "schema_version": 2,
        "source_ref": "dev",
        "repository_commit": "b" * 40,
        "modules": [
            {
                "id": "ocr",
                "label": "OCR",
                "commit": "same",
                "committed_at": "2026-08-01T00:00:00+00:00",
            }
        ],
    }
    monkeypatch.setattr(
        module_build_status,
        "github_branch_module_snapshot",
        lambda *_args, **_kwargs: {
            "available": True,
            "relation_to_build": "behind",
            "modules": {
                "ocr": {
                    "commit": "new",
                    "committed_at": "2026-09-14T11:22:47Z",
                }
            },
        },
    )

    row = module_build_status.module_status_snapshot(manifest, Path("C:/"), {})["modules"][0]

    assert row["status"] == "build_outside_source"


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
