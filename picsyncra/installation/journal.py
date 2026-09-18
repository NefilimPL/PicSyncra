"""Durable, idempotent operation state for installed maintenance work."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

from .contracts import Action, OperationRequest, OperationSnapshot, OperationState


class OperationConflict(RuntimeError):
    """Another update, restart or component installation is still active."""


class OperationJournalError(RuntimeError):
    """The persisted operation journal is unreadable or unsafe to use."""


_ACTIONS = frozenset({"update", "downgrade", "install_ocr", "restart"})
_TERMINAL = frozenset({"committed", "rolled_back", "recovery_required", "failed"})
_TRANSITIONS: dict[str, frozenset[str]] = {
    "downloading": frozenset({"verified", "draining", "failed"}),
    "verified": frozenset({"draining", "failed"}),
    "draining": frozenset({"countdown", "stopping", "backing_up", "failed"}),
    "countdown": frozenset({"stopping", "backing_up", "failed"}),
    "stopping": frozenset({"backing_up", "installing", "failed"}),
    "backing_up": frozenset({"installing", "migrating", "validating", "rolling_back", "failed"}),
    "installing": frozenset({"migrating", "validating", "rolling_back", "failed"}),
    "migrating": frozenset({"validating", "rolling_back", "recovery_required", "failed"}),
    "validating": frozenset({"committed", "rolling_back", "recovery_required", "failed"}),
    "rolling_back": frozenset({"rolled_back", "recovery_required"}),
}


def _valid_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128 or any(character in value for character in "\\/\x00"):
        raise ValueError(f"{name} is invalid")
    return value


def _snapshot_from_payload(payload: object) -> OperationSnapshot:
    if not isinstance(payload, dict) or set(payload) != {
        "operation_id", "state", "action", "target_release_id", "active_tasks", "queued_tasks",
        "other_users", "deadline_utc", "force_allowed", "error_code",
    }:
        raise OperationJournalError("The operation journal contains an invalid snapshot.")
    operation_id = _valid_id(payload["operation_id"], name="operation")
    state = payload["state"]
    action = payload["action"]
    target = payload["target_release_id"]
    counts = (payload["active_tasks"], payload["queued_tasks"], payload["other_users"])
    if (
        state not in _TRANSITIONS and state not in _TERMINAL
        or action not in _ACTIONS
        or (target is not None and (isinstance(target, bool) or not isinstance(target, int) or target <= 0))
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts)
        or (payload["deadline_utc"] is not None and not isinstance(payload["deadline_utc"], str))
        or not isinstance(payload["force_allowed"], bool)
        or (payload["error_code"] is not None and not isinstance(payload["error_code"], str))
    ):
        raise OperationJournalError("The operation journal contains invalid values.")
    return OperationSnapshot(
        operation_id=operation_id,
        state=state,  # type: ignore[arg-type]
        action=action,  # type: ignore[arg-type]
        target_release_id=target,
        active_tasks=counts[0],
        queued_tasks=counts[1],
        other_users=counts[2],
        deadline_utc=payload["deadline_utc"],
        force_allowed=payload["force_allowed"],
        error_code=payload["error_code"],
    )


class OperationJournal:
    """Keep request idempotency and the only active maintenance operation."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._operations: dict[str, OperationSnapshot] = {}
        self._requests: dict[str, str] = {}
        self._load()

    def submit(self, request: OperationRequest, *, actor_id: str) -> OperationSnapshot:
        request_id = _valid_id(request.request_id, name="request")
        _valid_id(actor_id, name="actor")
        if request.action not in _ACTIONS:
            raise ValueError("action is invalid")
        with self._lock:
            existing_id = self._requests.get(request_id)
            if existing_id is not None:
                return self._operations[existing_id]
            if any(item.state not in _TERMINAL for item in self._operations.values()):
                raise OperationConflict("Another maintenance operation is active.")
            target = request.release_id
            if request.action in {"update", "downgrade"} and (not isinstance(target, int) or isinstance(target, bool) or target <= 0):
                raise ValueError("release operations require a release identifier")
            if request.action in {"restart", "install_ocr"} and target is not None:
                raise ValueError("this operation cannot target a release")
            operation = OperationSnapshot(
                operation_id=f"op-{uuid4().hex}", state="downloading", action=request.action,
                target_release_id=target, active_tasks=0, queued_tasks=0, other_users=0,
                deadline_utc=None, force_allowed=False, error_code=None,
            )
            self._operations[operation.operation_id] = operation
            self._requests[request_id] = operation.operation_id
            self._persist()
            return operation

    def read(self, operation_id: str) -> OperationSnapshot:
        with self._lock:
            return self._operations[_valid_id(operation_id, name="operation")]

    def by_request_id(self, request_id: str) -> OperationSnapshot | None:
        """Return an existing idempotency result without creating work."""
        with self._lock:
            operation_id = self._requests.get(_valid_id(request_id, name="request"))
            return self._operations.get(operation_id) if operation_id is not None else None

    def unfinished(self) -> OperationSnapshot | None:
        """Return the sole durable operation that needs startup recovery."""
        with self._lock:
            active = [item for item in self._operations.values() if item.state not in _TERMINAL]
            if len(active) > 1:
                raise OperationJournalError("More than one unfinished operation exists.")
            return active[0] if active else None

    def transition(self, operation_id: str, state: OperationState, *, error_code: str | None = None) -> OperationSnapshot:
        with self._lock:
            current = self.read(operation_id)
            if current.state in _TERMINAL:
                raise ValueError("A terminal operation cannot change state.")
            if state not in _TRANSITIONS.get(current.state, frozenset()):
                raise ValueError("The operation state transition is invalid.")
            next_snapshot = OperationSnapshot(
                **{**asdict(current), "state": state, "error_code": error_code}
            )
            self._operations[current.operation_id] = next_snapshot
            self._persist()
            return next_snapshot

    def update_runtime(
        self,
        operation_id: str,
        *,
        active_tasks: int,
        other_users: int,
        deadline_utc: str | None,
        force_allowed: bool,
    ) -> OperationSnapshot:
        """Persist live drain details without changing the operation state."""
        if (
            isinstance(active_tasks, bool) or not isinstance(active_tasks, int) or active_tasks < 0
            or isinstance(other_users, bool) or not isinstance(other_users, int) or other_users < 0
            or (deadline_utc is not None and not isinstance(deadline_utc, str))
            or not isinstance(force_allowed, bool)
        ):
            raise ValueError("runtime operation details are invalid")
        with self._lock:
            current = self.read(operation_id)
            next_snapshot = OperationSnapshot(
                **{
                    **asdict(current),
                    "active_tasks": active_tasks,
                    "other_users": other_users,
                    "deadline_utc": deadline_utc,
                    "force_allowed": force_allowed,
                }
            )
            self._operations[current.operation_id] = next_snapshot
            self._persist()
            return next_snapshot

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise OperationJournalError("Cannot read the installed operation journal.") from exc
        if not isinstance(raw, dict) or set(raw) != {"schema", "operations", "requests"} or raw["schema"] != 1:
            raise OperationJournalError("The installed operation journal has an invalid schema.")
        if not isinstance(raw["operations"], dict) or not isinstance(raw["requests"], dict):
            raise OperationJournalError("The installed operation journal has invalid entries.")
        self._operations = {str(key): _snapshot_from_payload(value) for key, value in raw["operations"].items()}
        self._requests = { _valid_id(key, name="request"): _valid_id(value, name="operation") for key, value in raw["requests"].items() }
        if any(operation_id not in self._operations for operation_id in self._requests.values()):
            raise OperationJournalError("The installed operation journal has a dangling request.")

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{uuid4().hex}.tmp")
        payload = {
            "schema": 1,
            "operations": {key: asdict(value) for key, value in self._operations.items()},
            "requests": self._requests,
        }
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = ["OperationConflict", "OperationJournal", "OperationJournalError"]
