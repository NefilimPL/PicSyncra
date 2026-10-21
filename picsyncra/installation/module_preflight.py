"""Space and write-access checks before staging and before mandatory backup."""
import os
import errno
from pathlib import Path
import shutil
import tempfile
from .module_filesystem import safe_path
from .module_state import module_set_root
from .module_executor import ModuleExecutionError


class ModuleAccessError(ModuleExecutionError):
    def __init__(self, location, exc):
        winerror = getattr(exc, 'winerror', None)
        denied = winerror == 5 or (winerror is None and exc.errno in {errno.EACCES, errno.EPERM, errno.EROFS})
        code = 'permission_required' if denied else 'files_in_use' if winerror in {32, 33} else 'preflight_io_error'
        message = ('Brak dostępu do plików wymaganych do aktualizacji. Użyj jednorazowego logowania Windows.' if denied else
                   'Plik wymagany do aktualizacji jest używany przez inny proces. Spróbuj ponownie.' if code == 'files_in_use' else
                   'Nie udało się sprawdzić plików wymaganych do aktualizacji. Sprawdź szczegóły błędu i spróbuj ponownie.')
        super().__init__(message)
        self.details = dict(code=code, message=message, location=location,
                            system_code=winerror or exc.errno,
                            retryable=True)


def _probe_existing_file(path, *, require_delete=True):
    if not path.exists(): return
    # Directory write access does not imply read/write/delete access to an
    # existing file with its own ACL. Do not change its contents during a probe.
    with path.open('r+b'): pass
    if os.name == 'nt' and require_delete:
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        api.CreateFileW.restype = wintypes.HANDLE
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.CreateFileW(str(path), 0x10000, 7, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
        api.CloseHandle(handle)


def _check_existing_file(path, *, require_delete=True):
    from time import sleep
    for attempt in range(8):
        try:
            _probe_existing_file(path, require_delete=require_delete)
            return
        except OSError as exc:
            if isinstance(exc, FileNotFoundError): return
            if getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt == 7: raise
            sleep(min(.15, .025 * (attempt + 1)))


def check_update_access(context):
    """Probe the executing account before network, staging or maintenance."""
    files = [('maintenance_ready', context.state_root, 'module-maintenance-ready.json'),
             ('maintenance_request', context.state_root, 'module-maintenance-request.json'),
             ('journal', context.state_root, 'module-operation.json'),
             ('active_marker', context.program_root, 'active.json')]
    for role, root, relative in files:
        try: _check_existing_file(safe_path(root, relative))
        except OSError as exc: raise ModuleAccessError(role, exc) from exc
    # SQLite remains open during preparation. Probe its file ACL without
    # requesting DELETE access against files held by the running backend.
    for path in (context.database_path, context.database_path.with_name(context.database_path.name + '-wal'),
                 context.database_path.with_name(context.database_path.name + '-shm')):
        try: _check_existing_file(safe_path(path), require_delete=False)
        except OSError as exc: raise ModuleAccessError('database', exc) from exc
    try:
        config_root = safe_path(context.config_root)
        for path in config_root.rglob('*'):
            if path.is_file(): _check_existing_file(safe_path(config_root, path.relative_to(config_root).as_posix()))
    except OSError as exc: raise ModuleAccessError('configuration', exc) from exc
    roots = [('program', context.program_root), ('state', context.state_root),
             ('configuration', context.config_root), ('database', context.database_path.parent)]
    roots += [(name, context.program_root / name) for name in ('content', 'sets')]
    roots += [(name, context.state_root / name) for name in ('module-plans', 'module-progress', 'module-operations', 'backups/operations')]
    for role, root in roots:
        root = safe_path(root)
        while not root.exists(): root = root.parent
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix='.module-write-check-', dir=root)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(b'PicSyncra preflight')
                stream.flush()
                os.fsync(stream.fileno())
            Path(temporary).unlink()
            temporary = None
        except OSError as exc: raise ModuleAccessError(role, exc) from exc
        finally:
            if temporary is not None: Path(temporary).unlink(missing_ok=True)


def _tree_size(root):
    root = safe_path(root)
    return sum(safe_path(root, path.relative_to(root).as_posix()).stat().st_size
               for path in root.rglob('*') if path.is_file())


def check_operation_preflight(context, target, active, content, *, inspect_cache=True):
    check_update_access(context)
    from .module_executor import ModuleExecutionError
    cache = content.available_hashes() if inspect_cache else frozenset()
    files = {file.sha256: file.size for module in (*target.modules, *active.modules) for file in module.files}
    cache_bytes = sum(size for digest, size in files.items() if digest not in cache)
    staging = module_set_root(context, target)
    set_bytes = sum(file.size for module in target.modules for file in module.files
                    if not safe_path(staging, file.path).is_file())
    database_bytes = context.database_path.stat().st_size
    wal = context.database_path.with_name(context.database_path.name + '-wal')
    if wal.is_file(): database_bytes += wal.stat().st_size
    config_bytes = _tree_size(context.config_root)
    # Snapshot plus temporary restore copies; old active sets are retained.
    demands = [(context.program_root, cache_bytes + set_bytes),
               (context.state_root, database_bytes + 3 * config_bytes),
               (context.database_path.parent, 2 * database_bytes),
               (context.config_root, config_bytes)]
    volumes = {}
    for path, needed in demands:
        path = Path(path)
        key = path.resolve().anchor.casefold() if os.name == 'nt' else os.stat(path).st_dev
        previous = volumes.get(key, (path, 0))
        volumes[key] = previous[0], previous[1] + needed
    for path, needed in volumes.values():
        reserve = max(64 * 1024 * 1024, needed // 20)
        if shutil.disk_usage(path).free < needed + reserve:
            raise ModuleExecutionError(f'Brak miejsca na {path.anchor}: potrzebne {needed + reserve:,} bajtów na moduły, kopię danych i odzyskiwanie.')
    # Check each destination, including installations with a DB on another drive.
    for root in {context.program_root, context.state_root, context.config_root, context.database_path.parent}:
        root = safe_path(root)
        descriptor = None
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix='.module-write-check-', dir=root)
            os.write(descriptor, b'PicSyncra preflight')
            os.fsync(descriptor)
        except OSError as exc:
            raise ModuleExecutionError(f'Brak możliwości zapisu modułów, kopii lub odzyskiwania: {root}.') from exc
        finally:
            if descriptor is not None: os.close(descriptor)
            if temporary is not None: Path(temporary).unlink(missing_ok=True)
