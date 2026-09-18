from __future__ import annotations

from pathlib import Path

import pytest

from picsyncra.installation.contracts import ComponentRef, OperationRequest, ReleaseChoice
from tests.test_installation_package_apply import context


def release() -> ReleaseChoice:
    component = ComponentRef("web", "web", "web.zip", "a" * 64, 1)
    migrator = ComponentRef("migrator", "migrator", "migrator.zip", "b" * 64, 1)
    return ReleaseChoice(42, "v42", "c" * 40, "stable", "main", "d" * 64, (component, migrator), True, None)


def test_factory_accepts_only_a_signed_choice_from_the_selected_channel(tmp_path: Path, monkeypatch) -> None:
    from picsyncra.installation import release_operation_factory as module

    captured = {}
    monkeypatch.setattr(module, "download_selected_components", lambda choice, record, staging, names: captured.update(choice=choice, record=record, staging=staging, names=names) or {"web": Path("web.zip"), "migrator": Path("migrator.zip")})
    factory = module.VerifiedReleaseOperationFactory(context(tmp_path), catalog=lambda channel: (release(),) if channel == "stable" else (), release_record=lambda release_id: {"id": release_id, "assets": []})

    executor = factory(OperationRequest("request-1", "update", 42, None, False))

    assert executor.__class__.__name__ == "StagedReleaseExecutor"
    assert captured["choice"].release_id == 42
    assert captured["names"] == {"web", "migrator"}


def test_factory_rejects_a_release_outside_the_signed_catalog(tmp_path: Path) -> None:
    from picsyncra.installation.release_operation_factory import ReleaseSelectionError, VerifiedReleaseOperationFactory

    factory = VerifiedReleaseOperationFactory(context(tmp_path), catalog=lambda _channel: (), release_record=lambda _id: None)
    with pytest.raises(ReleaseSelectionError):
        factory(OperationRequest("request-1", "update", 42, None, False))


def test_factory_stages_compatible_ocr_only_when_ocr_is_already_installed(
    tmp_path: Path, monkeypatch
) -> None:
    from picsyncra.installation import release_operation_factory as module

    installed = context(tmp_path)
    ocr_root = installed.program_root / "components" / "ocr"
    (ocr_root / "ocr-41").mkdir(parents=True)
    (ocr_root / "ocr-41" / "PicSyncra-OCR.exe").write_bytes(b"old")
    (ocr_root / "active.json").write_text(
        '{"schema":1,"release_id":41,"component_id":"ocr-41","build_id":"release-41","protocol":1}',
        encoding="utf-8",
    )
    ocr = ComponentRef("ocr", "ocr-42", "ocr.zip", "c" * 64, 1)
    target = ReleaseChoice(
        42, "v42", "c" * 40, "stable", "main", "d" * 64,
        (*release().components, ocr), True, None,
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        module,
        "download_selected_components",
        lambda _choice, _record, _staging, names: captured.update(names=names) or {
            "web": Path("web.zip"), "migrator": Path("migrator.zip"), "ocr": Path("ocr.zip")
        },
    )

    module.VerifiedReleaseOperationFactory(
        installed,
        catalog=lambda _channel: (target,),
        release_record=lambda release_id: {"id": release_id, "assets": []},
    )(OperationRequest("request-1", "update", 42, None, False))

    assert captured["names"] == {"web", "migrator", "ocr"}
