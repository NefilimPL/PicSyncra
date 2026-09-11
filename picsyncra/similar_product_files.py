"""Pure local discovery of files from colour variants of a product."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os

from .slot_utils import normalize_slot_prefix
from .workflow_utils import (
    normalize_extra_segment,
    normalize_color_slots,
    parse_slot_filename,
    sanitize_path_segment,
)


@dataclass(frozen=True)
class SimilarFileCandidate:
    candidate_id: str
    source_prefix: str
    target_prefix: str
    source_path: str
    filename: str
    source_color_segment: str
    size_bytes: int
    sha256: str
    is_pdf: bool


def normalize_similar_file_settings(raw_settings, slot_defs) -> dict[str, object]:
    """Return safe, current similar-file settings for the supplied slots."""

    raw_settings = raw_settings if isinstance(raw_settings, dict) else {}
    known = {slot["prefix"] for slot in slot_defs if isinstance(slot, dict)}
    prefixes: list[str] = []
    raw_prefixes = raw_settings.get("slot_prefixes", [])
    if not isinstance(raw_prefixes, (list, tuple)):
        raw_prefixes = []
    for value in raw_prefixes:
        prefix = normalize_slot_prefix(value)
        if prefix in known and prefix not in prefixes:
            prefixes.append(prefix)
    return {"enabled": bool(raw_settings.get("enabled")), "slot_prefixes": prefixes}


def _product_value(product, *keys) -> object:
    if not isinstance(product, dict):
        return ""
    for key in keys:
        if key in product:
            return product[key]
    return ""


def _directory_names(path: str) -> list[str]:
    try:
        with os.scandir(path) as entries:
            return sorted((entry.name for entry in entries if entry.is_dir()), key=str.casefold)
    except OSError:
        return []


def _file_names(path: str) -> list[str]:
    try:
        with os.scandir(path) as entries:
            return sorted((entry.name for entry in entries if entry.is_file()), key=str.casefold)
    except OSError:
        return []


def _merged_names(*name_groups) -> list[str]:
    names: dict[str, str] = {}
    for group in name_groups:
        if not isinstance(group, (list, tuple, set)):
            continue
        for value in group:
            name = str(value or "").strip()
            if name:
                names[name.casefold()] = name
    return sorted(names.values(), key=str.casefold)


def _safe_child(parent: str, segment: object) -> str | None:
    """Return a resolved, direct child path only for a safe directory entry."""

    name = str(segment or "").strip()
    normalized = sanitize_path_segment(name)
    if not name or not normalized or normalized.casefold() != name.casefold():
        return None
    child = os.path.realpath(os.path.join(parent, name))
    try:
        if os.path.commonpath((parent, child)) != parent:
            return None
    except ValueError:
        return None
    return child


def _read_digest(path: str) -> tuple[int, str] | None:
    digest = hashlib.sha256()
    size = 0
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
    except OSError:
        return None
    return size, digest.hexdigest()


class _DigestCache:
    """Reuse digests while a file's path and metadata remain unchanged."""

    def __init__(self) -> None:
        self._digests: dict[tuple[str, int, int], tuple[int, str]] = {}
        self._keys_by_path: dict[str, tuple[str, int, int]] = {}

    def get(self, path: str) -> tuple[int, str] | None:
        canonical = os.path.realpath(os.path.abspath(path))
        stat = os.stat(canonical)
        key = (canonical, stat.st_size, stat.st_mtime_ns)
        cached = self._digests.get(key)
        if cached is not None:
            return cached

        previous_key = self._keys_by_path.get(canonical)
        if previous_key is not None and previous_key != key:
            self._digests.pop(previous_key, None)
        digest_data = _read_digest(canonical)
        if digest_data is not None:
            self._digests[key] = digest_data
            self._keys_by_path[canonical] = key
        return digest_data


_DIGEST_CACHE = _DigestCache()


def _color_signature(values) -> tuple[str, ...]:
    """Normalize a colour combination without making its field order significant."""

    return tuple(sorted(normalize_color_slots(values), key=str.casefold))


def _index_values(file_index, method_name: str, *args) -> list[str]:
    method = getattr(file_index, method_name, None)
    if not callable(method):
        return []
    try:
        values = method(*args)
    except (OSError, TypeError, ValueError):
        return []
    return list(values) if isinstance(values, (list, tuple, set)) else []


