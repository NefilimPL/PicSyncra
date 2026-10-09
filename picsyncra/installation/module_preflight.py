"""Space and write-access checks before staging and before mandatory backup."""
import os
from pathlib import Path
import shutil
import tempfile
from .module_filesystem import safe_path
from .module_state import module_set_root


def _tree_size(root):
    root = safe_path(root)
    return sum(safe_path(root, path.relative_to(root).as_posix()).stat().st_size
               for path in root.rglob('*') if path.is_file())


def check_operation_preflight(context, target, active, content):
    from .module_executor import ModuleExecutionError
    cache = content.available_hashes()
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
