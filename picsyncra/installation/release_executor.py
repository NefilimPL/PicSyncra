"""Transactional adapter for an already verified, staged release bundle."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from .backups import create_operation_backup
from .contracts import BackupReceipt, ComponentRef, InstallContext, OperationRequest, ReleaseChoice
from .ocr_component import resolve_active_ocr_component
from .ocr_install import install_ocr_component
from .package_apply import PackageApplyError
from .package_apply import install_release_packages
from .update_helper import activate_release, read_active_release


class ReleaseExecutorError(RuntimeError):
    """A staged release cannot safely be made active."""


class StagedReleaseExecutor:
    """Adapter for ``UpdateTransaction``; never downloads or trusts URLs itself."""

    def __init__(
        self,
        context: InstallContext,
        choice: ReleaseChoice,
        staged: dict[str, Path],
        *,
        ocr_component: ComponentRef | None = None,
        ocr_archive: Path | None = None,
    ) -> None:
        if (ocr_component is None) != (ocr_archive is None):
            raise ValueError("OCR component and archive must be provided together.")
        if ocr_component is not None and (
            ocr_component.name != "ocr" or ocr_component not in choice.components
        ):
            raise ValueError("OCR component must be a signed component of this release.")
        self._context = context
        self._choice = choice
        self._staged = {name: Path(path) for name, path in staged.items()}
        self._ocr_component = ocr_component
        self._ocr_archive = Path(ocr_archive) if ocr_archive is not None else None
        self._previous_release: int | None = None
        self._previous_ocr_marker: bytes | None = None
        self._ocr_marker_captured = False

    def create_backup(self, operation_id: str) -> BackupReceipt:
        receipt = create_operation_backup(self._context, operation_id)
        if self._ocr_component is not None:
            self._capture_ocr_marker()
        return receipt

    def apply(self, request: OperationRequest) -> None:
        if request.action not in {"update", "downgrade"} or request.release_id != self._choice.release_id:
            raise ReleaseExecutorError("The request does not match the verified staged release.")
        self._previous_release = read_active_release(self._context)
        if self._ocr_component is not None and not self._ocr_marker_captured:
            self._capture_ocr_marker()
        install_release_packages(self._context, self._choice, self._staged)
        activate_release(self._context, self._choice.release_id)
        if self._ocr_component is not None and self._ocr_archive is not None:
            install_ocr_component(self._context, self._ocr_component, self._ocr_archive)

    def validate(self, request: OperationRequest) -> bool:
        if request.release_id != self._choice.release_id or read_active_release(self._context) != self._choice.release_id:
            return False
        if self._ocr_component is None:
            return True
        active_ocr = resolve_active_ocr_component(self._context)
        return active_ocr is not None and active_ocr.component_id == self._ocr_component.component_id

    def rollback(self, _backup: BackupReceipt) -> None:
        if self._previous_release is None:
            raise ReleaseExecutorError("No previous release is available for rollback.")
        activate_release(self._context, self._previous_release)
        if self._ocr_component is not None:
            self._restore_ocr_marker()

    def _restore_ocr_marker(self) -> None:
        root = self._context.program_root / "components" / "ocr"
        marker = root / "active.json"
        if self._previous_ocr_marker is None:
            marker.unlink(missing_ok=True)
            return
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / f".active.{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as handle:
                handle.write(self._previous_ocr_marker)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, marker)
        except OSError as exc:
            raise PackageApplyError("Cannot restore the prior OCR component marker.") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def _capture_ocr_marker(self) -> None:
        marker = self._context.program_root / "components" / "ocr" / "active.json"
        if marker.is_symlink():
            raise ReleaseExecutorError("The OCR active marker is unsafe.")
        self._previous_ocr_marker = marker.read_bytes() if marker.is_file() else None
        self._ocr_marker_captured = True


__all__ = ["ReleaseExecutorError", "StagedReleaseExecutor"]
