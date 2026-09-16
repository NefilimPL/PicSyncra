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
