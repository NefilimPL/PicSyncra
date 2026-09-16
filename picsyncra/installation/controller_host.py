"""Long-lived installed controller which owns the active WEB child process.

The controller is started as a SYSTEM scheduled task.  It is deliberately
separate from WEB: an update can change ``active.json`` and ask this process to
restart the backend without relying on the process being restarted.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
from typing import Callable, Protocol
from uuid import uuid4

from ..install_paths import load_registered_install_context
from .contracts import InstallContext
from .control_pipe import NamedPipeControlServer
from .control_protocol import ControlDispatcher
from .controller import InstallationController
from .windows_service import ControllerPipeHost
from .update_helper import ActiveReleaseError, read_active_release


class ControllerHostError(RuntimeError):
    """The installed controller cannot safely own the selected backend."""


class Process(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float) -> int: ...

    def kill(self) -> None: ...


ProcessFactory = Callable[[list[str]], Process]
ScheduledWork = Callable[[], None]


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return path != root


def active_web_executable(context: InstallContext) -> Path:
    """Return the active WEB executable only when it remains inside its bundle."""

    try:
        program_root = Path(context.program_root).resolve(strict=True)
        release_id = read_active_release(context)
        bundle = program_root / "versions" / str(release_id)
        executable = bundle / "web" / "PicSyncra-WEB.exe"
        resolved_bundle = bundle.resolve(strict=True)
        resolved_executable = executable.resolve(strict=True)
    except (ActiveReleaseError, OSError, RuntimeError) as exc:
        raise ControllerHostError("The active WEB executable is unavailable.") from exc
    if (
        Path(context.program_root).is_symlink()
        or bundle.is_symlink()
        or executable.is_symlink()
        or not resolved_bundle.is_dir()
        or not resolved_executable.is_file()
        or not _within(resolved_bundle, program_root / "versions")
        or not _within(resolved_executable, resolved_bundle)
        or resolved_executable.name.lower() != "picsyncra-web.exe"
    ):
        raise ControllerHostError("The active WEB executable is unsafe.")
    return resolved_executable


def _default_process_factory(command: list[str]) -> Process:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(command, close_fds=True, creationflags=creation_flags)


class ActiveBackendSupervisor:
    """Own precisely one child backend and persist its boot preference.

    The process reference is never reconstructed from a PID or a port.  A
    foreign listener therefore cannot be terminated, including for a forced
    maintenance action.
    """

    def __init__(
        self,
        context: InstallContext,
        *,
        backend_port: int = 8010,
        host: str = "0.0.0.0",
        process_factory: ProcessFactory = _default_process_factory,
        port_in_use: Callable[[], bool] | None = None,
        stop_timeout_seconds: float = 30.0,
    ) -> None:
        if not isinstance(backend_port, int) or not 1 <= backend_port <= 65535:
            raise ValueError("backend_port must be a valid TCP port")
        if stop_timeout_seconds <= 0:
            raise ValueError("stop_timeout_seconds must be positive")
        self._context = context
        self._backend_port = backend_port
        self._host = host
        self._process_factory = process_factory
        self._port_in_use = port_in_use or self._listen_probe
        self._stop_timeout_seconds = stop_timeout_seconds
        self._lock = threading.RLock()
        self._process: Process | None = None
        self._settings_path = context.state_root / "controller-settings.json"

    def listener_owner(self, port: int) -> str | None:
        if port != self._backend_port:
            return "foreign-listener" if self._port_in_use() else None
        with self._lock:
            if self._is_running():
                return self._context.installation_id
        return "foreign-listener" if self._port_in_use() else None

    def start_backend(self) -> None:
        with self._lock:
            if self._is_running():
                return
            if self._port_in_use():
                raise ControllerHostError("The configured WEB port is already in use.")
            executable = active_web_executable(self._context)
            self._process = self._process_factory(
                [str(executable), "--service-run", "--port", str(self._backend_port), "--host", self._host]
            )

    def stop_backend(self, *, force: bool) -> bool:
        if not isinstance(force, bool):
            raise ValueError("force must be a boolean")
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._process = None
                return not self._port_in_use()
            process.terminate()
            try:
                process.wait(timeout=self._stop_timeout_seconds)
            except (subprocess.TimeoutExpired, TimeoutError):
                if not force:
                    return False
                process.kill()
                try:
                    process.wait(timeout=self._stop_timeout_seconds)
                except (subprocess.TimeoutExpired, TimeoutError):
                    return False
            self._process = None
            return True

    def set_autostart(self, enabled: bool) -> bool:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._settings_path.with_name(
            f".{self._settings_path.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump({"autostart": enabled}, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._settings_path)
        finally:
            temporary.unlink(missing_ok=True)
        return self.autostart_enabled()

    def autostart_enabled(self) -> bool:
        try:
            payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return True
        return bool(payload.get("autostart", True)) if isinstance(payload, dict) else True

    def snapshot(self) -> dict[str, bool]:
        with self._lock:
            running = self._is_running()
        return {"backend_running": running, "autostart": self.autostart_enabled()}

    def _is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _listen_probe(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self._backend_port), timeout=0.25):
                return True
        except OSError:
            return False


class DeferredRestartController:
    """Reply to the pipe client before its WEB process is stopped.

    The caller is ordinarily a request handler inside the backend being
    restarted.  Deferring the destructive part lets the pipe response, journal
    commit and HTTP ``202`` leave that process first.
    """

    def __init__(
        self,
        controller: InstallationController,
        *,
        schedule: Callable[[ScheduledWork], object] | None = None,
    ) -> None:
        self._controller = controller
        self._lock = threading.Lock()
        self._restart_pending = False
        self._schedule = schedule or self._schedule_after_response

    def snapshot(self) -> dict[str, object]:
        return self._controller.snapshot()

    def start_backend(self) -> None:
        self._controller.start_backend()

    def stop_backend(self, force: bool) -> bool:
        return self._controller.stop_backend(force=force)

    def set_autostart(self, enabled: bool) -> bool:
        return self._controller.set_autostart(enabled)

    def restart_backend(self) -> bool:
        with self._lock:
            if self._restart_pending:
                return False
            self._restart_pending = True
        self._schedule(self._restart_after_response)
        return True

    def _restart_after_response(self) -> None:
        try:
            self._controller.restart_backend()
        finally:
            with self._lock:
                self._restart_pending = False

    @staticmethod
    def _schedule_after_response(work: ScheduledWork) -> None:
        # A short grace period gives the named-pipe server and the requesting
        # HTTP handler enough time to flush their success responses.
        timer = threading.Timer(1.0, work)
        timer.daemon = True
        timer.start()


def run_controller(installation_id: str, *, stop_requested: Callable[[], bool] | None = None) -> int:
    """Run one registered controller task until Windows stops the process."""

    context = load_registered_install_context(installation_id)
    if context is None:
        raise ControllerHostError("The registered installation is unavailable.")
    supervisor = ActiveBackendSupervisor(context)
    controller = InstallationController(context, supervisor, backend_port=8010)
    if supervisor.autostart_enabled():
        controller.start_backend()
    dispatcher = ControlDispatcher(
        DeferredRestartController(controller),
        installation_id=context.installation_id,
        authorized_identities={"S-1-5-18"},
    )
    ControllerPipeHost(
        server_factory=lambda: NamedPipeControlServer(
            dispatcher,
            installation_id=context.installation_id,
            allowed_sids={"S-1-5-18"},
        ),
        stop_requested=stop_requested or (lambda: False),
    ).serve_forever()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="PicSyncra-Controller")
    parser.add_argument("--installation-id", required=True)
    arguments = parser.parse_args(argv)
    try:
        return run_controller(arguments.installation_id)
    except ControllerHostError:
        return 1


__all__ = [
    "ActiveBackendSupervisor",
    "ControllerHostError",
    "DeferredRestartController",
    "active_web_executable",
    "main",
    "run_controller",
]
