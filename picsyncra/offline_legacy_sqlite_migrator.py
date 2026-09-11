"""Safe, offline migration of one explicitly configured pre-rebrand SQLite DB."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import json
import shutil
import tempfile
from collections.abc import Callable

from . import storage_settings
from .sqlite_store import SqliteStore


LEGACY_SQLITE_FILENAME = "picorgftp_sql.sqlite"
TARGET_SQLITE_FILENAME = "picsyncra.sqlite"
DATA_MODE_KEY = "data_mode"
DATABASE_LOCATION_MODE_KEY = "database_location_mode"
DATABASE_PATH_KEY = "database_path"


class OfflineMigrationError(RuntimeError):
    """A user-actionable migration failure which leaves source data untouched."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MigrationPaths:
    """Explicit paths approved for one offline SQLite migration."""

    app_root: Path
    settings_path: Path
    source: Path
    target: Path


@dataclass(frozen=True)
class MigrationProgress:
    """One safe-to-display status update from the offline migration."""

    stage: str
    current: int | None
    total: int | None
    message: str


@dataclass(frozen=True)
class OfflineMigrationReport:
    """Validated outcome summary without credentials or account hashes."""

    source: Path
    target: Path
    table_counts: dict[str, int]
    product_count: int
    user_count: int
    archive_dir: Path | None = None
    archive_warning: str | None = None


def _configured_legacy_source(settings_path: Path, payload: dict[str, object]) -> Path:
    """Prefer the explicit old DB path retained in pre-rebrand configurations."""

    mode = str(payload.get(DATABASE_LOCATION_MODE_KEY) or "").strip().lower()
    if mode == "exe_dir":
        return (settings_path.parent / LEGACY_SQLITE_FILENAME).resolve()
    configured = str(payload.get(DATABASE_PATH_KEY) or "").strip()
    if configured:
        expanded = os.path.expandvars(os.path.expanduser(configured.strip("\"'")))
        candidate = Path(expanded)
        if not candidate.is_absolute():
            candidate = settings_path.parent / candidate
        candidate = candidate.resolve()
        if candidate.name == LEGACY_SQLITE_FILENAME:
            return candidate
    if mode == "image_dir":
        base_dir = str(payload.get("base_dir_override") or "").strip()
        if base_dir:
            return (Path(os.path.expandvars(os.path.expanduser(base_dir))) / TARGET_SQLITE_FILENAME).resolve()
    return Path()


def _load_offline_settings(settings_path: Path) -> dict[str, object]:
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise OfflineMigrationError("settings_invalid", "Nie można odczytać local_settings.json.") from error
    if not isinstance(payload, dict):
        raise OfflineMigrationError("settings_invalid", "Plik local_settings.json nie zawiera ustawień aplikacji.")
    return payload


def _update_offline_settings(settings_path: Path, updates: dict[str, object]) -> None:
    payload = _load_offline_settings(settings_path)
    payload.update(updates)
    temporary = settings_path.with_name(f".{settings_path.name}.migrator.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, settings_path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _check_sqlite_integrity(source: Path) -> None:
    try:
        with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as error:
        raise OfflineMigrationError(
            "source_unreadable",
            "Nie można odczytać wskazanej źródłowej bazy SQLite. Zamknij główną aplikację i spróbuj ponownie.",
        ) from error
    if not rows or any(str(row[0]).lower() != "ok" for row in rows):
        raise OfflineMigrationError(
            "source_integrity",
            "Kontrola integralności wskazanej źródłowej bazy SQLite nie powiodła się.",
        )


def resolve_offline_migration_paths(app_root: Path) -> MigrationPaths:
    """Resolve and validate the one legacy database selected by app settings."""

    resolved_app_root = Path(app_root).resolve()
    settings_path = resolved_app_root / "local_settings.json"
    if not settings_path.is_file():
        raise OfflineMigrationError(
            "settings_missing",
            "W wybranym katalogu aplikacji nie znaleziono pliku local_settings.json.",
        )

    payload = _load_offline_settings(settings_path)
    source = _configured_legacy_source(settings_path, payload)
    if source.name != LEGACY_SQLITE_FILENAME:
        raise OfflineMigrationError(
            "source_name",
            "Konfiguracja nie wskazuje pliku picorgftp_sql.sqlite sprzed rebrandingu.",
        )
    if not source.is_file():
        raise OfflineMigrationError(
            "source_missing",
            "Skonfigurowany plik picorgftp_sql.sqlite nie istnieje.",
        )

    target = source.with_name(TARGET_SQLITE_FILENAME)
    if target.exists():
        raise OfflineMigrationError(
            "target_exists",
            "Plik picsyncra.sqlite już istnieje. Migrator nie nadpisuje istniejącej bazy.",
        )

    _check_sqlite_integrity(source)
    return MigrationPaths(
        app_root=resolved_app_root,
        settings_path=settings_path.resolve(),
        source=source,
        target=target,
    )


def _source_connection(source: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)


def _application_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """Count preserved application tables, excluding generated schema structures."""

    excluded = {"schema_version", "operational_events", "operational_event_stream"}
    names = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    counts: dict[str, int] = {}
    for name in names:
        if name in excluded or name.startswith(("product_entries_fts", "product_entries_short_fts")):
            continue
        quoted_name = name.replace('"', '""')
        counts[name] = int(connection.execute(f'SELECT COUNT(*) FROM "{quoted_name}"').fetchone()[0])
    return counts


def _product_ids(connection: sqlite3.Connection) -> tuple[str, ...]:
    try:
        rows = connection.execute(
            "SELECT product_id FROM product_entries ORDER BY product_id"
        ).fetchall()
    except sqlite3.Error:
        return ()
    return tuple(str(row[0]) for row in rows)


def _web_users(connection: sqlite3.Connection) -> dict[str, tuple[str, bool, str]]:
    try:
        rows = connection.execute(
            "SELECT username, payload_json FROM web_users ORDER BY username"
        ).fetchall()
    except sqlite3.Error:
        return {}
    users = {}
    for username, payload_json in rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, ValueError):
            payload = {}
        users[str(username)] = (
            str(payload.get("role") or ""),
            bool(payload.get("enabled", False)),
            str(payload.get("password_hash") or ""),
        )
    return users


