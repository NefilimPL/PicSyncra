"""Transactional adapter for an already verified, staged release bundle."""

from __future__ import annotations

from pathlib import Path

from .backups import create_operation_backup
from .contracts import BackupReceipt, InstallContext, OperationRequest, ReleaseChoice
from .package_apply import install_release_packages
from .update_helper import activate_release, read_active_release


class ReleaseExecutorError(RuntimeError):
    """A staged release cannot safely be made active."""


class StagedReleaseExecutor:
    """Adapter for ``UpdateTransaction``; never downloads or trusts URLs itself."""

    def __init__(self, context: InstallContext, choice: ReleaseChoice, staged: dict[str, Path]) -> None:
        self._context = context
        self._choice = choice
        self._staged = {name: Path(path) for name, path in staged.items()}
        self._previous_release: int | None = None

    def create_backup(self, operation_id: str) -> BackupReceipt:
        return create_operation_backup(self._context, operation_id)

    def apply(self, request: OperationRequest) -> None:
        if request.action not in {"update", "downgrade"} or request.release_id != self._choice.release_id:
            raise ReleaseExecutorError("The request does not match the verified staged release.")
        self._previous_release = read_active_release(self._context)
        install_release_packages(self._context, self._choice, self._staged)
        activate_release(self._context, self._choice.release_id)

    def validate(self, request: OperationRequest) -> bool:
        return request.release_id == self._choice.release_id and read_active_release(self._context) == self._choice.release_id

    def rollback(self, _backup: BackupReceipt) -> None:
        if self._previous_release is None:
            raise ReleaseExecutorError("No previous release is available for rollback.")
        activate_release(self._context, self._previous_release)


__all__ = ["ReleaseExecutorError", "StagedReleaseExecutor"]