def find_similar_file_candidates(
    base_dir,
    product,
    slot_defs,
    settings,
    *,
    file_index=None,
    occupied_prefixes=(),
) -> list[SimilarFileCandidate]:
    """Find readable local files in sibling colour folders without side effects."""

    normalized_settings = normalize_similar_file_settings(settings, slot_defs)
    selected_prefixes = normalized_settings["slot_prefixes"]
    if not normalized_settings["enabled"] or not selected_prefixes:
        return []

    name = sanitize_path_segment(_product_value(product, "name"))
    type_name = sanitize_path_segment(_product_value(product, "type_name", "type"))
    model = sanitize_path_segment(_product_value(product, "model"))
    colors = normalize_color_slots(
        [_product_value(product, "color1"), _product_value(product, "color2"), _product_value(product, "color3")]
    )
    color_signature = _color_signature(colors)
    has_color_filter = bool(colors)
    raw_extra = str(_product_value(product, "extra") or "").strip()
    selected_extra = normalize_extra_segment(raw_extra) if raw_extra else ""
    if not all((name, type_name, model)):
        return []

    root = os.path.realpath(os.path.abspath(str(base_dir or "")))
    identity_path = os.path.join(root, name, type_name, model)
    if os.path.commonpath((root, os.path.realpath(identity_path))) != root:
        return []

    indexed_colors = _index_values(file_index, "get_colors", name, type_name, model)
    color_dirs = _merged_names(indexed_colors, _directory_names(identity_path))
    source_files: list[tuple[str, str, str, str]] = []
    for source_color in color_dirs:
        if has_color_filter and _color_signature(source_color.split("-")) == color_signature:
            continue
        color_path = _safe_child(identity_path, source_color)
        if color_path is None:
            continue
        indexed_extras = _index_values(
            file_index,
            "get_extras",
            name,
            type_name,
            model,
            source_color.split("-"),
        )
        for source_extra in _merged_names(indexed_extras, _directory_names(color_path)):
            if selected_extra and normalize_extra_segment(source_extra) != selected_extra:
                continue
            product_path = _safe_child(color_path, source_extra)
            if product_path is None:
                continue
            indexed_files = _index_values(
                file_index,
                "get_product_files",
                name,
                type_name,
                model,
                source_color.split("-"),
                source_extra,
            )
            for filename in _merged_names(indexed_files, _file_names(product_path)):
                source_path = _safe_child(product_path, filename)
                if source_path is None:
                    continue
                parsed = parse_slot_filename(filename)
                source_prefix = normalize_slot_prefix(parsed.normalized_label) if parsed else ""
                if source_prefix not in selected_prefixes or not os.path.isfile(source_path):
                    continue
                source_files.append((source_color, filename, source_prefix, source_path))

    occupied = {normalize_slot_prefix(prefix) for prefix in occupied_prefixes}
    assigned = set(occupied)
    seen_digests: set[str] = set()
    candidates: list[SimilarFileCandidate] = []
    for source_color, filename, source_prefix, source_path in sorted(
        source_files, key=lambda item: (item[0].casefold(), item[1].casefold())
    ):
        try:
            digest_data = _DIGEST_CACHE.get(source_path)
        except OSError:
            continue
        if digest_data is None:
            continue
        size_bytes, sha256 = digest_data
        if sha256 in seen_digests:
            continue
        seen_digests.add(sha256)
        available = [prefix for prefix in selected_prefixes if prefix not in assigned]
        if not available:
            break
        target_prefix = source_prefix if source_prefix in available else available[0]
        assigned.add(target_prefix)
        relative_path = os.path.relpath(source_path, root).replace("\\", "/")
        candidate_id = hashlib.sha256(
            f"{relative_path}\x00{sha256}".encode("utf-8")
        ).hexdigest()
        candidates.append(
            SimilarFileCandidate(
                candidate_id=candidate_id,
                source_prefix=source_prefix,
                target_prefix=target_prefix,
                source_path=source_path,
                filename=filename,
                source_color_segment=source_color,
                size_bytes=size_bytes,
                sha256=sha256,
                is_pdf=os.path.splitext(filename)[1].lower() == ".pdf",
            )
        )
    return candidates
