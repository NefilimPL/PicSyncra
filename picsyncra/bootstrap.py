"""Runtime bootstrap helpers."""

from pathlib import Path

from . import config, settings
from .brand import SQLITE_FILENAME
from .legacy_migration import (
    _LEGACY_SQLITE_FILENAME,
    process_pending_legacy_target_cleanups,
)
from .sqlite_coordination import clear_retired_database_marker
from .storage_settings import resolve_backup_dir, resolve_sqlite_path


def _clear_completed_legacy_handover_markers() -> None:
    """Do not leave a completed handover marker in the user data directory."""

    try:
        process_pending_legacy_target_cleanups(Path(resolve_backup_dir()))
    except OSError:
        pass
    configured_database: Path | None = None
    roots = {
        Path(settings.AC),
        Path(settings.BASE_DIR_SETTINGS_PATH).parent,
    }
    try:
        configured_database = Path(resolve_sqlite_path())
        roots.add(configured_database.parent)
    except (OSError, ValueError):
        pass
    for root in roots:
        legacy_database = root / _LEGACY_SQLITE_FILENAME
        current_database = root / SQLITE_FILENAME
        configured_database_is_here = (
            configured_database is not None
            and configured_database.parent == root
            and configured_database.is_file()
        )
        if current_database.is_file() or configured_database_is_here:
            clear_retired_database_marker(legacy_database)


def initialize_application_runtime(*, interactive=None):
    """Initialize runtime paths and configuration explicitly."""

    settings.initialize_runtime(interactive=interactive)
    _clear_completed_legacy_handover_markers()
    config.initialize_config(interactive=interactive)
    if settings.BASE_DIR_OVERRIDE_WARNING:
        try:
            from .logging_utils import log_error

            log_error(f"Runtime base directory fallback: {settings.BASE_DIR_OVERRIDE_WARNING}")
        except Exception:
            pass
    return {
        "base_dir": settings.AC,
        "config_path": config.CONFIG_PATH,
        "warning": settings.BASE_DIR_OVERRIDE_WARNING,
    }
