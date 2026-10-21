"""The OCR dependency bundle must retain chardet's dynamic native imports."""

from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path
import runpy

import pytest


HOOK = Path(__file__).resolve().parents[1] / "installer/hooks/hook-chardet.py"


@pytest.mark.parametrize("compiled", [False, True])
def test_chardet_hook_collects_nested_modules_and_model_data(tmp_path, monkeypatch, compiled):
    pytest.importorskip("PyInstaller")
    package = tmp_path / "chardet"
    models = package / "models"
    pipeline = package / "pipeline"
    models.mkdir(parents=True)
    pipeline.mkdir()
    for directory in (package, models, pipeline):
        (directory / "__init__.py").write_text("", encoding="utf-8")
    (models / "_format.py").write_text("", encoding="utf-8")
    (models / "models.bin").write_bytes(b"model data")
    files = []
    if compiled:
        # Nested counterparts model the Windows wheel's dynamic imports.
        for path in (models / "_format__mypyc.py", pipeline / "orchestrator__mypyc.py"):
            path.write_text("", encoding="utf-8")
            files.append(path.relative_to(tmp_path).as_posix())
        # Older wheels also place a hash-named extension outside the package.
        extension = "abc123__mypyc" + EXTENSION_SUFFIXES[0]
        (tmp_path / extension).write_bytes(b"")
        files.append(extension)
    metadata = tmp_path / "chardet-7.7.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: chardet\nVersion: 7.7.0\n", encoding="utf-8")
    (metadata / "RECORD").write_text("".join(f"{name},,\n" for name in files), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    collected = runpy.run_path(str(HOOK))

    hidden = set(collected["hiddenimports"])
    assert "chardet.models._format" in hidden
    if compiled:
        assert {"chardet.models._format__mypyc", "chardet.pipeline.orchestrator__mypyc",
                "abc123__mypyc"} <= hidden
        assert "_format__mypyc" not in hidden
        assert "orchestrator__mypyc" not in hidden
    else:
        assert not any("__mypyc" in name for name in hidden)
    assert (str(models / "models.bin"), "chardet/models") in {
        (source, destination.replace("\\", "/")) for source, destination in collected["datas"]
    }
