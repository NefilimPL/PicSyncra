"""In-process maintenance coordination for SQLite databases."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import threading


class RetiredDatabaseError(RuntimeError):
    """Raised when a legacy database was adopted and must no longer be written."""


class _DatabaseGate:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.active_connections = 0
        self.maintenance_active = False
        self.retired = False
        self.activity_file_lock = None


_GATES: dict[str, _DatabaseGate] = {}
_GATES_LOCK = threading.Lock()
_LOCK_OFFSET = 0x3FFFFFFF


def _gate_for(path: str | Path) -> _DatabaseGate:
    key = str(Path(path).resolve()).casefold()
    with _GATES_LOCK:
        return _GATES.setdefault(key, _DatabaseGate())


def _marker_path(path: str | Path) -> Path:
    database_path = Path(path)
    return database_path.with_name(f".{database_path.name}.picsyncra-adoption")


def _set_marker(path: str | Path, state: str) -> None:
    marker = _marker_path(path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{marker.name}-",
        suffix=".tmp",
        dir=marker.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(state)
        os.replace(temporary_path, marker)
    finally:
        if os.path.exists(temporary_path):
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def _has_marker(path: str | Path) -> bool:
    return _marker_path(path).is_file()


def maintenance_state(path: str | Path) -> str:
    """Return the persisted handover state, if any."""

    try:
        return _marker_path(path).read_text(encoding="ascii").strip().lower()
    except OSError:
        return ""


@contextmanager
def _database_file_lock(path: str | Path, *, exclusive: bool):
    """Coordinate database handover between desktop and web processes."""

    database_path = Path(path)
    if not database_path.is_file():
        yield
        return
    descriptor = os.open(str(database_path), os.O_RDWR)
    locked = False
    windows_lock = None
    try:
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            class _Overlapped(ctypes.Structure):
                _fields_ = [
                    ("internal", ctypes.c_size_t),
                    ("internal_high", ctypes.c_size_t),
                    ("offset", wintypes.DWORD),
                    ("offset_high", wintypes.DWORD),
                    ("event", wintypes.HANDLE),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            lock_file_ex = kernel32.LockFileEx
            lock_file_ex.argtypes = (
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(_Overlapped),
            )
            lock_file_ex.restype = wintypes.BOOL
            windows_lock = _Overlapped(offset=_LOCK_OFFSET)
            flags = 0x00000001 | (0x00000002 if exclusive else 0x00000000)
            if not lock_file_ex(
                msvcrt.get_osfhandle(descriptor),
                flags,
                0,
                1,
                0,
                ctypes.byref(windows_lock),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            import fcntl

            mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(descriptor, mode)
        locked = True
        yield
    finally:
        try:
            if locked:
                if os.name == "nt":
                    import ctypes
                    import msvcrt
                    from ctypes import wintypes

                    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                    unlock_file_ex = kernel32.UnlockFileEx
                    unlock_file_ex.argtypes = (
                        wintypes.HANDLE,
                        wintypes.DWORD,
                        wintypes.DWORD,
                        wintypes.DWORD,
                        ctypes.POINTER(type(windows_lock)),
                    )
                    unlock_file_ex.restype = wintypes.BOOL
                    unlock_file_ex(
                        msvcrt.get_osfhandle(descriptor),
                        0,
                        1,
                        0,
                        ctypes.byref(windows_lock),
                    )
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


@contextmanager
def database_activity(path: str | Path):
    """Allow a normal SQLite operation unless maintenance has retired its path."""

    gate = _gate_for(path)
    try:
        with gate.condition:
            if _has_marker(path):
                raise RetiredDatabaseError(
                    "Ta stara baza SQLite jest w trakcie przenoszenia lub juz przeniesiona."
                )
            while gate.maintenance_active:
                gate.condition.wait()
            if gate.retired or _has_marker(path):
                raise RetiredDatabaseError("Ta stara baza SQLite zostala juz przeniesiona do archiwum.")
            if gate.active_connections == 0:
                file_lock = _database_file_lock(path, exclusive=False)
                file_lock.__enter__()
                gate.activity_file_lock = file_lock
            gate.active_connections += 1
    except OSError as exc:
        raise RetiredDatabaseError(
            "Ta stara baza SQLite jest w trakcie przenoszenia lub juz przeniesiona."
        ) from exc
    try:
        if _has_marker(path):
            raise RetiredDatabaseError(
                "Ta stara baza SQLite jest w trakcie przenoszenia lub juz przeniesiona."
            )
        yield
    finally:
        file_lock_to_release = None
        with gate.condition:
            gate.active_connections -= 1
            if gate.active_connections == 0:
                file_lock_to_release = gate.activity_file_lock
                gate.activity_file_lock = None
            gate.condition.notify_all()
        if file_lock_to_release is not None:
            file_lock_to_release.__exit__(None, None, None)


@contextmanager
def database_maintenance(path: str | Path):
    """Quiesce PicSyncra connections for a database while it is handed over."""

    gate = _gate_for(path)
    with gate.condition:
        while gate.maintenance_active:
            gate.condition.wait()
        gate.maintenance_active = True
        while gate.active_connections:
            gate.condition.wait()
        try:
            _set_marker(path, "active")
        except OSError:
            gate.maintenance_active = False
            gate.condition.notify_all()
            raise
    try:
        with _database_file_lock(path, exclusive=True):
            yield
    finally:
        with gate.condition:
            retired = gate.retired
        if not retired:
            try:
                _marker_path(path).unlink()
            except FileNotFoundError:
                pass
        with gate.condition:
            gate.maintenance_active = False
            gate.condition.notify_all()


def retire_database(path: str | Path) -> None:
    """Prevent queued PicSyncra work from recreating a migrated source database."""

    gate = _gate_for(path)
    with gate.condition:
        _set_marker(path, "retired")
        gate.retired = True


def clear_retired_database_marker(path: str | Path) -> None:
    """Remove the persistent marker once the old database no longer exists."""

    marker = _marker_path(path)
    if maintenance_state(path) != "retired" or Path(path).exists():
        return
    try:
        marker.unlink()
    except FileNotFoundError:
        pass
