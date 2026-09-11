"""Process boundaries for the standalone offline SQLite migrator."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from .offline_legacy_sqlite_migrator import OfflineMigrationError


PID_FILENAMES = (".picsyncra_web.pid", ".picorg_web.pid")
APP_EXECUTABLE_PREFIXES = ("picsyncra", "picorgftp")


@dataclass(frozen=True)
class ManagedProcess:
    """A PID candidate paired with the executable Windows reports for it."""

    pid: int
    executable: Path | None


def _safe_pid(value: object) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _metadata_candidates(app_root: Path) -> tuple[int, ...]:
    pids: list[int] = []
    for filename in PID_FILENAMES:
        try:
            payload = json.loads((app_root / filename).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        for key in ("pid", "launcher_pid"):
            pid = _safe_pid(payload.get(key))
            if pid is not None and pid not in pids:
                pids.append(pid)
    return tuple(pids)


def _process_exists(pid: int) -> bool:
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_executable_path(pid: int) -> Path | None:
    if os.name == "nt":
        script = (
            "$p = Get-CimInstance Win32_Process -Filter "
            f"\"ProcessId = {pid}\" -ErrorAction SilentlyContinue; "
            "if ($p) { $p.ExecutablePath }"
        )
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        text = result.stdout.strip()
        return Path(text).resolve() if text else None
    try:
        return Path(os.readlink(f"/proc/{pid}/exe")).resolve()
    except OSError:
        return None


def find_managed_processes(app_root: Path) -> tuple[ManagedProcess, ...]:
    """Read only recorded application PIDs; never enumerate generic Python."""

    root = Path(app_root).resolve()
    processes = []
    for pid in _metadata_candidates(root):
        if _process_exists(pid):
            processes.append(ManagedProcess(pid, _read_executable_path(pid)))
    return tuple(processes)


def _is_verified_application_process(process: ManagedProcess, app_root: Path) -> bool:
    executable = process.executable
    if executable is None:
        return False
    try:
        executable.resolve().relative_to(app_root.resolve())
    except ValueError:
        return False
    return executable.name.casefold().startswith(APP_EXECUTABLE_PREFIXES)


def _terminate_process(process: ManagedProcess, force: bool) -> bool:
    if os.name == "nt":
        command = ["taskkill", "/PID", str(process.pid), "/T"]
        if force:
            command.append("/F")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0
    try:
        os.kill(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        return False
    return True


def _wait_for_exit(
    pid: int,
    *,
    timeout: float,
    process_is_running: Callable[[int], bool],
    sleep: Callable[[float], None],
) -> bool:
    if not process_is_running(pid):
        return True
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        sleep(0.2)
        if not process_is_running(pid):
            return True
    return False


def stop_managed_processes(
    app_root: Path,
    notify: Callable[[str], None],
    *,
    list_processes: Callable[[], Iterable[ManagedProcess]] | None = None,
    terminate_process: Callable[[ManagedProcess, bool], bool] = _terminate_process,
    process_is_running: Callable[[int], bool] = _process_exists,
    sleep: Callable[[float], None] = time.sleep,
    wait_timeout: float = 5.0,
) -> None:
    """Stop only recorded, verified application EXEs from ``app_root``."""

    root = Path(app_root).resolve()
    candidates = tuple(
        list_processes() if list_processes is not None else find_managed_processes(root)
    )
    unverified = [process for process in candidates if process.executable is None]
    if unverified:
        raise OfflineMigrationError(
            "process_unverified",
            "Nie można bezpiecznie zweryfikować procesu głównej aplikacji; migracja nie została rozpoczęta.",
        )

    verified = [
        process
        for process in candidates
        if _is_verified_application_process(process, root)
    ]
    for process in candidates:
        if process not in verified:
            notify(f"Pomijam niezweryfikowany proces PID {process.pid}.")

    for process in verified:
        notify(f"Zatrzymywanie zweryfikowanej aplikacji (PID {process.pid})…")
        if not terminate_process(process, False):
            raise OfflineMigrationError(
                "process_stop_failed",
                "Nie udało się zakończyć zweryfikowanej głównej aplikacji.",
            )
        if _wait_for_exit(
            process.pid,
            timeout=wait_timeout,
            process_is_running=process_is_running,
            sleep=sleep,
        ):
            continue
        notify(f"Wymuszanie zatrzymania zweryfikowanej aplikacji (PID {process.pid})…")
        if not terminate_process(process, True) or not _wait_for_exit(
            process.pid,
            timeout=wait_timeout,
            process_is_running=process_is_running,
            sleep=sleep,
        ):
            raise OfflineMigrationError(
                "process_still_running",
                "Zweryfikowana główna aplikacja nadal działa; migracja nie została rozpoczęta.",
            )
