from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

import pytest

from picsyncra.installation.contracts import ComponentRef, InstallContext, ReleaseChoice


def context(tmp_path: Path) -> InstallContext:
    program = tmp_path / "program"
    state = tmp_path / "state"
    (program / "versions" / "41").mkdir(parents=True)
    (state / "config").mkdir(parents=True)
    (program / "active.json").write_text(
        '{"schema":1,"installation_id":"site-1","release_id":41}', encoding="utf-8"
    )
    return InstallContext("site-1", program, state, state / "config", state / "data.sqlite")


def archive(path: Path, member: str, data: bytes = b"exe") -> ComponentRef:
    with zipfile.ZipFile(path, "w") as output:
        output.writestr(member, data)
    raw = path.read_bytes()
    return ComponentRef(path.stem, path.stem, path.name, hashlib.sha256(raw).hexdigest(), len(raw))


def choice(web: ComponentRef, migrator: ComponentRef) -> ReleaseChoice:
    return ReleaseChoice(42, "v42", "a" * 40, "stable", "main", "b" * 64, (web, migrator), True, None)


def test_installer_publishes_a_complete_new_release_without_touching_active_one(tmp_path: Path) -> None:
    from picsyncra.installation.package_apply import install_release_packages

    staged = tmp_path / "staged"
    staged.mkdir()
    installed = context(tmp_path)
    web = archive(staged / "web.zip", "PicSyncra-WEB.exe")
    migrator = archive(staged / "migrator.zip", "PicSyncra-Migrator.exe")

    result = install_release_packages(installed, choice(web, migrator), {"web": staged / "web.zip", "migrator": staged / "migrator.zip"})

    assert result == 42
    assert (installed.program_root / "versions" / "42" / "web" / "PicSyncra-WEB.exe").is_file()
    assert (installed.program_root / "versions" / "42" / "migrator" / "PicSyncra-Migrator.exe").is_file()
    assert installed.program_root.joinpath("active.json").read_text(encoding="utf-8").find('"release_id":41') >= 0


def test_installer_rejects_zip_traversal_and_removes_incomplete_release(tmp_path: Path) -> None:
    from picsyncra.installation.package_apply import PackageApplyError, install_release_packages

    staged = tmp_path / "staged"
    staged.mkdir()
    installed = context(tmp_path)
    web = archive(staged / "web.zip", "../outside.exe")
    migrator = archive(staged / "migrator.zip", "PicSyncra-Migrator.exe")

    with pytest.raises(PackageApplyError):
        install_release_packages(installed, choice(web, migrator), {"web": staged / "web.zip", "migrator": staged / "migrator.zip"})
    assert not (installed.program_root / "versions" / "42").exists()
