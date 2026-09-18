"""Publish a previously verified installed-release bundle without overwrites."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
from uuid import uuid4
import zipfile

from .contracts import ComponentRef, InstallContext, ReleaseChoice


class PackageApplyError(RuntimeError):
    """A signed release component cannot safely become an installed bundle."""


_REQUIRED = frozenset({"web", "migrator"})
_SEPARATELY_INSTALLED = frozenset({"ocr"})
_MAX_FILES_PER_COMPONENT = 20_000
_MAX_UNPACKED_BYTES = 4 * 1024 * 1024 * 1024


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def _root(context: InstallContext) -> Path:
    try:
        root = context.program_root.resolve(strict=True)
    except OSError as exc:
        raise PackageApplyError("Installed program directory is unavailable.") from exc
    if context.program_root.is_symlink() or not root.is_dir():
        raise PackageApplyError("Installed program directory is unsafe.")
    return root


def _member_path(name: str) -> Path:
    member = Path(name)
    if not name or member.is_absolute() or "\\" in name or any(part in {"", ".", ".."} for part in member.parts):
        raise PackageApplyError("Release archive contains an unsafe path.")
    return member


def _extract(component: ComponentRef, archive: Path, destination: Path) -> None:
    if not archive.is_file() or archive.is_symlink() or _digest(archive) != component.sha256:
        raise PackageApplyError("Staged release component changed after verification.")
    try:
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            if not entries or len(entries) > _MAX_FILES_PER_COMPONENT:
                raise PackageApplyError("Release archive has an invalid file count.")
            total = 0
            for info in entries:
                path = _member_path(info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise PackageApplyError("Release archive contains a symbolic link.")
                total += info.file_size
                if total > _MAX_UNPACKED_BYTES:
                    raise PackageApplyError("Release archive is too large when unpacked.")
                if info.is_dir():
                    continue
                target = destination / path
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as input_file, target.open("xb") as output_file:
                    shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackageApplyError("Release archive cannot be unpacked safely.") from exc


def install_release_packages(
    context: InstallContext,
    choice: ReleaseChoice,
    staged_components: dict[str, Path],
) -> int:
    """Publish all signed components as one new immutable version directory.

    The active pointer is intentionally not changed here. The maintenance
    transaction switches it only after the required backup and validation.
    """
    if not choice.can_install or _REQUIRED - {component.name for component in choice.components}:
        raise PackageApplyError("Release is not a complete installable bundle.")
    root = _root(context)
    versions = root / "versions"
    final = versions / str(choice.release_id)
    if final.exists() or final.is_symlink():
        raise PackageApplyError("This release is already present in the installation.")
    temporary = versions / f".{choice.release_id}.{uuid4().hex}.tmp"
    try:
        versions.mkdir(exist_ok=True)
        temporary.mkdir()
        for component in choice.components:
            if component.name in _SEPARATELY_INSTALLED:
                continue
            archive = staged_components.get(component.name)
            if archive is None:
                raise PackageApplyError("A signed release component is missing from staging.")
            destination = temporary / component.name
            destination.mkdir()
            _extract(component, Path(archive), destination)
        os.replace(temporary, final)
        return choice.release_id
    except (OSError, PackageApplyError) as exc:
        raise exc if isinstance(exc, PackageApplyError) else PackageApplyError("Cannot publish release bundle.") from exc
    finally:
        if temporary.exists() and not temporary.is_symlink():
            shutil.rmtree(temporary, ignore_errors=True)


__all__ = ["PackageApplyError", "install_release_packages"]
