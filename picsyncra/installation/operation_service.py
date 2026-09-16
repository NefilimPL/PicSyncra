"""Installed-only execution facade used by the protected WEB API."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .contracts import InstallContext, OperationRequest
from .journal import OperationJournal
from .presence import PresenceRegistry
from .session_epoch import advance_session_epoch, read_session_epoch
from .update_helper import read_active_release
from .update_transaction import UpdateTransaction


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
        self._settings_path = context.state_root / "installation-settings.json"

    def status(self) -> dict[str, object]:
        controller = self._controller.snapshot()
        return {
            "channel": self._channel(),
            "build": str(read_active_release(self._context)),
            "backend_running": bool(controller.get("backend_running", False)),
            "autostart": bool(controller.get("autostart", False)),
            "session_epoch": read_session_epoch(self._context),
        }

    def submit(self, request: OperationRequest, *, actor_id: str) -> dict[str, object]:
        if request.action != "restart":
            raise OperationUnavailable("Ta operacja wymaga jeszcze zweryfikowanego wykonawcy pakietu.")
        existing = self._journal.by_request_id(request.request_id)
        if existing is not None:
            return asdict(existing)
        transaction = UpdateTransaction(
            self._journal,
            create_backup=lambda _operation_id: (_ for _ in ()).throw(AssertionError("restart does not create a backup")),
            apply=lambda _request: self._restart(),
            validate=lambda _request: bool(self._controller.snapshot().get("backend_running", False)),
            rollback=lambda _receipt: None,
        )
        snapshot = transaction.execute(request, actor_id=actor_id)
        if snapshot.state == "committed":
            advance_session_epoch(self._context)
        return asdict(snapshot)

    def read_operation(self, operation_id: str) -> dict[str, object] | None:
        try:
            return asdict(self._journal.read(operation_id))
        except (KeyError, ValueError):
            return None

    def force_operation(self, _operation_id: str) -> dict[str, object] | None:
        # Force is added only when task cancellation is wired to every writer.
        return None

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
        return {"state": "idle", "session_epoch": read_session_epoch(self._context)}

    def public_status(self) -> dict[str, object]:
        return {"state": "idle", "build": str(read_active_release(self._context))}

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
