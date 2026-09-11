"""Lightweight single-instance runtime guard."""

from __future__ import annotations

import hashlib
import os
import tempfile

ERROR_ALREADY_EXISTS = 183


class SingleInstanceGuard:
    """Prevent launching the same GUI multiple times at once."""

    def __init__(self, app_id: str, *, scope: str = "", use_system_lock: bool = True):
        normalized_scope = os.path.abspath(scope or tempfile.gettempdir())
        digest = hashlib.sha256(f"{app_id}|{normalized_scope}".encode("utf-8")).hexdigest()[:20]
        self._mutex_name = f"Local\\{app_id}-{digest}"
        self._lock_path = os.path.join(tempfile.gettempdir(), f"{app_id}-{digest}.lock")
        self._use_system_lock = bool(use_system_lock)
        self._mutex_handle = None
        self._lock_handle = None

    def acquire(self) -> bool:
        """Return True when the current process became the active instance."""

        if self._use_system_lock and os.name == "nt" and self._acquire_windows_mutex():
            return True
        return self._acquire_file_lock()

    def release(self) -> None:
        """Release any held runtime lock."""

        handle = self._lock_handle
        self._lock_handle = None
        if handle is not None:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass
        mutex_handle = self._mutex_handle
        self._mutex_handle = None
        if mutex_handle is not None:
            try:
                import ctypes

                ctypes.windll.kernel32.CloseHandle(mutex_handle)
            except Exception:
                pass

    def __enter__(self) -> "SingleInstanceGuard":
        if not self.acquire():
            raise RuntimeError("single instance already running")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def _acquire_windows_mutex(self) -> bool:
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateMutexW(None, False, self._mutex_name)
            if not handle:
                return False
            if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                kernel32.CloseHandle(handle)
                return False
            self._mutex_handle = handle
            return True
        except Exception:
            return False

    def _acquire_file_lock(self) -> bool:
        os.makedirs(os.path.dirname(self._lock_path) or ".", exist_ok=True)
        handle = open(self._lock_path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    handle.close()
                    return False
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    handle.close()
                    return False
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()).encode("ascii", errors="ignore"))
            handle.flush()
            self._lock_handle = handle
            return True
        except Exception:
            try:
                handle.close()
            except Exception:
                pass
            raise


def acquire_single_instance_lock(lock_path: str) -> SingleInstanceGuard | None:
    """Backward-compatible helper returning a held lock or ``None``."""

    scope = os.path.dirname(os.path.abspath(lock_path or tempfile.gettempdir()))
    app_id = os.path.splitext(os.path.basename(lock_path or "PicSyncra.lock"))[0]
    guard = SingleInstanceGuard(app_id or "PicSyncra", scope=scope)
    if not guard.acquire():
        return None
    return guard
