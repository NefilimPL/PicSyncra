"""Safety policy around the SCM adapter for one installed backend."""

from __future__ import annotations

from typing import Protocol

from .contracts import InstallContext


class InstallationControllerError(RuntimeError):
    """A requested backend action would be unsafe for this installation."""


class ScmAdapter(Protocol):
    """The narrow, platform-specific boundary used by the controller."""

    def listener_owner(self, port: int) -> str | None: ...

    def start_backend(self) -> None: ...

    def stop_backend(self, *, force: bool) -> bool: ...

    def set_autostart(self, enabled: bool) -> bool: ...

    def snapshot(self) -> dict[str, object]: ...


class InstallationController:
    """Supervise only the backend registered to one managed installation."""

    def __init__(
        self, context: InstallContext, scm: ScmAdapter, *, backend_port: int
    ) -> None:
        if not isinstance(backend_port, int) or isinstance(backend_port, bool):
            raise ValueError("The backend port must be an integer.")
        if not 1 <= backend_port <= 65535:
            raise ValueError("The backend port must be between 1 and 65535.")
        self._context = context
        self._scm = scm
        self._backend_port = backend_port

    def _foreign_listener_exists(self) -> bool:
        owner = self._scm.listener_owner(self._backend_port)
        return owner is not None and owner != self._context.installation_id

    def start_backend(self) -> None:
        """Start the backend unless another process owns its configured port."""

        if self._foreign_listener_exists():
            raise InstallationControllerError(
                "The backend port is occupied by a process outside this installation."
            )
        self._scm.start_backend()

    def stop_backend(self, force: bool) -> bool:
        """Stop our service only; force never authorises acting on another process."""

        if not isinstance(force, bool):
            raise ValueError("force must be a boolean.")
        if self._foreign_listener_exists():
            return False
        return self._scm.stop_backend(force=force)

    def restart_backend(self) -> bool:
        """Restart only this installation's service through the SCM boundary."""

        if self._foreign_listener_exists() or not self.stop_backend(force=False):
            return False
        try:
            self.start_backend()
        except InstallationControllerError:
            return False
        return True

    def set_autostart(self, enabled: bool) -> bool:
        """Persist the SCM start mode and return its confirmed result."""

        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean.")
        return self._scm.set_autostart(enabled)

    def snapshot(self) -> dict[str, object]:
        """Return controller state without exposing implementation paths."""

        state = self._scm.snapshot()
        return {
            "installation_id": self._context.installation_id,
            "backend_port": self._backend_port,
            "backend_running": bool(state.get("backend_running", False)),
            "autostart": bool(state.get("autostart", False)),
        }


__all__ = ["InstallationController", "InstallationControllerError", "ScmAdapter"]
