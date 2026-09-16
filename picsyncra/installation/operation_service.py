"""Installed-only execution facade used by the protected WEB API."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import threading
import time
from typing import Protocol
from uuid import uuid4

from .contracts import InstallContext, OperationRequest
from .journal import OperationJournal
from .maintenance import MaintenanceCoordinator, MaintenanceGate
from .presence import PresenceRegistry
from .session_epoch import advance_session_epoch, read_session_epoch
from .update_helper import read_active_release


class OperationUnavailable(RuntimeError):
    """A selected installed operation has no verified executor yet."""


class InstalledController(Protocol):
    def restart_backend(self) -> bool: ...

    def snapshot(self) -> dict[str, bool]: ...

    def set_autostart(self, enabled: bool) -> bool: ...


class InstalledOperationService:
    """Expose bounded installed operations without exposing system commands."""

    def __init__(self, context: InstallContext, controller: InstalledController) -> None:
        self._context = context
        self._controller = controller
        self._journal = OperationJournal(context.state_root / "operations.json")
        self._presence = PresenceRegistry()
        self._maintenance_gate = MaintenanceGate()
        self._maintenance = MaintenanceCoordinator(self._maintenance_gate, self._presence)
        self._operation_threads: dict[str, threading.Thread] = {}
        self._operation_threads_lock = threading.Lock()
        self._settings_path = context.state_root / "installation-settings.json"

    @property
    def maintenance_gate(self) -> MaintenanceGate:
        """The single admission gate shared with every installed write queue."""
        return self._maintenance_gate

    def status(self) -> dict[str, object]:
        controller = self._controller.snapshot()
        return {
            "channel": self._channel(),
            "build": str(read_active_release(self._context)),
            "backend_running": bool(controller.get("backend_running", False)),
            "autostart": bool(controller.get("autostart", False)),
            "session_epoch": read_session_epoch(self._context),
            "maintenance": self._maintenance.snapshot(),
        }

    def submit(self, request: OperationRequest, *, actor_id: str) -> dict[str, object]:
        if request.action != "restart":
            raise OperationUnavailable("Ta operacja wymaga jeszcze zweryfikowanego wykonawcy pakietu.")
        existing = self._journal.by_request_id(request.request_id)
        if existing is not None:
            return asdict(existing)
        operation = self._journal.submit(request, actor_id=actor_id)
        self._maintenance.begin(operation.operation_id, initiator_id=actor_id)
        self._journal.transition(operation.operation_id, "draining")
        phase = self._maintenance.advance()
        self._sync_maintenance(operation.operation_id, phase)
        if phase["state"] == "ready":
            return asdict(self._execute_restart(operation.operation_id))
        self._start_maintenance_worker(operation.operation_id)
        return asdict(self._journal.read(operation.operation_id))

    def read_operation(self, operation_id: str) -> dict[str, object] | None:
        try:
            return asdict(self._journal.read(operation_id))
        except (KeyError, ValueError):
            return None

    def force_operation(self, operation_id: str) -> dict[str, object] | None:
        try:
            operation = self._journal.read(operation_id)
        except (KeyError, ValueError):
            return None
        if operation.state in {"committed", "rolled_back", "recovery_required", "failed"}:
            return None
        phase = self._maintenance.snapshot()
        if phase.get("operation_id") != operation_id:
            return None
        phase = self._maintenance.force()
        return asdict(self._sync_maintenance(operation_id, phase))

    def change_channel(self, channel: str) -> dict[str, object]:
        if channel not in {"stable", "dev"}:
            raise ValueError("channel is invalid")
        self._write_settings({"channel": channel})
        return {"channel": channel}

    def set_autostart(self, enabled: bool) -> dict[str, object]:
        if not isinstance(enabled, bool):
            raise ValueError("autostart is invalid")
        return {"autostart": self._controller.set_autostart(enabled)}

    def heartbeat(self, user_id: str, session_id: str) -> dict[str, object]:
        self._presence.heartbeat(user_id, session_id)
        phase = self._maintenance.advance()
        return {
            "state": phase["state"],
            "active_tasks": phase["active_tasks"],
            "other_users": phase["other_users"],
            "deadline_utc": phase["deadline_utc"],
            "session_epoch": read_session_epoch(self._context),
        }

    def public_status(self) -> dict[str, object]:
        phase = self._maintenance.snapshot()
        return {
            "state": phase["state"],
            "active_tasks": phase["active_tasks"],
            "other_users": phase["other_users"],
            "deadline_utc": phase["deadline_utc"],
            "build": str(read_active_release(self._context)),
        }

    def _start_maintenance_worker(self, operation_id: str) -> None:
        with self._operation_threads_lock:
            if operation_id in self._operation_threads:
                return
            worker = threading.Thread(
                target=self._wait_for_maintenance_then_restart,
                args=(operation_id,),
                name=f"PicSyncraMaintenance-{operation_id}",
                daemon=True,
            )
            self._operation_threads[operation_id] = worker
            worker.start()

    def _wait_for_maintenance_then_restart(self, operation_id: str) -> None:
        try:
            while True:
                phase = self._maintenance.advance()
                self._sync_maintenance(operation_id, phase)
                if phase["state"] == "ready":
                    self._execute_restart(operation_id)
                    return
                time.sleep(0.2)
        finally:
            with self._operation_threads_lock:
                self._operation_threads.pop(operation_id, None)

    def _execute_restart(self, operation_id: str):
        try:
            self._journal.transition(operation_id, "stopping")
            self._journal.transition(operation_id, "installing")
            self._restart()
            self._journal.transition(operation_id, "validating")
            if not bool(self._controller.snapshot().get("backend_running", False)):
                return self._journal.transition(operation_id, "failed", error_code="validation_failed")
            snapshot = self._journal.transition(operation_id, "committed")
            advance_session_epoch(self._context)
            return snapshot
        except Exception:
            return self._journal.transition(operation_id, "failed", error_code="apply_failed")
        finally:
            if self._maintenance_gate.wait_for_drain(timeout=0):
                self._maintenance_gate.complete(operation_id)

    def _sync_maintenance(self, operation_id: str, phase: dict[str, object]):
        deadline = phase.get("deadline_utc")
        return self._journal.update_runtime(
            operation_id,
            active_tasks=int(phase.get("active_tasks", 0)),
            other_users=int(phase.get("other_users", 0)),
            deadline_utc=None if deadline is None else str(deadline),
            force_allowed=bool(phase.get("force_allowed", False)),
        )

    def _restart(self) -> None:
        if not self._controller.restart_backend():
            raise OperationUnavailable("Kontroler nie potwierdzil restartu backendu.")

    def _channel(self) -> str:
        try:
            payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return "stable"
        return payload.get("channel") if isinstance(payload, dict) and payload.get("channel") in {"stable", "dev"} else "stable"

    def _write_settings(self, payload: dict[str, object]) -> None:
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._settings_path.with_name(f".{self._settings_path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._settings_path)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = ["InstalledOperationService", "OperationUnavailable"]
