"""Safe offline import of one explicitly selected PicOrgFTP-SQL profile."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import storage_settings
from .legacy_migration import adoption_database_path, adopt_legacy_profile
from .legacy_profile import load_legacy_profile
from .offline_legacy_sqlite_migrator import MigrationProgress


class OfflineLegacyProfileMigrationError(RuntimeError):
    """A user-actionable failure that leaves the selected profile unchanged."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OfflineLegacyProfilePaths:
    """Validated inputs for one selected old-application profile."""

    app_root: Path
    settings_path: Path
    source_root: Path
    target: Path
    backup_root: Path
    source_names: tuple[str, ...]


@dataclass(frozen=True)
class OfflineLegacyProfileReport:
    """Non-sensitive result summary suitable for the standalone GUI."""

    source_root: Path
    target: Path
    source_kind: str
    component_counts: dict[str, int]
    archive_dir: Path | None
    archive_warning: str | None


def _settings_target(settings_path: Path) -> Path:
    payload = storage_settings.load_bootstrap_settings_file(settings_path)
    configured = storage_settings.resolve_sqlite_path_for_settings_file(
        settings_path, payload
    )
    if not configured:
        raise OfflineLegacyProfileMigrationError(
            "target_missing",
            "Konfiguracja wybranej aplikacji nie wskazuje docelowej bazy SQLite.",
        )
    target = adoption_database_path(Path(configured)).resolve()
    if target.name in {"", "."}:
        raise OfflineLegacyProfileMigrationError(
            "target_missing",
            "Konfiguracja wybranej aplikacji nie wskazuje docelowego pliku SQLite.",
        )
    return target


def resolve_offline_legacy_profile_paths(
    app_root: Path, source_root: Path
) -> OfflineLegacyProfilePaths:
    """Validate exactly the profile directory chosen in the standalone migrator."""

    resolved_app_root = Path(app_root).resolve()
    settings_path = resolved_app_root / "local_settings.json"
    if not settings_path.is_file():
        raise OfflineLegacyProfileMigrationError(
            "settings_missing",
            "W wybranym katalogu aplikacji nie znaleziono pliku local_settings.json.",
        )
    profile = load_legacy_profile(Path(source_root))
    if profile is None:
        raise OfflineLegacyProfileMigrationError(
            "profile_missing",
            "Wybrany folder nie zawiera kompletnej starej konfiguracji PicOrgFTP-SQL.",
        )
    target = _settings_target(settings_path)
    if target.exists():
        raise OfflineLegacyProfileMigrationError(
            "target_exists",
            "Plik docelowej bazy SQLite już istnieje. Migrator nie nadpisuje istniejącej bazy.",
        )
    return OfflineLegacyProfilePaths(
        app_root=resolved_app_root,
        settings_path=settings_path.resolve(),
        source_root=profile.root,
        target=target,
        backup_root=(resolved_app_root / "BACKUP").resolve(),
        source_names=profile.manifest.source_names,
    )


def _component_counts(report: dict[str, object] | None) -> dict[str, int]:
    if not isinstance(report, dict):
        return {}
    values = report.get("component_counts")
    if not isinstance(values, dict):
        return {}
    return {
        str(name): value
        for name, value in values.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def run_offline_legacy_profile_migration(
    app_root: Path,
    source_root: Path,
    progress: Callable[[MigrationProgress], None],
) -> OfflineLegacyProfileReport:
    """Import, activate, and archive one user-selected legacy profile."""

    paths = resolve_offline_legacy_profile_paths(app_root, source_root)
    from .offline_migrator_processes import stop_managed_processes

    progress(MigrationProgress("process", 0, None, "Weryfikacja głównej aplikacji…"))
    stop_managed_processes(
        paths.app_root,
        notify=lambda message: progress(MigrationProgress("process", None, None, message)),
    )
    settings_snapshot = paths.settings_path.read_bytes()
    activation_error: Exception | None = None

    def activate(target_path: Path, imported_bootstrap: dict[str, object] | None = None):
        nonlocal activation_error
        updates = dict(imported_bootstrap or {})
        updates.update(
            {
                storage_settings.DATA_MODE_KEY: storage_settings.DATA_MODE_SQLITE,
                storage_settings.DATABASE_LOCATION_MODE_KEY: storage_settings.DATABASE_LOCATION_CUSTOM,
                storage_settings.DATABASE_PATH_KEY: str(target_path),
            }
        )
        try:
            storage_settings.update_bootstrap_settings_file(paths.settings_path, updates)
        except Exception as error:
            activation_error = error
            try:
                storage_settings.restore_bootstrap_settings_file(
                    paths.settings_path, settings_snapshot
                )
            except OSError:
                pass
            raise

        def rollback() -> None:
            storage_settings.restore_bootstrap_settings_file(
                paths.settings_path, settings_snapshot
            )

        return rollback

    progress(MigrationProgress("import", 0, None, "Importowanie starej konfiguracji…"))
    result = adopt_legacy_profile(
        source_root=paths.source_root,
        database_path=paths.target,
        backup_root=paths.backup_root,
        finalize=activate,
        reject_existing_target=True,
        preserve_source_paths=(paths.settings_path,)
        if paths.settings_path.parent == paths.source_root
        else (),
    )
    if not result.migrated:
        if activation_error is not None:
            raise OfflineLegacyProfileMigrationError(
                "settings_update",
                "Nie można aktywować nowej bazy w local_settings.json; baza docelowa została usunięta.",
            ) from activation_error
        raise OfflineLegacyProfileMigrationError(
            result.error_code or "adoption_failed",
            result.error or "Nie udało się zaimportować wybranej starej konfiguracji.",
        )
    progress(MigrationProgress("activation", 1, 1, "Nowa baza SQLite została aktywowana."))
    cleanup_message = (
        "Niektóre pliki legacy oczekują na przeniesienie do BACKUP."
        if result.error
        else "Pliki legacy zostały przeniesione do BACKUP."
    )
    progress(MigrationProgress("cleanup", 1, 1, cleanup_message))
    return OfflineLegacyProfileReport(
        source_root=paths.source_root,
        target=paths.target,
        source_kind=result.source_kind,
        component_counts=_component_counts(result.report),
        archive_dir=result.archive_dir,
        archive_warning=result.error,
    )
