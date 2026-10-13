"""Long-lived installed controller which owns the active WEB child process.

The controller is started as a SYSTEM scheduled task.  It is deliberately
separate from WEB: an update can change ``active.json`` and ask this process to
restart the backend without relying on the process being restarted.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from typing import Callable, Protocol
from urllib.error import URLError, HTTPError
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler
from uuid import uuid4

from ..install_paths import load_registered_install_context
from .contracts import InstallContext
from .control_pipe import NamedPipeControlServer
from .control_protocol import ControlDispatcher
from .controller import InstallationController, InstallationControllerError
from .journal import OperationJournal
from .restart_handoff import (
    RestartHandoffError,
    clear_restart_handoff,
    read_restart_handoff,
    restore_restart_handoff,
)
from .session_epoch import advance_session_epoch
from .windows_service import ControllerPipeHost
from .update_helper import ActiveReleaseError, read_active_release


class ControllerHostError(RuntimeError):
    """The installed controller cannot safely own the selected backend."""


class Process(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float) -> int: ...

    def kill(self) -> None: ...


class ChildProcessJob(Protocol):
    """Own child processes for the lifetime of the controller task."""

    def assign(self, process: Process) -> None: ...

    def close(self) -> None: ...


ProcessFactory = Callable[[list[str]], Process]
JobFactory = Callable[[], ChildProcessJob]
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
        bundle_parent = program_root / 'versions'
        executable = bundle / "web" / "PicSyncra-WEB.exe"
        marker = json.loads((program_root / 'active.json').read_text(encoding='utf-8'))
        if marker.get('schema') == 2:
            from .module_state import read_module_set, module_set_root
            from .module_filesystem import safe_path
            selected = read_module_set(context)
            bundle = module_set_root(context, selected)
            bundle_parent = program_root / 'sets'
            executable = safe_path(bundle, 'apps/web/PicSyncra-WEB.exe')
            import hashlib
            descriptor = next((f for m in selected.modules for f in m.files if f.path == 'apps/web/PicSyncra-WEB.exe'), None)
            if descriptor is None: raise ControllerHostError('Brak hosta WEB w aktywnym zestawie.')
            with executable.open('rb') as handle:
                if executable.stat().st_size != descriptor.size or hashlib.file_digest(handle, 'sha256').hexdigest() != descriptor.sha256:
                    raise ControllerHostError('Host WEB ma niezgodną sumę kontrolną.')
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
        or not _within(resolved_bundle, bundle_parent)
        or not _within(resolved_executable, resolved_bundle)
        or resolved_executable.name.lower() != "picsyncra-web.exe"
    ):
        raise ControllerHostError("The active WEB executable is unsafe.")
    return resolved_executable


def _default_process_factory(command: list[str]) -> Process:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(command, close_fds=True, creationflags=creation_flags)


class _WindowsKillOnCloseJob:
    """A Windows Job Object which kills its child if the controller dies."""

    def __init__(self) -> None:  # pragma: no cover - exercised by installed build
        try:
            import win32api
            import win32job
        except ImportError as exc:
            raise ControllerHostError("pywin32 job support is required for the controller.") from exc
        self._win32api = win32api
        self._win32job = win32job
        self._handle = win32job.CreateJobObject(None, "")
        information = win32job.QueryInformationJobObject(
            self._handle, win32job.JobObjectExtendedLimitInformation
        )
        information["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        win32job.SetInformationJobObject(
            self._handle, win32job.JobObjectExtendedLimitInformation, information
        )

    def assign(self, process: Process) -> None:  # pragma: no cover - installed build
        handle = getattr(process, "_handle", None)
        if not isinstance(handle, int):
            raise ControllerHostError("The backend process has no Windows handle.")
        self._win32job.AssignProcessToJobObject(self._handle, handle)

    def close(self) -> None:  # pragma: no cover - installed build
        if self._handle is not None:
            self._win32api.CloseHandle(self._handle)
            self._handle = None


def _default_job_factory() -> ChildProcessJob:
    return _WindowsKillOnCloseJob()


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
        job_factory: JobFactory = _default_job_factory,
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
        self._job_factory = job_factory
        self._port_in_use = port_in_use or self._listen_probe
        self._stop_timeout_seconds = stop_timeout_seconds
        self._lock = threading.RLock()
        self._process: Process | None = None
        self._job: ChildProcessJob | None = None
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
            self._process = None
            self._close_job()
            if self._port_in_use():
                raise ControllerHostError("The configured WEB port is already in use.")
            executable = active_web_executable(self._context)
            process = self._process_factory(
                [str(executable), "--service-run", "--port", str(self._backend_port), "--host", self._host]
            )
            try:
                job = self._job_factory()
                job.assign(process)
            except Exception:
                try:
                    process.terminate()
                except Exception:
                    pass
                raise
            self._process = process
            self._job = job

    def stop_backend(self, *, force: bool) -> bool:
        if not isinstance(force, bool):
            raise ValueError("force must be a boolean")
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._process = None
                self._close_job()
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
            self._close_job()
            return True

    def shutdown(self) -> None:
        """End the owned WEB child when the controller exits normally."""

        self.stop_backend(force=True)

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
            pid = getattr(self._process, 'pid', None) if running else None
        result = {"backend_running": running, "autostart": self.autostart_enabled()}
        if pid is not None: result['backend_pid'] = pid
        return result

    def _is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _close_job(self) -> None:
        job = self._job
        self._job = None
        if job is not None:
            job.close()

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
        complete_restart: Callable[[bool], None] | None = None,
    ) -> None:
        self._controller = controller
        self._lock = threading.Lock()
        self._restart_pending = False
        self._schedule = schedule or self._schedule_after_response
        self._complete_restart = complete_restart

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
            succeeded = self._controller.restart_backend()
            if self._complete_restart is not None:
                self._complete_restart(succeeded)
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


BACKEND_START_TIMEOUT = 180.0


class _BackendHealthRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise URLError('Backend health redirects are not allowed.')


def _owned_backend_process(pid, owner_pid):
    # Older application modules have no process_id. A bootloader/wrapper may
    # own the root process while the HTTP server is one of its children.
    if pid is None or owner_pid is None: return True
    if type(pid) is not int or pid <= 0: return False
    if pid == owner_pid: return True
    import psutil
    try:
        process = psutil.Process(pid)
        for _ in range(16):
            process = process.parent()
            if process is None: return False
            if process.pid == owner_pid: return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False


def _read_backend_health(response, deadline):
    data = bytearray()
    limit = 256*1024
    while time.monotonic()<deadline:
        # read1 returns available data instead of waiting for the whole body.
        # Check the overall deadline even if the peer keeps sending a trickle.
        chunk = response.read1(min(8192,limit+1-len(data)))
        if not chunk: return bytes(data)
        data.extend(chunk)
        if len(data)>limit: raise ValueError('Oversized backend health response.')
    raise TimeoutError('Backend health deadline exceeded.')


def _backend_ready(controller: InstallationController, *, timeout_seconds: float = BACKEND_START_TIMEOUT,
                   on_status=None) -> bool:
    """Require the new process to serve its own health response before commit."""

    started = time.monotonic()
    deadline = started + timeout_seconds
    # Loopback probes must not follow the user's/company's proxy configuration
    # or redirects to another listener.
    opener = build_opener(ProxyHandler({}), _BackendHealthRedirect())
    details = dict(code='backend_health_timeout', timeout_seconds=timeout_seconds)
    while time.monotonic() < deadline:
        snapshot = controller.snapshot()
        if not bool(snapshot.get("backend_running", False)):
            details.update(code='backend_exited', backend_running=False)
            if on_status: on_status(details)
            return False
        port = snapshot.get('backend_port', 8010)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid backend health port.')
        url = f'http://127.0.0.1:{port}/api/health'
        try:
            with opener.open(url, timeout=min(1.0, max(0.01, deadline-time.monotonic()))) as response:
                if hasattr(response, 'geturl') and response.geturl() != url:
                    raise ValueError('Redirected backend health response.')
                raw = _read_backend_health(response,deadline)
                payload = json.loads(raw.decode('utf-8'))
            if not isinstance(payload, dict): raise ValueError('Invalid backend health response.')
            details.update(backend_running=True, observation='unhealthy')
            components = payload.get('components')
            if isinstance(components, dict):
                details['components'] = {name: item['status'] for name in ('backend','sqlite','job_processor','notification_worker')
                    if isinstance(item:=components.get(name),dict) and isinstance(item.get('status'),str)
                    and item['status'] in {'online','critical','degraded','unknown'}}
            own_process = _owned_backend_process(payload.get('process_id'),snapshot.get('backend_pid'))
            own_app = payload.get('application')=='picsyncra'
            if not own_process or not own_app:
                details['observation'] = 'different_process' if not own_process else 'different_application'
            if payload.get('ok') is True and own_process and own_app:
                current = controller.snapshot()
                if not current.get('backend_running') or current.get('backend_pid')!=snapshot.get('backend_pid'):
                    details['observation'] = 'process_changed'
                else:
                    if on_status: on_status(dict(code='ready', elapsed_seconds=round(time.monotonic()-started,1)))
                    return True
        except HTTPError as exc:
            details.update(backend_running=True,observation='http_error',http_status=exc.code)
        except (OSError, URLError, ValueError, http.client.HTTPException):
            details.update(backend_running=True, observation='no_valid_response')
        time.sleep(min(0.2, max(0, deadline-time.monotonic())))
    details['elapsed_seconds'] = round(time.monotonic()-started,1)
    if on_status: on_status(details)
    return False


def _complete_restart_handoff(
    context: InstallContext,
    controller: InstallationController,
    restarted: bool,
    *,
    readiness_check: Callable[[InstallationController], bool] = _backend_ready,
) -> None:
    """Commit only a healthy new backend, otherwise restore its active bundle."""

    try:
        handoff = read_restart_handoff(context)
        if handoff is None:
            return
        journal = OperationJournal(context.state_root / "operations.json")
        operation = journal.read(handoff.operation_id)
        if operation.state != "validating":
            return
        if restarted and readiness_check(controller):
            try:
                advance_session_epoch(context)
            except OSError:
                restarted = False
            else:
                journal.transition(operation.operation_id, "committed")
                clear_restart_handoff(context, operation.operation_id)
                return
        controller.stop_backend(force=True)
        restore_restart_handoff(context, handoff)
        if controller.restart_backend() and readiness_check(controller):
            journal.transition(operation.operation_id, "rolling_back", error_code="restart_failed")
            journal.transition(operation.operation_id, "rolled_back", error_code="restart_failed")
            clear_restart_handoff(context, operation.operation_id)
            return
        journal.transition(operation.operation_id, "recovery_required", error_code="restart_failed")
    except (RestartHandoffError, OSError, ValueError):
        # The durable journal remains non-terminal and is converted only when
        # possible; no unverified release is reported as committed.
        return


def run_controller(installation_id: str, *, stop_requested: Callable[[], bool] | None = None) -> int:
    """Run one registered controller task until Windows stops the process."""

    context = load_registered_install_context(installation_id)
    if context is None:
        raise ControllerHostError("The registered installation is unavailable.")
    supervisor = ActiveBackendSupervisor(context)
    controller = InstallationController(context, supervisor, backend_port=8010)
    from .module_service import ModuleService
    modules = ModuleService(context, controller)
    try:
        recovered = modules.executor.recover()
    except (RuntimeError, OSError, ValueError):
        recovered = 'recovery_required'
    if recovered == 'recovery_required':
        # Keep the recovery pipe alive even if the selected application is bad.
        supervisor.set_autostart(False)
    if supervisor.autostart_enabled():
        try:
            controller.start_backend()
        except (ControllerHostError, InstallationControllerError, OSError, ValueError):
            # The stable recovery endpoint must survive a missing/corrupt WEB
            # payload or an occupied port. Explicit starts still report failure.
            pass
        else:
            _complete_restart_handoff(context, controller, True)
    dispatcher = ControlDispatcher(
        DeferredRestartController(
            controller,
            complete_restart=lambda restarted: _complete_restart_handoff(context, controller, restarted),
        ),
        installation_id=context.installation_id,
        authorized_identities={"S-1-5-18", "S-1-5-32-544"},
        module_service=modules,
    )
    try:
        ControllerPipeHost(
            server_factory=lambda: NamedPipeControlServer(
                dispatcher,
                installation_id=context.installation_id,
                allowed_sids={"S-1-5-18", "S-1-5-32-544"},
            ),
            stop_requested=stop_requested or (lambda: False),
        ).serve_forever()
    finally:
        supervisor.shutdown()
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
