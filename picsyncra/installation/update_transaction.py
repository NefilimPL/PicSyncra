"""Fail-closed execution of an installed update, OCR install or restart."""

from __future__ import annotations

from collections.abc import Callable

from .contracts import BackupReceipt, OperationRequest, OperationSnapshot
from .journal import OperationJournal


BackupCreator = Callable[[str], BackupReceipt]
ApplyOperation = Callable[[OperationRequest], None]
ValidateOperation = Callable[[OperationRequest], bool]
RollbackOperation = Callable[[BackupReceipt], None]


class UpdateTransaction:
    """Execute one journaled operation without ever bypassing its backup.

    The callbacks are intentionally narrow: package download and file exchange
    happen in ``apply`` only after the durable pre-operation snapshot exists;
    rollback receives that exact verified snapshot.
    """

    def __init__(
        self,
        journal: OperationJournal,
        create_backup: BackupCreator,
        apply: ApplyOperation,
        validate: ValidateOperation,
        rollback: RollbackOperation,
    ) -> None:
        self._journal = journal
        self._create_backup = create_backup
        self._apply = apply
        self._validate = validate
        self._rollback = rollback

    def execute(self, request: OperationRequest, *, actor_id: str) -> OperationSnapshot:
        """Run the operation and persist its final state before returning."""
        operation = self._journal.submit(request, actor_id=actor_id)
        if operation.state in {"committed", "rolled_back", "recovery_required", "failed"}:
            return operation
        operation_id = operation.operation_id
        self._journal.transition(operation_id, "draining")
        backup: BackupReceipt | None = None
        if request.action == "restart":
            self._journal.transition(operation_id, "stopping")
        else:
            self._journal.transition(operation_id, "backing_up")
            try:
                backup = self._create_backup(operation_id)
            except Exception:
                return self._journal.transition(operation_id, "failed", error_code="backup_failed")
        self._journal.transition(operation_id, "installing")
        try:
            self._apply(request)
        except Exception:
            return self._rollback_after_failure(operation_id, backup, "apply_failed")
        self._journal.transition(operation_id, "validating")
        try:
            valid = self._validate(request)
        except Exception:
            valid = False
        if not valid:
            return self._rollback_after_failure(operation_id, backup, "validation_failed")
        return self._journal.transition(operation_id, "committed")

    def _rollback_after_failure(
        self, operation_id: str, backup: BackupReceipt | None, error_code: str
    ) -> OperationSnapshot:
        if backup is None:
            return self._journal.transition(operation_id, "failed", error_code=error_code)
        self._journal.transition(operation_id, "rolling_back", error_code=error_code)
        try:
            self._rollback(backup)
        except Exception:
            return self._journal.transition(
                operation_id, "recovery_required", error_code=error_code
            )
        return self._journal.transition(operation_id, "rolled_back", error_code=error_code)


__all__ = ["UpdateTransaction"]