def _validate_short_search_triggers(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
        "AND name LIKE 'trg_product_entries_short_fts_%'"
    ).fetchall()
    statements = [str(row[0] or "") for row in rows]
    if len(statements) != 3 or any("picorg_product_short_grams" in sql for sql in statements):
        raise OfflineMigrationError(
            "staging_trigger_validation",
            "Migracja roboczej kopii nie odtworzyła poprawnych triggerów wyszukiwania.",
        )
    if any("picsyncra_product_short_grams" not in sql for sql in statements):
        raise OfflineMigrationError(
            "staging_trigger_validation",
            "Migracja roboczej kopii nie odtworzyła poprawnych triggerów wyszukiwania.",
        )


def _validate_staging_copy(
    staging: Path,
    source_counts: dict[str, int],
    source_product_ids: tuple[str, ...],
    source_users: dict[str, tuple[str, bool, str]],
) -> OfflineMigrationReport:
    with closing(sqlite3.connect(staging)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        if not integrity or any(str(row[0]).lower() != "ok" for row in integrity):
            raise OfflineMigrationError(
                "staging_integrity",
                "Kontrola integralności roboczej kopii SQLite nie powiodła się.",
            )
        staging_counts = _application_table_counts(connection)
        for name, source_count in source_counts.items():
            if staging_counts.get(name) != source_count:
                raise OfflineMigrationError(
                    "staging_table_validation",
                    "Walidacja liczby rekordów roboczej kopii SQLite nie powiodła się.",
                )
        if _product_ids(connection) != source_product_ids:
            raise OfflineMigrationError(
                "staging_product_validation",
                "Walidacja produktów roboczej kopii SQLite nie powiodła się.",
            )
        if _web_users(connection) != source_users:
            raise OfflineMigrationError(
                "staging_user_validation",
                "Walidacja kont roboczej kopii SQLite nie powiodła się.",
            )
        _validate_short_search_triggers(connection)
    return OfflineMigrationReport(
        source=Path(),
        target=Path(),
        table_counts=source_counts,
        product_count=len(source_product_ids),
        user_count=len(source_users),
    )


def build_validated_legacy_sqlite_copy(
    paths: MigrationPaths,
    progress: Callable[[MigrationProgress], None],
) -> tuple[Path, OfflineMigrationReport]:
    """Copy, upgrade and verify source SQLite without opening it for writes."""

    progress(MigrationProgress("copy", 0, None, "Tworzenie roboczej kopii SQLite…"))
    work_dir = Path(
        tempfile.mkdtemp(prefix=".picsyncra-migrator-", dir=paths.target.parent)
    )
    staging = work_dir / TARGET_SQLITE_FILENAME
    try:
        with closing(_source_connection(paths.source)) as source_connection:
            source_counts = _application_table_counts(source_connection)
            source_product_ids = _product_ids(source_connection)
            source_users = _web_users(source_connection)
            with closing(sqlite3.connect(staging)) as staging_connection:
                def report_backup(status: int, remaining: int, total: int) -> None:
                    progress(
                        MigrationProgress(
                            "copy",
                            max(0, total - remaining),
                            total,
                            "Kopiowanie źródłowej SQLite…",
                        )
                    )

                source_connection.backup(staging_connection, pages=256, progress=report_backup)

        progress(MigrationProgress("schema", 0, None, "Aktualizacja schematu roboczej kopii…"))
        SqliteStore(str(staging)).initialize()
        progress(MigrationProgress("validation", 0, None, "Walidacja roboczej kopii SQLite…"))
        report = _validate_staging_copy(
            staging,
            source_counts,
            source_product_ids,
            source_users,
        )
        progress(MigrationProgress("validation", 1, 1, "Walidacja roboczej kopii zakończona."))
        return staging, OfflineMigrationReport(
            source=paths.source,
            target=paths.target,
            table_counts=report.table_counts,
            product_count=report.product_count,
            user_count=report.user_count,
        )
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def _publish_staging_database(staging: Path, target: Path) -> None:
    """Atomically create ``target`` without an overwrite-capable replace call."""

    if target.exists():
        raise OfflineMigrationError(
            "target_exists",
            "Plik picsyncra.sqlite już istnieje. Migrator nie nadpisuje istniejącej bazy.",
        )
    try:
        os.link(staging, target)
    except FileExistsError as error:
        raise OfflineMigrationError(
            "target_exists",
            "Plik picsyncra.sqlite już istnieje. Migrator nie nadpisuje istniejącej bazy.",
        ) from error
    except OSError as error:
        raise OfflineMigrationError(
            "target_publish",
            "Nie można opublikować zweryfikowanej bazy docelowej SQLite.",
        ) from error
    try:
        staging.unlink()
    except OSError as error:
        try:
            target.unlink()
        except OSError:
            pass
        raise OfflineMigrationError(
            "target_publish",
            "Nie można zakończyć publikowania zweryfikowanej bazy docelowej SQLite.",
        ) from error


def _archive_legacy_sqlite_files(paths: MigrationPaths) -> tuple[Path, str | None]:
    """Move only the migrated legacy SQLite set into the selected app's BACKUP."""

    from .legacy_migration import (
        _defer_remaining_source_cleanup,
        _handover_sources_to_archive,
        _legacy_archive_dir,
        _sqlite_source_files,
    )

    backup_root = paths.app_root / "BACKUP"
    archive_dir = _legacy_archive_dir(backup_root)
    try:
        error = _handover_sources_to_archive(
            _sqlite_source_files(paths.source), archive_dir, sqlite_source=True
        )
    except OSError as exc:
        return archive_dir, f"Nie można utworzyć archiwum BACKUP: {exc}"
    remaining = _sqlite_source_files(paths.source)
    if not remaining:
        return archive_dir, error
    deferred_warning = _defer_remaining_source_cleanup(
        sources=remaining,
        sqlite_source=True,
        retired_database=None,
        archive_dir=archive_dir,
        backup_root=backup_root,
    )
    warning = "; ".join(
        item for item in (error, deferred_warning) if item
    ) or "Nie udało się przenieść wszystkich plików legacy do BACKUP."
    return archive_dir, warning


def run_offline_legacy_migration(
    app_root: Path,
    progress: Callable[[MigrationProgress], None],
) -> OfflineMigrationReport:
    """Validate, publish and activate one configured SQLite migration safely."""

    paths = resolve_offline_migration_paths(app_root)
    from .offline_migrator_processes import stop_managed_processes

    progress(MigrationProgress("process", 0, None, "Weryfikacja głównej aplikacji…"))
    stop_managed_processes(
        paths.app_root,
        notify=lambda message: progress(MigrationProgress("process", None, None, message)),
    )
    staging: Path | None = None
    settings_snapshot = paths.settings_path.read_bytes()
    try:
        staging, report = build_validated_legacy_sqlite_copy(paths, progress)
        progress(MigrationProgress("activation", 0, None, "Publikowanie nowej bazy SQLite…"))
        _publish_staging_database(staging, paths.target)
        try:
            _update_offline_settings(
                paths.settings_path,
                {
                    DATA_MODE_KEY: "sqlite",
                    DATABASE_LOCATION_MODE_KEY: "custom",
                    DATABASE_PATH_KEY: str(paths.target),
                },
            )
        except Exception as error:
            try:
                paths.target.unlink()
            except OSError:
                pass
            try:
                storage_settings.restore_bootstrap_settings_file(
                    paths.settings_path, settings_snapshot
                )
            except OSError:
                pass
            raise OfflineMigrationError(
                "settings_update",
                "Nie można aktywować nowej bazy w local_settings.json; baza docelowa została usunięta.",
            ) from error
        progress(MigrationProgress("cleanup", 0, None, "Archiwizowanie plików legacy…"))
        archive_dir, archive_warning = _archive_legacy_sqlite_files(paths)
        cleanup_message = (
            "Niektóre pliki legacy oczekują na przeniesienie do BACKUP."
            if archive_warning
            else "Pliki legacy zostały przeniesione do BACKUP."
        )
        progress(MigrationProgress("cleanup", 1, 1, cleanup_message))
        progress(MigrationProgress("activation", 1, 1, "Nowa baza została aktywowana."))
        return OfflineMigrationReport(
            source=report.source,
            target=report.target,
            table_counts=report.table_counts,
            product_count=report.product_count,
            user_count=report.user_count,
            archive_dir=archive_dir,
            archive_warning=archive_warning,
        )
    finally:
        if staging is not None:
            shutil.rmtree(staging.parent, ignore_errors=True)
