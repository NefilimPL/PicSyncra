"""Data helpers for the LAN web interface."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import ctypes
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
import unicodedata
import uuid

from openpyxl import Workbook

from . import common, config, data_store, settings, storage_settings
from . import encryption
from .common import (
    APP_SECRET_KEY,
    AUTO_CONTENT_FIT_KEY,
    COLOR_FIELD_LABELS_KEY,
    H,
    K,
    LOCAL_FILE_INDEX_KEY,
    M,
    N,
    P,
    PROCESSING_SETTINGS_KEY,
    RESOURCE_MONITOR_SETTINGS_KEY,
    SECURITY_SETTINGS_KEY,
    SIMILAR_FILE_DETECTION_KEY,
    WEB_DISPLAY_SETTINGS_KEY,
    SQL_AVAILABLE_COLUMNS_KEY,
    SQL_COLUMN_MAP_KEY,
    SLOT_DEFS_KEY,
    TRANSLATION_API_KEY,
    TRANSLATION_SETTINGS_KEY,
    b,
    c,
    ft,
    m,
    p,
    r,
    u,
    v,
    w,
)
from .config import save_config
from .data_store import get_active_store
from .email_settings import (
    EMAIL_CLIENT_SECRET,
    EMAIL_SETTINGS_KEY,
    EMAIL_SMTP_PASSWORD,
    normalize_email_address,
    normalize_email_settings,
    public_email_settings,
    validate_email_rule_recipients,
)
from .database import connect_db
from .excel_utils import (
    COLOR1_HEADER,
    COLOR2_HEADER,
    COLOR3_HEADER,
    EAN_HEADER,
    ENTRY_RECORDS_KEY,
    EXTRA_HEADER,
    MODEL_HEADER,
    NAME_HEADER,
    PRODUCT_ID_HEADER,
    TYPE_HEADER,
    add_to_list,
    find_list_value_usage,
    prepare_excel_lists,
    remove_from_list,
    save_ean_entry,
    NO_EAN_PLACEHOLDER,
)
from .logging_utils import log_error, log_info
from .observability import SECRET_KEY_RE, emit_event
from .services.ftp_service import connect_ftp, list_remote_files_for_ean, list_remote_filenames
from .services.sql_service import (
    extract_presence_context,
    query_presence_details,
    should_check_presence,
)
from .services.pimcore_sql_service import (
    SqlValueResult,
    connect_profile,
    execute_sql_value_query,
)
from .services.sql_execution_context import SqlExecutionContext
from .services.template_execution import (
    classify_template_operation,
    execute_independent_operations,
)
from .file_index import LocalFileIndex
from .pimcore_config import (
    PIMCORE_API_KEY,
    PIMCORE_SETTINGS_KEY,
    field_mapping_issues,
    normalize_pimcore_settings,
)
from .ocr_settings import OCR_SETTINGS_KEY, normalize_ocr_settings
from .pimcore_operations import PimcoreOperationRegistry, redact_pimcore_log_value
from .pimcore_templates import (
    PRODUCT_SOURCES,
    SourceDefinition,
    TemplateError,
    generate_test_values,
    placeholder_sources,
    render_mapping_templates,
)
from .sqlite_store import SqliteStore
from .redaction import redact_sensitive_value, sanitize_free_text
from .services.pimcore_service import (
    PimcoreClient,
    PimcoreConflictError,
    create_product,
    discover_classes,
    discover_fields,
    discover_folders,
    fetch_product_for_edit,
    find_product_by_ean,
    pimcore_client_scope,
    run_settings_test,
    run_test_create,
    update_product,
)
from .services.translation_service import clear_translation_cache, translate_text
from .slot_utils import (
    normalize_slot_definitions,
    normalize_slot_prefix,
    normalize_sql_column_map,
)
from .similar_product_files import (
    SimilarFileCandidate,
    find_similar_file_candidates,
    normalize_similar_file_settings,
)
from .sql_profiles import (
    DEFAULT_SQL_PROFILE_ID,
    SQL_PROFILES_KEY,
    additional_sql_profiles,
    normalize_sql_profiles,
    public_sql_profiles,
    resolve_sql_profile,
)
from .product_fields import (
    PRODUCT_FIELDS_KEY,
    effective_product_values,
    missing_required_fields,
    normalize_product_fields,
)
from .product_queries import ProductSearchCriteria

from .workflow_utils import (
    build_product_directory,
    parse_slot_filename,
    sanitize_path_segment,
    select_remote_files_for_ean,
)
from .web_workflow import available_convert_formats
from .version import get_display_version


SQL_PROFILE_WARNING_CODES_MAX = 20
SQL_PROFILE_ERROR_MAX_BYTES = 2000
_SQL_ASSIGNMENT_RE = re.compile(
    r"(?ix)(?<![a-z0-9_.-])(?P<key>[a-z0-9_.-]+)\s*[:=]\s*"
    r'(?:"(?:\\.|[^"\r\n])*"|\'(?:\\.|[^\'\r\n])*\'|[^\r\n;,]*)'
)


WEB_FTP_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
WEB_FTP_CACHE_CLEAN_INTERVAL_SECONDS = 60 * 60
_FTP_CACHE_LAST_CLEANUP = 0.0

LIST_SHEETS = {
    "names": "NAZWY",
    "types": "TYPY",
    "models": "MODELE",
    "colors": "KOLORY",
    "extras": "DODATKI",
}

WEB_USERS_PATH = "web_users.json"
WEB_HISTORY_PATH = "web_history.json"
LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCK_SECONDS = 60 * 60
IMAGE_PREVIEW_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".psd",
    ".eps",
    ".ai",
    ".tif",
    ".tiff",
    ".webp",
}
PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 200_000
_FILE_INDEX: LocalFileIndex | None = None
_FILE_INDEX_KEY: tuple[str, str, str, str] | None = None
_FILE_INDEX_REFRESH_STARTED = False
_FTP_CACHE_LOCKS: dict[str, threading.Lock] = {}
_FTP_CACHE_LOCKS_GUARD = threading.Lock()
_USERS_LOCK = threading.RLock()
_CONFIG_SECRET_FIELDS = {
    H: {N, M},
    P: {N, M},
    K: {N, M},
    TRANSLATION_SETTINGS_KEY: {TRANSLATION_API_KEY},
    PIMCORE_SETTINGS_KEY: {PIMCORE_API_KEY},
    EMAIL_SETTINGS_KEY: {"entra.client_secret", "smtp.password"},
}
_PIMCORE_OPERATIONS = PimcoreOperationRegistry()


class ListValueInUseError(ValueError):
    """Raised when an Excel list value is still referenced by product entries."""

    def __init__(self, list_key: str, value: str, used_by: list[dict[str, str]]):
        self.list_key = list_key
        self.value = value
        self.used_by = used_by
        super().__init__("Nie usunieto wartosci, bo jest uzywana przez produkty.")


@dataclass(frozen=True)
class WebEntry:
    """Entry record returned to the web UI."""

    product_id: str
    ean: str
    name: str
    type_name: str
    model: str
    color1: str
    color2: str
    color3: str
    extra: str

    @property
    def label(self) -> str:
        parts = [self.name, self.type_name, self.model]
        colors = " / ".join(item for item in (self.color1, self.color2, self.color3) if item)
        if colors:
            parts.append(colors)
        if self.extra:
            parts.append(self.extra)
        suffix = f"EAN {self.ean}" if self.ean else self.product_id
        return " | ".join(item for item in parts if item) + (f" - {suffix}" if suffix else "")


def _text(value: object) -> str:
    return str(value or "").strip()


def _active_sqlite_store():
    """Return the active SQLite store adapter, or None in legacy mode."""

    try:
        store = data_store.get_active_store()
        if getattr(store, "mode", "") == "sqlite":
            return store
    except Exception:
        return None
    return None


def _pimcore_submission_store():
    """Return the SQLite store used for Pimcore audit records."""

    active_store = _active_sqlite_store()
    if active_store is not None:
        return active_store
    database_path = storage_settings.resolve_sqlite_path()
    if not _text(database_path):
        return None
    return SqliteStore(database_path)


def _norm(value: object) -> str:
    return _text(value).upper()


def _list_value_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", _text(value)).casefold()
    return "".join(ch for ch in text if not unicodedata.combining(ch)).strip()


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return ":".join(
        [
            PASSWORD_ALGORITHM,
            str(PASSWORD_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a stored user password hash."""

    try:
        algorithm, iterations_raw, salt_raw, digest_raw = str(stored_hash or "").split(":", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def _entry_from_record(record: dict[str, object]) -> WebEntry:
    return WebEntry(
        product_id=_text(record.get(PRODUCT_ID_HEADER)),
        ean=_text(record.get(EAN_HEADER)),
        name=_text(record.get(NAME_HEADER)),
        type_name=_text(record.get(TYPE_HEADER)),
        model=_text(record.get(MODEL_HEADER)),
        color1=_text(record.get(COLOR1_HEADER)),
        color2=_text(record.get(COLOR2_HEADER)),
        color3=_text(record.get(COLOR3_HEADER)),
        extra=_text(record.get(EXTRA_HEADER)),
    )


def entry_to_payload(entry: WebEntry) -> dict[str, str]:
    """Return a browser-friendly dict for a workbook entry."""

    return {
        "product_id": entry.product_id,
        "ean": entry.ean,
        "name": entry.name,
        "type_name": entry.type_name,
        "model": entry.model,
        "color1": entry.color1,
        "color2": entry.color2,
        "color3": entry.color3,
        "extra": entry.extra,
        "label": entry.label,
    }


def load_web_data() -> dict[str, object]:
    """Load list values and entry records for the web UI."""

    lists = prepare_excel_lists()
    entries = [_entry_from_record(item) for item in lists.get(ENTRY_RECORDS_KEY, [])]
    return {
        "lists": {
            key: list(lists.get(sheet, []))
            for key, sheet in LIST_SHEETS.items()
        },
        "entries": [entry_to_payload(entry) for entry in entries],
        "file_index": file_index_status(start=True),
        "color_field_labels": dict(config.CONFIG.get(COLOR_FIELD_LABELS_KEY, {}) or {}),
        "product_fields": normalize_product_fields(
            config.CONFIG.get(PRODUCT_FIELDS_KEY),
            legacy_color_labels=config.CONFIG.get(COLOR_FIELD_LABELS_KEY),
        ),
        "ftp_enabled": bool(config.CONFIG.get(ft, True)),
    }


def _file_index_enabled() -> bool:
    return bool(config.CONFIG.get(LOCAL_FILE_INDEX_KEY, True))


def _get_file_index(*, start: bool = False) -> LocalFileIndex | None:
    global _FILE_INDEX
    global _FILE_INDEX_KEY
    global _FILE_INDEX_REFRESH_STARTED
    if not _file_index_enabled():
        return None
    root_dir = os.path.abspath(settings.l)
    index_path = os.path.abspath(os.path.join(settings.AC, "file_index.json"))
    active_store = data_store.get_active_store()
    cache_store = (
        active_store
        if getattr(active_store, "mode", "") == storage_settings.DATA_MODE_SQLITE
        else None
    )
    store_key = str(getattr(cache_store, "database_path", "")) if cache_store else ""
    key = (root_dir, index_path, getattr(active_store, "mode", ""), store_key)
    if _FILE_INDEX is None or _FILE_INDEX_KEY != key:
        index = LocalFileIndex(root_dir, index_path, cache_store=cache_store)
        index.load_cache()
        _FILE_INDEX = index
        _FILE_INDEX_KEY = key
        _FILE_INDEX_REFRESH_STARTED = False
    if start and _FILE_INDEX is not None and not _FILE_INDEX_REFRESH_STARTED:
        _FILE_INDEX.refresh_if_stale()
        _FILE_INDEX_REFRESH_STARTED = True
    return _FILE_INDEX


def _parse_generated_at(value: object) -> tuple[str, float | None]:
    text = _text(value)
    if text.endswith("Z") and "T" in text:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return text, dt.timestamp()
        except ValueError:
            return text, None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return text, None
    iso = (
        datetime.fromtimestamp(number, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    return iso, number


def file_index_status(*, start: bool = False) -> dict[str, object]:
    """Return web-friendly local file index status."""

    if not _file_index_enabled():
        return {"enabled": False, "state": "disabled", "label": "Indeks lokalny wylaczony."}
    index = _get_file_index(start=start)
    if index is None:
        return {"enabled": False, "state": "disabled", "label": "Indeks lokalny wylaczony."}
    status = index.get_status()
    generated_at, generated_ts = _parse_generated_at(status.get("generated_at"))
    age_seconds = int(time.time() - generated_ts) if generated_ts is not None else None
    state = str(status.get("state") or "idle")
    if state == "refreshing":
        label = "Indeksowanie lokalnych plikow..."
    elif generated_at:
        label = "Indeks lokalny"
    elif status.get("cache_loaded"):
        label = "Indeks lokalny: cache wczytany."
    else:
        label = "Indeks lokalny: brak snapshotu."
    return {
        "enabled": True,
        "state": state,
        "cache_loaded": bool(status.get("cache_loaded")),
        "has_snapshot": bool(status.get("has_snapshot")),
        "dirs_scanned": int(status.get("dirs_scanned") or 0),
        "products_scanned": int(status.get("products_scanned") or 0),
        "name_count": int(status.get("name_count") or 0),
        "generated_at": generated_at,
        "age_seconds": age_seconds,
        "error": str(status.get("error") or ""),
        "label": label,
    }


def refresh_file_index() -> dict[str, object]:
    """Start a background local file index refresh."""

    index = _get_file_index(start=False)
    if index is not None:
        index.refresh_if_stale(force=True)
    return file_index_status()


def _history_path() -> Path:
    return Path(settings.AC) / WEB_HISTORY_PATH


def _load_history_records() -> list[dict[str, object]]:
    sqlite_store = _active_sqlite_store()
    if sqlite_store is not None:
        return sqlite_store.load_history()
    path = _history_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(payload, list):
        return []
    records: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        redacted = redact_sensitive_value(item)
        if isinstance(redacted, dict):
            records.append(redacted)
    return records


def _save_history_records(records: list[dict[str, object]]) -> None:
    safe_records = redact_sensitive_value(records[-2000:])
    bounded_records = safe_records if isinstance(safe_records, list) else []
    sqlite_store = _active_sqlite_store()
    if sqlite_store is not None:
        sqlite_store.save_history(bounded_records)
        return
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bounded_records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def record_history(
    *,
    username: str,
    action: str,
    ean: object = "",
    product_id: object = "",
    summary: str = "",
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    """Append a compact web history entry."""

    timestamp = time.time()
    record = {
        "id": f"{int(timestamp * 1000)}-{secrets.token_hex(4)}",
        "ts": timestamp,
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
        "user": _text(username) or "unknown",
        "action": _text(action),
        "ean": _text(ean) or "BRAK-EAN",
        "product_id": _text(product_id),
        "summary": _text(summary),
        "details": details or {},
    }
    safe_record = redact_sensitive_value(record)
    record = safe_record if isinstance(safe_record, dict) else {}
    sqlite_store = _active_sqlite_store()
    if sqlite_store is not None:
        sqlite_store.append_history(record)
        return record
    records = _load_history_records()
    records.append(record)
    _save_history_records(records)
    return record


def _history_record_search_text(item: dict[str, object]) -> str:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    entry = details.get("entry") if isinstance(details.get("entry"), dict) else {}
    pieces = [
        item.get("ean"),
        item.get("product_id"),
        item.get("summary"),
        item.get("action"),
        item.get("user"),
    ]
    pieces.extend(entry.values())
    return " ".join(_text(piece) for piece in pieces if _text(piece)).casefold()


def _history_timestamp_value(item: dict[str, object]) -> float:
    value = item.get("created_at") or item.get("ts")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        text = _text(value)
    if text.endswith("Z") and "T" in text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _filter_history_records(
    records: list[dict[str, object]], *, user: str = "", query: str = ""
) -> list[dict[str, object]]:
    """Apply the history filters to an already loaded record collection."""

    user_filter = _text(user).lower()
    query_filter = _text(query).casefold()
    if user_filter:
        records = [
            item for item in records if _text(item.get("user")).lower() == user_filter
        ]
    if query_filter:
        records = [
            item
            for item in records
            if query_filter in _history_record_search_text(item)
        ]
    return records


def _history_group_entry(items: list[dict[str, object]]) -> dict[str, object]:
    """Return the first display-safe product entry available in a group."""

    for item in items:
        details = item.get("details")
        if not isinstance(details, dict):
            continue
        entry = details.get("entry")
        if isinstance(entry, dict):
            return entry
    return {}


def _group_history_records(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for item in records:
        ean = _text(item.get("ean")) or "BRAK-EAN"
        group = grouped.setdefault(ean, {"ean": ean, "latest_ts": 0.0, "items": []})
        group["items"].append(item)
        group["latest_ts"] = max(
            float(group.get("latest_ts") or 0),
            _history_timestamp_value(item),
        )
    return sorted(
        grouped.values(),
        key=lambda item: float(item.get("latest_ts") or 0),
        reverse=True,
    )


def history_snapshot(
    *,
    user: str = "",
    query: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, object]:
    """Return a page of lightweight web history groups."""

    sqlite_store = _active_sqlite_store()
    if sqlite_store is not None:
        history_store = getattr(sqlite_store, "store", sqlite_store)
        return history_store.history_summary_snapshot(
            user=user,
            query=query,
            page=page,
            page_size=page_size,
        )

    all_records = sorted(
        _load_history_records(), key=_history_timestamp_value, reverse=True
    )
    users = sorted(
        {_text(item.get("user")) for item in all_records if _text(item.get("user"))}
    )
    records = _filter_history_records(all_records, user=user, query=query)
    groups = _group_history_records(records)
    page_size = max(1, min(50, int(page_size or 50)))
    page = max(1, int(page or 1))
    total_groups = len(groups)
    total_pages = max(1, (total_groups + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    groups_page = [
        {
            "ean": _text(group.get("ean")) or "BRAK-EAN",
            "latest_ts": float(group.get("latest_ts") or 0),
            "change_count": len(group.get("items") or []),
            "entry": _history_group_entry(group.get("items") or []),
        }
        for group in groups[start : start + page_size]
    ]
    return {
        "groups": groups_page,
        "users": users,
        "count": len(records),
        "total_groups": total_groups,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "query": _text(query),
    }


def history_group_snapshot(
    *, ean: str, user: str = "", query: str = "", page: int = 1, page_size: int = 25
) -> dict[str, object] | None:
    """Return one bounded page of filtered history details for an EAN group."""

    sqlite_store = _active_sqlite_store()
    if sqlite_store is not None:
        history_store = getattr(sqlite_store, "store", sqlite_store)
        return history_store.history_group_snapshot(
            ean=ean,
            user=user,
            query=query,
            page=page,
            page_size=page_size,
        )

    normalized_ean = _text(ean) or "BRAK-EAN"
    records = sorted(
        _load_history_records(), key=_history_timestamp_value, reverse=True
    )
    filtered = _filter_history_records(records, user=user, query=query)
    items = [
        item
        for item in filtered
        if (_text(item.get("ean")) or "BRAK-EAN") == normalized_ean
    ]
    if not items:
        return None
    try:
        bounded_page_size = max(1, min(25, int(page_size or 25)))
    except (TypeError, ValueError):
        bounded_page_size = 25
    try:
        requested_page = max(1, int(page or 1))
    except (TypeError, ValueError):
        requested_page = 1
    total_items = len(items)
    total_pages = max(1, (total_items + bounded_page_size - 1) // bounded_page_size)
    current_page = min(requested_page, total_pages)
    start = (current_page - 1) * bounded_page_size
    return {
        "ean": normalized_ean,
        "latest_ts": _history_timestamp_value(items[0]),
        "items": items[start : start + bounded_page_size],
        "total_items": total_items,
        "page": current_page,
        "page_size": bounded_page_size,
        "total_pages": total_pages,
    }


def _ftp_cache_dir(ean: object, cache_scope: object = "") -> str:
    safe_ean = sanitize_path_segment(ean) or "NO-EAN"
    safe_scope = sanitize_path_segment(cache_scope)
    if safe_scope:
        return os.path.join(settings.AC, "web_ftp_cache", safe_scope, safe_ean)
    return os.path.join(settings.AC, "web_ftp_cache", safe_ean)


def _ftp_cache_root() -> str:
    return os.path.join(settings.AC, "web_ftp_cache")


def cleanup_web_ftp_cache(
    *,
    max_age_seconds: int = WEB_FTP_CACHE_MAX_AGE_SECONDS,
    min_interval_seconds: int = WEB_FTP_CACHE_CLEAN_INTERVAL_SECONDS,
    force: bool = False,
) -> dict[str, object]:
    """Remove stale browser FTP preview cache files."""

    global _FTP_CACHE_LAST_CLEANUP
    now = time.time()
    if not force and now - _FTP_CACHE_LAST_CLEANUP < max(1, int(min_interval_seconds or 1)):
        return {"deleted_files": 0, "deleted_dirs": 0, "skipped": True, "errors": []}
    _FTP_CACHE_LAST_CLEANUP = now
    root = os.path.abspath(_ftp_cache_root())
    if not os.path.isdir(root):
        return {"deleted_files": 0, "deleted_dirs": 0, "skipped": False, "errors": []}

    cutoff = now - max(60, int(max_age_seconds or WEB_FTP_CACHE_MAX_AGE_SECONDS))
    deleted_files = 0
    deleted_dirs = 0
    errors: list[str] = []
    for current_root, dirs, files in os.walk(root, topdown=False):
        try:
            if os.path.commonpath([root, os.path.abspath(current_root)]) != root:
                continue
        except ValueError:
            continue
        for filename in files:
            path = os.path.join(current_root, filename)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    deleted_files += 1
            except OSError as exc:
                errors.append(f"{path}: {exc}")
        for dirname in dirs:
            path = os.path.join(current_root, dirname)
            try:
                os.rmdir(path)
                deleted_dirs += 1
            except OSError:
                pass
    try:
        os.rmdir(root)
        deleted_dirs += 1
    except OSError:
        pass
    return {
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
        "skipped": False,
        "errors": errors,
    }


def _ftp_cache_filename(filename: object) -> str:
    basename = os.path.basename(_text(filename))
    parsed = parse_slot_filename(basename)
    if parsed and parsed.normalized_name:
        basename = parsed.normalized_name
    stem, ext = os.path.splitext(basename)
    safe_stem = sanitize_path_segment(stem) or "ftp_file"
    safe_ext = ext if ext and len(ext) <= 12 else ""
    return f"{safe_stem}{safe_ext}"


def _cached_ftp_previews(ean: object) -> tuple[dict[str, str], dict[str, str]]:
    """Return remote FTP filenames and cached local preview paths for an EAN."""

    if not ean or not bool(config.CONFIG.get(ft, True)):
        return {}, {}
    ftp = connect_ftp(config.CONFIG.get(H, {}))
    cache_dir = _ftp_cache_dir(ean)
    os.makedirs(cache_dir, exist_ok=True)
    try:
        remote_files = select_remote_files_for_ean(ean, list_remote_filenames(ftp))
        preview_paths: dict[str, str] = {}
        for prefix, filename in remote_files.items():
            target_path = os.path.join(cache_dir, _ftp_cache_filename(filename))
            _download_ftp_to_cache(ftp, filename, target_path)
            if os.path.isfile(target_path):
                preview_paths[prefix] = target_path
        return remote_files, preview_paths
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def cache_ftp_preview(ean: object, filename: object, cache_scope: object = "") -> str:
    """Download one FTP file to the web preview cache and return the local path."""

    cleanup_web_ftp_cache()
    ean_text = _text(ean)
    filename_text = os.path.basename(_text(filename))
    if not ean_text or not filename_text:
        raise ValueError("Brakuje EAN albo nazwy pliku FTP.")
    parsed = parse_slot_filename(filename_text)
    if not parsed or _norm(parsed.ean) != _norm(ean_text):
        raise ValueError("Plik FTP nie pasuje do wybranego EAN.")
    cache_dir = _ftp_cache_dir(ean_text, cache_scope=cache_scope)
    os.makedirs(cache_dir, exist_ok=True)
    target_path = os.path.join(cache_dir, _ftp_cache_filename(filename_text))
    if os.path.isfile(target_path):
        return target_path
    ftp = connect_ftp(config.CONFIG.get(H, {}))
    try:
        _download_ftp_to_cache(ftp, filename_text, target_path)
        return target_path
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def invalidate_ftp_preview_cache(
    ean: object,
    filenames: list[object] | set[object] | tuple[object, ...],
    cache_scope: object = "",
) -> dict[str, object]:
    """Remove cached FTP previews for remote files that were changed."""

    ean_text = _text(ean)
    if not ean_text:
        return {"deleted": 0, "errors": []}
    cache_dir = _ftp_cache_dir(ean_text, cache_scope=cache_scope)
    deleted = 0
    errors: list[str] = []
    for filename in filenames or []:
        filename_text = os.path.basename(_text(filename))
        if not filename_text:
            continue
        target_path = os.path.join(cache_dir, _ftp_cache_filename(filename_text))
        try:
            if os.path.isfile(target_path):
                os.remove(target_path)
                deleted += 1
        except OSError as exc:
            errors.append(f"{filename_text}: {exc}")
    return {"deleted": deleted, "errors": errors}


def _ftp_cache_lock(target_path: str) -> threading.Lock:
    key = os.path.abspath(target_path)
    with _FTP_CACHE_LOCKS_GUARD:
        lock = _FTP_CACHE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FTP_CACHE_LOCKS[key] = lock
        return lock


def _download_ftp_to_cache(ftp, filename: str, target_path: str) -> str:
    """Download an FTP file into cache without racing concurrent web requests."""

    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    lock = _ftp_cache_lock(target_path)
    with lock:
        if os.path.isfile(target_path):
            return target_path
        temp_path = f"{target_path}.{secrets.token_hex(8)}.download"
        try:
            with open(temp_path, "wb") as handle:
                ftp.retrbinary(f"RETR {filename}", handle.write)
            last_error: OSError | None = None
            for _attempt in range(5):
                try:
                    if os.path.isfile(target_path):
                        return target_path
                    os.replace(temp_path, target_path)
                    return target_path
                except OSError as exc:
                    last_error = exc
                    time.sleep(0.2)
            if os.path.isfile(target_path):
                return target_path
            if last_error is not None:
                raise last_error
            return target_path
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


def _dedupe(values: list[object], *, limit: int = 200) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = _text(value)
        if not text:
            continue
        key = text.upper()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


PRODUCT_QUERY_MAX_LIMIT = 100


def _bounded_product_query_limit(limit: object, *, default: int) -> int:
    """Return a positive, server-bounded product query limit."""

    try:
        requested = int(limit)
    except (TypeError, ValueError):
        requested = default
    return max(1, min(requested, PRODUCT_QUERY_MAX_LIMIT))


def _product_suggestion_context(field: str, payload: dict[str, object]) -> dict[str, str]:
    """Return the non-target product fields that narrow a suggestion query."""

    return {
        key: "" if key == field else _text(payload.get(key))
        for key in ("product_id", "ean", "name", "type_name", "model")
    }


def field_suggestions(
    field: str,
    payload: dict[str, object],
    *,
    limit: int = PRODUCT_QUERY_MAX_LIMIT,
) -> list[str]:
    """Return context-aware suggestions, with existing product data first."""

    store = get_active_store()
    bounded_limit = _bounded_product_query_limit(limit, default=PRODUCT_QUERY_MAX_LIMIT)
    prefix = _text(payload.get(field))
    context = _product_suggestion_context(field, payload)
    name = _text(payload.get("name"))
    type_name = _text(payload.get("type_name"))
    model = _text(payload.get("model"))
    colors = [_text(payload.get("color1")), _text(payload.get("color2")), _text(payload.get("color3"))]
    extra = _text(payload.get("extra"))
    existing: list[object] = store.suggest_product_field(
        field,
        prefix,
        context,
        limit=bounded_limit,
    )
    workbook: list[object] = []
    entries: list[WebEntry] = []

    def _entry_context(entry: WebEntry, *, through: str) -> bool:
        if through in {"type_name", "model", "color", "extra"} and name and not _matches_field(entry.name, name):
            return False
        if through in {"model", "color", "extra"} and type_name and not _matches_field(entry.type_name, type_name):
            return False
        if through in {"color", "extra"} and model and not _matches_field(entry.model, model):
            return False
        return True

    index = _get_file_index(start=True)
    if field == "name":
        if index is not None and index.has_snapshot():
            existing = [*index.get_names(), *existing]
        workbook_key = "names"
    elif field == "type_name":
        if index is not None and index.has_snapshot():
            indexed = index.get_types(name)
            if indexed:
                existing = [*indexed, *existing]
        workbook_key = "types"
    elif field == "model":
        if index is not None and index.has_snapshot():
            indexed = index.get_models(name, type_name)
            if indexed:
                existing = [*indexed, *existing]
        workbook_key = "models"
    elif field in {"color1", "color2", "color3"}:
        if index is not None and index.has_snapshot():
            indexed = index.get_colors(name, type_name, model)
            if indexed:
                indexed_colors = []
                for item in indexed:
                    indexed_colors.extend(str(item).replace("_", "-").split("-"))
                existing = [*indexed_colors, *existing]
        workbook_key = "colors"
    elif field == "extra":
        if index is not None and index.has_snapshot():
            indexed = index.get_extras(name, type_name, model, colors)
            if indexed:
                existing = [*indexed, *existing]
        workbook_key = "extras"
    else:
        workbook_key = ""

    if getattr(store, "mode", "") != storage_settings.DATA_MODE_SQLITE:
        lists = prepare_excel_lists()
        entries = [_entry_from_record(item) for item in lists.get(ENTRY_RECORDS_KEY, [])]
        if field in {"color1", "color2", "color3"}:
            existing.extend(
                color
                for entry in entries
                if _entry_context(entry, through="color")
                for color in (entry.color1, entry.color2, entry.color3)
            )
        elif field == "extra":
            existing.extend(
                entry.extra for entry in entries if _entry_context(entry, through="extra")
            )
        if workbook_key:
            workbook = list(lists.get(LIST_SHEETS[workbook_key], []) or [])
    if field == "extra" and not extra:
        existing.insert(0, "NO-LED")
    return _dedupe([*existing, *workbook], limit=bounded_limit)


def _public_user(user: dict[str, object]) -> dict[str, object]:
    now = time.time()
    lock_until = _float_user_value(user.get("login_locked_until"))
    manual_lock = bool(user.get("login_lock_manual", False))
    temporary_lock = lock_until > now
    locked = manual_lock or temporary_lock
    failed_at = _float_user_value(user.get("last_failed_login_at"))
    token_issued_at = _float_user_value(user.get("extension_token_issued_at"))
    token_last_used_at = _float_user_value(user.get("extension_token_last_used_at"))
    return {
        "id": _text(user.get("id")),
        "username": _text(user.get("username")),
        "email": normalize_email_address(user.get("email")),
        "role": "admin" if _text(user.get("role")) == "admin" else "user",
        "enabled": bool(user.get("enabled", True)),
        "has_password": bool(_text(user.get("password_hash"))),
        "session_version": _int_user_value(user.get("session_version")),
        "extension_token_version": _int_user_value(user.get("extension_token_version")),
        "extension_token_issued_ts": token_issued_at,
        "extension_token_issued_at": _format_local_time(token_issued_at) if token_issued_at else "",
        "extension_token_last_used_ts": token_last_used_at,
        "extension_token_last_used_at": _format_local_time(token_last_used_at) if token_last_used_at else "",
        "locked": locked,
        "lock_manual": manual_lock,
        "lock_expires_ts": lock_until if temporary_lock else 0.0,
        "lock_expires_at": _format_local_time(lock_until) if temporary_lock else "",
        "lock_reason": _text(user.get("login_lock_reason")),
        "failed_login_count": _int_user_value(user.get("failed_login_count")),
        "last_failed_login_ts": failed_at,
        "last_failed_login_at": _format_local_time(failed_at) if failed_at else "",
        "last_failed_login_ip": _text(user.get("last_failed_login_ip")),
        "last_failed_login_user_agent": _text(user.get("last_failed_login_user_agent")),
    }


def _default_admin() -> dict[str, object]:
    return {
        "id": _new_user_id(),
        "username": "admin",
        "email": "",
        "role": "admin",
        "enabled": True,
        "password_hash": _hash_password("admin"),
        "session_version": 0,
        "extension_token_version": 0,
        "extension_token_issued_at": 0.0,
        "extension_token_last_used_at": 0.0,
        "failed_login_count": 0,
        "last_failed_login_at": 0.0,
        "last_failed_login_ip": "",
        "last_failed_login_user_agent": "",
        "login_locked_until": 0.0,
        "login_lock_manual": False,
        "login_lock_reason": "",
    }


def _int_user_value(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _float_user_value(value: object) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _format_local_time(timestamp: float) -> str:
    if not timestamp:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(timestamp)))


def _new_user_id() -> str:
    return str(uuid.uuid4())


def _normalized_user_id(value: object) -> str:
    try:
        parsed = uuid.UUID(_text(value))
    except (AttributeError, TypeError, ValueError):
        return _new_user_id()
    if parsed.version != 4:
        return _new_user_id()
    return str(parsed)


def _normalized_user_record(item: dict[str, object]) -> dict[str, object] | None:
    username = _text(item.get("username"))
    if not username:
        return None
    role = _text(item.get("role")) or "user"
    return {
        "id": _normalized_user_id(item.get("id")),
        "username": username,
        "email": normalize_email_address(item.get("email")),
        "role": "admin" if role == "admin" else "user",
        "enabled": bool(item.get("enabled", True)),
        "password_hash": _text(item.get("password_hash"))
        or (_hash_password("admin") if username.lower() == "admin" else ""),
        "session_version": _int_user_value(item.get("session_version")),
        "extension_token_version": _int_user_value(item.get("extension_token_version")),
        "extension_token_issued_at": _float_user_value(item.get("extension_token_issued_at")),
        "extension_token_last_used_at": _float_user_value(item.get("extension_token_last_used_at")),
        "failed_login_count": _int_user_value(item.get("failed_login_count")),
        "last_failed_login_at": _float_user_value(item.get("last_failed_login_at")),
        "last_failed_login_ip": _text(item.get("last_failed_login_ip")),
        "last_failed_login_user_agent": _text(item.get("last_failed_login_user_agent"))[:200],
        "login_locked_until": _float_user_value(item.get("login_locked_until")),
        "login_lock_manual": bool(item.get("login_lock_manual", False)),
        "login_lock_reason": _text(item.get("login_lock_reason")),
    }


def _login_lock_active(user: dict[str, object], now: float | None = None) -> bool:
    now_value = time.time() if now is None else float(now)
    if bool(user.get("login_lock_manual", False)):
        return True
    return _float_user_value(user.get("login_locked_until")) > now_value


def _clear_login_state(user: dict[str, object]) -> None:
    user["failed_login_count"] = 0
    user["login_locked_until"] = 0.0
    user["login_lock_manual"] = False
    user["login_lock_reason"] = ""


def _bump_user_counter(user: dict[str, object], key: str) -> int:
    value = _int_user_value(user.get(key)) + 1
    user[key] = value
    return value


def load_user_records() -> list[dict[str, object]]:
    """Load full local web user records, including password hashes."""

    with _USERS_LOCK:
        sqlite_store = _active_sqlite_store()
        if sqlite_store is not None:
            data = sqlite_store.load_users()
            changed = not bool(data)
        else:
            path = Path(settings.AC) / WEB_USERS_PATH
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = []
            changed = not isinstance(data, list)
            if not isinstance(data, list):
                data = []
        users = []
        seen_usernames = set()
        seen_ids = set()
        for item in data:
            if not isinstance(item, dict):
                changed = True
                continue
            user = _normalized_user_record(item)
            if not user or user["username"].lower() in seen_usernames:
                changed = True
                continue
            if user["id"] in seen_ids:
                user["id"] = _new_user_id()
            if _text(item.get("id")) != user["id"]:
                changed = True
            users.append(user)
            seen_usernames.add(user["username"].lower())
            seen_ids.add(user["id"])
        if not any(user["username"].lower() == "admin" for user in users):
            users.insert(0, _default_admin())
            changed = True
        if changed:
            _persist_user_records(users)
        return users


def load_users() -> list[dict[str, object]]:
    """Load public web user records for settings UI."""

    return [_public_user(user) for user in load_user_records()]


def _persist_user_records(users: list[dict[str, object]]) -> None:
    sqlite_store = _active_sqlite_store()
    if sqlite_store is not None:
        sqlite_store.save_users(users)
        return
    path = Path(settings.AC) / WEB_USERS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(users, indent=4, ensure_ascii=False), encoding="utf-8")


def save_users(users: list[dict[str, object]]) -> list[dict[str, object]]:
    """Persist local web user records."""

    with _USERS_LOCK:
        _persist_user_records(users)
        return load_users()


def authenticate_user(username: str, password: str) -> dict[str, object] | None:
    """Return a public user record when credentials are valid."""

    normalized = _text(username).lower()
    with _USERS_LOCK:
        for user in load_user_records():
            if _text(user.get("username")).lower() != normalized:
                continue
            if not bool(user.get("enabled", True)) or _login_lock_active(user):
                return None
            if verify_password(password, _text(user.get("password_hash"))):
                return _public_user(user)
    return None


def authenticate_login(
    username: str,
    password: str,
    *,
    remote_address: str = "",
    user_agent: str = "",
) -> dict[str, object]:
    """Authenticate a login attempt and update lockout state."""

    normalized = _text(username).lower()
    now = time.time()
    with _USERS_LOCK:
        users = load_user_records()
        matched: dict[str, object] | None = None
        for user in users:
            if _text(user.get("username")).lower() == normalized:
                matched = user
                break
        if matched is None:
            return {
                "ok": False,
                "known": False,
                "reason": "unknown_user",
                "failed_login_count": 0,
            }
        if not bool(matched.get("enabled", True)):
            return {
                "ok": False,
                "known": True,
                "reason": "disabled",
                "user": _public_user(matched),
            }
        expired_lock_cleared = False
        if (
            not bool(matched.get("login_lock_manual", False))
            and _float_user_value(matched.get("login_locked_until"))
            and _float_user_value(matched.get("login_locked_until")) <= now
        ):
            _clear_login_state(matched)
            expired_lock_cleared = True
        if _login_lock_active(matched, now):
            return {
                "ok": False,
                "known": True,
                "reason": "locked",
                "user": _public_user(matched),
            }
        if verify_password(password, _text(matched.get("password_hash"))):
            had_failed_state = bool(_int_user_value(matched.get("failed_login_count"))) or bool(
                matched.get("login_lock_reason")
            )
            if had_failed_state or expired_lock_cleared:
                _clear_login_state(matched)
                save_users(users)
            return {
                "ok": True,
                "known": True,
                "reason": "ok",
                "user": _public_user(matched),
            }

        failed_count = _int_user_value(matched.get("failed_login_count")) + 1
        matched["failed_login_count"] = failed_count
        matched["last_failed_login_at"] = now
        matched["last_failed_login_ip"] = _text(remote_address)
        matched["last_failed_login_user_agent"] = _text(user_agent)[:200]
        just_locked = False
        if failed_count >= LOGIN_FAILURE_LIMIT:
            just_locked = True
            if _text(matched.get("role")) == "admin":
                matched["login_lock_manual"] = True
                matched["login_locked_until"] = 0.0
                matched["login_lock_reason"] = "admin_failed_logins_manual_unlock"
            else:
                matched["login_lock_manual"] = False
                matched["login_locked_until"] = now + LOGIN_LOCK_SECONDS
                matched["login_lock_reason"] = "failed_logins_temporary_lock"
        save_users(users)
        return {
            "ok": False,
            "known": True,
            "reason": "locked" if just_locked else "bad_password",
            "just_locked": just_locked,
            "failed_login_count": failed_count,
            "limit": LOGIN_FAILURE_LIMIT,
            "user": _public_user(matched),
        }


def find_user(username: str) -> dict[str, object] | None:
    """Return a public user by username."""

    normalized = _text(username).lower()
    for user in load_user_records():
        if _text(user.get("username")).lower() == normalized:
            return _public_user(user)
    return None


def find_user_by_id(user_id: str) -> dict[str, object] | None:
    """Return a public user by stable server-generated identifier."""

    try:
        normalized_id = uuid.UUID(_text(user_id))
    except (AttributeError, TypeError, ValueError):
        return None
    if normalized_id.version != 4:
        return None
    candidate = str(normalized_id)
    for user in load_user_records():
        if hmac.compare_digest(_text(user.get("id")), candidate):
            return _public_user(user)
    return None


def add_user(
    username: str,
    password: str,
    role: str = "user",
    email: str = "",
) -> list[dict[str, object]]:
    """Add a web user account."""

    username = _text(username)
    if not username:
        raise ValueError("Nazwa uzytkownika nie moze byc pusta.")
    if not _text(password):
        raise ValueError("Haslo uzytkownika nie moze byc puste.")
    email = normalize_email_address(email)
    users = load_user_records()
    if any(user["username"].lower() == username.lower() for user in users):
        raise ValueError("Taki uzytkownik juz istnieje.")
    users.append(
        {
            "id": _new_user_id(),
            "username": username,
            "email": email,
            "role": "admin" if _text(role) == "admin" else "user",
            "enabled": True,
            "password_hash": _hash_password(password),
            "session_version": 0,
            "extension_token_version": 0,
            "extension_token_issued_at": 0.0,
            "extension_token_last_used_at": 0.0,
            "failed_login_count": 0,
            "last_failed_login_at": 0.0,
            "last_failed_login_ip": "",
            "last_failed_login_user_agent": "",
            "login_locked_until": 0.0,
            "login_lock_manual": False,
            "login_lock_reason": "",
        }
    )
    return save_users(users)


def update_user(
    username: str,
    *,
    enabled: bool | None = None,
    role: str | None = None,
    password: str | None = None,
    email: str | None = None,
    unlock: bool | None = None,
    revoke_sessions: bool | None = None,
    revoke_extension_token: bool | None = None,
    current_username: str = "",
) -> list[dict[str, object]]:
    """Update a web user account."""

    users = load_user_records()
    for user in users:
        if user["username"].lower() != _text(username).lower():
            continue
        if enabled is not None:
            if _text(current_username).lower() == _text(username).lower() and not bool(enabled):
                raise ValueError("Nie mozna wylaczyc konta, na ktorym jestes zalogowany.")
            user["enabled"] = bool(enabled)
        if role is not None:
            user["role"] = "admin" if _text(role) == "admin" else "user"
        if email is not None:
            user["email"] = normalize_email_address(email)
        if password is not None and _text(password):
            user["password_hash"] = _hash_password(password)
            _bump_user_counter(user, "session_version")
            _bump_user_counter(user, "extension_token_version")
        if unlock:
            _clear_login_state(user)
        if revoke_sessions:
            _bump_user_counter(user, "session_version")
        if revoke_extension_token:
            _bump_user_counter(user, "extension_token_version")
        return save_users(users)
    raise ValueError("Nie znaleziono uzytkownika.")


def unlock_user(username: str) -> list[dict[str, object]]:
    """Clear login lockout state for a web user account."""

    return update_user(username, unlock=True)


def mark_browser_extension_token_issued(username: str) -> dict[str, object] | None:
    """Store token issue time for the current browser extension token version."""

    normalized = _text(username).lower()
    with _USERS_LOCK:
        users = load_user_records()
        for user in users:
            if _text(user.get("username")).lower() != normalized:
                continue
            user["extension_token_issued_at"] = time.time()
            save_users(users)
            return _public_user(user)
    return None


def mark_browser_extension_token_used(username: str, version: int) -> dict[str, object] | None:
    """Store last-use time when an extension token matches the active version."""

    normalized = _text(username).lower()
    with _USERS_LOCK:
        users = load_user_records()
        for user in users:
            if _text(user.get("username")).lower() != normalized:
                continue
            if _int_user_value(user.get("extension_token_version")) != int(version):
                return None
            user["extension_token_last_used_at"] = time.time()
            save_users(users)
            return _public_user(user)
    return None


def _matches_field(entry_value: str, expected: str) -> bool:
    expected_norm = _norm(expected)
    if not expected_norm:
        return True
    return _norm(entry_value) == expected_norm


def search_entries(
    *,
    ean: str = "",
    product_id: str = "",
    name: str = "",
    type_name: str = "",
    model: str = "",
    query: str = "",
    limit: int = 30,
) -> list[dict[str, str]]:
    """Search saved product entries by EAN, product id or form fields."""

    bounded_limit = _bounded_product_query_limit(limit, default=30)
    criteria = ProductSearchCriteria(
        ean=ean,
        product_id=product_id,
        name=name,
        type_name=type_name,
        model=model,
        query=query,
    )
    records = get_active_store().search_product_entries(criteria, limit=bounded_limit)
    return [entry_to_payload(_entry_from_record(record)) for record in records]


def find_entry_by_identity(*, product_id: str = "", ean: str = "") -> dict[str, str] | None:
    """Return one saved entry by product id or EAN."""

    store = get_active_store()
    record = None
    if _text(product_id):
        record = store.get_product_by_id(product_id)
    elif _text(ean) and _text(ean).upper() != NO_EAN_PLACEHOLDER:
        record = store.get_product_by_ean(ean)
    if record:
        return entry_to_payload(_entry_from_record(record))
    return None


def save_web_entry(payload: dict[str, object]) -> dict[str, object]:
    """Create or update an Excel entry using the existing desktop helper."""

    field_settings = normalize_product_fields(
        config.CONFIG.get(PRODUCT_FIELDS_KEY),
        legacy_color_labels=config.CONFIG.get(COLOR_FIELD_LABELS_KEY),
    )
    payload = effective_product_values(payload, field_settings)
    missing = missing_required_fields(payload, field_settings)
    if missing:
        raise ValueError(
            " ".join(
                f"Pole „{label}” jest wymagane."
                for _key, label in missing
            )
        )
    product_id = _text(payload.get("product_id"))
    ean = _text(payload.get("ean"))
    existing = find_entry_by_identity(product_id=product_id, ean=ean)
    if existing:
        product_id = product_id or _text(existing.get("product_id"))
        if field_settings["ean"]["enabled"] and not ean and _text(existing.get("ean")):
            ean = _text(existing.get("ean"))
    result = save_ean_entry(
        ean or NO_EAN_PLACEHOLDER,
        _text(payload.get("name")),
        _text(payload.get("type_name")),
        _text(payload.get("model")),
        _text(payload.get("color1")),
        _text(payload.get("color2")),
        _text(payload.get("color3")),
        _text(payload.get("extra")),
        product_id=product_id,
    )
    if not result:
        raise ValueError("Nie udalo sie zapisac wpisu w Excelu.")
    return result


def add_list_value(list_key: str, value: str) -> dict[str, object]:
    """Add a value to one of the editable Excel list sheets."""

    sheet = LIST_SHEETS.get(list_key)
    if not sheet:
        raise ValueError("Nieznana lista.")
    if not _text(value):
        raise ValueError("Wartosc nie moze byc pusta.")
    lists = prepare_excel_lists()
    normalized = _list_value_key(value)
    if normalized and any(_list_value_key(item) == normalized for item in lists.get(sheet, [])):
        raise ValueError("Taka wartosc juz istnieje na liscie.")
    if not add_to_list(sheet, value):
        raise ValueError("Nie udalo sie dodac wartosci do listy.")
    return load_web_data()


def remove_list_value(list_key: str, value: str) -> dict[str, object]:
    """Remove a value from one of the editable Excel list sheets."""

    sheet = LIST_SHEETS.get(list_key)
    if not sheet:
        raise ValueError("Nieznana lista.")
    used_by = find_list_value_usage(sheet, value)
    if used_by:
        raise ListValueInUseError(list_key, value, used_by)
    remove_from_list(sheet, value)
    return load_web_data()


def is_windows_admin_process() -> bool:
    """Return True when the backend process is already elevated."""

    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _local_settings_path() -> Path:
    return Path(settings.BASE_DIR_SETTINGS_PATH)


def _normalize_base_dir(value: object) -> str:
    text = _text(value).strip("\"'")
    if not text:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(text))
    return os.path.abspath(expanded)


def _same_path(left: object, right: object) -> bool:
    try:
        return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
            os.path.abspath(str(right))
        )
    except Exception:
        return str(left or "") == str(right or "")


def _ensure_base_dir_web_access(path: str) -> None:
    ok, error = settings._ensure_directory_access(path)
    if not ok:
        details = f" Szczegoly: {error}" if error else ""
        raise ValueError(f"Nie mozna uzyc katalogu bazowego: {path}.{details}")
    try:
        fd, probe_path = tempfile.mkstemp(
            prefix="picsyncra_base_dir_check_",
            suffix=".tmp",
            dir=path,
        )
        os.close(fd)
        os.remove(probe_path)
    except OSError as exc:
        raise ValueError(f"Brak zapisu w katalogu bazowym: {path}. Szczegoly: {exc}") from exc


def _load_local_settings() -> dict[str, object]:
    path = _local_settings_path()
    if not path.exists():
        return dict(common.BASE_DIR_SETTINGS_TEMPLATE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(common.BASE_DIR_SETTINGS_TEMPLATE)
    return data if isinstance(data, dict) else dict(common.BASE_DIR_SETTINGS_TEMPLATE)


def _save_local_settings(payload: dict[str, object]) -> None:
    path = _local_settings_path()
    existing = _load_local_settings()
    existing.update(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix="local_settings_",
        suffix=".json.tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(existing, handle, indent=4, ensure_ascii=False)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _apply_base_dir_from_web(value: object) -> bool:
    requested = _normalize_base_dir(value)
    if not requested:
        return False
    _ensure_base_dir_web_access(requested)
    previous = settings.AC
    _save_local_settings({"base_dir_override": requested})
    settings.initialize_runtime(interactive=False)
    if not _same_path(settings.AC, requested):
        warning = settings.BASE_DIR_OVERRIDE_WARNING or "runtime pozostal przy poprzednim katalogu"
        raise ValueError(
            "Zapisano local_settings.json, ale backend nie przelaczyl sie na nowy "
            f"katalog. Wybrany: {requested}. Aktywny: {settings.AC}. {warning}"
        )
    return not _same_path(previous, settings.AC)


def _apply_app_secret_from_web(value: object) -> bool:
    secret = _text(value)
    if not secret:
        return False
    _save_local_settings({APP_SECRET_KEY: common._encode_local_secret(secret)})
    if secret == common.APP_SECRET:
        return False
    common.APP_SECRET = secret
    common.BASE_DIR_SETTINGS_TEMPLATE[APP_SECRET_KEY] = common._encode_local_secret(secret)
    encryption.APP_SECRET = secret
    return True


def parse_pimcore_csv_headers(content: bytes) -> list[str]:
    if not content:
        raise ValueError("Plik CSV jest pusty.")
    text = ""
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        raise ValueError("Nie mozna odczytac kodowania pliku CSV.")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        reader = csv.reader(io.StringIO(text), dialect)
    except csv.Error:
        reader = csv.reader(io.StringIO(text), delimiter=";")
    row = next(reader, [])
    headers: list[str] = []
    for value in row:
        header = str(value or "").strip()
        if header and header not in headers:
            headers.append(header)
    if not headers:
        raise ValueError("Plik CSV nie zawiera naglowkow.")
    return headers


def _merged_pimcore_settings(overrides: object = None) -> dict[str, object]:
    saved = normalize_pimcore_settings(config.CONFIG.get(PIMCORE_SETTINGS_KEY))
    merged = dict(saved)
    if isinstance(overrides, dict):
        merged.update(overrides)
        if not _text(overrides.get(PIMCORE_API_KEY)):
            merged[PIMCORE_API_KEY] = saved[PIMCORE_API_KEY]
    return normalize_pimcore_settings(merged)


def discover_pimcore_classes(overrides: object = None) -> dict[str, object]:
    settings_payload = _merged_pimcore_settings(overrides)
    with pimcore_client_scope(settings_payload, factory=PimcoreClient) as client:
        return {"items": discover_classes(client)}


def discover_pimcore_fields(overrides: object, class_id: object) -> dict[str, object]:
    settings_payload = _merged_pimcore_settings(overrides)
    with pimcore_client_scope(settings_payload, factory=PimcoreClient) as client:
        return {"items": discover_fields(client, class_id)}


def discover_pimcore_folders(overrides: object = None) -> dict[str, object]:
    settings_payload = _merged_pimcore_settings(overrides)
    with pimcore_client_scope(settings_payload, factory=PimcoreClient) as client:
        return {"items": discover_folders(client)}


def complete_pimcore_setup(payload: object, username: str) -> dict[str, object]:
    submitted = dict(payload) if isinstance(payload, dict) else {}
    submitted["object_key_template"] = "{EAN}"
    submitted["published"] = True
    submitted["setup_complete"] = False
    report = test_pimcore_settings(submitted, username)
    if not report.get("ok"):
        return {"saved": False, "report": report}
    submitted["setup_complete"] = True
    submitted["enabled"] = True
    snapshot = update_settings({PIMCORE_SETTINGS_KEY: submitted})
    return {"saved": True, "report": report, "settings": snapshot}


def test_pimcore_settings(
    overrides: object = None,
    username: str = "admin",
) -> dict[str, object]:
    merged = _merged_pimcore_settings(overrides)
    with pimcore_client_scope(merged, factory=PimcoreClient) as client:
        report = run_settings_test(merged, client=client)
    audit_report = redact_pimcore_log_value(report)
    record_history(
        username=username,
        action="pimcore_settings_test",
        summary=(
            "Test ustawien Pimcore zakonczony poprawnie."
            if report["ok"]
            else "Test ustawien Pimcore wykryl bledy."
        ),
        details={"pimcore_settings_test": audit_report},
    )
    return {
        **report,
        "checks": [
            {key: value for key, value in check.items() if key != "response_detail"}
            for check in report.get("checks", [])
            if isinstance(check, dict)
        ],
    }


def _persist_pimcore_operation(report: dict[str, object]) -> dict[str, object]:
    values = report.get("values") if isinstance(report.get("values"), dict) else {}
    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    result_object = result.get("object") if isinstance(result.get("object"), dict) else {}
    operation_type = _text(report.get("operation_type"))
    if operation_type == "test":
        action = "pimcore_test_create"
    elif operation_type == "manual_update":
        action = "pimcore_product_update"
    elif report.get("status") in {"duplicate", "failed"}:
        action = "pimcore_product_create_rejected"
    else:
        action = "pimcore_product_create"
    pimcore_change_set = (
        result.get("change_set")
        if isinstance(result.get("change_set"), dict)
        else {}
    )
    if pimcore_change_set:
        pimcore_change_set = dict(pimcore_change_set)
        object_id = _text(
            result.get("object_id")
            or result.get("id")
            or result_object.get("id")
        )
        object_path = _text(
            result.get("object_path")
            or result.get("path")
            or result_object.get("path")
            or result_object.get("fullPath")
        )
        if object_id:
            pimcore_change_set["object_id"] = object_id
        if object_path:
            pimcore_change_set["object_path"] = object_path

        def safe_elapsed(value: object) -> int | None:
            if isinstance(value, bool):
                return None
            try:
                return max(0, min(int(value), 86_400_000))
            except (TypeError, ValueError):
                return None

        total_ms = safe_elapsed(report.get("total_ms"))
        if total_ms is not None:
            pimcore_change_set["total_ms"] = total_ms
        events = report.get("events") if isinstance(report.get("events"), list) else []
        for event in events:
            if not isinstance(event, dict):
                continue
            elapsed = safe_elapsed(event.get("stage_elapsed_ms"))
            if elapsed is None:
                continue
            stage = _text(event.get("stage")).lower()
            if stage in {"create", "update"}:
                pimcore_change_set["send_ms"] = elapsed
            elif stage == "verify":
                pimcore_change_set["verification_ms"] = elapsed
        pimcore_change_set = redact_pimcore_log_value(pimcore_change_set)
    integrations = (
        report.get("integration_results")
        if isinstance(report.get("integration_results"), dict)
        else pimcore_change_set.get("integrations")
        if isinstance(pimcore_change_set.get("integrations"), dict)
        else {}
    )
    details: dict[str, object] = {
        "pimcore_operation": redact_pimcore_log_value(report)
    }
    if pimcore_change_set:
        details["change_set"] = {
            "kind": pimcore_change_set.get("kind", "synchronized"),
            "fields": [],
            "files": [],
            "integrations": integrations,
            "pimcore": pimcore_change_set,
        }
    return record_history(
        username=_text(report.get("username")),
        action=action,
        ean=values.get("EAN", ""),
        product_id=result.get("object_id") or result_object.get("id", ""),
        summary=f"Pimcore: {report.get('status', 'unknown')}.",
        details=details,
    )


def _pimcore_submission_record(report: dict[str, object]) -> dict[str, object]:
    values = report.get("values") if isinstance(report.get("values"), dict) else {}
    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    result_object = result.get("object") if isinstance(result.get("object"), dict) else {}
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    result_warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
    report_warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    return {
        "operation_id": _text(report.get("operation_id")),
        "operation_type": _text(report.get("operation_type")),
        "username": _text(report.get("username")),
        "ean": _text(values.get("EAN") or values.get("ean")),
        "object_id": _text(
            result.get("object_id")
            or result.get("id")
            or result_object.get("id")
        ),
        "object_path": _text(
            result.get("object_path")
            or result.get("path")
            or result_object.get("path")
            or result_object.get("fullPath")
        ),
        "status": _text(report.get("status")),
        "values": values,
        "payload": payload,
        "result": result,
        "warnings": report_warnings + result_warnings,
        "created_at": report.get("finished_at") or report.get("started_at") or time.time(),
    }


def _persist_pimcore_submission(report: dict[str, object]) -> None:
    store = _pimcore_submission_store()
    if store is None:
        return
    try:
        store.append_pimcore_submission(
            redact_pimcore_log_value(_pimcore_submission_record(report))
        )
    except Exception as exc:
        log_error(f"Failed to persist Pimcore submission: {exc}")


def _persist_pimcore_audit(report: dict[str, object]) -> None:
    _persist_pimcore_operation(report)
    _persist_pimcore_submission(report)


def _run_pimcore_test_create(
    settings_payload: dict[str, object],
    submitted: dict[str, object],
    policy: str,
    emit: object,
) -> dict[str, object]:
    with pimcore_client_scope(settings_payload, factory=PimcoreClient) as client:
        return run_test_create(
            settings_payload,
            submitted,
            policy,
            client=client,
            emit=emit,
        )


def start_pimcore_test_create(
    values: object,
    cleanup_policy: object,
    username: str,
) -> dict[str, object]:
    submitted = dict(values) if isinstance(values, dict) else {}
    policy = _text(cleanup_policy)
    settings_payload = normalize_pimcore_settings(config.CONFIG.get(PIMCORE_SETTINGS_KEY))
    return _PIMCORE_OPERATIONS.start(
        operation_type="test",
        username=username,
        values=submitted,
        cleanup_policy=policy,
        worker=lambda emit: _run_pimcore_test_create(
            settings_payload,
            submitted,
            policy,
            emit,
        ),
        persist=_persist_pimcore_audit,
    )


def _pimcore_runtime_form_schema(settings_payload: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "source": item["source"],
            "label": item["label"],
            "pimcore_field": item["pimcore_field"],
            "required": item["required"],
            "default": item["default"],
            "parser": item["parser"],
            "value_template": item["value_template"],
            "sql_query": item.get("sql_query", ""),
            "sql_profile_id": item.get("sql_profile_id", ""),
            "translate": item["translate"],
            "target_language": item["target_language"],
            "ocr_validation": bool(item.get("ocr_validation", False)),
            "layout_group": item.get("layout_group", ""),
            "layout_order": item.get("layout_order", 0),
        }
        for _index, item in sorted(
            enumerate(settings_payload["field_mappings"]),
            key=lambda pair: (
                int(pair[1].get("layout_order", pair[0])),
                pair[0],
            ),
        )
    ]


def _generated_product_template_values() -> dict[str, object]:
    generated = generate_test_values(
        [
            {"source": source.upper(), "type": "input", "parser": "text"}
            for source in PRODUCT_SOURCES
        ]
    )
    return {
        source: generated.get(source.upper(), "")
        for source in PRODUCT_SOURCES
    }


def _entry_product_template_values(entry: WebEntry) -> dict[str, object]:
    return {
        "name": entry.name,
        "type": entry.type_name,
        "model": entry.model,
        "color1": entry.color1,
        "color2": entry.color2,
        "color3": entry.color3,
        "extra": entry.extra,
        "ean": entry.ean,
    }


def _sample_product_template_values() -> dict[str, object]:
    try:
        records = prepare_excel_lists().get(ENTRY_RECORDS_KEY, [])
    except Exception:
        records = []
    entries = [
        _entry_from_record(item)
        for item in records
        if isinstance(item, dict)
    ]
    entries = [
        entry
        for entry in entries
        if any(
            (
                entry.name,
                entry.type_name,
                entry.model,
                entry.color1,
                entry.color2,
                entry.color3,
                entry.extra,
                entry.ean,
            )
        )
    ]
    if entries:
        selected = _entry_product_template_values(entries[secrets.randbelow(len(entries))])
        generated = _generated_product_template_values()
        return {
            key: value if _text(value) else generated.get(key, "")
            for key, value in selected.items()
        }
    return _generated_product_template_values()


def _product_template_values(raw: object, *, fill_missing: bool = False) -> dict[str, object]:
    source = raw if isinstance(raw, dict) else {}
    values = {
        "name": source.get("name", ""),
        "type": source.get("type", source.get("type_name", "")),
        "model": source.get("model", ""),
        "color1": source.get("color1", ""),
        "color2": source.get("color2", ""),
        "color3": source.get("color3", ""),
        "extra": source.get("extra", ""),
        "ean": source.get("ean", source.get("EAN", "")),
    }
    if fill_missing and any(not _text(value) for value in values.values()):
        sample = _sample_product_template_values()
        values = {
            key: value if _text(value) else sample.get(key, "")
            for key, value in values.items()
        }
    return values


def _template_uses_sql_source(template: object) -> bool:
    try:
        return any(source.casefold() == "sql" for source in placeholder_sources(template))
    except TemplateError:
        return False


def _sql_template_source(source: object) -> str:
    return f"SQL:{_text(source)}"


def _rewrite_sql_template_source(template: object, source: object) -> str:
    replacement = _sql_template_source(source)

    def replace(match):
        content = match.group(1)
        parts = content.split("|", 1)
        if _text(parts[0]).casefold() != "sql":
            return match.group(0)
        suffix = f"|{parts[1]}" if len(parts) == 2 else ""
        return "{" + replacement + suffix + "}"

    return re.sub(r"\{([^{}]+)\}", replace, str(template or ""))


def _redact_sql_integration_error(
    value: object,
    profiles: list[dict[str, object]],
) -> str:
    text = str(value or "")

    def redact_assignment(match: re.Match[str]) -> str:
        if not SECRET_KEY_RE.search(match.group("key")):
            return match.group(0)
        return "credential=[REDACTED]"

    text = _SQL_ASSIGNMENT_RE.sub(redact_assignment, text)
    known_secrets = {
        str(profile.get("password") or "")
        for profile in profiles
        if str(profile.get("password") or "")
    }
    for secret in sorted(known_secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return sanitize_free_text(text, limit=SQL_PROFILE_ERROR_MAX_BYTES)


def _sql_warning_codes(warnings: object) -> list[str]:
    if not isinstance(warnings, list):
        return []
    return [
        _text(warning.get("code"))
        for warning in warnings[:SQL_PROFILE_WARNING_CODES_MAX]
        if isinstance(warning, dict) and _text(warning.get("code"))
    ]


def _render_templates(
    settings_payload: dict[str, object],
    product_values: object,
    values: object,
    targets: list[str] | None = None,
    *,
    fill_missing_product_values: bool = False,
    mode: str = "create",
    image_slot_paths: Mapping[str, str] | None = None,
) -> dict[str, object]:
    with SqlExecutionContext(execute_query=execute_sql_value_query) as sql_context:
        return _render_templates_with_sql_context(
            settings_payload,
            product_values,
            values,
            targets,
            fill_missing_product_values=fill_missing_product_values,
            mode=mode,
            image_slot_paths=image_slot_paths,
            sql_context=sql_context,
        )


def _render_templates_with_sql_context(
    settings_payload: dict[str, object],
    product_values: object,
    values: object,
    targets: list[str] | None = None,
    *,
    fill_missing_product_values: bool = False,
    mode: str = "create",
    image_slot_paths: Mapping[str, str] | None = None,
    sql_context: SqlExecutionContext,
) -> dict[str, object]:
    submitted = dict(values) if isinstance(values, dict) else {}
    mappings_list = list(settings_payload["field_mappings"])
    sql_sources = {
        item["source"]
        for item in mappings_list
        if str(item.get("value_template") or "").strip().casefold() == "sql"
    }
    sql_template_sources = {
        item["source"]
        for item in mappings_list
        if item["source"] not in sql_sources
        and _template_uses_sql_source(item.get("value_template"))
    }
    selected_targets = set(targets or [item["source"] for item in mappings_list])
    template_mappings = [
        {
            **item,
            "value_template": ""
            if item["source"] in sql_sources
            else _rewrite_sql_template_source(item.get("value_template", ""), item["source"])
            if item["source"] in sql_template_sources
            else item.get("value_template", ""),
        }
        for item in mappings_list
    ]
    product_context = _product_template_values(
        product_values,
        fill_missing=fill_missing_product_values,
    )
    output = dict(submitted)
    warnings: list[dict[str, object]] = []
    calculated_values: dict[str, object] = {}
    changed: dict[str, bool] = {}
    profiles = normalize_sql_profiles(config.CONFIG)
    mappings = {
        item["source"]: item
        for item in mappings_list
    }
    extra_sources: list[SourceDefinition] = []
    extra_values: dict[str, object] = {}
    sql_profile_results: list[dict[str, object]] = []
    for source in sql_template_sources:
        mapping = mappings[source]
        required = bool(mapping.get("required"))
        sql_key = _sql_template_source(source)
        extra_sources.append(
            SourceDefinition(sql_key, f"SQL {mapping.get('label') or source}", "sql", (sql_key,))
        )
        integration_started = time.perf_counter()
        profile_id = _text(mapping.get("sql_profile_id"))
        try:
            profile = resolve_sql_profile(profiles, mapping.get("sql_profile_id"))
            profile_id = _text(profile.get("id")) or profile_id
            if not profile.get("enabled", True):
                label = profile.get("label") or profile.get("id")
                raise ValueError(f"Profil SQL {label} jest wylaczony.")
            sql_result = sql_context.execute(
                profile,
                mapping.get("sql_query"),
                product_context,
                output,
                mappings=mappings_list,
            )
        except Exception as exc:
            safe_error = _redact_sql_integration_error(exc, profiles)
            warnings.append({"source": source, "code": "sql_error", "message": safe_error})
            extra_values[sql_key] = ""
            sql_profile_results.append(
                {
                    "profile_id": profile_id,
                    "source": source,
                    "status": "error",
                    "elapsed_ms": int((time.perf_counter() - integration_started) * 1000),
                    "warning_codes": ["sql_error"],
                    "error": safe_error,
                    "required": required,
                }
            )
        else:
            extra_values[sql_key] = sql_result.value
            warnings.extend({"source": source, **warning} for warning in sql_result.warnings)
            warning_codes = _sql_warning_codes(sql_result.warnings)
            sql_profile_results.append(
                {
                    "profile_id": profile_id,
                    "source": source,
                    "status": "warning" if warning_codes else "success",
                    "elapsed_ms": int((time.perf_counter() - integration_started) * 1000),
                    "warning_codes": warning_codes,
                    "error": "",
                    "required": required,
                }
            )
    rendered = render_mapping_templates(
        template_mappings,
        product_values=product_context,
        pimcore_values=submitted,
        targets=targets,
        extra_sources=extra_sources,
        extra_values=extra_values,
        preserve_submitted_dependencies=mode == "edit",
    )
    translation_settings = config.CONFIG.get(TRANSLATION_SETTINGS_KEY, {}) or {}
    independent_translation_operations = [
        (
            lambda source=source: (
                source,
                translate_text(
                    rendered.values[source],
                    mappings[source].get("target_language"),
                    translation_settings,
                ),
            )
        )
        for source in rendered.order
        if mappings[source].get("translate")
        and classify_template_operation(mappings[source]).independent
    ]
    translated_values = dict(
        execute_independent_operations(independent_translation_operations)
    )
    for source in rendered.order:
        mapping = mappings[source]
        value = rendered.values[source]
        if mapping.get("translate"):
            translated = translated_values.get(source)
            if translated is None:
                translated = translate_text(
                    value,
                    mapping.get("target_language"),
                    translation_settings,
                )
            value = translated.text
            if translated.warning:
                warnings.append({"source": source, **translated.warning})
        output[source] = value
    for mapping in mappings_list:
        source = mapping["source"]
        required = bool(mapping.get("required"))
        if source not in selected_targets:
            continue
        if source not in sql_sources:
            if source in output:
                calculated_values[source] = output[source]
                changed[source] = str(submitted.get(source, "")) != str(output[source])
            continue
        integration_started = time.perf_counter()
        profile_id = _text(mapping.get("sql_profile_id"))
        try:
            profile = resolve_sql_profile(profiles, mapping.get("sql_profile_id"))
            profile_id = _text(profile.get("id")) or profile_id
            if not profile.get("enabled", True):
                label = profile.get("label") or profile.get("id")
                raise ValueError(f"Profil SQL {label} jest wylaczony.")
            sql_result = sql_context.execute(
                profile,
                mapping.get("sql_query"),
                product_context,
                output,
                mappings=mappings_list,
            )
        except Exception as exc:
            safe_error = _redact_sql_integration_error(exc, profiles)
            warnings.append({"source": source, "code": "sql_error", "message": safe_error})
            calculated = ""
            sql_profile_results.append(
                {
                    "profile_id": profile_id,
                    "source": source,
                    "status": "error",
                    "elapsed_ms": int((time.perf_counter() - integration_started) * 1000),
                    "warning_codes": ["sql_error"],
                    "error": safe_error,
                    "required": required,
                }
            )
        else:
            calculated = sql_result.value
            warnings.extend({"source": source, **warning} for warning in sql_result.warnings)
            warning_codes = _sql_warning_codes(sql_result.warnings)
            sql_profile_results.append(
                {
                    "profile_id": profile_id,
                    "source": source,
                    "status": "warning" if warning_codes else "success",
                    "elapsed_ms": int((time.perf_counter() - integration_started) * 1000),
                    "warning_codes": warning_codes,
                    "error": "",
                    "required": required,
                }
            )
        calculated_values[source] = calculated
        current = str(submitted.get(source, ""))
        changed[source] = current != str(calculated)
        if (mode in {"create", "test", "preview"} and not _text(current)) or mode == "apply":
            output[source] = calculated
            changed[source] = False
    return {
        "values": output,
        "calculated_values": calculated_values,
        "warnings": warnings,
        "changed": changed,
        "integrations": {"sql_profiles": sql_profile_results},
    }


def preview_pimcore_template(
    payload: object,
    *,
    image_slot_paths: Mapping[str, str] | None = None,
) -> dict[str, object]:
    source = payload if isinstance(payload, dict) else {}
    settings_payload = normalize_pimcore_settings(
        {"field_mappings": source.get("mappings", [])}
    )
    target = _text(source.get("target_source"))
    if not target:
        raise ValueError("Wybierz pole docelowe szablonu.")
    return _render_templates(
        settings_payload,
        source.get("product_values"),
        source.get("values"),
        [target],
        fill_missing_product_values=True,
        mode="preview",
        image_slot_paths=image_slot_paths,
    )


def pimcore_test_sample() -> dict[str, object]:
    settings_payload = normalize_pimcore_settings(config.CONFIG.get(PIMCORE_SETTINGS_KEY))
    if not settings_payload["setup_complete"]:
        raise ValueError("Integracja Pimcore nie zostala skonfigurowana.")
    samples = generate_test_values(settings_payload["field_mappings"])
    product_samples = _sample_product_template_values()
    rendered = _render_templates(settings_payload, product_samples, samples, mode="test")
    return {
        "form_schema": _pimcore_runtime_form_schema(settings_payload),
        **rendered,
    }


def render_saved_pimcore_templates(
    product_values: object,
    values: object,
    targets: object,
    mode: str = "create",
    *,
    image_slot_paths: Mapping[str, str] | None = None,
) -> dict[str, object]:
    settings_payload = _active_pimcore_runtime_settings()
    selected = [str(item) for item in targets] if isinstance(targets, list) else None
    return _render_templates(
        settings_payload,
        product_values,
        values,
        selected,
        mode=mode,
        image_slot_paths=image_slot_paths,
    )


def pimcore_runtime_capabilities() -> dict[str, bool]:
    settings_payload = normalize_pimcore_settings(config.CONFIG.get(PIMCORE_SETTINGS_KEY))
    complete = bool(settings_payload["setup_complete"])
    return {
        "enabled": bool(settings_payload["enabled"] and complete),
        "setup_complete": complete,
    }


def _active_pimcore_runtime_settings() -> dict[str, object]:
    settings_payload = normalize_pimcore_settings(config.CONFIG.get(PIMCORE_SETTINGS_KEY))
    if not settings_payload["setup_complete"]:
        raise ValueError("Integracja Pimcore nie zostala skonfigurowana.")
    if not settings_payload["enabled"]:
        raise ValueError("Integracja Pimcore jest wylaczona.")
    return settings_payload


def find_pimcore_product_by_ean(ean: object) -> dict[str, object]:
    settings_payload = normalize_pimcore_settings(config.CONFIG.get(PIMCORE_SETTINGS_KEY))
    setup_complete = bool(settings_payload["setup_complete"])
    if not settings_payload["enabled"] or not setup_complete:
        return {
            "enabled": False,
            "setup_complete": setup_complete,
            "exists": False,
            "object": None,
            "form_schema": [],
        }
    found = find_product_by_ean(settings_payload, ean)
    return {
        "enabled": True,
        "setup_complete": True,
        "exists": bool(found),
        "object": found,
        "form_schema": _pimcore_runtime_form_schema(settings_payload),
    }


def _safe_pimcore_integration_results(
    value: object,
    settings_payload: dict[str, object],
) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    raw_profiles = source.get("sql_profiles")
    profiles: list[dict[str, object]] = []
    if not isinstance(raw_profiles, list):
        return {"sql_profiles": profiles}
    configured_profiles = normalize_sql_profiles(config.CONFIG)
    trusted_mappings: dict[tuple[str, str], bool] = {}
    for mapping in settings_payload.get("field_mappings", []):
        if not isinstance(mapping, dict):
            continue
        template = mapping.get("value_template")
        if not (
            str(template or "").strip().casefold() == "sql"
            or _template_uses_sql_source(template)
        ):
            continue
        mapping_source = _text(mapping.get("source"))
        profile_id = _text(mapping.get("sql_profile_id")) or DEFAULT_SQL_PROFILE_ID
        if mapping_source:
            trusted_mappings[(mapping_source, profile_id)] = bool(mapping.get("required"))
    for item in raw_profiles[:100]:
        if not isinstance(item, dict):
            continue
        profile_id = _text(item.get("profile_id")) or DEFAULT_SQL_PROFILE_ID
        item_source = _text(item.get("source"))
        trusted_key = (item_source, profile_id)
        if trusted_key not in trusted_mappings:
            continue
        status = _text(item.get("status")).casefold()
        if status not in {"success", "warning", "error"}:
            status = "error"
        try:
            elapsed_ms = max(0, min(int(item.get("elapsed_ms") or 0), 86_400_000))
        except (TypeError, ValueError):
            elapsed_ms = 0
        raw_codes = item.get("warning_codes")
        warning_codes = (
            [
                _text(code)[:100]
                for code in raw_codes[:SQL_PROFILE_WARNING_CODES_MAX]
                if isinstance(code, str) and _text(code)
            ]
            if isinstance(raw_codes, list)
            else []
        )
        filtered = {
            "profile_id": profile_id[:200],
            "source": item_source[:200],
            "status": status,
            "elapsed_ms": elapsed_ms,
            "warning_codes": warning_codes,
            "error": _redact_sql_integration_error(item.get("error"), configured_profiles),
            "required": trusted_mappings[trusted_key],
        }
        safe = redact_pimcore_log_value(filtered)
        profiles.append(safe if isinstance(safe, dict) else filtered)
    return {"sql_profiles": profiles}


def _emit_sql_profile_integration_events(
    integrations: dict[str, object],
    *,
    username: str,
    job_id: str,
    ean: object,
) -> None:
    profiles = integrations.get("sql_profiles")
    if not isinstance(profiles, list):
        return
    for item in profiles:
        if not isinstance(item, dict):
            continue
        status = _text(item.get("status"))
        warning_codes = item.get("warning_codes")
        event_details = {
            **item,
            "warning_count": len(warning_codes) if isinstance(warning_codes, list) else 0,
        }
        emit_event(
            severity=(
                "error"
                if status == "error" and bool(item.get("required"))
                else "info"
            ),
            event_type="integration.sql_profile.completed",
            module="pimcore.runtime",
            stage="sql_profile",
            username=username,
            ean=_text(ean),
            job_id=job_id,
            summary=f"Profil SQL {_text(item.get('profile_id'))}: {status}.",
            details=event_details,
        )


def _emit_pimcore_integration_event(
    result: dict[str, object],
    *,
    status: str,
    operation_type: str,
    username: str,
    job_id: str,
    ean: object,
    elapsed_ms: int,
    failure: BaseException | None = None,
) -> None:
    change_set = result.get("change_set") if isinstance(result.get("change_set"), dict) else {}
    fields = change_set.get("fields") if isinstance(change_set.get("fields"), list) else []
    result_object = result.get("object") if isinstance(result.get("object"), dict) else {}
    event_kwargs: dict[str, object] = {}
    if status == "failed" and failure is not None:
        event_kwargs = {
            "exception": failure,
            "recommended_action": (
                "Otworz historie operacji Pimcore dla tego EAN i sprawdz "
                "zredagowany zalacznik diagnostyczny."
            ),
        }
    emit_event(
        severity="error" if status == "failed" else "info",
        event_type="integration.pimcore.completed",
        module="pimcore.runtime",
        stage=operation_type,
        username=username,
        ean=_text(ean),
        job_id=job_id,
        summary=f"Integracja Pimcore: {status}.",
        details={
            "status": status,
            "operation_type": operation_type,
            "elapsed_ms": max(0, int(elapsed_ms)),
            "field_count": len(fields),
            "object_count": 1 if result_object else 0,
            "object_id": result_object.get("id", ""),
        },
        **event_kwargs,
    )


def create_pimcore_product(
    values: object,
    username: str,
    integration_results: object = None,
) -> dict[str, object]:
    submitted = dict(values) if isinstance(values, dict) else {}
    settings_payload = _active_pimcore_runtime_settings()
    safe_integrations = _safe_pimcore_integration_results(
        integration_results,
        settings_payload,
    )
    operation_id = secrets.token_hex(12)
    started = time.time()
    events: list[dict[str, object]] = []
    result: dict[str, object] = {}
    status = "failed"
    failure: BaseException | None = None

    def emit(stage: str, severity: str, message: str, **details: object) -> None:
        now = time.time()
        event = {
            "sequence": len(events) + 1,
            "timestamp": now,
            "elapsed_ms": int(max(0, now - started) * 1000),
            "stage": stage,
            "severity": severity,
            "message": message,
        }
        event.update(details)
        events.append(event)

    try:
        with pimcore_client_scope(settings_payload, factory=PimcoreClient) as client:
            result = create_product(
                settings_payload,
                submitted,
                client=client,
                emit=emit,
            )
        change_set = result.get("change_set") if isinstance(result.get("change_set"), dict) else {}
        if change_set:
            result["change_set"] = {**change_set, "integrations": safe_integrations}
        status = "duplicate" if result.get("duplicate") else "completed"
        return result
    except Exception as exc:
        status = "failed"
        failure = exc
        emit("finish", "error", str(exc) or exc.__class__.__name__)
        raise
    finally:
        finished = time.time()
        report = redact_pimcore_log_value(
            {
                "operation_id": operation_id,
                "operation_type": "manual_create",
                "username": username,
                "values": submitted,
                "status": status,
                "started_at": started,
                "finished_at": finished,
                "total_ms": int(max(0, finished - started) * 1000),
                "events": events,
                "result": result,
                "integration_results": safe_integrations,
            }
        )
        _persist_pimcore_operation(report)
        _persist_pimcore_submission(report)
        _emit_sql_profile_integration_events(
            safe_integrations,
            username=username,
            job_id=operation_id,
            ean=submitted.get("EAN"),
        )
        _emit_pimcore_integration_event(
            result,
            status=status,
            operation_type="create",
            username=username,
            job_id=operation_id,
            ean=submitted.get("EAN"),
            elapsed_ms=int(max(0, finished - started) * 1000),
            failure=failure,
        )


def get_pimcore_product_for_edit(
    object_id: object,
    username: str = "",
) -> dict[str, object]:
    settings_payload = _active_pimcore_runtime_settings()
    operation_id = secrets.token_hex(12)
    started = time.time()
    result: dict[str, object] = {}
    status = "failed"
    events: list[dict[str, object]] = []
    try:
        with pimcore_client_scope(settings_payload, factory=PimcoreClient) as client:
            result = fetch_product_for_edit(
                settings_payload,
                object_id,
                client=client,
            )
        result["form_schema"] = _pimcore_runtime_form_schema(settings_payload)
        status = "completed"
        return result
    except Exception as exc:
        now = time.time()
        events.append(
            {
                "sequence": 1,
                "timestamp": now,
                "elapsed_ms": int(max(0, now - started) * 1000),
                "stage": "load",
                "severity": "error",
                "message": str(exc) or exc.__class__.__name__,
            }
        )
        raise
    finally:
        finished = time.time()
        if status == "completed":
            result_object = (
                result.get("object") if isinstance(result.get("object"), dict) else {}
            )
            events.append(
                {
                    "sequence": 1,
                    "timestamp": finished,
                    "elapsed_ms": int(max(0, finished - started) * 1000),
                    "stage": "load",
                    "severity": "success",
                    "message": "Wczytano dane produktu Pimcore.",
                    "object_id": result_object.get("id", object_id),
                    "object_path": result_object.get("path", ""),
                }
            )
        values = result.get("values") if isinstance(result.get("values"), dict) else {}
        report = {
            "operation_id": operation_id,
            "operation_type": "manual_load",
            "username": username,
            "values": values,
            "status": status,
            "started_at": started,
            "finished_at": finished,
            "total_ms": int(max(0, finished - started) * 1000),
            "events": events,
            "result": result,
        }
        _persist_pimcore_audit(report)


def update_pimcore_product(
    object_id: object,
    marker: object,
    values: object,
    username: str,
    integration_results: object = None,
) -> dict[str, object]:
    settings_payload = _active_pimcore_runtime_settings()
    submitted = dict(values) if isinstance(values, dict) else {}
    safe_integrations = _safe_pimcore_integration_results(
        integration_results,
        settings_payload,
    )
    operation_id = secrets.token_hex(12)
    started = time.time()
    events: list[dict[str, object]] = []
    result: dict[str, object] = {}
    status = "failed"
    failure: BaseException | None = None

    def emit(stage: str, severity: str, message: str, **details: object) -> None:
        now = time.time()
        event = {
            "sequence": len(events) + 1,
            "timestamp": now,
            "elapsed_ms": int(max(0, now - started) * 1000),
            "stage": stage,
            "severity": severity,
            "message": message,
        }
        event.update(details)
        events.append(event)

    try:
        with pimcore_client_scope(settings_payload, factory=PimcoreClient) as client:
            result = update_product(
                settings_payload,
                object_id,
                str(marker or ""),
                submitted,
                client=client,
                emit=emit,
            )
        change_set = result.get("change_set") if isinstance(result.get("change_set"), dict) else {}
        if change_set:
            result["change_set"] = {**change_set, "integrations": safe_integrations}
        status = "completed"
        return result
    except PimcoreConflictError:
        status = "conflict"
        raise
    except Exception as exc:
        failure = exc
        emit("finish", "error", str(exc) or exc.__class__.__name__)
        raise
    finally:
        finished = time.time()
        report = {
            "operation_id": operation_id,
            "operation_type": "manual_update",
            "username": username,
            "values": submitted,
            "status": status,
            "started_at": started,
            "finished_at": finished,
            "total_ms": int(max(0, finished - started) * 1000),
            "events": events,
            "result": result,
            "integration_results": safe_integrations,
        }
        _persist_pimcore_operation(report)
        _persist_pimcore_submission(report)
        _emit_sql_profile_integration_events(
            safe_integrations,
            username=username,
            job_id=operation_id,
            ean=submitted.get("EAN"),
        )
        _emit_pimcore_integration_event(
            result,
            status=status,
            operation_type="update",
            username=username,
            job_id=operation_id,
            ean=submitted.get("EAN"),
            elapsed_ms=int(max(0, finished - started) * 1000),
            failure=failure,
        )


def pimcore_operation_status(
    operation_id: str,
    after_sequence: int = 0,
) -> dict[str, object] | None:
    return _PIMCORE_OPERATIONS.status(operation_id, after_sequence=after_sequence)


def pimcore_operation_history(
    *,
    operation_type: str = "",
    result: str = "",
    user: str = "",
    query: str = "",
    date_from: float = 0,
    date_to: float = 0,
    limit: int = 200,
) -> dict[str, object]:
    records = []
    for item in reversed(_load_history_records()):
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        operation = (
            details.get("pimcore_operation")
            if isinstance(details.get("pimcore_operation"), dict)
            else None
        )
        if not operation:
            continue
        if operation_type and _text(operation.get("operation_type")) != _text(operation_type):
            continue
        if result and _text(operation.get("status")) != _text(result):
            continue
        if user and _text(operation.get("username")).casefold() != _text(user).casefold():
            continue
        started_at = float(operation.get("started_at") or operation.get("created_at") or 0)
        if date_from and started_at < float(date_from):
            continue
        if date_to and started_at > float(date_to):
            continue
        searchable = json.dumps(operation, ensure_ascii=False).casefold()
        if query and _text(query).casefold() not in searchable:
            continue
        records.append(operation)
        if len(records) >= max(1, min(1000, int(limit or 200))):
            break
    return {"items": records, "count": len(records)}


def _pimcore_export_cell(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _pimcore_submission_export_mappings() -> list[tuple[str, str, str]]:
    settings_payload = normalize_pimcore_settings(config.CONFIG.get(PIMCORE_SETTINGS_KEY))
    sources_by_field = {
        _text(mapping.get("pimcore_field")): _text(mapping.get("source"))
        for mapping in settings_payload.get("field_mappings", [])
        if _text(mapping.get("pimcore_field")) and _text(mapping.get("source"))
    }
    columns: list[tuple[str, str, str]] = []
    for column in settings_payload.get("export_columns", []):
        column_type = _text(column.get("type")).lower()
        header = _text(column.get("header"))
        if column_type == "blank":
            columns.append((header, "", column_type))
            continue
        if column_type != "field":
            continue
        source = sources_by_field.get(_text(column.get("pimcore_field")), "")
        if source:
            columns.append((header, source, column_type))
    return columns


def _pimcore_submission_values(row: dict[str, object]) -> dict[str, object]:
    values = row.get("values") if isinstance(row.get("values"), dict) else {}
    if not values:
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        values = result.get("values") if isinstance(result.get("values"), dict) else {}
    if row.get("ean") and not any(str(key).casefold() == "ean" for key in values):
        values = {**values, "EAN": row.get("ean")}
    return values


def _pimcore_mapping_value(values: dict[str, object], source: str) -> object:
    if source in values:
        return values[source]
    normalized_source = source.casefold()
    for key, value in values.items():
        if str(key).casefold() == normalized_source:
            return value
    return ""


def _deduplicate_pimcore_submission_export_rows(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep one importable record per EAN, preferring the latest success."""

    export_eans = [
        _text(row.get("ean")) or _text(_pimcore_mapping_value(_pimcore_submission_values(row), "ean"))
        for row in rows
    ]
    fallback_by_ean: dict[str, int] = {}
    completed_by_ean: dict[str, int] = {}
    for index, (row, ean) in enumerate(zip(rows, export_eans)):
        normalized_ean = ean.casefold()
        if not normalized_ean:
            continue
        fallback_by_ean.setdefault(normalized_ean, index)
        if _text(row.get("status")).casefold() == "completed":
            completed_by_ean.setdefault(normalized_ean, index)
    selected_indexes = {
        completed_by_ean.get(ean, fallback_index)
        for ean, fallback_index in fallback_by_ean.items()
    }
    return [
        row
        for index, row in enumerate(rows)
        if not export_eans[index] or index in selected_indexes
    ]


def _pimcore_submission_export_table(
    rows: list[dict[str, object]],
) -> tuple[list[str], list[list[object]]]:
    mappings = _pimcore_submission_export_mappings()
    columns = [header for header, _source, _column_type in mappings]
    table_rows: list[list[object]] = []
    for row in rows:
        values = _pimcore_submission_values(row)
        table_rows.append(
            [
                (
                    ""
                    if column_type == "blank"
                    else _pimcore_export_cell(_pimcore_mapping_value(values, source))
                )
                for _header, source, column_type in mappings
            ]
        )
    return columns, table_rows


def export_pimcore_submissions(
    *,
    export_format: str = "json",
    operation_type: str = "",
    status: str = "",
    user: str = "",
    query: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 1000,
) -> dict[str, object]:
    """Export persisted Pimcore SQLite submission records."""

    fmt = _text(export_format).lower() or "json"
    store = _pimcore_submission_store()
    rows = (
        store.query_pimcore_submissions(
            operation_type=operation_type,
            status=status,
            user=user,
            query=query,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        if store is not None
        else []
    )

    rows = _deduplicate_pimcore_submission_export_rows(rows)
    columns, table_rows = _pimcore_submission_export_table(rows)

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(columns)
        for row in table_rows:
            writer.writerow(row)
        return {"format": "csv", "content": output.getvalue(), "count": len(rows)}
    if fmt == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Pimcore"
        sheet.append(columns)
        for row in table_rows:
            sheet.append(row)
        output = io.BytesIO()
        workbook.save(output)
        return {"format": "xlsx", "content": output.getvalue(), "count": len(rows)}
    return {"format": "json", "items": rows, "count": len(rows)}


def _preserve_unsubmitted_config_secrets(payload: dict[str, object]) -> dict[str, set[str]]:
    preserve = {section: set(keys) for section, keys in _CONFIG_SECRET_FIELDS.items()}
    ftp_payload = payload.get("ftp") if isinstance(payload.get("ftp"), dict) else {}
    if _text(ftp_payload.get("user")):
        preserve[H].discard(N)
    if _text(ftp_payload.get("password")):
        preserve[H].discard(M)

    db_payload = payload.get("database") if isinstance(payload.get("database"), dict) else {}
    for section_key, section_name in ((P, "mssql"), (K, "mysql")):
        section_payload = db_payload.get(section_name)
        if not isinstance(section_payload, dict):
            continue
        if _text(section_payload.get("user")):
            preserve[section_key].discard(N)
        if _text(section_payload.get("password")):
            preserve[section_key].discard(M)
    profile_preserve = set()
    submitted_profiles = (
        db_payload.get("profiles")
        if isinstance(db_payload.get("profiles"), list)
        else []
    )
    existing_profiles = {
        _text(item.get("id")): item
        for item in config.CONFIG.get(SQL_PROFILES_KEY, [])
        if isinstance(item, dict) and _text(item.get("id"))
    }
    for item in submitted_profiles:
        if not isinstance(item, dict):
            continue
        profile_id = _text(item.get("id"))
        if profile_id in existing_profiles and (
            not _text(item.get("user")) or not _text(item.get("password"))
        ):
            profile_preserve.add(profile_id)
    if profile_preserve:
        preserve[SQL_PROFILES_KEY] = profile_preserve
    pimcore_payload = payload.get(PIMCORE_SETTINGS_KEY)
    if isinstance(pimcore_payload, dict) and _text(pimcore_payload.get(PIMCORE_API_KEY)):
        preserve[PIMCORE_SETTINGS_KEY].discard(PIMCORE_API_KEY)
    email_payload = payload.get(EMAIL_SETTINGS_KEY)
    if isinstance(email_payload, dict):
        entra_payload = email_payload.get("entra")
        if isinstance(entra_payload, dict) and _text(
            entra_payload.get(EMAIL_CLIENT_SECRET)
        ):
            preserve[EMAIL_SETTINGS_KEY].discard("entra.client_secret")
        smtp_payload = email_payload.get("smtp")
        if isinstance(smtp_payload, dict) and _text(
            smtp_payload.get(EMAIL_SMTP_PASSWORD)
        ):
            preserve[EMAIL_SETTINGS_KEY].discard("smtp.password")
    return {section: keys for section, keys in preserve.items() if keys}


def _merged_sql_profiles_from_settings_payload(
    cfg: dict[str, object],
    db_payload: dict[str, object],
) -> list[dict[str, object]]:
    submitted_profiles = db_payload.get("profiles")
    if not isinstance(submitted_profiles, list):
        return additional_sql_profiles(cfg)
    current_profiles = {
        _text(item.get("id")): item
        for item in cfg.get(SQL_PROFILES_KEY, [])
        if isinstance(item, dict) and _text(item.get("id"))
    }
    merged_profiles = []
    for item in submitted_profiles:
        if not isinstance(item, dict):
            continue
        profile = dict(item)
        profile_id = _text(profile.get("id"))
        if profile_id and profile_id in current_profiles:
            if not _text(profile.get("user")):
                profile["user"] = current_profiles[profile_id].get("user", "")
            if not _text(profile.get("password")):
                profile["password"] = current_profiles[profile_id].get("password", "")
        merged_profiles.append(profile)
    return additional_sql_profiles({SQL_PROFILES_KEY: merged_profiles})


def update_settings(payload: dict[str, object]) -> dict[str, object]:
    """Update editable settings from the web UI."""

    app_payload = payload.get("app") if isinstance(payload.get("app"), dict) else {}
    ftp_payload = payload.get("ftp") if isinstance(payload.get("ftp"), dict) else {}
    db_payload = payload.get("database") if isinstance(payload.get("database"), dict) else {}
    processing_payload = payload.get("processing") if isinstance(payload.get("processing"), dict) else {}
    resource_monitor_payload = (
        payload.get(RESOURCE_MONITOR_SETTINGS_KEY)
        if isinstance(payload.get(RESOURCE_MONITOR_SETTINGS_KEY), dict)
        else {}
    )
    security_payload = payload.get("security") if isinstance(payload.get("security"), dict) else {}
    web_display_payload = payload.get(WEB_DISPLAY_SETTINGS_KEY)
    translation_payload = payload.get(TRANSLATION_SETTINGS_KEY)
    pimcore_payload = payload.get(PIMCORE_SETTINGS_KEY)
    ocr_payload = payload.get(OCR_SETTINGS_KEY)
    email_payload = payload.get(EMAIL_SETTINGS_KEY)
    previous_entra_identity = ("", "")
    updated_entra_identity = ("", "")
    entra_configuration_changed = False
    if isinstance(web_display_payload, dict) and "time_zone" in web_display_payload:
        submitted_time_zone = _text(web_display_payload.get("time_zone"))
        if submitted_time_zone not in config.available_display_time_zones():
            raise ValueError("Nieprawidlowa strefa czasowa.")
    if isinstance(email_payload, dict):
        validate_email_rule_recipients(email_payload)
    backup_payload = payload.get("sqlite_backup") if isinstance(payload.get("sqlite_backup"), dict) else None
    slots_payload = payload.get("slots") if isinstance(payload.get("slots"), list) else None
    runtime_reloaded = False
    translation_settings_changed = False

    if "image_dir" in app_payload:
        runtime_reloaded = _apply_base_dir_from_web(app_payload.get("image_dir")) or runtime_reloaded
    elif "base_dir" in app_payload:
        runtime_reloaded = _apply_base_dir_from_web(app_payload.get("base_dir")) or runtime_reloaded
    storage_updates: dict[str, object] = {}
    for payload_key, settings_key in {
        "data_mode": storage_settings.DATA_MODE_KEY,
        "database_location_mode": storage_settings.DATABASE_LOCATION_MODE_KEY,
        "database_path": storage_settings.DATABASE_PATH_KEY,
    }.items():
        if payload_key in app_payload:
            storage_updates[settings_key] = app_payload.get(payload_key)
    if storage_updates:
        storage_settings.save_bootstrap_settings(storage_updates)
        data_store.reset_active_store_cache()
        runtime_reloaded = True
    if backup_payload is not None:
        storage_settings.save_backup_settings(backup_payload)
    if APP_SECRET_KEY in security_payload:
        runtime_reloaded = _apply_app_secret_from_web(security_payload.get(APP_SECRET_KEY)) or runtime_reloaded
    elif APP_SECRET_KEY in app_payload:
        runtime_reloaded = _apply_app_secret_from_web(app_payload.get(APP_SECRET_KEY)) or runtime_reloaded
    if runtime_reloaded:
        config.initialize_config(interactive=False)
    cfg = config.CONFIG

    if LOCAL_FILE_INDEX_KEY in app_payload:
        cfg[LOCAL_FILE_INDEX_KEY] = bool(app_payload.get(LOCAL_FILE_INDEX_KEY))
    if AUTO_CONTENT_FIT_KEY in app_payload:
        cfg[AUTO_CONTENT_FIT_KEY] = bool(app_payload.get(AUTO_CONTENT_FIT_KEY))
    if COLOR_FIELD_LABELS_KEY in app_payload and isinstance(
        app_payload.get(COLOR_FIELD_LABELS_KEY), dict
    ):
        cfg[COLOR_FIELD_LABELS_KEY] = {
            key: _text(value)
            for key, value in app_payload[COLOR_FIELD_LABELS_KEY].items()
            if key in {"color1", "color2", "color3"} and _text(value)
        }
    if PRODUCT_FIELDS_KEY in app_payload:
        cfg[PRODUCT_FIELDS_KEY] = normalize_product_fields(
            app_payload.get(PRODUCT_FIELDS_KEY),
        )

    if processing_payload:
        merged_processing = dict(cfg.get(PROCESSING_SETTINGS_KEY, {}) or {})
        merged_processing.update(processing_payload)
        cfg[PROCESSING_SETTINGS_KEY] = config._normalize_processing_settings(merged_processing)

    if resource_monitor_payload:
        merged_resource_monitor = config._normalize_resource_monitor_settings(
            cfg.get(RESOURCE_MONITOR_SETTINGS_KEY, {})
        )
        merged_resource_monitor.update(resource_monitor_payload)
        cfg[RESOURCE_MONITOR_SETTINGS_KEY] = config._normalize_resource_monitor_settings(
            merged_resource_monitor
        )

    if security_payload:
        merged_security = dict(cfg.get(SECURITY_SETTINGS_KEY, {}) or {})
        merged_security.update(security_payload)
        cfg[SECURITY_SETTINGS_KEY] = config._normalize_security_settings(merged_security)

    if isinstance(web_display_payload, dict):
        merged_web_display = config.normalize_web_display_settings(
            cfg.get(WEB_DISPLAY_SETTINGS_KEY, {})
        )
        merged_web_display.update(web_display_payload)
        cfg[WEB_DISPLAY_SETTINGS_KEY] = config.normalize_web_display_settings(
            merged_web_display
        )

    if isinstance(translation_payload, dict):
        current_translation = dict(cfg.get(TRANSLATION_SETTINGS_KEY, {}) or {})
        merged_translation = dict(current_translation)
        merged_translation.update(translation_payload)
        if not _text(translation_payload.get(TRANSLATION_API_KEY)):
            merged_translation[TRANSLATION_API_KEY] = current_translation.get(
                TRANSLATION_API_KEY,
                "",
            )
        cfg[TRANSLATION_SETTINGS_KEY] = merged_translation
        translation_settings_changed = True

    if isinstance(pimcore_payload, dict):
        if "field_mappings" in pimcore_payload:
            profile_cfg = dict(cfg)
            if isinstance(db_payload.get("profiles"), list):
                profile_cfg[SQL_PROFILES_KEY] = _merged_sql_profiles_from_settings_payload(
                    cfg,
                    db_payload,
                )
            issues = field_mapping_issues(
                pimcore_payload.get("field_mappings"),
                sql_profiles=normalize_sql_profiles(profile_cfg),
            )
            if issues:
                raise ValueError(" ".join(issues))
        current = normalize_pimcore_settings(cfg.get(PIMCORE_SETTINGS_KEY))
        merged = dict(current)
        merged.update(pimcore_payload)
        if not _text(pimcore_payload.get(PIMCORE_API_KEY)):
            merged[PIMCORE_API_KEY] = current[PIMCORE_API_KEY]
        cfg[PIMCORE_SETTINGS_KEY] = normalize_pimcore_settings(merged)

    if isinstance(ocr_payload, dict):
        current_ocr = normalize_ocr_settings(cfg.get(OCR_SETTINGS_KEY, {}))
        merged_ocr = dict(current_ocr)
        merged_ocr.update(ocr_payload)
        cfg[OCR_SETTINGS_KEY] = normalize_ocr_settings(merged_ocr)

    if isinstance(email_payload, dict):
        current_email = normalize_email_settings(cfg.get(EMAIL_SETTINGS_KEY))
        current_entra = current_email["entra"]
        previous_entra_identity = (
            _text(current_entra.get("tenant_id")),
            _text(current_entra.get("client_id")),
        )
        merged_email = dict(current_email)
        merged_email.update(email_payload)
        for channel, secret_key in (
            ("entra", EMAIL_CLIENT_SECRET),
            ("smtp", EMAIL_SMTP_PASSWORD),
        ):
            current_channel = current_email[channel]
            submitted_channel = email_payload.get(channel)
            if isinstance(submitted_channel, dict):
                merged_channel = dict(current_channel)
                merged_channel.update(submitted_channel)
                if not _text(submitted_channel.get(secret_key)):
                    merged_channel[secret_key] = current_channel[secret_key]
                merged_email[channel] = merged_channel
        cfg[EMAIL_SETTINGS_KEY] = normalize_email_settings(merged_email)
        updated_entra = cfg[EMAIL_SETTINGS_KEY]["entra"]
        updated_entra_identity = (
            _text(updated_entra.get("tenant_id")),
            _text(updated_entra.get("client_id")),
        )
        entra_configuration_changed = any(
            _text(current_entra.get(key)) != _text(updated_entra.get(key))
            for key in ("tenant_id", "client_id", EMAIL_CLIENT_SECRET)
        )

    if ftp_payload:
        ftp = cfg.setdefault(H, {})
        for key, cfg_key in {
            "host": v,
            "path": m,
            "user": N,
            "password": M,
        }.items():
            if key in ftp_payload:
                value = _text(ftp_payload.get(key))
                if key in {"user", "password"} and not value:
                    continue
                ftp[cfg_key] = value
        if "port" in ftp_payload:
            try:
                ftp[r] = int(ftp_payload.get("port") or 21)
            except ValueError:
                ftp[r] = 21
        if "enabled" in ftp_payload:
            cfg[ft] = bool(ftp_payload.get("enabled"))

    if db_payload:
        db_type = _text(db_payload.get("type")).lower()
        if db_type in {"mysql", "mssql"}:
            cfg[p] = K if db_type == "mysql" else "mssql"
        if "sql_update_enabled" in db_payload:
            cfg[u] = bool(db_payload.get("sql_update_enabled"))
        if "query" in db_payload:
            cfg[w] = _text(db_payload.get("query"))
        for section_key, section_name in ((P, "mssql"), (K, "mysql")):
            section_payload = db_payload.get(section_name)
            if not isinstance(section_payload, dict):
                continue
            section = cfg.setdefault(section_key, {})
            for key, cfg_key in {
                "server": c,
                "database": b,
                "user": N,
                "password": M,
            }.items():
                if key in section_payload:
                    value = _text(section_payload.get(key))
                    if key in {"user", "password"} and not value:
                        continue
                    section[cfg_key] = value
        if isinstance(db_payload.get("profiles"), list):
            cfg[SQL_PROFILES_KEY] = _merged_sql_profiles_from_settings_payload(
                cfg,
                db_payload,
            )

    if slots_payload is not None:
        slot_defs, _slot_issues = normalize_slot_definitions(slots_payload)
        submitted_map = {
            _text(slot.get("prefix")): _text(slot.get("sql_column"))
            for slot in slots_payload
            if isinstance(slot, dict) and _text(slot.get("prefix"))
        }
        merged_map = dict(cfg.get(SQL_COLUMN_MAP_KEY, {}) or {})
        merged_map.update({key: value for key, value in submitted_map.items() if value})
        sql_map, _map_issues = normalize_sql_column_map(merged_map, slot_defs)
        cfg[SLOT_DEFS_KEY] = slot_defs
        cfg[SQL_COLUMN_MAP_KEY] = sql_map

    similar_payload = payload.get(SIMILAR_FILE_DETECTION_KEY)
    if isinstance(similar_payload, dict):
        cfg[SIMILAR_FILE_DETECTION_KEY] = normalize_similar_file_settings(
            similar_payload,
            cfg.get(SLOT_DEFS_KEY, []),
        )

    save_config(cfg, preserve_secrets=_preserve_unsubmitted_config_secrets(payload))
    config.initialize_config(interactive=False)
    if translation_settings_changed:
        clear_translation_cache()
    if entra_configuration_changed:
        try:
            from .entra_secret_monitor import refresh_entra_secret_status
            from .observability import observability_store

            store = observability_store()
            for tenant_id, client_id in {
                previous_entra_identity,
                updated_entra_identity,
            }:
                if tenant_id and client_id:
                    store.clear_entra_secret_status(tenant_id, client_id)
            refresh_entra_secret_status(force=True)
        except Exception:
            # A configuration save is valid even when Graph cannot be reached.
            pass
    return settings_snapshot()


def settings_snapshot() -> dict[str, object]:
    """Return non-secret settings for the web settings view."""

    cfg = config.CONFIG
    storage = storage_settings.storage_summary()
    ftp = cfg.get(H, {})
    sql = cfg.get(P, {})
    mysql_cfg = cfg.get(K, {})
    slot_defs = cfg.get(SLOT_DEFS_KEY, []) or []
    sql_map = cfg.get(SQL_COLUMN_MAP_KEY, {}) or {}
    pimcore = normalize_pimcore_settings(cfg.get(PIMCORE_SETTINGS_KEY))
    pimcore_public = {
        key: value for key, value in pimcore.items() if key != PIMCORE_API_KEY
    }
    pimcore_public["api_key_set"] = bool(_text(pimcore[PIMCORE_API_KEY]))
    return {
        "version": get_display_version(),
        "windows_admin": is_windows_admin_process(),
        "base_dir": settings.AC,
        "image_dir": storage.get("image_dir", settings.AC),
        "data_mode": storage.get("data_mode", "legacy"),
        "database_location_mode": storage.get("database_location_mode", "image_dir"),
        "database_path": storage.get("database_path", ""),
        "sqlite_backup": storage_settings.load_backup_settings(),
        "sqlite_backup_dir": storage_settings.resolve_backup_dir(),
        "processed_dir": settings.l,
        "config_path": config.CONFIG_PATH,
        "local_settings_path": str(_local_settings_path()),
        "runtime_warning": settings.BASE_DIR_OVERRIDE_WARNING,
        "auth_enabled": True,
        "users": load_users(),
        "app_secret_set": bool(_text(common.APP_SECRET)),
        "local_file_index": bool(cfg.get(LOCAL_FILE_INDEX_KEY, True)),
        "auto_content_fit": bool(cfg.get(AUTO_CONTENT_FIT_KEY, False)),
        SIMILAR_FILE_DETECTION_KEY: normalize_similar_file_settings(
            cfg.get(SIMILAR_FILE_DETECTION_KEY),
            slot_defs,
        ),
        "processing": config._normalize_processing_settings(
            cfg.get(PROCESSING_SETTINGS_KEY, {})
        ),
        RESOURCE_MONITOR_SETTINGS_KEY: config._normalize_resource_monitor_settings(
            cfg.get(RESOURCE_MONITOR_SETTINGS_KEY, {})
        ),
        "security": config._normalize_security_settings(
            cfg.get(SECURITY_SETTINGS_KEY, {})
        ),
        WEB_DISPLAY_SETTINGS_KEY: config.normalize_web_display_settings(
            cfg.get(WEB_DISPLAY_SETTINGS_KEY, {})
        ),
        "processing_formats": available_convert_formats(),
        "ftp": {
            "host": _text(ftp.get(v)),
            "port": ftp.get(r),
            "path": _text(ftp.get(m)),
            "user_set": bool(_text(ftp.get(N))),
            "password_set": bool(_text(ftp.get(M))),
            "enabled": bool(cfg.get(ft, True)),
        },
        "database": {
            "type": _text(cfg.get(p)),
            "sql_update_enabled": bool(cfg.get(u, True)),
            "query": _text(cfg.get(w)),
            "mssql": {
                "server": _text(sql.get(c)),
                "database": _text(sql.get(b)),
                "user_set": bool(_text(sql.get(N))),
                "password_set": bool(_text(sql.get(M))),
            },
            "mysql": {
                "server": _text(mysql_cfg.get(c)),
                "database": _text(mysql_cfg.get(b)),
                "user_set": bool(_text(mysql_cfg.get(N))),
                "password_set": bool(_text(mysql_cfg.get(M))),
            },
            "profiles": public_sql_profiles(additional_sql_profiles(cfg)),
        },
        "slot_count": len(slot_defs),
        "sql_map_count": len(sql_map),
        "sql_available_columns_count": len(cfg.get(SQL_AVAILABLE_COLUMNS_KEY, []) or []),
        "sql_available_columns": cfg.get(SQL_AVAILABLE_COLUMNS_KEY, []) or [],
        "color_field_labels": cfg.get(COLOR_FIELD_LABELS_KEY, {}) or {},
        "product_fields": normalize_product_fields(
            cfg.get(PRODUCT_FIELDS_KEY),
            legacy_color_labels=cfg.get(COLOR_FIELD_LABELS_KEY),
        ),
        "pimcore": pimcore_public,
        OCR_SETTINGS_KEY: normalize_ocr_settings(cfg.get(OCR_SETTINGS_KEY, {})),
        EMAIL_SETTINGS_KEY: public_email_settings(cfg.get(EMAIL_SETTINGS_KEY)),
        "slots": [
            {
                "prefix": slot.get("prefix", ""),
                "label": slot.get("label", ""),
                "filename_label": slot.get("filename_label", slot.get("label", "")),
                "filename_label_explicit": bool(slot.get("filename_label")),
                "sql_column": sql_map.get(slot.get("prefix", ""), ""),
            }
            for slot in slot_defs
        ],
    }


SIMILAR_LOOKUP_CACHE_TTL_SECONDS = 10.0
SIMILAR_LOOKUP_CACHE_MAX_ITEMS = 32
_SIMILAR_LOOKUP_CACHE: dict[tuple[str, ...], tuple[float, tuple[SimilarFileCandidate, ...]]] = {}
_SIMILAR_LOOKUP_IN_FLIGHT: dict[tuple[str, ...], threading.Event] = {}
_SIMILAR_LOOKUP_LOCK = threading.Lock()


def _normalized_similar_lookup_text(value: object) -> str:
    return unicodedata.normalize("NFC", str(value or "").strip()).casefold()


def _similar_lookup_key(
    normalized_payload: dict[str, object], occupied_prefixes: object
) -> tuple[str, ...]:
    prefixes = occupied_prefixes if isinstance(occupied_prefixes, (list, tuple, set)) else ()
    return (
        *(
            _normalized_similar_lookup_text(normalized_payload.get(name))
            for name in ("name", "type_name", "model", "color1", "color2", "color3", "extra")
        ),
        *sorted(normalize_slot_prefix(prefix) for prefix in prefixes),
    )


def reset_similar_file_lookup_cache() -> None:
    """Clear web similar-file lookup state for test isolation."""

    with _SIMILAR_LOOKUP_LOCK:
        _SIMILAR_LOOKUP_CACHE.clear()
        _SIMILAR_LOOKUP_IN_FLIGHT.clear()


def _log_similar_lookup(key: tuple[str, ...], started_at: float, count: int) -> None:
    fingerprint = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:12]
    elapsed_ms = round((time.monotonic() - started_at) * 1000)
    log_info(
        f"similar_file_lookup key={fingerprint} elapsed_ms={elapsed_ms} result_count={count}"
    )


def find_web_similar_file_candidates(
    product_payload: dict[str, object],
) -> list[SimilarFileCandidate]:
    """Find local suggestions for a web product without external side effects."""

    started_at = time.monotonic()
    field_settings = normalize_product_fields(
        config.CONFIG.get(PRODUCT_FIELDS_KEY),
        legacy_color_labels=config.CONFIG.get(COLOR_FIELD_LABELS_KEY),
    )
    normalized_payload = effective_product_values(product_payload, field_settings)
    occupied_prefixes = product_payload.get("occupied_prefixes", ())
    if not isinstance(occupied_prefixes, (list, tuple, set)):
        occupied_prefixes = ()
    key = _similar_lookup_key(normalized_payload, occupied_prefixes)

    while True:
        cached_result: list[SimilarFileCandidate] | None = None
        with _SIMILAR_LOOKUP_LOCK:
            now = time.monotonic()
            cached = _SIMILAR_LOOKUP_CACHE.get(key)
            if cached is not None and now - cached[0] < SIMILAR_LOOKUP_CACHE_TTL_SECONDS:
                cached_result = list(cached[1])
            else:
                _SIMILAR_LOOKUP_CACHE.pop(key, None)
                event = _SIMILAR_LOOKUP_IN_FLIGHT.get(key)
                if event is None:
                    event = threading.Event()
                    _SIMILAR_LOOKUP_IN_FLIGHT[key] = event
                    break
        if cached_result is not None:
            _log_similar_lookup(key, started_at, len(cached_result))
            return cached_result
        event.wait()

    try:
        result = tuple(
            find_similar_file_candidates(
                settings.l,
                normalized_payload,
                normalize_slot_definitions(config.CONFIG.get(SLOT_DEFS_KEY))[0],
                config.CONFIG.get(SIMILAR_FILE_DETECTION_KEY),
                file_index=_get_file_index(start=False),
                occupied_prefixes=occupied_prefixes,
            )
        )
    except Exception:
        with _SIMILAR_LOOKUP_LOCK:
            _SIMILAR_LOOKUP_IN_FLIGHT.pop(key, None)
            event.set()
        raise

    with _SIMILAR_LOOKUP_LOCK:
        now = time.monotonic()
        expired = [
            cached_key
            for cached_key, (cached_at, _cached_result) in _SIMILAR_LOOKUP_CACHE.items()
            if now - cached_at >= SIMILAR_LOOKUP_CACHE_TTL_SECONDS
        ]
        for cached_key in expired:
            _SIMILAR_LOOKUP_CACHE.pop(cached_key, None)
        while len(_SIMILAR_LOOKUP_CACHE) >= SIMILAR_LOOKUP_CACHE_MAX_ITEMS:
            _SIMILAR_LOOKUP_CACHE.pop(next(iter(_SIMILAR_LOOKUP_CACHE)))
        _SIMILAR_LOOKUP_CACHE[key] = (now, result)
        _SIMILAR_LOOKUP_IN_FLIGHT.pop(key, None)
        event.set()

    response = list(result)
    _log_similar_lookup(key, started_at, len(response))
    return response


def settings_secret_values() -> dict[str, object]:
    """Return decrypted settings secrets for the explicit admin reveal action."""

    cfg = config.CONFIG
    ftp = cfg.get(H, {}) if isinstance(cfg.get(H), dict) else {}
    mssql_cfg = cfg.get(P, {}) if isinstance(cfg.get(P), dict) else {}
    mysql_cfg = cfg.get(K, {}) if isinstance(cfg.get(K), dict) else {}
    profiles = {
        profile["id"]: {
            "user": _text(profile.get("user")),
            "password": _text(profile.get("password")),
        }
        for profile in additional_sql_profiles(cfg)
    }
    return {
        "app_secret": _text(common.APP_SECRET),
        "ftp": {
            "user": _text(ftp.get(N)),
            "password": _text(ftp.get(M)),
        },
        "database": {
            "mssql": {
                "user": _text(mssql_cfg.get(N)),
                "password": _text(mssql_cfg.get(M)),
            },
            "mysql": {
                "user": _text(mysql_cfg.get(N)),
                "password": _text(mysql_cfg.get(M)),
            },
            "profiles": profiles,
        },
    }


def test_local_paths() -> dict[str, object]:
    """Check backend access to local working folders."""

    targets = {
        "base_dir": settings.AC,
        "processed_dir": settings.l,
        "config_dir": os.path.dirname(config.CONFIG_PATH),
    }
    checks = []
    for key, path in targets.items():
        check = {"key": key, "path": path, "exists": os.path.isdir(path), "read": False, "write": False, "error": ""}
        try:
            os.makedirs(path, exist_ok=True)
            os.listdir(path)
            check["exists"] = True
            check["read"] = True
            fd, temp_path = tempfile.mkstemp(prefix="picsyncra_web_check_", suffix=".tmp", dir=path)
            os.close(fd)
            os.remove(temp_path)
            check["write"] = True
        except Exception as exc:
            log_error(f"Local path diagnostics failed ({type(exc).__name__}).")
            check["error"] = "Nie udalo sie sprawdzic folderu lokalnego."
        checks.append(check)
    return {"ok": all(item["read"] and item["write"] for item in checks), "checks": checks}


def test_ftp_connection() -> dict[str, object]:
    """Check FTP connectivity using current config."""

    if not bool(config.CONFIG.get(ft, True)):
        return {"ok": False, "message": "Aktualizacja FTP jest wylaczona."}
    try:
        files = list_remote_files_for_ean(config.CONFIG.get(H, {}), "")
        return {"ok": True, "message": "Polaczenie FTP dziala.", "sample_count": len(files)}
    except Exception as exc:
        log_error(f"FTP diagnostics failed ({type(exc).__name__}).")
        return {
            "ok": False,
            "message": "Nie udalo sie polaczyc z FTP. Sprawdz konfiguracje i log serwera.",
        }


def test_sql_connection() -> dict[str, object]:
    """Check database connectivity using current config."""

    try:
        conn = connect_db()
        try:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return {"ok": True, "message": "Polaczenie SQL dziala."}
    except Exception as exc:
        log_error(f"SQL diagnostics failed ({type(exc).__name__}).")
        return {
            "ok": False,
            "message": "Nie udalo sie polaczyc z SQL. Sprawdz konfiguracje i log serwera.",
        }


def test_sql_profile_connection(profile_id: object) -> dict[str, object]:
    """Check database connectivity using one configured SQL profile."""

    try:
        profile = resolve_sql_profile(normalize_sql_profiles(config.CONFIG), profile_id)
    except KeyError:
        return {"ok": False, "message": "Nieznany profil SQL."}
    if profile.get("id") == "default":
        return test_sql_connection()

    conn = None
    cursor = None
    try:
        conn = connect_profile(profile)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        return {"ok": True, "message": "Polaczenie SQL dziala."}
    except Exception as exc:
        log_error(f"SQL profile diagnostics failed ({type(exc).__name__}).")
        return {
            "ok": False,
            "message": "Nie udalo sie polaczyc z SQL. Sprawdz konfiguracje i log serwera.",
        }
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def find_product_photos(
    entry_payload: dict[str, object],
    *,
    include_local: bool = True,
    include_ftp: bool = True,
    include_sql: bool = True,
) -> list[dict[str, object]]:
    """Find processed photos and presence flags for a saved web entry."""

    field_settings = normalize_product_fields(
        config.CONFIG.get(PRODUCT_FIELDS_KEY),
        legacy_color_labels=config.CONFIG.get(COLOR_FIELD_LABELS_KEY),
    )
    entry_payload = effective_product_values(entry_payload, field_settings)
    entry = _entry_from_record(
        {
            PRODUCT_ID_HEADER: entry_payload.get("product_id"),
            EAN_HEADER: entry_payload.get("ean"),
            NAME_HEADER: entry_payload.get("name"),
            TYPE_HEADER: entry_payload.get("type_name"),
            MODEL_HEADER: entry_payload.get("model"),
            COLOR1_HEADER: entry_payload.get("color1"),
            COLOR2_HEADER: entry_payload.get("color2"),
            COLOR3_HEADER: entry_payload.get("color3"),
            EXTRA_HEADER: entry_payload.get("extra"),
        }
    )
    product_dir = build_product_directory(
        settings.l,
        entry.name,
        entry.type_name,
        entry.model,
        [entry.color1, entry.color2, entry.color3],
        entry.extra,
    )
    target_ean = _norm(entry.ean)
    results_by_prefix: dict[str, dict[str, object]] = {}
    file_names: list[str] = []
    if include_local:
        seen_files = set()
        index = _get_file_index(start=True)
        if index is not None and index.has_snapshot():
            indexed = index.get_product_files(
                entry.name,
                entry.type_name,
                entry.model,
                [entry.color1, entry.color2, entry.color3],
                entry.extra,
            )
            if indexed is not None:
                for filename in indexed:
                    if filename not in seen_files:
                        file_names.append(filename)
                        seen_files.add(filename)
        if os.path.isdir(product_dir):
            for filename in os.listdir(product_dir):
                if filename not in seen_files:
                    file_names.append(filename)
                    seen_files.add(filename)
    if include_local and file_names:
        for filename in file_names:
            path = os.path.join(product_dir, filename)
            if not os.path.isfile(path):
                continue
            parsed = parse_slot_filename(filename)
            if not parsed:
                continue
            if target_ean and _norm(parsed.ean) != target_ean:
                continue
            ext = os.path.splitext(filename)[1].lower()
            results_by_prefix[parsed.normalized_label] = {
                "ean": entry.ean,
                "prefix": parsed.normalized_label,
                "filename": filename,
                "path": path,
                "is_image": ext in IMAGE_PREVIEW_EXTENSIONS,
                "local": True,
                "ftp": False,
                "sql": False,
                "ftp_path": "",
                "ftp_filename": "",
                "sql_value": "",
                "sql_checked": False,
            }
    ean = entry.ean
    if include_ftp and ean and bool(config.CONFIG.get(ft, True)):
        try:
            remote = list_remote_files_for_ean(config.CONFIG.get(H, {}), ean)
            for prefix, filename in remote.items():
                item = results_by_prefix.setdefault(
                    prefix,
                    {
                        "ean": entry.ean,
                        "prefix": prefix,
                        "filename": "",
                        "path": "",
                        "is_image": False,
                        "local": False,
                        "sql": False,
                        "sql_value": "",
                        "sql_checked": False,
                    },
                )
                item["ftp"] = True
                item["ean"] = entry.ean
                item["ftp_filename"] = filename
                item["ftp_path"] = ""
                ext = os.path.splitext(filename)[1].lower()
                item["is_image"] = bool(item.get("is_image")) or ext in IMAGE_PREVIEW_EXTENSIONS
        except Exception:
            pass
    if include_sql and ean and should_check_presence(config.CONFIG):
        try:
            context = extract_presence_context(config.CONFIG, ean)
            if context:
                table, where_clause = context
                slots = config.CONFIG.get(SLOT_DEFS_KEY, []) or []
                sql_map = config.CONFIG.get(SQL_COLUMN_MAP_KEY, {}) or {}
                columns = [
                    (slot.get("prefix", ""), sql_map.get(slot.get("prefix", ""), ""), slot.get("label", ""))
                    for slot in slots
                    if sql_map.get(slot.get("prefix", ""), "")
                ]
                presence, values = query_presence_details(
                    columns,
                    table,
                    where_clause,
                    config.CONFIG.get(p, K),
                )
                for prefix, present in presence.items():
                    if present is None:
                        continue
                    item = results_by_prefix.setdefault(
                        prefix,
                        {
                            "ean": entry.ean,
                            "prefix": prefix,
                            "filename": "",
                            "path": "",
                            "is_image": False,
                            "local": False,
                            "ftp": False,
                            "ftp_path": "",
                            "ftp_filename": "",
                            "sql_checked": False,
                        },
                    )
                    if not present and not (item.get("local") or item.get("ftp")):
                        results_by_prefix.pop(prefix, None)
                        continue
                    item["sql"] = bool(present)
                    item["sql_checked"] = True
                    item["ean"] = entry.ean
                    item["sql_value"] = values.get(prefix, "")
        except Exception:
            pass
    return sorted(results_by_prefix.values(), key=lambda item: str(item.get("prefix", "")))
