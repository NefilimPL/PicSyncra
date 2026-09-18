from __future__ import annotations

from pathlib import Path

from picsyncra.installation.contracts import OperationRequest, ReleaseChoice
from tests.test_installation_package_apply import archive, choice, context


def test_executor_switches_only_the_verified_requested_release(tmp_path: Path) -> None:
    from picsyncra.installation.release_executor import StagedReleaseExecutor

    staged = tmp_path / "staged"
    staged.mkdir()
    web = archive(staged / "web.zip", "PicSyncra-WEB.exe")
    migrator = archive(staged / "migrator.zip", "PicSyncra-Migrator.exe")
    executor = StagedReleaseExecutor(context(tmp_path), choice(web, migrator), {"web": staged / "web.zip", "migrator": staged / "migrator.zip"})
    request = OperationRequest("request-1", "update", 42, None, False)

    executor.apply(request)

    assert executor.validate(request) is True


def test_executor_upgrades_an_already_installed_ocr_component_with_the_release(tmp_path: Path) -> None:
    from picsyncra.installation.ocr_component import resolve_active_ocr_component
    from picsyncra.installation.release_executor import StagedReleaseExecutor

    staged = tmp_path / "staged"
    staged.mkdir()
    installed = context(tmp_path)
    web = archive(staged / "web.zip", "PicSyncra-WEB.exe")
    migrator = archive(staged / "migrator.zip", "PicSyncra-Migrator.exe")
    ocr = archive(staged / "ocr.zip", "PicSyncra-OCR.exe")
    ocr = type(ocr)("ocr", "ocr-42", ocr.asset_name, ocr.sha256, ocr.size)
    release = ReleaseChoice(
        42, "v42", "a" * 40, "stable", "main", "b" * 64,
        (web, migrator, ocr), True, None,
    )
    executor = StagedReleaseExecutor(
        installed,
        release,
        {"web": staged / "web.zip", "migrator": staged / "migrator.zip", "ocr": staged / "ocr.zip"},
        ocr_component=ocr,
        ocr_archive=staged / "ocr.zip",
    )
    request = OperationRequest("request-ocr", "update", 42, None, False)

    executor.apply(request)

    active = resolve_active_ocr_component(installed)
    assert executor.validate(request) is True
    assert active is not None
    assert active.component_id == "ocr-42"


def test_executor_restores_the_previous_ocr_marker_when_release_rollback_runs(tmp_path: Path) -> None:
    from picsyncra.installation.ocr_component import resolve_active_ocr_component
    from picsyncra.installation.release_executor import StagedReleaseExecutor

    staged = tmp_path / "staged"
    staged.mkdir()
    installed = context(tmp_path)
    old_root = installed.program_root / "components" / "ocr"
    (old_root / "ocr-41").mkdir(parents=True)
    (old_root / "ocr-41" / "PicSyncra-OCR.exe").write_bytes(b"old")
    (old_root / "active.json").write_text(
        '{"schema":1,"release_id":41,"component_id":"ocr-41","build_id":"release-41","protocol":1}',
        encoding="utf-8",
    )
    web = archive(staged / "web.zip", "PicSyncra-WEB.exe")
    migrator = archive(staged / "migrator.zip", "PicSyncra-Migrator.exe")
    archive_ref = archive(staged / "ocr.zip", "PicSyncra-OCR.exe")
    ocr = type(archive_ref)("ocr", "ocr-42", archive_ref.asset_name, archive_ref.sha256, archive_ref.size)
    release = ReleaseChoice(42, "v42", "a" * 40, "stable", "main", "b" * 64, (web, migrator, ocr), True, None)
    executor = StagedReleaseExecutor(
        installed, release,
        {"web": staged / "web.zip", "migrator": staged / "migrator.zip", "ocr": staged / "ocr.zip"},
        ocr_component=ocr, ocr_archive=staged / "ocr.zip",
    )
    request = OperationRequest("request-rollback", "update", 42, None, False)

    executor.apply(request)
    executor.rollback(None)  # type: ignore[arg-type]  # Backup data is not read by this executor.

    active = resolve_active_ocr_component(installed)
    assert active is not None
    assert active.component_id == "ocr-41"
