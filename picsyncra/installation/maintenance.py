"""Drain and countdown state machine for installed restart and update operations."""

from __future__ import annotations

from collections.abc import Callable
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .presence import PresenceRegistry


class MaintenanceLease:
    """One admitted write operation, released exactly once by its owner."""

    def __init__(self, gate: "MaintenanceGate", token: int) -> None:
        self._gate = gate
        self._token = token

    def finish(self) -> bool:
        return self._gate._finish(self._token)


class MaintenanceGate:
    """Atomically reject new mutating work after draining begins."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._operation_id: str | None = None
        self._initiator_id: str | None = None
        self._leases: dict[int, tuple[str, Callable[[], None] | None]] = {}
        self._next_token = 0
        self._force_requested = False

    def try_admit(
        self, kind: str, *, on_cancel: Callable[[], None] | None = None
    ) -> MaintenanceLease | None:
        if not isinstance(kind, str) or not kind:
            raise ValueError("kind must be a non-empty string")
        with self._condition:
            if self._operation_id is not None:
                return None
            self._next_token += 1
            token = self._next_token
            self._leases[token] = (kind, on_cancel)
            return MaintenanceLease(self, token)

    def begin(self, operation_id: str, *, initiator_id: str) -> None:
        if not isinstance(operation_id, str) or not operation_id or not isinstance(initiator_id, str) or not initiator_id:
            raise ValueError("operation_id and initiator_id must be non-empty strings")
        with self._condition:
            if self._operation_id is None:
                self._operation_id = operation_id
                self._initiator_id = initiator_id
                return
            if self._operation_id != operation_id:
                raise RuntimeError("maintenance is owned by another operation")

    def wait_for_drain(self, *, timeout: float | None = None) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: not self._leases, timeout=timeout)

    def request_force_cancel(self) -> int:
        with self._condition:
            if self._operation_id is None or self._force_requested:
                return 0
            self._force_requested = True
            callbacks = tuple(callback for _kind, callback in self._leases.values() if callback is not None)
        for callback in callbacks:
            try:
                callback()
            except Exception:
                # The task remains active and still blocks restart; a failed
                # cancellation cannot turn a possibly writing task into safe work.
                continue
        return len(callbacks)

    def complete(self, operation_id: str) -> None:
        with self._condition:
            if self._operation_id != operation_id:
                raise RuntimeError("maintenance is not owned by this operation")
            if self._leases:
                raise RuntimeError("active tasks must finish before maintenance completes")
            self._operation_id = None
            self._initiator_id = None
            self._force_requested = False
            self._condition.notify_all()

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            by_kind: dict[str, int] = {}
            for kind, _callback in self._leases.values():
                by_kind[kind] = by_kind.get(kind, 0) + 1
            return {
                "state": "idle" if self._operation_id is None else "draining",
                "operation_id": self._operation_id,
                "initiator_id": self._initiator_id,
                "active_tasks": len(self._leases),
                "active_by_kind": by_kind,
                "force_requested": self._force_requested,
            }

    def _finish(self, token: int) -> bool:
        with self._condition:
            if token not in self._leases:
                return False
            del self._leases[token]
            self._condition.notify_all()
            return True


class MaintenanceCoordinator:
    """Add user warning timing to the gate without reopening it during countdown."""

    def __init__(
        self,
        gate: MaintenanceGate,
        presence: "PresenceRegistry",
        *,
        clock: Callable[[], float] = time.monotonic,
        countdown_seconds: float = 120.0,
    ) -> None:
        if countdown_seconds < 0:
            raise ValueError("countdown_seconds cannot be negative")
        self._gate = gate
        self._presence = presence
        self._clock = clock
        self._countdown_seconds = countdown_seconds
        self._state = "idle"
        self._operation_id: str | None = None
        self._initiator_id: str | None = None
        self._deadline: float | None = None

    def begin(self, operation_id: str, *, initiator_id: str) -> None:
        if self._state not in {"idle", "ready"} and self._operation_id != operation_id:
            raise RuntimeError("maintenance coordinator is busy")
        self._gate.begin(operation_id, initiator_id=initiator_id)
        self._operation_id = operation_id
        self._initiator_id = initiator_id
        self._deadline = None
        self._state = "draining"

    def advance(self) -> dict[str, object]:
        if self._state == "draining":
            gate_state = self._gate.snapshot()
            if int(gate_state["active_tasks"]) == 0:
                other_users = self._presence.other_user_count(self._initiator_id or "")
                if other_users:
                    self._deadline = self._clock() + self._countdown_seconds
                    self._state = "countdown"
                else:
                    self._state = "ready"
        elif self._state == "countdown" and self._deadline is not None and self._clock() >= self._deadline:
            self._state = "ready"
        return self.snapshot()

    def force(self) -> dict[str, object]:
        self._gate.request_force_cancel()
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        state = self._gate.snapshot()
        return {
            **state,
            "state": self._state if self._state != "idle" else state["state"],
            "other_users": self._presence.other_user_count(self._initiator_id or "")
            if self._initiator_id is not None else 0,
            "deadline_utc": self._deadline,
            "force_allowed": self._state == "draining" and int(state["active_tasks"]) > 0,
        }
