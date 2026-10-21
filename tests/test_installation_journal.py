from __future__ import annotations

from pathlib import Path

import pytest

from picsyncra.installation.contracts import OperationRequest


def request(request_id: str, *, action: str = "update") -> OperationRequest:
    return OperationRequest(
        request_id=request_id,
        action=action,  # type: ignore[arg-type]
        release_id=42 if action in {"update", "downgrade"} else None,
        restore_backup_id=None,
        acknowledge_data_loss=False,
    )


def test_journal_makes_the_same_request_idempotent_after_restart(tmp_path: Path) -> None:
    from picsyncra.installation.journal import OperationJournal

    path = tmp_path / "state" / "operations.json"
    first = OperationJournal(path)
    submitted = first.submit(request("request-1"), actor_id="admin-1")
    reloaded = OperationJournal(path)

    repeated = reloaded.submit(request("request-1"), actor_id="admin-1")
    assert repeated == submitted
    assert reloaded.read(submitted.operation_id) == submitted


def test_journal_blocks_a_second_unfinished_operation_but_allows_one_after_commit(tmp_path: Path) -> None:
    from picsyncra.installation.journal import OperationConflict, OperationJournal

    journal = OperationJournal(tmp_path / "operations.json")
    initial = journal.submit(request("request-1"), actor_id="admin-1")
    with pytest.raises(OperationConflict):
        journal.submit(request("request-2", action="restart"), actor_id="admin-1")

    journal.transition(initial.operation_id, "draining")
    journal.transition(initial.operation_id, "backing_up")
    journal.transition(initial.operation_id, "validating")
    committed = journal.transition(initial.operation_id, "committed")
    following = journal.submit(request("request-2", action="restart"), actor_id="admin-1")
    assert committed.state == "committed"
    assert following.action == "restart"


def test_journal_persists_only_valid_state_transitions(tmp_path: Path) -> None:
    from picsyncra.installation.journal import OperationJournal

    journal = OperationJournal(tmp_path / "operations.json")
    initial = journal.submit(request("request-1"), actor_id="admin-1")
    assert journal.transition(initial.operation_id, "draining").state == "draining"
    assert journal.transition(initial.operation_id, "backing_up").state == "backing_up"
    assert journal.transition(initial.operation_id, "installing").state == "installing"
    assert journal.transition(initial.operation_id, "validating").state == "validating"
    assert journal.transition(initial.operation_id, "committed").state == "committed"

    with pytest.raises(ValueError, match="terminal"):
        journal.transition(initial.operation_id, "installing")


def test_journal_rejects_invalid_actor_and_unknown_operation(tmp_path: Path) -> None:
    from picsyncra.installation.journal import OperationJournal

    journal = OperationJournal(tmp_path / "operations.json")
    with pytest.raises(ValueError, match="actor"):
        journal.submit(request("request-1"), actor_id="")
    with pytest.raises(KeyError):
        journal.read("op-missing")
