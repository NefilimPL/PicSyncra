from __future__ import annotations

from pathlib import Path

from picsyncra.installation.contracts import BackupReceipt, OperationRequest


def request(request_id: str = "request-1", action: str = "update") -> OperationRequest:
    return OperationRequest(
        request_id=request_id,
        action=action,  # type: ignore[arg-type]
        release_id=42 if action in {"update", "downgrade"} else None,
        restore_backup_id=None,
        acknowledge_data_loss=False,
    )


def receipt(operation_id: str) -> BackupReceipt:
    return BackupReceipt(operation_id, operation_id, "a" * 64, "b" * 64, 17, 41, True)


def transaction(tmp_path: Path, events: list[str], *, apply_fails=False, rollback_fails=False, valid=True):
    from picsyncra.installation.journal import OperationJournal
    from picsyncra.installation.update_transaction import UpdateTransaction

    def backup(operation_id: str) -> BackupReceipt:
        events.append("backup")
        return receipt(operation_id)

    def apply(_request: OperationRequest) -> None:
        events.append("apply")
        if apply_fails:
            raise RuntimeError("apply failed")

    def rollback(_backup: BackupReceipt) -> None:
        events.append("rollback")
        if rollback_fails:
            raise RuntimeError("rollback failed")

    def validate(_request: OperationRequest) -> bool:
        events.append("validate")
        return valid

    return UpdateTransaction(OperationJournal(tmp_path / "operations.json"), backup, apply, validate, rollback)


def test_update_creates_backup_before_apply_and_commits_only_after_validation(tmp_path: Path) -> None:
    events: list[str] = []
    result = transaction(tmp_path, events).execute(request(), actor_id="admin-1")

    assert result.state == "committed"
    assert events == ["backup", "apply", "validate"]


def test_backup_failure_stops_before_any_version_change(tmp_path: Path) -> None:
    from picsyncra.installation.journal import OperationJournal
    from picsyncra.installation.update_transaction import UpdateTransaction

    events: list[str] = []

    def backup(_operation_id: str):
        events.append("backup")
        raise RuntimeError("disk full")

    transaction_instance = UpdateTransaction(
        OperationJournal(tmp_path / "operations.json"), backup,
        lambda _request: events.append("apply"), lambda _request: True,
        lambda _receipt: events.append("rollback"),
    )
    result = transaction_instance.execute(request(), actor_id="admin-1")

    assert result.state == "failed"
    assert result.error_code == "backup_failed"
    assert events == ["backup"]


def test_failed_install_rolls_back_from_the_verified_backup(tmp_path: Path) -> None:
    events: list[str] = []
    result = transaction(tmp_path, events, apply_fails=True).execute(request(), actor_id="admin-1")

    assert result.state == "rolled_back"
    assert result.error_code == "apply_failed"
    assert events == ["backup", "apply", "rollback"]


def test_failed_rollback_requires_explicit_recovery_and_keeps_original_error(tmp_path: Path) -> None:
    events: list[str] = []
    result = transaction(tmp_path, events, valid=False, rollback_fails=True).execute(request(), actor_id="admin-1")

    assert result.state == "recovery_required"
    assert result.error_code == "validation_failed"
    assert events == ["backup", "apply", "validate", "rollback"]


def test_restart_does_not_create_a_database_backup(tmp_path: Path) -> None:
    events: list[str] = []
    result = transaction(tmp_path, events).execute(request(action="restart"), actor_id="admin-1")

    assert result.state == "committed"
    assert events == ["apply", "validate"]
