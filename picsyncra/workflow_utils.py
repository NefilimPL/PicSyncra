"""Pure helpers for filesystem and SQL workflow decisions."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Iterable, Sequence

NO_EAN_PLACEHOLDER = "BRAK-EAN"
NO_EXTRA_PLACEHOLDER = "NO-LED"
INVALID_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
PATH_SPACING_RE = re.compile(r"\s+")


def normalize_text(value: object) -> str:
    """Return an upper-cased, stripped text representation."""

    if value is None:
        return ""
    return str(value).strip().upper()


def sanitize_path_segment(value: object, *, fallback: str = "") -> str:
    """Normalize text for safe directory and file name segments."""

    text = normalize_text(value)
    if not text:
        return fallback
    text = INVALID_PATH_CHARS_RE.sub("-", text)
    text = PATH_SPACING_RE.sub(" ", text).strip(" .-_")
    return text or fallback


def normalize_color_slots(colors: Iterable[object], slots: int = 3) -> list[str]:
    """Normalize color slots and compact gaps to the left."""

    compact = []
    for color in colors:
        normalized = sanitize_path_segment(color)
        if normalized:
            compact.append(normalized)
    compact = compact[:slots]
    compact.extend([""] * max(slots - len(compact), 0))
    return compact


def normalize_extra_segment(
    value: object,
    fallback: str = NO_EXTRA_PLACEHOLDER,
    *,
    default: str | None = None,
) -> str:
    """Normalize the extra value used in directory and filename segments."""

    if default is not None:
        fallback = default
    if isinstance(value, dict):
        value = ""
    text = str(value or "").strip().replace("_", "-")
    if not text:
        return fallback
    normalized = sanitize_path_segment(text.replace("_", "-"), fallback=fallback)
    if normalized == fallback.upper():
        return fallback
    return normalized


def build_color_segment(colors: Iterable[object], separator: str = "-") -> str:
    """Join non-empty colors into the canonical directory segment."""

    cleaned = normalize_color_slots(colors)
    return separator.join(color for color in cleaned if color)


def build_product_path(
    base_dir: str,
    name: object,
    type_name: object,
    model: object,
    colors: Iterable[object],
    extra: object,
    *,
    color_separator: str = "-",
    default_extra: str = NO_EXTRA_PLACEHOLDER,
) -> str:
    """Return the canonical product directory path."""

    segments = [
        sanitize_path_segment(name),
        sanitize_path_segment(type_name),
        sanitize_path_segment(model),
        build_color_segment(colors, separator=color_separator),
        normalize_extra_segment(extra, fallback=default_extra),
    ]
    return os.path.join(base_dir, *[segment for segment in segments if segment])


def build_output_filename(
    ean: object,
    prefix: object,
    category: object,
    name: object,
    type_name: object,
    model: object,
    colors: Iterable[object],
    extra: object,
    extension: str,
) -> str:
    """Build the structured output filename for a slot."""

    parts = [
        sanitize_path_segment(ean) or NO_EAN_PLACEHOLDER,
        str(prefix).strip(),
        sanitize_path_segment(category),
        sanitize_path_segment(name),
        sanitize_path_segment(type_name),
        sanitize_path_segment(model),
    ]
    parts.extend(color for color in normalize_color_slots(colors) if color)
    parts.append(normalize_extra_segment(extra))
    ext = extension or ""
    return "_".join(parts) + ext


def build_product_directory(
    base_dir: str,
    name: object,
    type_name: object,
    model: object,
    colors: Iterable[object],
    extra: object,
    *,
    color_separator: str = "-",
    default_extra: str = NO_EXTRA_PLACEHOLDER,
) -> str:
    """Backward-compatible alias used by the GUI refactor."""

    return build_product_path(
        base_dir,
        name,
        type_name,
        model,
        colors,
        extra,
        color_separator=color_separator,
        default_extra=default_extra,
    )


def build_slot_filename(
    ean: object,
    prefix: object,
    category: object,
    name: object,
    type_name: object,
    model: object,
    colors: Iterable[object],
    extra: object,
    extension: str,
) -> str:
    """Backward-compatible alias used by the GUI refactor."""

    return build_output_filename(
        ean,
        prefix,
        category,
        name,
        type_name,
        model,
        colors,
        extra,
        extension,
    )


def build_remote_slot_filename(
    ean: object,
    prefix: object,
    extension: str,
) -> str:
    """Build the canonical short FTP filename for a slot."""

    ext = extension or ""
    return f"{sanitize_path_segment(ean) or NO_EAN_PLACEHOLDER}_{str(prefix).strip()}{ext}"


@dataclass(frozen=True)
class ParsedSlotFilename:
    """Parsed representation of a slot file name."""

    basename: str
    ean: str
    slot_label: str
    normalized_label: str
    extension: str
    normalized_name: str | None


def parse_slot_filename(filename: object) -> ParsedSlotFilename | None:
    """Parse the slot prefix from a structured file name."""

    basename = os.path.basename(str(filename or "")).strip()
    if not basename:
        return None
    stem, extension = os.path.splitext(basename)
    parts = stem.split("_")
    if len(parts) < 2:
        return None
    ean = parts[0].strip()
    slot_label = parts[1].strip()
    if not ean or not slot_label:
        return None
    normalized_label = slot_label.zfill(2)
    normalized_name = None
    if normalized_label != slot_label:
        normalized_parts = list(parts)
        normalized_parts[1] = normalized_label
        normalized_name = "_".join(normalized_parts) + extension
    return ParsedSlotFilename(
        basename=basename,
        ean=ean,
        slot_label=slot_label,
        normalized_label=normalized_label,
        extension=extension,
        normalized_name=normalized_name,
    )


def select_remote_files_for_ean(ean: object, filenames: Iterable[object]) -> dict[str, str]:
    """Return a slot-prefix-to-file map for FTP results matching the EAN."""

    normalized_ean = normalize_text(ean)
    if not normalized_ean:
        return {}
    selected: dict[str, str] = {}
    for raw_name in filenames:
        parsed = parse_slot_filename(raw_name)
        if not parsed:
            continue
        if normalize_text(parsed.ean) != normalized_ean:
            continue
        selected[parsed.normalized_label] = parsed.basename
    return selected


def build_sql_presence_query(
    table: str,
    where_clause: str,
    columns: Sequence[str],
    db_type: str,
    *,
    mysql_key: str = "mysql",
) -> str:
    """Build a single SQL query that checks all configured slot columns."""

    cleaned_columns = [str(column).strip() for column in columns if str(column).strip()]
    if not table or not cleaned_columns:
        return ""
    select_columns = ", ".join(cleaned_columns)
    if str(db_type).lower() == str(mysql_key).lower():
        base_query = f"SELECT {select_columns} FROM {table}{where_clause}"
        if " limit " not in base_query.lower():
            base_query = f"{base_query.rstrip('; ')} LIMIT 1"
        return base_query
    return f"SELECT TOP 1 {select_columns} FROM {table}{where_clause}".rstrip(";\n\r\t ")


def has_sql_value(value: object) -> bool:
    """Normalize SQL cell values into a boolean presence flag."""

    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            value = value.decode("latin-1", errors="ignore")
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def normalize_sql_value(value: object) -> str:
    """Normalize a SQL cell value into a displayable string."""

    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            value = value.decode("latin-1", errors="ignore")
    if value is None:
        return ""
    return str(value).strip()


def has_presence_value(value: object) -> bool:
    """Backward-compatible alias used by the GUI refactor."""

    return has_sql_value(value)


def unique_columns(columns: Iterable[object]) -> list[str]:
    """Return unique, non-empty column names while preserving order."""

    seen: set[str] = set()
    result: list[str] = []
    for column in columns:
        text = str(column).strip()
        key = text.lower()
        if not text or key in seen:
            continue
        result.append(text)
        seen.add(key)
    return result


def sql_row_to_presence_map(prefixes: Sequence[str], row: object) -> dict[str, bool]:
    """Convert a SQL row into a per-slot presence map."""

    result = {prefix: False for prefix in prefixes}
    if row is None:
        return result
    try:
        values = list(row)
    except TypeError:
        values = [row]
    for index, prefix in enumerate(prefixes):
        if index >= len(values):
            break
        result[prefix] = has_sql_value(values[index])
    return result


def sql_row_to_value_map(prefixes: Sequence[str], row: object) -> dict[str, str]:
    """Convert a SQL row into a per-slot raw value map."""

    result = {prefix: "" for prefix in prefixes}
    if row is None:
        return result
    try:
        values = list(row)
    except TypeError:
        values = [row]
    for index, prefix in enumerate(prefixes):
        if index >= len(values):
            break
        result[prefix] = normalize_sql_value(values[index])
    return result
