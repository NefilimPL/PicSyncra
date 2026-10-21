from __future__ import annotations

from pathlib import Path
import hashlib
import zipfile

import pytest

from picsyncra.installation.contracts import ComponentRef, OperationRequest, ReleaseChoice
from tests.test_installation_package_apply import context


def _choice(release_id: int = 41) -> ReleaseChoice:
    return ReleaseChoice(
        release_id, f"v{release_id}", "a" * 40, "stable", "main", "b" * 64,
        (ComponentRef("ocr", f"ocr-{release_id}", "ocr.zip", "c" * 64, 1),),
        True, None,
    )


def test_ocr_factory_accepts_only_the_signed_component_for_the_active_release(tmp_path: Path, monkeypatch) -> None:
    from picsyncra.installation import ocr_operation_factory as module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        module,
        "download_selected_components",
        lambda choice, record, staging, names: captured.update(choice=choice, record=record, staging=staging, names=names) or {"ocr": Path("ocr.zip")},
    )
    installed = context(tmp_path)
    factory = module.VerifiedOcrOperationFactory(
        installed,
        catalog=lambda channel: (_choice(),) if channel == "stable" else (),
        release_record=lambda release_id: {"id": release_id, "assets": []},
    )

    executor = factory(OperationRequest("ocr-1", "install_ocr", None, None, False))

    assert executor.__class__.__name__ == "StagedOcrExecutor"
    assert captured["choice"] == _choice()
    assert captured["names"] == {"ocr"}


def test_ocr_factory_rejects_a_component_not_matching_the_active_release(tmp_path: Path) -> None:
    from picsyncra.installation.ocr_operation_factory import OcrSelectionError, VerifiedOcrOperationFactory

    factory = VerifiedOcrOperationFactory(
        context(tmp_path), catalog=lambda _channel: (_choice(43),), release_record=lambda _id: None
    )
    with pytest.raises(OcrSelectionError, match="active"):
        factory(OperationRequest("ocr-1", "install_ocr", None, None, False))


def test_staged_ocr_executor_refuses_a_component_from_another_release(tmp_path: Path) -> None:
    from picsyncra.installation.ocr_executor import OcrExecutorError, StagedOcrExecutor

    installed = context(tmp_path)
    archive = tmp_path / "ocr.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("PicSyncra-OCR.exe", b"ocr")
    raw = archive.read_bytes()
    component = ComponentRef("ocr", "ocr-42", "ocr.zip", hashlib.sha256(raw).hexdigest(), len(raw))
    executor = StagedOcrExecutor(installed, _choice(42), component, archive)

    with pytest.raises(OcrExecutorError, match="active release"):
        executor.apply(OperationRequest("ocr-1", "install_ocr", None, None, False))
