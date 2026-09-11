"""One-time adoption of PicSyncra data from the working product name."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .brand import SQLITE_FILENAME
from .legacy_import import import_legacy_to_sqlite
from .legacy_profile import (
    LEGACY_DATA_FILENAMES as PROFILE_LEGACY_DATA_FILENAMES,
    LEGACY_SQLITE_FILENAME as PROFILE_SQLITE_FILENAME,
    LEGACY_SQLITE_SIDECARS as PROFILE_SQLITE_SIDECARS,
    LegacyProfile,
    discover_legacy_profiles,
    load_legacy_profile,
)
from .legacy_profile_import import stage_legacy_profile_import
from .sqlite_coordination import (
    clear_retired_database_marker,
    database_maintenance,
    maintenance_state,
    retire_database,
)


_LEGACY_SQLITE_FILENAME = "picorgftp_sql.sqlite"
_SQLITE_SIDECARS = ("-wal", "-shm")
_EMPTY_TARGET_TABLES = frozenset({"schema_version", "operational_event_stream"})
_EMPTY_TARGET_FTS_PREFIXES = ("product_entries_fts", "product_entries_short_fts")
_LEGACY_DATA_FILENAMES = (
    "config.json",
    "lists.xlsx",
    "web_users.json",
    "web_history.json",
    "file_index.json",
)
_TARGET_EXISTS = "target_exists"
_ADOPTION_IN_PROGRESS = "adoption_in_progress"
_SPLIT_FILE_SOURCES = "split_file_sources"
_MIXED_SOURCES = "mixed_sources"
_ADOPTION_FAILED = "adoption_failed"
_PENDING_TARGET_CLEANUP_DIRNAME = ".pending-target-cleanup"
_PENDING_SOURCE_CLEANUP_DIRNAME = ".pending-source-cleanup"
_PENDING_TARGET_CLEANUP_RETRY_SECONDS = 1.0
_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()
_PENDING_TARGET_CLEANUPS: set[str] = set()
_PENDING_TARGET_CLEANUPS_GUARD = threading.Lock()
_PENDING_SOURCE_CLEANUPS: set[str] = set()
_PENDING_SOURCE_CLEANUPS_GUARD = threading.Lock()


class _AdoptionInProgressError(RuntimeError):
    """The target is currently guarded by another PicSyncra import action."""


class _TargetAlreadyExistsError(FileExistsError):
    """The target appeared while a staged database was being prepared."""


@dataclass(frozen=True)
class MigrationResult:
    migrated: bool
    skipped: bool
    copied_paths: tuple[Path, ...] = ()
    error: str | None = None
    source_kind: str = ""
    archive_dir: Path | None = None
    error_code: str | None = None
    replaced_target: bool = False
    report: dict[str, object] | None = None


def _unique_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.resolve()
        key = str(resolved).casefold()
        if key not in seen:
            unique.append(resolved)
            seen.add(key)
    return tuple(unique)


def migrate_legacy_data(application_root: Path, data_root: Path) -> MigrationResult:
    """Retired automatic importer kept as a no-op compatibility function.

    A caller must use the explicit, profile-scoped import action instead of
    silently copying files during startup.
    """

    del application_root, data_root
    return MigrationResult(migrated=False, skipped=True)


def _legacy_sqlite_source(
    application_root: Path,
    data_root: Path,
    legacy_database_path: Path | None = None,
) -> Path | None:
    configured = Path(legacy_database_path) if legacy_database_path else None
    if (
        configured is not None
        and configured.name.casefold() == _LEGACY_SQLITE_FILENAME.casefold()
        and configured.is_file()
    ):
        return configured
    for root in _unique_paths((Path(data_root), Path(application_root))):
        candidate = root / _LEGACY_SQLITE_FILENAME
        if candidate.is_file():
            return candidate
    return None


def adoption_database_path(database_path: Path) -> Path:
    """Return the current database name when settings still point to the old one."""

    candidate = Path(database_path)
    if candidate.name.casefold() == _LEGACY_SQLITE_FILENAME.casefold():
        return candidate.with_name(SQLITE_FILENAME)
    return candidate


def _profile_sqlite_source_files(profile: LegacyProfile) -> tuple[Path, ...]:
    if profile.sqlite_path is None:
        return ()
    return tuple(
        source
        for source in profile.source_files
        if source.name.casefold()
        in {
            PROFILE_SQLITE_FILENAME.casefold(),
            *(f"{PROFILE_SQLITE_FILENAME}{suffix}".casefold() for suffix in PROFILE_SQLITE_SIDECARS),
        }
    )


def _snapshot_legacy_profile(profile: LegacyProfile, snapshot_root: Path) -> LegacyProfile:
    """Create one stable copy of a profile before reading, archiving, or publishing it."""

    snapshot_root.mkdir(parents=True, exist_ok=False)
    sqlite_sources = set(_profile_sqlite_source_files(profile))
    if profile.sqlite_path is not None:
        _copy_sqlite_database(
            profile.sqlite_path,
            snapshot_root / PROFILE_SQLITE_FILENAME,
        )
    for source in profile.source_files:
        if source in sqlite_sources:
            continue
        destination = snapshot_root / source.name
        shutil.copy2(source, destination)
        if not _files_match(source, destination):
            raise OSError(f"Nie udalo sie zweryfikowac snapshotu: {source.name}")
    snapshot = load_legacy_profile(snapshot_root)
    if snapshot is None:
        raise OSError("Nie udalo sie utworzyc snapshotu starej konfiguracji.")
    return snapshot


def _archive_profile_snapshot(profile: LegacyProfile, archive_dir: Path) -> None:
    """Persist a verified stable source snapshot before publishing a new target."""

    archive_dir.mkdir(parents=True, exist_ok=False)
    for source in profile.source_files:
        destination = archive_dir / source.name
        shutil.copy2(source, destination)
        if source.name.casefold() == PROFILE_SQLITE_FILENAME.casefold():
            _validate_sqlite_database(destination)
        elif not _files_match(source, destination):
            raise OSError(f"Nie udalo sie zweryfikowac archiwum: {source.name}")


def _profile_publish_path(target: Path) -> Path:
    """Use a fresh target whenever replacing an active database on Windows."""

    if not target.exists():
        return target
    return target.with_name(f"{target.stem}-import-{uuid4().hex[:8]}{target.suffix}")


def _publish_profile_staging(
    staging: Path, destination: Path, *, reject_existing_target: bool = False
) -> None:
    if reject_existing_target:
        try:
            os.link(staging, destination)
        except FileExistsError as exc:
            raise _TargetAlreadyExistsError("Docelowa baza PicSyncra juz istnieje.") from exc
        return
    if destination.exists():
        raise _TargetAlreadyExistsError("Docelowa baza PicSyncra juz istnieje.")
    os.replace(staging, destination)


def _write_profile_import_report(archive_dir: Path, report: dict[str, object]) -> None:
    destination = archive_dir / "import-report.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, destination)


def _move_profile_sources_to_archive(profile: LegacyProfile, archive_dir: Path) -> str | None:
    """Move only the original selected profile; no discovery runs during cleanup."""

    errors: list[str] = []
    sqlite_sources = _profile_sqlite_source_files(profile)
    if sqlite_sources:
        error = _handover_sources_to_archive(
            sqlite_sources,
            archive_dir,
            sqlite_source=True,
        )
        if error:
            errors.append(error)
    other_sources = tuple(source for source in profile.source_files if source not in sqlite_sources)
    if other_sources:
        error = _handover_sources_to_archive(
            other_sources,
            archive_dir,
            sqlite_source=False,
        )
        if error:
            errors.append(error)
    return "; ".join(errors) or None


def adopt_legacy_profile(
    *,
    source_root: Path,
    database_path: Path,
    backup_root: Path,
    finalize: Callable[[Path, dict[str, object]], Callable[[], None] | None] | None = None,
    replace_existing_target: bool = False,
    reject_existing_target: bool = False,
    preserve_source_paths: tuple[Path, ...] = (),
) -> MigrationResult:
    """Atomically activate data from one complete old-application profile."""

    profile = load_legacy_profile(source_root)
    if profile is None:
        return MigrationResult(migrated=False, skipped=True)
    target = Path(database_path).resolve()
    backup = Path(backup_root).resolve()
    if target.exists() and (
        reject_existing_target or not _is_empty_picsyncra_database(target)
    ) and not replace_existing_target:
        return MigrationResult(
            migrated=False,
            skipped=False,
            error="Docelowa baza PicSyncra juz istnieje.",
            error_code=_TARGET_EXISTS,
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    archive_dir = _legacy_archive_dir(backup)
    publish_path = _profile_publish_path(target)
    preserved_paths = {Path(path).resolve() for path in preserve_source_paths}
    movable_sources = tuple(
        source for source in profile.source_files if source.resolve() not in preserved_paths
    )
    source_kind = "sqlite+files" if profile.has_sqlite and len(profile.source_files) > 1 else (
        "sqlite" if profile.has_sqlite else "files"
    )
    published = False
    replaced_existing_target = False
    report: dict[str, object] | None = None
    activation_rollback: Callable[[], None] | None = None
    temporary_cleanup_warning: str | None = None
    try:
        with _exclusive_path_lock(
            backup_root=backup,
            scope="profile-source",
            protected_path=profile.root,
        ):
            with _exclusive_path_lock(
                backup_root=backup,
                scope="profile-target",
                protected_path=target,
            ):
                temporary_directory = TemporaryDirectory(
                    prefix=".picsyncra-profile-", dir=target.parent
                )
                try:
                    temporary_root = Path(temporary_directory.name)
                    snapshot_root = temporary_root / "profile-snapshot"
                    staging = temporary_root / publish_path.name
                    maintenance = (
                        database_maintenance(profile.sqlite_path)
                        if profile.sqlite_path is not None
                        else nullcontext()
                    )
                    with maintenance:
                        source_lock = (
                            _locked_sqlite_source(profile.sqlite_path)
                            if profile.sqlite_path is not None
                            else nullcontext()
                        )
                        with source_lock:
                            snapshot = _snapshot_legacy_profile(profile, snapshot_root)
                            staged_report = stage_legacy_profile_import(snapshot, staging)
                            report = staged_report.public_dict()
                            _archive_profile_snapshot(snapshot, archive_dir)
                            _write_profile_import_report(archive_dir, report)
                            if target.exists():
                                if reject_existing_target and not replace_existing_target:
                                    raise _TargetAlreadyExistsError(
                                        "Docelowa baza PicSyncra juz istnieje."
                                    )
                                _archive_existing_target(target, archive_dir)
                                replaced_existing_target = True
                            _publish_profile_staging(
                                staging,
                                publish_path,
                                reject_existing_target=(
                                    reject_existing_target and not replace_existing_target
                                ),
                            )
                            published = True
                            if finalize is not None:
                                activation_rollback = finalize(
                                    publish_path, staged_report.bootstrap_settings
                                )
                            if profile.sqlite_path is not None:
                                retire_database(profile.sqlite_path)
                finally:
                    try:
                        temporary_directory.cleanup()
                    except OSError as cleanup_error:
                        if not published:
                            raise
                        temporary_cleanup_warning = (
                            "Nie udało się usunąć roboczego katalogu migracji: "
                            f"{cleanup_error}"
                        )
    except _AdoptionInProgressError as exc:
        return MigrationResult(
            migrated=False,
            skipped=False,
            error=str(exc),
            error_code=_ADOPTION_IN_PROGRESS,
        )
    except _TargetAlreadyExistsError as exc:
        return MigrationResult(
            migrated=False,
            skipped=False,
            error=str(exc),
            error_code=_TARGET_EXISTS,
        )
    except Exception as exc:
        rollback_error: Exception | None = None
        if activation_rollback is not None:
            try:
                activation_rollback()
            except Exception as rollback_exc:
                rollback_error = rollback_exc
        if published:
            try:
                publish_path.unlink()
            except OSError:
                pass
        error = str(exc)
        if rollback_error is not None:
            error = f"{error}; nie udalo sie wycofac aktywacji: {rollback_error}"
        return MigrationResult(
            migrated=False,
            skipped=False,
            error=error,
            error_code=_ADOPTION_FAILED,
        )

    cleanup_profile = LegacyProfile(
        root=profile.root,
        sqlite_path=(
            profile.sqlite_path
            if profile.sqlite_path is not None and profile.sqlite_path.resolve() not in preserved_paths
            else None
        ),
        source_files=movable_sources,
        manifest=profile.manifest,
    )
    cleanup_error = _move_profile_sources_to_archive(cleanup_profile, archive_dir)
    sqlite_remaining = tuple(
        source for source in _profile_sqlite_source_files(cleanup_profile) if source.is_file()
    )
    other_remaining = tuple(
        source
        for source in cleanup_profile.source_files
        if source not in sqlite_remaining and source.is_file()
    )
    cleanup_warnings: list[str] = []
    if sqlite_remaining:
        cleanup_warnings.append(
            _defer_remaining_source_cleanup(
                sources=sqlite_remaining,
                sqlite_source=True,
                retired_database=profile.sqlite_path,
                archive_dir=archive_dir,
                backup_root=backup,
            )
            or ""
        )
    if other_remaining:
        cleanup_warnings.append(
            _defer_remaining_source_cleanup(
                sources=other_remaining,
                sqlite_source=False,
                retired_database=profile.sqlite_path,
                archive_dir=archive_dir,
                backup_root=backup,
            )
            or ""
        )
    if not sqlite_remaining and not other_remaining and profile.sqlite_path is not None:
        clear_retired_database_marker(profile.sqlite_path)
    replaced_target_warning = (
        _archive_or_defer_replaced_target(
            previous_target=target,
            active_target=publish_path,
            archive_dir=archive_dir,
            backup_root=backup,
        )
        if replaced_existing_target
        else None
    )

    return MigrationResult(
        migrated=True,
        skipped=False,
        copied_paths=(publish_path,),
        error="; ".join(
            item
            for item in (
                cleanup_error,
                *cleanup_warnings,
                replaced_target_warning,
                temporary_cleanup_warning,
            )
            if item
        )
        or None,
        source_kind=source_kind,
        archive_dir=archive_dir,
        replaced_target=replaced_existing_target,
        report=report,
    )


def _legacy_file_source_sets(
    application_root: Path,
    data_root: Path,
    *,
    sqlite_source: Path | None = None,
) -> tuple[tuple[Path, tuple[Path, ...]], ...]:
    """Return complete per-directory source sets without combining directories.

    A configured legacy database defines the old configuration directory.  Its
    companion JSON/XLSX files must be discovered there first: after a rebrand
    the new application and image roots can contain unrelated, freshly-created
    files.  Any second directory with legacy files is still reported as an
    ambiguous import instead of silently combining configurations.
    """

    source_sets: list[tuple[Path, tuple[Path, ...]]] = []
    companion_root = sqlite_source.parent if sqlite_source is not None else Path(data_root)
    for root in _unique_paths((companion_root, Path(data_root), Path(application_root))):
        sources = tuple(root / filename for filename in _LEGACY_DATA_FILENAMES if (root / filename).is_file())
        if sources:
            source_sets.append((root, sources))
    return tuple(source_sets)


def _sqlite_source_files(source: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in (source, *(source.with_name(source.name + suffix) for suffix in _SQLITE_SIDECARS))
        if path.is_file()
    )


def _legacy_archive_dir(backup_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return backup_root / "legacy-import" / f"{timestamp}-{uuid4().hex[:8]}"


def _latest_archived_legacy_files(backup_root: Path) -> Path | None:
    """Find an archived JSON/XLSX source left by a completed earlier import."""

    archive_root = Path(backup_root) / "legacy-import"
    try:
        candidates = sorted(
            (path for path in archive_root.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for candidate in candidates:
        if any((candidate / filename).is_file() for filename in _LEGACY_DATA_FILENAMES):
            return candidate
    return None


def _copy_sqlite_database(source: Path, target: Path) -> None:
    connection = None
    target_connection = None
    try:
        connection = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
        target_connection = sqlite3.connect(str(target))
        connection.backup(target_connection)
        integrity = target_connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            raise sqlite3.DatabaseError("SQLite integrity check failed")
    finally:
        if target_connection is not None:
            target_connection.close()
        if connection is not None:
            connection.close()


@contextmanager
def _locked_sqlite_source(source: Path) -> Iterator[None]:
    """Prevent new legacy SQLite writes while its data is copied and archived."""

    connection = sqlite3.connect(
        f"{source.resolve().as_uri()}?mode=rw",
        uri=True,
        timeout=5,
    )
    try:
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("BEGIN IMMEDIATE")
        yield
    finally:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        connection.close()


def _validate_sqlite_database(path: Path) -> None:
    connection = None
    try:
        connection = sqlite3.connect(str(path))
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            raise sqlite3.DatabaseError("SQLite integrity check failed")
    finally:
        if connection is not None:
            connection.close()


def _is_empty_picsyncra_database(path: Path) -> bool:
    """Return whether a target contains only the schema made during first start."""

    connection = None
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        table_rows = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        for table_name, definition in table_rows:
            table_name = str(table_name)
            if table_name in _EMPTY_TARGET_TABLES:
                continue
            if table_name.startswith(_EMPTY_TARGET_FTS_PREFIXES):
                continue
            if str(definition or "").lstrip().upper().startswith("CREATE VIRTUAL TABLE"):
                continue
            quoted_name = table_name.replace('"', '""')
            if connection.execute(f'SELECT 1 FROM "{quoted_name}" LIMIT 1').fetchone() is not None:
                return False
        return True
    except (OSError, sqlite3.Error):
        return False
    finally:
        if connection is not None:
            connection.close()


def _copy_sources_to_archive(
    sources: tuple[Path, ...],
    archive_dir: Path,
    *,
    sqlite_source: Path | None = None,
    sqlite_snapshot: Path | None = None,
) -> None:
    archive_dir.mkdir(parents=True, exist_ok=sqlite_source is not None)
    if sqlite_source is not None:
        if sqlite_snapshot is None:
            raise ValueError("Brakuje zweryfikowanego snapshotu SQLite do archiwizacji.")
        destination = archive_dir / sqlite_source.name
        shutil.copy2(sqlite_snapshot, destination)
        _validate_sqlite_database(destination)
    for source in sources:
        destination = archive_dir / source.name
        if destination.exists():
            destination = archive_dir / f"{source.stem}-{uuid4().hex[:8]}{source.suffix}"
        shutil.copy2(source, destination)
        if destination.stat().st_size != source.stat().st_size:
            raise OSError(f"Nie udalo sie zweryfikowac kopii archiwalnej: {source.name}")


def _archive_existing_target(target: Path, archive_dir: Path) -> Path:
    """Store a verified SQLite snapshot before a confirmed target replacement."""

    destination = archive_dir / f"previous-{target.name}"
    if destination.exists():
        raise FileExistsError(f"Archiwum docelowej bazy juz istnieje: {destination.name}")
    _copy_sqlite_database(target, destination)
    _validate_sqlite_database(destination)
    return destination


def _handover_sources_to_archive(
    sources: tuple[Path, ...],
    archive_dir: Path,
    *,
    sqlite_source: bool,
) -> str | None:
    """Move originals to the archive without a copy-then-delete race."""

    errors: list[str] = []
    source_files = tuple(source for source in sources if source.is_file())
    if not source_files:
        return "Nie znaleziono zrodlowych plikow do przeniesienia po imporcie."
    destination_root = archive_dir / "legacy-source-files" if sqlite_source else archive_dir
    destination_root.mkdir(parents=True, exist_ok=True)
    changed_files = [
        source.name
        for source in source_files
        if not sqlite_source
        and (destination := destination_root / source.name).is_file()
        and not _files_match(source, destination)
    ]
    try:
        same_volume = all(
            source.stat().st_dev == destination_root.stat().st_dev for source in source_files
        )
    except OSError as exc:
        return f"Nie udalo sie sprawdzic plikow przed przeniesieniem: {exc}"
    quarantine_dir: Path | None = None
    if not same_volume:
        quarantine_dir = source_files[0].parent / f".picsyncra-legacy-{uuid4().hex}"
        quarantine_dir.mkdir()
    moved_files: list[tuple[Path, Path]] = []
    for source in source_files:
        destination = (
            destination_root / source.name
            if quarantine_dir is None
            else quarantine_dir / source.name
        )
        try:
            os.replace(source, destination)
            moved_files.append((source, destination))
        except FileNotFoundError:
            errors.append(f"{source.name}: plik zniknal przed przeniesieniem")
        except OSError as exc:
            errors.append(f"{source.name}: {exc}")
            # A SQLite sidecar without its main database is not a useful archive.
            # If Windows still keeps the database open, leave the whole set in
            # place and let the deferred handover retry it together.
            if sqlite_source and source == source_files[0]:
                break
    if quarantine_dir is not None and moved_files:
        for _source, staged in moved_files:
            destination = destination_root / staged.name
            try:
                shutil.copy2(staged, destination)
                if destination.stat().st_size != staged.stat().st_size:
                    raise OSError("nieudana weryfikacja kopii po przeniesieniu")
            except OSError as exc:
                errors.append(f"{staged.name}: {exc}")
        if os.name == "nt" and not errors:
            for _source, staged in moved_files:
                try:
                    staged.unlink()
                except OSError as exc:
                    errors.append(f"{staged.name}: {exc}")
            try:
                quarantine_dir.rmdir()
            except OSError as exc:
                errors.append(f"{quarantine_dir.name}: {exc}")
        elif os.name != "nt":
            errors.append(
                f"{quarantine_dir.name}: zachowano kwarantanne dla bezpieczenstwa danych"
            )
    if changed_files:
        errors.append(
            "Zrodlo zmienilo sie podczas importu; najnowsza wersja zostala przeniesiona do archiwum: "
            + ", ".join(changed_files)
        )
    return "; ".join(errors) or None


def _pending_target_cleanup_dir(backup_root: Path) -> Path:
    return Path(backup_root) / "legacy-import" / _PENDING_TARGET_CLEANUP_DIRNAME


def _pending_source_cleanup_dir(backup_root: Path) -> Path:
    return Path(backup_root) / "legacy-import" / _PENDING_SOURCE_CLEANUP_DIRNAME


def _is_descendant(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _write_pending_target_cleanup(
    *,
    source: Path,
    archive_dir: Path,
    backup_root: Path,
) -> Path:
    """Persist a deferred move so an interrupted process can resume it later."""

    pending_dir = _pending_target_cleanup_dir(backup_root)
    pending_dir.mkdir(parents=True, exist_ok=True)
    manifest = pending_dir / f"{uuid4().hex}.json"
    temporary = manifest.with_suffix(".tmp")
    payload = {
        "source": str(source.resolve()),
        "archive_dir": str(archive_dir.resolve()),
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, manifest)
    return manifest


def _write_pending_source_cleanup(
    *,
    sources: tuple[Path, ...],
    archive_dir: Path,
    backup_root: Path,
    sqlite_source: bool,
    retired_database: Path | None = None,
) -> Path:
    """Persist a deferred legacy-source move after a temporary file lock."""

    pending_dir = _pending_source_cleanup_dir(backup_root)
    pending_dir.mkdir(parents=True, exist_ok=True)
    manifest = pending_dir / f"{uuid4().hex}.json"
    temporary = manifest.with_suffix(".tmp")
    payload = {
        "sources": [str(source.resolve()) for source in sources],
        "archive_dir": str(archive_dir.resolve()),
        "sqlite_source": bool(sqlite_source),
        "retired_database": str(retired_database.resolve()) if retired_database else "",
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, manifest)
    return manifest


def _process_pending_target_cleanup(manifest: Path, backup_root: Path) -> bool:
    """Return whether a persisted post-switch archive move has completed."""

    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        source = Path(payload["source"]).resolve()
        archive_dir = Path(payload["archive_dir"]).resolve()
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return False

    legacy_backup_root = (Path(backup_root) / "legacy-import").resolve()
    if not _is_descendant(archive_dir, legacy_backup_root):
        return False

    _handover_sources_to_archive(
        _sqlite_source_files(source),
        archive_dir,
        sqlite_source=True,
    )
    return not _sqlite_source_files(source)


def _process_pending_source_cleanup(manifest: Path, backup_root: Path) -> bool:
    """Retry an archived companion-file handover recorded after a file lock."""

    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        sources = tuple(Path(value).resolve() for value in payload["sources"])
        archive_dir = Path(payload["archive_dir"]).resolve()
        sqlite_source = bool(payload["sqlite_source"])
        retired_text = str(payload.get("retired_database") or "")
        retired_database = Path(retired_text).resolve() if retired_text else None
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return False

    legacy_backup_root = (Path(backup_root) / "legacy-import").resolve()
    if not sources or not _is_descendant(archive_dir, legacy_backup_root):
        return False
    if sqlite_source:
        valid_source_names = {
            _LEGACY_SQLITE_FILENAME,
            *(
                f"{_LEGACY_SQLITE_FILENAME}{suffix}"
                for suffix in _SQLITE_SIDECARS
            ),
        }
    else:
        valid_source_names = set(_LEGACY_DATA_FILENAMES) | set(PROFILE_LEGACY_DATA_FILENAMES)
    if any(source.name.casefold() not in valid_source_names for source in sources):
        return False

    _handover_sources_to_archive(sources, archive_dir, sqlite_source=sqlite_source)
    completed = not any(source.is_file() for source in sources)
    if completed and retired_database is not None:
        clear_retired_database_marker(retired_database)
    return completed


def process_pending_legacy_target_cleanups(backup_root: Path) -> None:
    """Finish old-target and companion-file moves left pending by file locks."""

    for pending_dir, processor in (
        (_pending_target_cleanup_dir(backup_root), _process_pending_target_cleanup),
        (_pending_source_cleanup_dir(backup_root), _process_pending_source_cleanup),
    ):
        if not pending_dir.is_dir():
            continue
        for manifest in sorted(pending_dir.glob("*.json")):
            if processor(manifest, backup_root):
                try:
                    manifest.unlink()
                except OSError:
                    pass


def _schedule_pending_target_cleanup(manifest: Path, backup_root: Path) -> None:
    """Retry a locked old database in the background without another import."""

    key = str(manifest.resolve()).casefold()
    with _PENDING_TARGET_CLEANUPS_GUARD:
        if key in _PENDING_TARGET_CLEANUPS:
            return
        _PENDING_TARGET_CLEANUPS.add(key)

    def retry() -> None:
        try:
            while manifest.exists():
                if _process_pending_target_cleanup(manifest, backup_root):
                    try:
                        manifest.unlink()
                    except OSError:
                        pass
                    return
                time.sleep(_PENDING_TARGET_CLEANUP_RETRY_SECONDS)
        finally:
            with _PENDING_TARGET_CLEANUPS_GUARD:
                _PENDING_TARGET_CLEANUPS.discard(key)

    threading.Thread(
        target=retry,
        name="picsyncra-legacy-target-cleanup",
        daemon=True,
    ).start()


def _schedule_pending_source_cleanup(manifest: Path, backup_root: Path) -> None:
    """Retry a locked legacy companion move without another import action."""

    key = str(manifest.resolve()).casefold()
    with _PENDING_SOURCE_CLEANUPS_GUARD:
        if key in _PENDING_SOURCE_CLEANUPS:
            return
        _PENDING_SOURCE_CLEANUPS.add(key)

    def retry() -> None:
        try:
            while manifest.exists():
                if _process_pending_source_cleanup(manifest, backup_root):
                    try:
                        manifest.unlink()
                    except OSError:
                        pass
                    return
                time.sleep(_PENDING_TARGET_CLEANUP_RETRY_SECONDS)
        finally:
            with _PENDING_SOURCE_CLEANUPS_GUARD:
                _PENDING_SOURCE_CLEANUPS.discard(key)

    threading.Thread(
        target=retry,
        name="picsyncra-legacy-source-cleanup",
        daemon=True,
    ).start()


def _defer_remaining_source_cleanup(
    *,
    sources: tuple[Path, ...],
    sqlite_source: bool,
    retired_database: Path | None,
    archive_dir: Path,
    backup_root: Path,
) -> str | None:
    """Record and schedule a retry only for source files that still exist."""

    remaining = tuple(source for source in sources if source.is_file())
    if not remaining:
        return None
    try:
        manifest = _write_pending_source_cleanup(
            sources=remaining,
            archive_dir=archive_dir,
            backup_root=backup_root,
            sqlite_source=sqlite_source,
            retired_database=retired_database,
        )
        _schedule_pending_source_cleanup(manifest, backup_root)
    except OSError as exc:
        return f"Nie udalo sie zaplanowac przeniesienia pozostalych plikow: {exc}"
    return (
        "Niektore zrodlowe pliki sa jeszcze uzywane przez inny proces. "
        "Zostana automatycznie przeniesione do BACKUP po zwolnieniu plikow."
    )


def _archive_or_defer_replaced_target(
    *,
    previous_target: Path,
    active_target: Path,
    archive_dir: Path,
    backup_root: Path,
) -> str | None:
    """Archive a replaced target now, or automatically after its handle closes."""

    if previous_target.resolve() == active_target.resolve():
        return None

    _handover_sources_to_archive(
        _sqlite_source_files(previous_target),
        archive_dir,
        sqlite_source=True,
    )
    if not _sqlite_source_files(previous_target):
        return None

    manifest = _write_pending_target_cleanup(
        source=previous_target,
        archive_dir=archive_dir,
        backup_root=backup_root,
    )
    _schedule_pending_target_cleanup(manifest, backup_root)
    return (
        "Poprzednia baza SQLite jest jeszcze uzywana przez inny proces. "
        "Zostanie automatycznie przeniesiona do BACKUP po zwolnieniu pliku."
    )


def _files_match(first: Path, second: Path) -> bool:
    try:
        if first.stat().st_size != second.stat().st_size:
            return False
        return hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    except OSError:
        return False


@contextmanager
def _exclusive_path_lock(
    *,
    backup_root: Path,
    scope: str,
    protected_path: Path,
) -> Iterator[None]:
    """Use process- and OS-level locks that are released when a process exits."""

    canonical_path = str(protected_path.resolve()).casefold()
    lock_key = f"{scope}:{canonical_path}"
    digest = hashlib.sha256(lock_key.encode("utf-8")).hexdigest()
    lock_path = Path(backup_root) / "legacy-import" / ".locks" / f"{scope}-{digest}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _PATH_LOCKS_GUARD:
        local_lock = _PATH_LOCKS.setdefault(lock_key, threading.Lock())
    with local_lock:
        descriptor = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
        locked = False
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise _AdoptionInProgressError(
                        "Trwa juz wczytywanie starej konfiguracji dla tej bazy."
                    ) from exc
                raise
            yield
        finally:
            try:
                if locked:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _publish_staged_target(
    staging: Path,
    target: Path,
    *,
    replace_target: bool = False,
) -> tuple[Path, str | None]:
    """Publish a staged database without replacing an unapproved target."""

    if replace_target and target.exists():
        try:
            target.unlink()
        except PermissionError as exc:
            if getattr(exc, "winerror", None) != 32:
                raise
            fallback = target.with_name(
                f"{target.stem}-legacy-import-{uuid4().hex[:8]}{target.suffix}"
            )
            os.link(staging, fallback)
            return (
                fallback,
                "Biezaca baza SQLite byla uzywana przez inny proces. "
                f"Wczytane dane zostaly aktywowane w pliku {fallback.name}.",
            )
    try:
        os.link(staging, target)
    except FileExistsError as exc:
        raise _TargetAlreadyExistsError("Docelowa baza PicSyncra juz istnieje.") from exc
    return target, None


def _restore_archived_legacy_data(
    *,
    archived_source: Path,
    target: Path,
    backup_root: Path,
    finalize: Callable[[Path], None] | None,
) -> MigrationResult:
    """Repair an earlier incomplete adoption from its immutable BACKUP copy."""

    archive_dir = _legacy_archive_dir(backup_root)
    archive_dir.mkdir(parents=True, exist_ok=False)
    archived_database = archived_source / _LEGACY_SQLITE_FILENAME
    source_kind = "backup-sqlite+files" if archived_database.is_file() else "backup-files"
    target_replaced = target.exists()
    previous_target = target
    publish_warning: str | None = None
    deferred_cleanup_warning: str | None = None
    try:
        with _exclusive_path_lock(
            backup_root=backup_root,
            scope="target",
            protected_path=target,
        ):
            with TemporaryDirectory(prefix=".picsyncra-legacy-recovery-", dir=target.parent) as temporary_dir:
                staging = Path(temporary_dir) / target.name
                if archived_database.is_file():
                    _copy_sqlite_database(archived_database, staging)
                elif target.exists():
                    _copy_sqlite_database(target, staging)
                import_legacy_to_sqlite(
                    str(archived_source),
                    str(staging),
                    merge_existing=True,
                )
                _validate_sqlite_database(staging)
                if target.exists():
                    _archive_existing_target(target, archive_dir)
                target, publish_warning = _publish_staged_target(
                    staging,
                    target,
                    replace_target=target.exists(),
                )
                if finalize is not None:
                    finalize(target)
    except _AdoptionInProgressError as exc:
        return MigrationResult(
            migrated=False,
            skipped=False,
            error=str(exc),
            error_code=_ADOPTION_IN_PROGRESS,
        )
    except (OSError, sqlite3.Error, ValueError) as exc:
        return MigrationResult(
            migrated=False,
            skipped=False,
            error=str(exc),
            error_code=_ADOPTION_FAILED,
        )
    deferred_cleanup_warning = _archive_or_defer_replaced_target(
        previous_target=previous_target,
        active_target=target,
        archive_dir=archive_dir,
        backup_root=backup_root,
    )
    return MigrationResult(
        migrated=True,
        skipped=False,
        copied_paths=(target,),
        error="; ".join(
            warning for warning in (publish_warning, deferred_cleanup_warning) if warning
        ) or None,
        source_kind=source_kind,
        archive_dir=archive_dir,
        replaced_target=target_replaced,
    )


def adopt_legacy_data(
    *,
    application_root: Path,
    data_root: Path,
    database_path: Path,
    backup_root: Path,
    legacy_database_path: Path | None = None,
    finalize: Callable[[Path], None] | None = None,
    replace_existing_target: bool = False,
) -> MigrationResult:
    """Compatibility adapter for the profile-transaction importer.

    The product UI calls :func:`adopt_legacy_profile` directly.  This retained
    public entry point deliberately performs only the same one-profile
    selection and delegates all staging, validation, activation and cleanup to
    that transaction; it must never combine independent roots.
    """

    configured_source = Path(legacy_database_path) if legacy_database_path else None
    candidate_roots = (
        (configured_source.parent,)
        if configured_source is not None
        and configured_source.name.casefold() == PROFILE_SQLITE_FILENAME.casefold()
        else (Path(data_root), Path(application_root))
    )
    profiles = discover_legacy_profiles(candidate_roots)
    if not profiles:
        return MigrationResult(migrated=False, skipped=True)
    if len(profiles) != 1:
        return MigrationResult(
            migrated=False,
            skipped=False,
            error="Znaleziono stare dane w wiecej niz jednej lokalizacji.",
            error_code=_MIXED_SOURCES if configured_source is not None else _SPLIT_FILE_SOURCES,
        )

    def finalize_profile(
        active_database: Path, _bootstrap_settings: dict[str, object]
    ) -> Callable[[], None] | None:
        return finalize(active_database) if finalize is not None else None

    return adopt_legacy_profile(
        source_root=profiles[0].root,
        database_path=adoption_database_path(Path(database_path)),
        backup_root=Path(backup_root),
        finalize=finalize_profile if finalize is not None else None,
        replace_existing_target=replace_existing_target,
    )


def _retired_adopt_legacy_data(
    *,
    application_root: Path,
    data_root: Path,
    database_path: Path,
    backup_root: Path,
    legacy_database_path: Path | None = None,
    finalize: Callable[[Path], None] | None = None,
    replace_existing_target: bool = False,
) -> MigrationResult:
    """Adopt historical data into one PicSyncra SQLite database and archive sources."""

    sqlite_source = _legacy_sqlite_source(
        application_root,
        data_root,
        legacy_database_path,
    )
    file_source_sets = _legacy_file_source_sets(
        application_root,
        data_root,
        sqlite_source=sqlite_source,
    )
    if sqlite_source is not None:
        sqlite_source_root = sqlite_source.parent.resolve()
        if any(root.resolve() != sqlite_source_root for root, _sources in file_source_sets):
            return MigrationResult(
                migrated=False,
                skipped=False,
                error=(
                    "Stare pliki danych nie znajduja sie obok wskazanej starej bazy SQLite. "
                    "Import nie polaczy niezaleznych konfiguracji."
                ),
                error_code=_MIXED_SOURCES,
            )
    if len(file_source_sets) > 1:
        return MigrationResult(
            migrated=False,
            skipped=False,
            error="Znaleziono stare pliki danych w wiecej niz jednej lokalizacji.",
            error_code=_SPLIT_FILE_SOURCES,
        )
    file_sources = file_source_sets[0][1] if file_source_sets else ()
    target = Path(database_path).resolve()
    previous_target = target
    backup_root = Path(backup_root).resolve()
    if sqlite_source is None and not file_sources:
        archived_source = _latest_archived_legacy_files(backup_root)
        if archived_source is not None:
            if target.exists() and not replace_existing_target:
                return MigrationResult(
                    migrated=False,
                    skipped=False,
                    error="Docelowa baza PicSyncra juz istnieje.",
                    error_code=_TARGET_EXISTS,
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            return _restore_archived_legacy_data(
                archived_source=archived_source,
                target=target,
                backup_root=backup_root,
                finalize=finalize,
            )
        return MigrationResult(migrated=False, skipped=True)

    resume_interrupted_adoption = (
        sqlite_source is not None
        and target.exists()
        and maintenance_state(sqlite_source) in {"active", "retired"}
    )
    if (
        target.exists()
        and not resume_interrupted_adoption
        and not _is_empty_picsyncra_database(target)
        and not replace_existing_target
    ):
        return MigrationResult(
            migrated=False,
            skipped=False,
            error="Docelowa baza PicSyncra juz istnieje.",
            error_code=_TARGET_EXISTS,
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    archive_dir = _legacy_archive_dir(backup_root)
    source_kind = (
        "sqlite+files" if sqlite_source is not None and file_sources
        else "sqlite" if sqlite_source is not None
        else "files"
    )
    sources = _sqlite_source_files(sqlite_source) if sqlite_source else file_sources
    source_lock_path = sqlite_source if sqlite_source is not None else file_source_sets[0][0]
    source_lock_scope = "sqlite-source" if sqlite_source is not None else "files-source"
    target_published = False
    target_replaced = False
    cleanup_error: str | None = None
    publish_warning: str | None = None
    deferred_cleanup_warning: str | None = None
    pending_source_cleanup_requests: list[tuple[tuple[Path, ...], bool, Path | None]] = []
    try:
        with _exclusive_path_lock(
            backup_root=backup_root,
            scope=source_lock_scope,
            protected_path=source_lock_path,
        ):
            if sqlite_source is not None and not sqlite_source.is_file():
                return MigrationResult(migrated=False, skipped=True)
            if sqlite_source is None and not all(source.is_file() for source in file_sources):
                return MigrationResult(migrated=False, skipped=True)
            with _exclusive_path_lock(
                backup_root=backup_root,
                scope="target",
                protected_path=target,
            ):
                replace_target = (
                    target.exists()
                    and not resume_interrupted_adoption
                    and (
                        replace_existing_target
                        or _is_empty_picsyncra_database(target)
                    )
                )
                if target.exists() and not resume_interrupted_adoption and not replace_target:
                    return MigrationResult(
                        migrated=False,
                        skipped=False,
                        error="Docelowa baza PicSyncra juz istnieje.",
                        error_code=_TARGET_EXISTS,
                )
                with TemporaryDirectory(prefix=".picsyncra-legacy-", dir=target.parent) as temporary_dir:
                    staging = Path(temporary_dir) / target.name
                    if sqlite_source is not None:
                        with database_maintenance(sqlite_source):
                            if resume_interrupted_adoption:
                                _validate_sqlite_database(target)
                                _copy_sources_to_archive(
                                    file_sources,
                                    archive_dir,
                                    sqlite_source=sqlite_source,
                                    sqlite_snapshot=target,
                                )
                                if finalize is not None:
                                    finalize(target)
                            else:
                                with _locked_sqlite_source(sqlite_source):
                                    _copy_sqlite_database(sqlite_source, staging)
                                    if file_sources:
                                        staging_sources = Path(temporary_dir) / "legacy-files"
                                        staging_sources.mkdir()
                                        for source in file_sources:
                                            shutil.copy2(source, staging_sources / source.name)
                                        import_legacy_to_sqlite(
                                            str(staging_sources),
                                            str(staging),
                                            merge_existing=True,
                                        )
                                        _validate_sqlite_database(staging)
                                    _copy_sources_to_archive(
                                        file_sources,
                                        archive_dir,
                                        sqlite_source=sqlite_source,
                                        sqlite_snapshot=staging,
                                    )
                                    if replace_existing_target and target.exists():
                                        _archive_existing_target(target, archive_dir)
                                        target, publish_warning = _publish_staged_target(
                                            staging,
                                            target,
                                            replace_target=True,
                                        )
                                        target_replaced = True
                                    else:
                                        target, publish_warning = _publish_staged_target(
                                            staging,
                                            target,
                                            replace_target=replace_target,
                                        )
                                    target_published = True
                                    if finalize is not None:
                                        finalize(target)
                            retire_database(sqlite_source)
                        cleanup_error = _handover_sources_to_archive(
                            _sqlite_source_files(sqlite_source),
                            archive_dir,
                            sqlite_source=True,
                        )
                        if file_sources:
                            supplemental_cleanup_error = _handover_sources_to_archive(
                                file_sources,
                                archive_dir,
                                sqlite_source=False,
                            )
                            cleanup_error = "; ".join(
                                error
                                for error in (cleanup_error, supplemental_cleanup_error)
                                if error
                            ) or None
                        residual_sqlite_files = _sqlite_source_files(sqlite_source)
                        if residual_sqlite_files:
                            residual_error = _handover_sources_to_archive(
                                residual_sqlite_files,
                                archive_dir,
                                sqlite_source=True,
                            )
                            residual_names = ", ".join(
                                source.name for source in _sqlite_source_files(sqlite_source)
                            )
                            residual_warning = (
                                f"Pozostaly zrodlowe pliki SQLite: {residual_names}"
                                if residual_names
                                else ""
                            )
                            cleanup_error = "; ".join(
                                error
                                for error in (cleanup_error, residual_error, residual_warning)
                                if error
                            ) or None
                        remaining_sqlite_files = _sqlite_source_files(sqlite_source)
                        remaining_file_sources = tuple(
                            source for source in file_sources if source.is_file()
                        )
                        if remaining_sqlite_files:
                            pending_source_cleanup_requests.append(
                                (remaining_sqlite_files, True, sqlite_source)
                            )
                        if remaining_file_sources:
                            pending_source_cleanup_requests.append(
                                (remaining_file_sources, False, sqlite_source)
                            )
                        if not remaining_sqlite_files and not remaining_file_sources:
                            clear_retired_database_marker(sqlite_source)
                    else:
                        staging_sources = Path(temporary_dir) / "legacy-files"
                        staging_sources.mkdir()
                        for source in file_sources:
                            shutil.copy2(source, staging_sources / source.name)
                        import_legacy_to_sqlite(str(staging_sources), str(staging))
                        _validate_sqlite_database(staging)
                        _copy_sources_to_archive(sources, archive_dir)
                        if replace_existing_target and target.exists():
                            _archive_existing_target(target, archive_dir)
                            target, publish_warning = _publish_staged_target(
                                staging,
                                target,
                                replace_target=True,
                            )
                            target_replaced = True
                        else:
                            target, publish_warning = _publish_staged_target(
                                staging,
                                target,
                                replace_target=replace_target,
                            )
                        target_published = True
                        if finalize is not None:
                            finalize(target)
                        cleanup_error = _handover_sources_to_archive(
                            sources,
                            archive_dir,
                            sqlite_source=False,
                        )
                        pending_source_cleanup_requests.append((sources, False, None))
    except _AdoptionInProgressError as exc:
        return MigrationResult(
            migrated=False,
            skipped=False,
            error=str(exc),
            error_code=_ADOPTION_IN_PROGRESS,
        )
    except _TargetAlreadyExistsError as exc:
        return MigrationResult(
            migrated=False,
            skipped=False,
            error=str(exc),
            error_code=_TARGET_EXISTS,
        )
    except (OSError, sqlite3.Error, ValueError) as exc:
        if target_published:
            try:
                target.unlink()
            except OSError:
                pass
        return MigrationResult(
            migrated=False,
            skipped=False,
            error=str(exc),
            error_code=_ADOPTION_FAILED,
        )
    deferred_source_cleanup_warning = "; ".join(
        warning
        for sources, is_sqlite_source, retired_database in pending_source_cleanup_requests
        if (
            warning := _defer_remaining_source_cleanup(
                sources=sources,
                sqlite_source=is_sqlite_source,
                retired_database=retired_database,
                archive_dir=archive_dir,
                backup_root=backup_root,
            )
        )
    ) or None
    deferred_cleanup_warning = _archive_or_defer_replaced_target(
        previous_target=previous_target,
        active_target=target,
        archive_dir=archive_dir,
        backup_root=backup_root,
    )
    return MigrationResult(
        migrated=True,
        skipped=False,
        copied_paths=(target,),
        error="; ".join(
            error
            for error in (
                publish_warning,
                cleanup_error,
                deferred_source_cleanup_warning,
                deferred_cleanup_warning,
            )
            if error
        )
        or None,
        source_kind=source_kind,
        archive_dir=archive_dir,
        replaced_target=target_replaced,
    )
