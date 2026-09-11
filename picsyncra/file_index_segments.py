"""Pure representations for persisted local file-index generations."""

from __future__ import annotations

from dataclasses import dataclass
import os
from collections.abc import Callable, Mapping
from typing import Iterable


@dataclass(frozen=True)
class FileIndexSegment:
    segment_key: str
    section: str
    lookup_key: str
    payload: object


@dataclass(frozen=True)
class FileIndexGeneration:
    cache_key: str
    generation_id: str
    root: str
    version: int
    generated_at: str
    complete: bool
    dirs_scanned: int = 0
    products_scanned: int = 0
    snapshot: dict[str, object] | None = None

    def empty_snapshot(self) -> dict[str, object]:
        return {
            "version": self.version,
            "root": self.root,
            "generated_at": self.generated_at,
            "dirs_scanned": self.dirs_scanned,
            "products_scanned": self.products_scanned,
            "names": [],
            "types": {},
            "models": {},
            "colors": {},
            "extras": {},
            "files": {},
            "fingerprints": {},
        }


@dataclass(frozen=True)
class DirectoryFingerprint:
    """Cheap, metadata-only description of one indexed product directory."""

    canonical_path: str
    mtime_ns: int
    entry_count: int
    parser_version: int
    reliable: bool = True


@dataclass(frozen=True)
class SegmentRefresh:
    """Classify index segments that must be rebuilt or can be copied unchanged."""

    fingerprints: dict[str, DirectoryFingerprint]
    changed_segment_keys: tuple[str, ...]
    reused_segment_keys: tuple[str, ...]
    full_scan_required: bool

    @property
    def segments_scanned(self) -> int:
        return len(self.changed_segment_keys)

    @property
    def segments_reused(self) -> int:
        return len(self.reused_segment_keys)


def normalize_segment_key(value: object) -> str:
    text = str(value or "").strip().upper()
    normalized = "".join(
        character if character.isascii() and character.isalnum() else "_"
        for character in text
    ).strip("_")
    return normalized or "_"


def _canonical_path(value: object) -> str:
    return os.path.realpath(os.path.abspath(os.fspath(value)))


def _directory_fingerprint(path: str, parser_version: int) -> DirectoryFingerprint:
    """Fingerprint a tree from directory metadata without opening file contents."""

    canonical_path = _canonical_path(path)
    pending_paths = [canonical_path]
    seen_paths: set[str] = set()
    max_mtime_ns = 0
    entry_count = 0
    try:
        while pending_paths:
            current_path = pending_paths.pop()
            if current_path in seen_paths:
                continue
            seen_paths.add(current_path)
            max_mtime_ns = max(max_mtime_ns, os.stat(current_path).st_mtime_ns)
            with os.scandir(current_path) as entries:
                child_entries = list(entries)
            entry_count += len(child_entries)
            for entry in child_entries:
                if entry.is_dir(follow_symlinks=False):
                    pending_paths.append(entry.path)
    except OSError:
        return DirectoryFingerprint(
            canonical_path=canonical_path,
            mtime_ns=max_mtime_ns,
            entry_count=entry_count,
            parser_version=parser_version,
            reliable=False,
        )
    return DirectoryFingerprint(
        canonical_path=canonical_path,
        mtime_ns=max_mtime_ns,
        entry_count=entry_count,
        parser_version=parser_version,
    )


def scan_changed_segments(
    root: str | os.PathLike[str],
    previous_fingerprints: Mapping[str, DirectoryFingerprint],
    *,
    parser_version: int = 1,
    fingerprint_provider: Callable[[str, int], DirectoryFingerprint] | None = None,
) -> SegmentRefresh:
    """Compare indexed product directories with a prior complete generation.

    The caller scans only ``changed_segment_keys`` and can copy
    ``reused_segment_keys`` directly from the previous SQLite generation.  A
    failed metadata read is deliberately conservative: nothing is reused.
    """

    root_path = _canonical_path(root)
    try:
        with os.scandir(root_path) as entries:
            product_entries = sorted(
                (entry for entry in entries if entry.is_dir(follow_symlinks=False)),
                key=lambda entry: entry.name.upper(),
            )
    except OSError:
        return SegmentRefresh({}, (), (), True)

    fingerprints: dict[str, DirectoryFingerprint] = {}
    for entry in product_entries:
        segment_key = normalize_segment_key(entry.name)
        try:
            fingerprint = (
                fingerprint_provider(entry.path, parser_version)
                if fingerprint_provider is not None
                else _directory_fingerprint(entry.path, parser_version)
            )
        except OSError:
            fingerprint = DirectoryFingerprint(
                canonical_path=_canonical_path(entry.path),
                mtime_ns=0,
                entry_count=0,
                parser_version=parser_version,
                reliable=False,
            )
        fingerprints[segment_key] = fingerprint

    segment_keys = tuple(sorted(fingerprints))
    prior = dict(previous_fingerprints)
    full_scan_required = (
        not prior
        or any(not fingerprint.reliable for fingerprint in fingerprints.values())
        or any(not fingerprint.reliable for fingerprint in prior.values())
        or any(fingerprint.parser_version != parser_version for fingerprint in prior.values())
    )
    if full_scan_required:
        return SegmentRefresh(fingerprints, segment_keys, (), True)

    changed = tuple(
        segment_key
        for segment_key in segment_keys
        if prior.get(segment_key) != fingerprints[segment_key]
    )
    changed_set = set(changed)
    reused = tuple(
        segment_key for segment_key in segment_keys if segment_key not in changed_set
    )
    return SegmentRefresh(fingerprints, changed, reused, False)


def snapshot_to_segments(snapshot: dict[str, object]) -> list[FileIndexSegment]:
    rows: list[FileIndexSegment] = []
    names = snapshot.get("names", [])
    for name in names if isinstance(names, list) else []:
        rows.append(
            FileIndexSegment(
                segment_key=normalize_segment_key(name),
                section="names",
                lookup_key=str(name).upper(),
                payload=name,
            )
        )
    for section in ("types", "models", "colors", "extras", "files"):
        values = snapshot.get(section, {})
        if not isinstance(values, dict):
            continue
        for lookup_key, payload in sorted(values.items()):
            name_key = str(lookup_key).split("\x1f", 1)[0]
            rows.append(
                FileIndexSegment(
                    segment_key=normalize_segment_key(name_key),
                    section=section,
                    lookup_key=str(lookup_key),
                    payload=payload,
                )
            )
    fingerprints = snapshot.get("fingerprints", {})
    if isinstance(fingerprints, dict):
        for segment_key, payload in sorted(fingerprints.items()):
            normalized_key = normalize_segment_key(segment_key)
            rows.append(
                FileIndexSegment(
                    segment_key=normalized_key,
                    section="fingerprints",
                    lookup_key=normalized_key,
                    payload=payload,
                )
            )
    return rows


def segments_to_snapshot(
    generation: FileIndexGeneration,
    segments: Iterable[FileIndexSegment],
) -> dict[str, object]:
    snapshot = generation.empty_snapshot()
    for segment in segments:
        if segment.section == "names":
            snapshot["names"].append(segment.payload)
        elif segment.section in {"types", "models", "colors", "extras", "files"}:
            snapshot[segment.section][segment.lookup_key] = segment.payload
        elif segment.section == "fingerprints":
            snapshot["fingerprints"][segment.lookup_key] = segment.payload
    snapshot["names"].sort()
    return snapshot
