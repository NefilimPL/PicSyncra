"""PaddleX checks distribution metadata even when Python modules are importable."""

import importlib.metadata
from pathlib import Path
import runpy
import shutil

import pytest


HOOK = Path(__file__).resolve().parents[1] / "installer/hooks/hook-paddlex.py"


def _distribution(root, name, *requirements, extras=()):
    directory = root / f"{name}-1.0.dist-info"
    directory.mkdir()
    lines = ["Metadata-Version: 2.1", f"Name: {name}", "Version: 1.0"]
    lines += [f"Provides-Extra: {extra}" for extra in extras]
    lines += [f"Requires-Dist: {requirement}" for requirement in requirements]
    (directory / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_ocr_bundle_keeps_metadata_for_core_extra_and_transitive_extras(tmp_path, monkeypatch):
    pytest.importorskip("PyInstaller")
    source = tmp_path / "site-packages"
    source.mkdir()
    _distribution(source, "paddlex", "ocr_base", 'ocr_plugin[engine]; extra == "ocr-core"',
                  'unused_training; extra == "train"', 'linux_only; sys_platform == "nonexistent"',
                  extras=("ocr-core", "train"))
    _distribution(source, "ocr_base", "ocr_shared")
    _distribution(source, "ocr_shared")
    _distribution(source, "ocr_plugin", 'ocr_engine; extra == "engine"', extras=("engine",))
    _distribution(source, "ocr_engine")
    monkeypatch.syspath_prepend(str(source))
    collected = runpy.run_path(str(HOOK))["datas"]
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    for src, destination in collected:
        shutil.copytree(src, bundled / destination, dirs_exist_ok=True)
    # This is the same distribution-discovery boundary used by PaddleX.
    found = {distribution.metadata["Name"] for distribution in
             importlib.metadata.distributions(path=[str(bundled)])}
    assert found == {"paddlex", "ocr_base", "ocr_shared", "ocr_plugin", "ocr_engine"}


def test_ocr_build_fails_if_core_extra_is_incomplete(tmp_path, monkeypatch):
    pytest.importorskip("PyInstaller")
    _distribution(tmp_path, "paddlex", 'missing_ocr_engine; extra == "ocr-core"',
                  extras=("ocr-core",))
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(importlib.metadata.PackageNotFoundError, match="missing_ocr_engine"):
        runpy.run_path(str(HOOK))
