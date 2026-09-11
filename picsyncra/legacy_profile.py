"""Discovery model for one complete PicOrgFTP-SQL configuration directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


LEGACY_SQLITE_FILENAME = "picorgftp_sql.sqlite"
LEGACY_SQLITE_SIDECARS = ("-wal", "-shm")
LEGACY_DATA_FILENAMES = (
    "config.json",
    "lists.xlsx",
    "web_users.json",
    "web_history.json",
    "file_index.json",
    "local_settings.json",
)


@dataclass(frozen=True)
class LegacyProfileManifest:
    """Non-sensitive inventory used to describe one selected source profile."""

    source_root: Path
    source_names: tuple[str, ...]


@dataclass(frozen=True)
class LegacyProfile:
    """Exact legacy source files found directly inside one directory."""

    root: Path
    sqlite_path: Path | None
    source_files: tuple[Path, ...]
    manifest: LegacyProfileManifest

    @property
    def has_sqlite(self) -> bool:
        return self.sqlite_path is not None


def _profile_source_files(root: Path) -> tuple[Path, ...]:
    candidates = [root / LEGACY_SQLITE_FILENAME]
    candidates.extend(
        root / f"{LEGACY_SQLITE_FILENAME}{suffix}"
        for suffix in LEGACY_SQLITE_SIDECARS
    )
    candidates.extend(root / filename for filename in LEGACY_DATA_FILENAMES)
    return tuple(path for path in candidates if path.is_file())


def load_legacy_profile(source_root: Path) -> LegacyProfile | None:
    """Load one profile without falling back to a different directory."""

    root = Path(source_root).resolve()
    source_files = _profile_source_files(root)
    has_importable_data = (root / LEGACY_SQLITE_FILENAME).is_file() or any(
        (root / filename).is_file()
        for filename in LEGACY_DATA_FILENAMES
        if filename != "local_settings.json"
    )
    if not source_files or not has_importable_data:
        return None
    sqlite_path = root / LEGACY_SQLITE_FILENAME
    if not sqlite_path.is_file():
        sqlite_path = None
    return LegacyProfile(
        root=root,
        sqlite_path=sqlite_path,
        source_files=source_files,
        manifest=LegacyProfileManifest(
            source_root=root,
            source_names=tuple(path.name for path in source_files),
        ),
    )


def discover_legacy_profiles(candidate_roots: Iterable[Path]) -> tuple[LegacyProfile, ...]:
    """Return one candidate per distinct root, preserving caller order."""

    profiles: list[LegacyProfile] = []
    seen_roots: set[str] = set()
    for candidate in candidate_roots:
        root = Path(candidate).resolve()
        key = str(root).casefold()
        if key in seen_roots:
            continue
        seen_roots.add(key)
        profile = load_legacy_profile(root)
        if profile is not None:
            profiles.append(profile)
    return tuple(profiles)
