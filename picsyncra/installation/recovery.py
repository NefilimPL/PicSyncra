"""Fail-closed startup recovery for an interrupted installed operation."""

from __future__ import annotations

from .contracts import InstallContext, OperationSnapshot
from .journal import OperationJournal
from .restart_handoff import RestartHandoffError, read_restart_handoff


def recover_pending_operation(context: InstallContext) -> OperationSnapshot | None:
    """Mark interrupted work for explicit recovery before writers are restarted.

    A process crash cannot establish whether an external migration or service
    restart completed. The safe result is ``recovery_required``; the durable
    backup and staged version are retained for an administrator.
    """
    journal = OperationJournal(context.state_root / "operations.json")
    pending = journal.unfinished()
    if pending is None:
        return None
    try:
        handoff = read_restart_handoff(context)
    except RestartHandoffError:
        handoff = None
    if (
        handoff is not None
        and handoff.operation_id == pending.operation_id
        and pending.state == "validating"
    ):
        # The independent controller is still checking the newly started WEB.
        # Do not convert that intentional handoff into a crash recovery while
        # the new process is importing the application.
        return None
    if pending.state not in {"backing_up", "installing", "migrating", "validating", "rolling_back"}:
        return journal.transition(pending.operation_id, "failed", error_code="interrupted_before_apply")
    if pending.state != "rolling_back":
        journal.transition(pending.operation_id, "rolling_back", error_code="interrupted_operation")
    return journal.transition(pending.operation_id, "recovery_required", error_code="interrupted_operation")


__all__ = ["recover_pending_operation"]
