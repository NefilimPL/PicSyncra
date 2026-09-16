from __future__ import annotations

from pathlib import Path

from picsyncra.installation.contracts import OperationRequest
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
