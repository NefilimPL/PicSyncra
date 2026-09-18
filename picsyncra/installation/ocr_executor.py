"""Transactional executor for an optional, already verified OCR archive."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from .backups import create_operation_backup
from .contracts import BackupReceipt, ComponentRef, InstallContext, OperationRequest, ReleaseChoice
from .ocr_component import resolve_active_ocr_component
from .ocr_install import install_ocr_component
from .package_apply import PackageApplyError
from .update_helper import read_active_release


class OcrExecutorError(RuntimeError):
    """The staged OCR archive cannot be activated safely."""


class StagedOcrExecutor:
    """Install one signed OCR archive and restore its marker on failure."""

    def __init__(self, context: InstallContext, choice: ReleaseChoice, component: ComponentRef, archive: Path) -> None:
        self._context = context
        self._choice = choice
        self._component = component
        self._archive = Path(archive)
        self._previous_marker: bytes | None = None

    def create_backup(self, operation_id: str) -> BackupReceipt:
        receipt = create_operation_backup(self._context, operation_id)
        marker = self._context.program_root / "components" / "ocr" / "active.json"
        if marker.is_symlink():
            raise OcrExecutorError("The OCR active marker is unsafe.")
        self._previous_marker = marker.read_bytes() if marker.is_file() else None
        return receipt

    def apply(self, request: OperationRequest) -> None:
        if request.action != "install_ocr" or request.release_id is not None:
            raise OcrExecutorError("The request does not match the staged OCR component.")
        if self._choice.release_id != read_active_release(self._context):
            raise OcrExecutorError("The staged OCR component does not match the active release.")
        if self._component not in self._choice.components:
            raise OcrExecutorError("The staged OCR component is absent from its signed release.")
        install_ocr_component(self._context, self._component, self._archive)

    def validate(self, request: OperationRequest) -> bool:
        active = resolve_active_ocr_component(self._context)
        return request.action == "install_ocr" and active is not None and active.component_id == self._component.component_id

    def rollback(self, _backup: BackupReceipt) -> None:
        root = self._context.program_root / "components" / "ocr"
        marker = root / "active.json"
        if self._previous_marker is None:
            marker.unlink(missing_ok=True)
            return
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / f".active.{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as handle:
                handle.write(self._previous_marker)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, marker)
        except OSError as exc:
            raise PackageApplyError("Cannot restore the prior OCR component marker.") from exc
        finally:
            temporary.unlink(missing_ok=True)


__all__ = ["OcrExecutorError", "StagedOcrExecutor"]
