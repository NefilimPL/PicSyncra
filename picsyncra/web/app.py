"""FastAPI LAN backend for the browser upload panel."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unicodedata
import warnings
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlsplit
import zipfile

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .. import brand, common, config, data_store, encryption, settings, sqlite_backup, storage_settings
from ..bootstrap import initialize_application_runtime
from ..common import (
    AUTO_CONTENT_FIT_KEY,
    COLOR_FIELD_LABELS_KEY,
    H,
    K,
    M,
    N,
    P,
    PROCESSING_SETTINGS_KEY,
    RESOURCE_MONITOR_SETTINGS_KEY,
    SECURITY_SETTINGS_KEY,
    SQL_AVAILABLE_COLUMNS_KEY,
    SQL_COLUMN_MAP_KEY,
    TRANSLATION_API_KEY,
    TRANSLATION_SETTINGS_KEY,
    WEB_DISPLAY_SETTINGS_KEY,
    ft,
    p,
    u,
    w,
)
from ..database import connect_db
from ..github_status import github_repository_status
from ..history_changes import history_change_set
from ..image_utils import fit_image_to_content
from ..services.image_dimensions import (
    ImageOcrDiagnostics,
    OcrDiagnosticCandidate,
    analyze_image_values,
    image_ocr_runtime_info,
)
from ..services.ocr_cache import (
    enqueue_ocr_crop_jobs,
    enqueue_ocr_fast_image_job,
    image_content_hash,
)
from ..services.module_build_status import (
    load_packaged_module_manifest,
    module_status_snapshot,
)
from ..services.ocr_slot_queue import process_slot_ocr_queue_job
from ..services.ocr_queue import OcrQueueLease, OcrQueueScheduler
from ..services.ocr_worker import OcrQueueWorker
from ..services.ocr_worker_process import OcrWorkerProcess
from ..services.ocr_execution_service import OcrExecutionService
from ..services.ocr_progress import OcrProgressRegistry
from ..services.ocr_resource_policy import ResourceTelemetry
from ..services.ocr_values import (
    comparison_key,
    normalize_entered_ocr_value,
    ocr_values_match,
)
from ..ocr_settings import OCR_SETTINGS_KEY, normalize_ocr_settings
from ..logging_utils import log_error
from ..email_settings import EMAIL_SETTINGS_KEY
from ..entra_secret_monitor import entra_secret_status, refresh_entra_secret_status
from ..observability import (
    SEVERITIES,
    emit_event,
    observability_store,
    prune_live_events,
    record_job,
)
from ..redaction import redact_sensitive_value, sanitize_free_text
from ..resource_monitor import ResourceMonitor
from ..notification_service import (
    notification_worker_health,
    send_test_message,
    send_test_notification_suite,
    start_notification_worker,
    stop_notification_worker,
)
from ..product_fields import PRODUCT_FIELDS_KEY, normalize_product_fields
from ..pimcore_templates import TemplateError
from ..file_tokens import FileTokenRegistry
from ..path_security import PathSecurityError, build_child_path, resolve_path_within_roots
from ..services.ftp_service import sync_remote_files
from ..services.pimcore_service import PimcoreApiError, PimcoreConflictError
from ..services.photo_sql_batch import build_photo_sql_batch
from ..services.sql_service import detect_available_columns, extract_presence_context
from ..sqlite_maintenance import repair_sqlite_database
from ..workflow_utils import build_product_directory, parse_slot_filename, sanitize_path_segment
from . import upload_staging
from .active_clients import ActiveClientRegistry
from .process_progress import ProcessProgressGate
from .process_api import ProcessApiDependencies, build_process_router
from .process_models import (
    ProcessFormSnapshot as _ProcessFormSnapshot,
    QueuedUploadFile as _QueuedUploadFile,
)
from .runtime_api import RuntimeApiDependencies, build_runtime_router
from .process_queue import (
    ProcessQueueService,
    QueueReservation,
)
from .runtime_status import RuntimeStatusService
from .upload_staging import (
    UploadSizeLimitExceeded,
    UploadStagingService,
    cleanup_expired_job_directories,
    cleanup_job_directory,
)
from ..web_image_import import (
    ImageImportError,
    discover_image_candidates,
    download_image_bytes,
    fetch_page_html,
    filename_from_url,
)
from ..web_workflow import (
    WebProductForm,
    WebUploadedSlot,
    effective_product_form,
    preprocess_cached_upload,
    process_web_uploads,
    normalized_product_payload,
    processing_options_from_config,
    slot_definitions_from_config,
    validate_product_form,
)
from ..web_data import (
    add_list_value,
    add_user,
    authenticate_login,
    authenticate_user,
    cache_ftp_preview,
    cleanup_web_ftp_cache,
    complete_pimcore_setup,
    discover_pimcore_classes,
    discover_pimcore_fields,
    discover_pimcore_folders,
    export_pimcore_submissions,
    field_suggestions,
    find_web_similar_file_candidates,
    find_entry_by_identity,
    find_pimcore_product_by_ean,
    find_user,
    find_user_by_id,
    find_product_photos,
    file_index_status,
    get_pimcore_product_for_edit,
    history_group_snapshot,
    invalidate_ftp_preview_cache,
    load_web_data,
    load_users,
    mark_browser_extension_token_issued,
    mark_browser_extension_token_used,
    history_snapshot,
    ListValueInUseError,
    parse_pimcore_csv_headers,
    pimcore_test_sample,
    pimcore_operation_history,
    pimcore_operation_status,
    pimcore_runtime_capabilities,
    refresh_file_index,
    render_saved_pimcore_templates,
    remove_list_value,
    record_history,
    save_web_entry,
    search_entries,
    create_pimcore_product,
    preview_pimcore_template,
    settings_snapshot,
    settings_secret_values,
    start_pimcore_test_create,
    test_pimcore_settings,
    test_ftp_connection,
    test_local_paths,
    test_sql_connection,
    test_sql_profile_connection,
    update_pimcore_product,
    update_settings,
    update_user,
)
from ..version import get_app_version, get_display_version

try:  # pragma: no cover - optional runtime dependency
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover
    Image = None
    ImageOps = None


STATIC_DIR = Path(__file__).resolve().parent / "static"
BROWSER_EXTENSION_DIR = Path(__file__).resolve().parents[1] / "browser_extension"
SESSION_COOKIE = "picsyncra_web_session"
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60
BROWSER_EXTENSION_TOKEN_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"
ACTIVE_CLIENT_MAX_AGE_SECONDS = 180
PRESENCE_CLIENT_MAX_AGE_SECONDS = 45
ACTIVE_CLIENT_FLUSH_INTERVAL_SECONDS = 15
PRESENCE_CLIENT_ID_HEADER = "x-picsyncra-client-id"
WEB_UPLOAD_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
WEB_UPLOAD_CACHE_CLEAN_INTERVAL_SECONDS = 30 * 60
OCR_QUEUE_VISIBLE_LIMIT = 5
OCR_QUEUE_COMPLETED_TTL_SECONDS = 10
CSRF_HEADER = "x-picsyncra-csrf"
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_UPLOAD_CACHE_LAST_CLEANUP = 0.0
_OCR_EXECUTION_SERVICE: OcrExecutionService | None = None
OCR_FEATURE_ENABLED = os.getenv("PICSYNCRA_OCR_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


def _require_ocr_feature() -> None:
    """Reject OCR-only routes in the lightweight web distribution."""

    if not OCR_FEATURE_ENABLED:
        raise HTTPException(status_code=404, detail="OCR nie jest dostepny w tym wydaniu.")


def _ocr_cpu_percent() -> float:
    """Read the shared host sample without taking an extra CPU measurement."""

    host = _RESOURCE_MONITOR.latest_public_snapshot().get("host", {})
    if not isinstance(host, dict):
        return 0.0
    try:
        return max(0.0, min(100.0, float(host.get("cpu_percent", 0.0))))
    except (TypeError, ValueError):
        return 0.0
_BROWSER_EXTENSION_IMPORTS: Dict[str, List[Dict[str, Any]]] = {}
_BROWSER_EXTENSION_IMPORTS_LOCK = threading.Lock()
_PROCESS_JOB_RETENTION_SECONDS = 6 * 60 * 60
_PROCESS_JOB_DIRECTORY_TTL_SECONDS = 24 * 60 * 60
_PROCESS_JOB_DIRECTORY_PREFIX = "job-"
_PROCESS_JOB_ROOT = Path(tempfile.gettempdir()) / "picsyncra_web_process_jobs"
# Active work is never discarded; only the newest terminal jobs stay in memory.
_PROCESS_JOB_MAX_COMPLETED = 200
_PROCESS_QUEUE = ProcessQueueService()
_FILE_TOKEN_REGISTRY = FileTokenRegistry()


class _ProcessQueueReference:
    """Delegates reservations to the active queue, including test replacements."""

    @property
    def limits(self) -> Any:
        return _PROCESS_QUEUE.limits

    def reserve(self, cache_scope: str) -> QueueReservation:
        return _PROCESS_QUEUE.reserve(cache_scope)


_PROCESS_QUEUE_REFERENCE = _ProcessQueueReference()
_PROCESS_JOBS: Dict[str, Dict[str, Any]] = {}
_PROCESS_JOBS_LOCK = threading.Lock()
_PROCESS_JOB_COMPLETIONS: Dict[str, threading.Event] = {}
_PROCESS_QUEUE_GENERATION = 0
_PROCESS_PROGRESS_GATE = ProcessProgressGate()
_ACTIVE_CLIENT_REGISTRY = ActiveClientRegistry(
    Path(settings.LOG_DIR) / "web_active_clients.json",
    max_age_seconds=ACTIVE_CLIENT_MAX_AGE_SECONDS,
    flush_interval_seconds=ACTIVE_CLIENT_FLUSH_INTERVAL_SECONDS,
)
_ACTIVE_CLIENT_REGISTRY_LIFECYCLE_LOCK = threading.Lock()
_RATE_LIMITS: Dict[str, List[float]] = {}
_RATE_LIMITS_LOCK = threading.Lock()
_UPLOAD_SCAN_RESULTS: Dict[str, Dict[str, Any]] = {}
_UPLOAD_SCAN_RESULTS_LOCK = threading.Lock()
_BACKUP_SCHEDULER_STOP = threading.Event()
_BACKUP_SCHEDULER_THREAD: threading.Thread | None = None
_LIVE_EVENT_PRUNE_INTERVAL_SECONDS = 60 * 60
_LIVE_EVENT_LAST_PRUNED = 0.0
_HEALTH_INTEGRATION_CACHE_SECONDS = 1.0
_HEALTH_INTEGRATION_CACHE_LOCK = threading.Lock()
_HEALTH_INTEGRATION_CACHE_PATH = ""
_HEALTH_INTEGRATION_CACHE_AT = 0.0
_HEALTH_INTEGRATION_CACHE: Dict[str, Any] | None = None
_HEALTH_STORE_CACHE_LOCK = threading.Lock()
_HEALTH_STORE_CACHE_PATH = ""
_HEALTH_STORE_CACHE: Any = None
_RESOURCE_MONITOR = ResourceMonitor(
    settings_provider=lambda: config.CONFIG.get(RESOURCE_MONITOR_SETTINGS_KEY, {}),
    context_provider=lambda: _resource_monitor_context(),
    event_emitter=lambda severity, event_type, details: _emit_resource_event(
        severity, event_type, details
    ),
    real_test_failure_reporter=lambda kind, report: _report_real_test_worker_failure(
        kind, report
    ),
)
RATE_LIMIT_LOGIN_ATTEMPTS = 20
RATE_LIMIT_LOGIN_WINDOW_SECONDS = 10 * 60
RATE_LIMIT_UPLOAD_ATTEMPTS = 80
RATE_LIMIT_UPLOAD_WINDOW_SECONDS = 60
ANTIVIRUS_SCAN_TIMEOUT_SECONDS = 120
EXECUTABLE_UPLOAD_EXTENSIONS = {
    "exe",
    "bat",
    "cmd",
    "com",
    "msi",
    "ps1",
    "vbs",
    "js",
    "jar",
    "dll",
    "scr",
    "pif",
    "sh",
}
GENERIC_UPLOAD_MIME_TYPES = {
    "",
    "application/octet-stream",
    "binary/octet-stream",
}
JPEG_UPLOAD_EXTENSIONS = {"jpg", "jpeg", "jfif", "jpe", "peg"}
PNG_UPLOAD_EXTENSIONS = {"png", "apng"}
BMP_UPLOAD_EXTENSIONS = {"bmp", "dib"}
TIFF_UPLOAD_EXTENSIONS = {"tif", "tiff"}
AVIF_UPLOAD_EXTENSIONS = {"avif", "avifs"}
HEIF_UPLOAD_EXTENSIONS = {"heic", "heif", "hif"}
JPEG2000_UPLOAD_EXTENSIONS = {"jp2", "j2k", "jpc", "jpx"}
PNM_UPLOAD_EXTENSIONS = {"ppm", "pgm", "pbm", "pnm"}
UPLOAD_MIME_TYPES = {
    "jpg": {"image/jpeg", "image/jpg", "image/pjpeg"},
    "jpeg": {"image/jpeg", "image/jpg", "image/pjpeg"},
    "jfif": {"image/jpeg", "image/jpg", "image/pjpeg"},
    "jpe": {"image/jpeg", "image/jpg", "image/pjpeg"},
    "peg": {"image/jpeg", "image/jpg", "image/pjpeg"},
    "png": {"image/png"},
    "apng": {"image/apng", "image/png"},
    "webp": {"image/webp"},
    "gif": {"image/gif"},
    "bmp": {"image/bmp", "image/x-ms-bmp", "image/x-windows-bmp"},
    "dib": {"image/bmp", "image/x-dib", "image/x-ms-bmp", "image/x-windows-bmp"},
    "tif": {"image/tiff", "image/tif"},
    "tiff": {"image/tiff", "image/tif"},
    "avif": {"image/avif", "image/heif", "image/heic"},
    "avifs": {"image/avif-sequence", "image/avif"},
    "heic": {"image/heic", "image/heic-sequence", "image/heif"},
    "heif": {"image/heif", "image/heif-sequence", "image/heic"},
    "hif": {"image/heif", "image/heic"},
    "jp2": {"image/jp2", "image/jpeg2000", "image/jpeg2000-image", "image/x-jpeg2000-image"},
    "j2k": {"image/j2k", "image/jp2", "image/jpeg2000", "image/x-jpeg2000-image"},
    "jpc": {"image/jpc", "image/jp2", "image/jpeg2000", "image/x-jpeg2000-image"},
    "jpx": {"image/jpx", "image/jp2", "image/jpeg2000", "image/x-jpeg2000-image"},
    "ico": {"image/x-icon", "image/vnd.microsoft.icon", "image/ico"},
    "cur": {"image/x-icon", "image/vnd.microsoft.icon", "image/cur"},
    "tga": {"image/x-tga", "image/tga", "image/targa"},
    "ppm": {"image/x-portable-pixmap"},
    "pgm": {"image/x-portable-graymap"},
    "pbm": {"image/x-portable-bitmap"},
    "pnm": {
        "image/x-portable-anymap",
        "image/x-portable-bitmap",
        "image/x-portable-graymap",
        "image/x-portable-pixmap",
    },
    "pcx": {"image/x-pcx", "image/pcx", "image/x-pc-paintbrush"},
    "psd": {"image/vnd.adobe.photoshop", "image/x-photoshop", "image/psd"},
    "pdf": {"application/pdf", "application/x-pdf"},
    "eps": {"application/postscript", "application/eps", "image/eps"},
    "ai": {
        "application/pdf",
        "application/postscript",
        "application/illustrator",
        "application/vnd.adobe.illustrator",
    },
}
IMAGE_UPLOAD_EXTENSIONS = {
    "jpg",
    "jpeg",
    "jfif",
    "jpe",
    "peg",
    "png",
    "apng",
    "webp",
    "gif",
    "bmp",
    "dib",
    "tif",
    "tiff",
    "avif",
    "avifs",
    "jp2",
    "j2k",
    "jpc",
    "jpx",
    "ico",
    "tga",
    "ppm",
    "pgm",
    "pbm",
    "pnm",
    "pcx",
    "psd",
}
METADATA_STRIP_UPLOAD_EXTENSIONS = {"jpg", "jpeg", "jfif", "jpe", "peg", "png", "apng"}
UPLOAD_EXTENSION_MIME_TYPE = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "jfif": "image/jpeg",
    "jpe": "image/jpeg",
    "peg": "image/jpeg",
    "png": "image/png",
    "apng": "image/apng",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "dib": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "avif": "image/avif",
    "avifs": "image/avif-sequence",
    "heic": "image/heic",
    "heif": "image/heif",
    "hif": "image/heif",
    "jp2": "image/jp2",
    "j2k": "image/j2k",
    "jpc": "image/jpc",
    "jpx": "image/jpx",
    "ico": "image/x-icon",
    "cur": "image/x-icon",
    "tga": "image/x-tga",
    "ppm": "image/x-portable-pixmap",
    "pgm": "image/x-portable-graymap",
    "pbm": "image/x-portable-bitmap",
    "pnm": "image/x-portable-anymap",
    "pcx": "image/x-pcx",
}
IMAGE_SIGNATURE_EXTENSIONS = (
    "jpg",
    "png",
    "webp",
    "gif",
    "bmp",
    "dib",
    "tif",
    "avif",
    "heic",
    "jp2",
    "j2k",
    "ico",
    "cur",
    "tga",
    "ppm",
    "pgm",
    "pbm",
    "pcx",
)


@dataclass(frozen=True)
class _SavedUploadCache:
    path: str
    size: int
    name: str


class _ProcessJobCancelled(Exception):
    """Signals cooperative cancellation before the next external process step."""


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _timing_item(key: str, label: str, started: float, **details: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "key": key,
        "label": label,
        "elapsed_ms": _elapsed_ms(started),
    }
    if details:
        payload["details"] = details
    return payload


def _timing_payload(stages: List[Dict[str, Any]], started: float) -> Dict[str, Any]:
    return {"total_ms": _elapsed_ms(started), "stages": stages}


def _processing_settings() -> Dict[str, Any]:
    return config._normalize_processing_settings(
        config.CONFIG.get(PROCESSING_SETTINGS_KEY, {})
    )


def _configured_time_zone_name() -> str:
    display = config.normalize_web_display_settings(
        config.CONFIG.get(WEB_DISPLAY_SETTINGS_KEY, {})
    )
    return str(display.get("time_zone") or "UTC")


def _active_product_field_settings() -> Dict[str, Dict[str, object]]:
    return normalize_product_fields(
        config.CONFIG.get(PRODUCT_FIELDS_KEY),
        legacy_color_labels=config.CONFIG.get(COLOR_FIELD_LABELS_KEY),
    )


def _security_settings() -> Dict[str, Any]:
    raw_security = config.CONFIG.get(SECURITY_SETTINGS_KEY, {})
    if not isinstance(raw_security, dict):
        raw_security = {}
    merged = dict(raw_security)
    legacy_processing = config.CONFIG.get(PROCESSING_SETTINGS_KEY, {})
    if isinstance(legacy_processing, dict):
        for key in ("max_upload_mb", "max_upload_pixels"):
            if key not in merged and key in legacy_processing:
                merged[key] = legacy_processing[key]
    return config._normalize_security_settings(merged)


def _upload_processing_mode() -> str:
    return str(_processing_settings().get("upload_processing_mode") or "save")


def _show_timing_details() -> bool:
    return bool(_processing_settings().get("show_timing_details", False))


def _upload_limits() -> tuple[int, int]:
    security = _security_settings()
    max_bytes = max(1, int(security.get("max_upload_mb") or 50)) * 1024 * 1024
    max_pixels = max(1, int(security.get("max_upload_pixels") or 25_000_000))
    return max_bytes, max_pixels


def _upload_limit_message(size: int, max_bytes: int) -> str:
    limit_mb = max_bytes / (1024 * 1024)
    return f"Plik ma zbyt duzy rozmiar. Limit uploadu to {limit_mb:g} MB."


def _raise_upload_too_large(message: str) -> None:
    raise HTTPException(status_code=413, detail=message)


def _auth_enabled() -> bool:
    return os.environ.get("PICSYNCRA_WEB_AUTH", "1").strip().lower() in {"1", "true", "yes", "on"}


def _admin_username() -> str:
    return (
        os.environ.get("PICSYNCRA_WEB_ADMIN_USER", DEFAULT_ADMIN_USERNAME).strip()
        or DEFAULT_ADMIN_USERNAME
    )


def _admin_password() -> str:
    return os.environ.get("PICSYNCRA_WEB_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)


def _session_secret() -> bytes:
    value = os.environ.get("PICSYNCRA_WEB_SESSION_SECRET") or common.APP_SECRET
    return value.encode("utf-8")


def _sign(payload: str) -> str:
    return hmac.new(_session_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _csrf_token_for_session(session_token: Optional[str]) -> str:
    token = str(session_token or "")
    if not token:
        return ""
    return _sign(f"csrf|{token}")


def _csrf_token(request: Request) -> str:
    if not _auth_enabled():
        return ""
    return _csrf_token_for_session(request.cookies.get(SESSION_COOKIE))


def _request_host(request: Request) -> str:
    return str(request.headers.get("host") or request.url.netloc or "").lower()


def _origin_matches_request(request: Request, value: str) -> bool:
    parsed = urlsplit(str(value or ""))
    if not parsed.scheme or not parsed.netloc:
        return False
    return (
        parsed.scheme.lower() == str(request.url.scheme or "").lower()
        and parsed.netloc.lower() == _request_host(request)
    )


def _require_same_origin_mutation(request: Request) -> None:
    origin = str(request.headers.get("origin") or "")
    referer = str(request.headers.get("referer") or "")
    fetch_site = str(request.headers.get("sec-fetch-site") or "").lower()
    if origin and not _origin_matches_request(request, origin):
        raise HTTPException(status_code=403, detail="Odrzucono request z obcego Origin.")
    if not origin and referer and not _origin_matches_request(request, referer):
        raise HTTPException(status_code=403, detail="Odrzucono request z obcego Referer.")
    if not origin and not referer and fetch_site in {"cross-site", "same-site"}:
        raise HTTPException(status_code=403, detail="Odrzucono request spoza panelu.")


def _validate_mutating_request(request: Request) -> None:
    method = str(request.method or "").upper()
    if method not in MUTATING_METHODS:
        return
    path = str(request.url.path or "")
    if path.startswith("/api/browser-extension/"):
        return
    _require_same_origin_mutation(request)
    if path == "/api/login":
        if str(request.headers.get("x-requested-with") or "").lower() != "xmlhttprequest":
            raise HTTPException(status_code=403, detail="Brak naglowka requestu panelu.")
        return
    # Logout is intentionally idempotent.  In particular, it must be able to
    # remove a cookie whose account id was replaced by a legacy import.
    if path == "/api/logout":
        return
    if not _auth_enabled():
        return
    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        return
    expected = _csrf_token_for_session(session_token)
    supplied = str(request.headers.get(CSRF_HEADER) or "")
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Niepoprawny token CSRF.")


def _make_session_token(user: Dict[str, Any]) -> str:
    session_version = int(user.get("session_version") or 0)
    user_id = str(user.get("id") or "")
    payload = f"session-v2|{user_id}|{session_version}|{int(time.time())}|{secrets.token_hex(12)}"
    token = f"{payload}|{_sign(payload)}"
    return base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii")


def _make_browser_extension_token(username: str) -> str:
    user = mark_browser_extension_token_issued(username) or find_user(username) or {}
    token_version = int(user.get("extension_token_version") or 0)
    payload = f"browser-extension|{username}|{token_version}|{int(time.time())}|{secrets.token_hex(16)}"
    token = f"{payload}|{_sign(payload)}"
    return base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii")


def _read_session_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        payload, signature = decoded.rsplit("|", 1)
    except Exception:
        return None
    if not hmac.compare_digest(_sign(payload), signature):
        return None
    parts = payload.split("|")
    if len(parts) != 5 or parts[0] != "session-v2":
        return None
    _marker, user_id, version_raw, issued_raw, _nonce = parts
    try:
        issued = int(issued_raw)
        session_version = int(version_raw)
    except ValueError:
        return None
    if int(time.time()) - issued > SESSION_MAX_AGE_SECONDS:
        return None
    user = find_user_by_id(user_id)
    if not user or not user.get("enabled") or user.get("locked"):
        return None
    if int(user.get("session_version") or 0) != session_version:
        return None
    return str(user.get("username") or "") or None


def _read_browser_extension_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        payload, signature = decoded.rsplit("|", 1)
    except Exception:
        return None
    if not hmac.compare_digest(_sign(payload), signature):
        return None
    parts = payload.split("|")
    if len(parts) == 5 and parts[0] == "browser-extension":
        _marker, username, version_raw, issued_raw, _nonce = parts
    elif len(parts) == 4 and parts[0] == "browser-extension":
        _marker, username, issued_raw, _nonce = parts
        version_raw = "0"
    else:
        return None
    try:
        issued = int(issued_raw)
        token_version = int(version_raw)
    except ValueError:
        return None
    if int(time.time()) - issued > BROWSER_EXTENSION_TOKEN_MAX_AGE_SECONDS:
        return None
    user = find_user(username)
    if not user or not user.get("enabled") or user.get("locked"):
        return None
    if int(user.get("extension_token_version") or 0) != token_version:
        return None
    mark_browser_extension_token_used(username, token_version)
    return username


def _current_user(request: Request) -> Optional[str]:
    if not _auth_enabled():
        return _admin_username()
    return _read_session_token(request.cookies.get(SESSION_COOKIE))


def _request_remote_address(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "")


def _rate_limit_scope(request: Request) -> tuple[str, int, int]:
    method = str(request.method or "").upper()
    path = str(request.url.path or "")
    if method == "POST" and path == "/api/login":
        return "login", RATE_LIMIT_LOGIN_ATTEMPTS, RATE_LIMIT_LOGIN_WINDOW_SECONDS
    upload_paths = {
        "/api/upload-cache",
        "/api/browser-extension/upload-cache",
        "/api/web-images/cache",
        "/api/web-images/scan",
        "/api/process",
        "/api/process/background",
    }
    if method == "POST" and path in upload_paths:
        return "upload", RATE_LIMIT_UPLOAD_ATTEMPTS, RATE_LIMIT_UPLOAD_WINDOW_SECONDS
    return "", 0, 0


def _check_rate_limit(request: Request) -> None:
    scope, limit, window = _rate_limit_scope(request)
    if not scope or limit <= 0 or window <= 0:
        return
    now = time.time()
    remote = _request_remote_address(request) or "unknown"
    key = f"{scope}|{remote}"
    cutoff = now - window
    _prune_rate_limits(now=now)
    with _RATE_LIMITS_LOCK:
        attempts = [item for item in _RATE_LIMITS.get(key, []) if item >= cutoff]
        if len(attempts) >= limit:
            retry_after = max(1, int(window - (now - attempts[0])))
            raise HTTPException(
                status_code=429,
                detail=f"Za duzo requestow z tego adresu IP. Sprobuj ponownie za {retry_after} s.",
                headers={"Retry-After": str(retry_after)},
            )
        attempts.append(now)
        _RATE_LIMITS[key] = attempts


def _prune_rate_limits(now: Optional[float] = None) -> None:
    current = time.time() if now is None else float(now)
    windows = {
        "login": RATE_LIMIT_LOGIN_WINDOW_SECONDS,
        "upload": RATE_LIMIT_UPLOAD_WINDOW_SECONDS,
    }
    fallback_window = max(windows.values())
    with _RATE_LIMITS_LOCK:
        for key, timestamps in list(_RATE_LIMITS.items()):
            scope = str(key).split("|", 1)[0]
            cutoff = current - windows.get(scope, fallback_window)
            retained = [timestamp for timestamp in timestamps if timestamp >= cutoff]
            if retained:
                _RATE_LIMITS[key] = retained
            else:
                _RATE_LIMITS.pop(key, None)


def _extension_bearer_token(request: Request) -> str:
    authorization = str(request.headers.get("authorization") or "").strip()
    if not authorization.lower().startswith("bearer "):
        return ""
    return authorization.split(None, 1)[1].strip()


def _require_browser_extension_user(request: Request) -> str:
    if not _auth_enabled():
        return _admin_username()
    username = _read_browser_extension_token(_extension_bearer_token(request))
    if not username:
        raise HTTPException(status_code=401, detail="Niepoprawny albo wygasly token rozszerzenia.")
    return username


def _require_user(request: Request) -> str:
    if not _auth_enabled():
        return _admin_username()
    username = _current_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Brak aktywnej sesji.")
    return username


def _current_user_payload(request: Request) -> Dict[str, Any]:
    username = _require_user(request)
    user = find_user(username)
    if not user:
        raise HTTPException(status_code=401, detail="Brak aktywnej sesji.")
    return user


def _user_cache_scope(request: Request, username: str) -> str:
    session_token = str(request.cookies.get(SESSION_COOKIE) or "")
    if session_token:
        scope_material = session_token
    else:
        client = getattr(request, "client", None)
        client_host = str(getattr(client, "host", "") or "")
        headers = getattr(request, "headers", {}) or {}
        user_agent = str(headers.get("user-agent", "") if hasattr(headers, "get") else "")
        scope_material = f"{client_host}|{user_agent}|no-session"
    token_digest = hashlib.sha1(scope_material.encode("utf-8")).hexdigest()[:12]
    raw_scope = f"{username}-{token_digest}"
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", raw_scope).strip("._-") or "user-session"


def _require_admin(request: Request) -> Dict[str, Any]:
    user = _current_user_payload(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Wymagane konto administratora.")
    return user


def _static_file(name: str) -> FileResponse:
    return FileResponse(STATIC_DIR / name)


def _safe_upload_name(filename: Optional[str], fallback: str) -> str:
    name = Path(filename or "").name.strip()
    if not name:
        name = fallback
    return name


def _safe_file_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.strip().lower()
    if suffix and len(suffix) <= 12 and re.fullmatch(r"\.[a-z0-9]+", suffix):
        return suffix
    return ""


def _upload_extension(filename: object) -> str:
    suffix = _safe_file_suffix(str(filename or ""))
    return suffix[1:] if suffix.startswith(".") else ""


def _validate_upload_extension(filename: object) -> None:
    extension = _upload_extension(filename)
    security = _security_settings()
    allowed = set(security.get("allowed_upload_extensions") or [])
    blocked = set(security.get("blocked_upload_extensions") or [])
    if not extension:
        raise HTTPException(status_code=400, detail="Plik musi miec rozszerzenie.")
    if extension in blocked:
        raise HTTPException(status_code=400, detail=f"Typ pliku .{extension} jest zablokowany.")
    if security.get("block_executable_uploads", True) and extension in EXECUTABLE_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Plik wykonywalny .{extension} jest zablokowany.",
        )
    if allowed and extension not in allowed:
        raise HTTPException(status_code=400, detail=f"Typ pliku .{extension} nie jest dozwolony.")


def _normalized_content_type(content_type: object) -> str:
    return str(content_type or "").split(";", 1)[0].strip().lower()


def _validate_upload_mime_type(filename: object, content_type: object) -> None:
    extension = _upload_extension(filename)
    normalized = _normalized_content_type(content_type)
    if normalized in GENERIC_UPLOAD_MIME_TYPES:
        return
    allowed = UPLOAD_MIME_TYPES.get(extension)
    if allowed is None:
        raise HTTPException(
            status_code=400,
            detail=f"Typ pliku .{extension} nie ma skonfigurowanej walidacji MIME.",
        )
    if normalized not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"MIME type {normalized} nie pasuje do pliku .{extension}.",
        )


def _is_iso_base_media_brand(header: bytes, allowed_brands: Set[bytes]) -> bool:
    if len(header) < 16 or header[4:8] != b"ftyp":
        return False
    brands = {header[8:12]}
    compatible = header[16:64]
    brands.update(compatible[index : index + 4] for index in range(0, len(compatible) - 3, 4))
    return any(brand in allowed_brands for brand in brands)


def _is_dib_header(header: bytes) -> bool:
    if len(header) < 16:
        return False
    header_size = int.from_bytes(header[:4], "little", signed=False)
    if header_size not in {12, 40, 52, 56, 64, 108, 124}:
        return False
    if header_size == 12:
        width = int.from_bytes(header[4:6], "little", signed=False)
        height = int.from_bytes(header[6:8], "little", signed=False)
        planes = int.from_bytes(header[8:10], "little", signed=False)
        bit_count = int.from_bytes(header[10:12], "little", signed=False)
    else:
        width = int.from_bytes(header[4:8], "little", signed=True)
        height = int.from_bytes(header[8:12], "little", signed=True)
        planes = int.from_bytes(header[12:14], "little", signed=False)
        bit_count = int.from_bytes(header[14:16], "little", signed=False)
    return width != 0 and height != 0 and planes == 1 and bit_count in {1, 2, 4, 8, 16, 24, 32}


def _is_jpeg2000_header(header: bytes) -> bool:
    return header.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n") or header.startswith(b"\xff\x4f\xff\x51")


def _is_tga_header(header: bytes) -> bool:
    if len(header) < 18:
        return False
    color_map_type = header[1]
    image_type = header[2]
    width = int.from_bytes(header[12:14], "little", signed=False)
    height = int.from_bytes(header[14:16], "little", signed=False)
    pixel_depth = header[16]
    return (
        color_map_type in {0, 1}
        and image_type in {1, 2, 3, 9, 10, 11}
        and width > 0
        and height > 0
        and pixel_depth in {8, 15, 16, 24, 32}
    )


def _is_pnm_header(header: bytes, extension: str) -> bool:
    if len(header) < 3 or header[:1] != b"P" or header[2:3] not in {b" ", b"\t", b"\r", b"\n"}:
        return False
    magic = header[1:2]
    if extension == "pbm":
        return magic in {b"1", b"4"}
    if extension == "pgm":
        return magic in {b"2", b"5"}
    if extension == "ppm":
        return magic in {b"3", b"6"}
    return magic in {b"1", b"2", b"3", b"4", b"5", b"6"}


def _is_pcx_header(header: bytes) -> bool:
    return (
        len(header) >= 4
        and header[0] == 0x0A
        and header[1] in {0, 2, 3, 5}
        and header[2] == 1
        and header[3] in {1, 2, 4, 8}
    )


def _upload_signature_matches(extension: str, header: bytes) -> bool:
    return upload_staging.signature_matches(extension, header)


def _upload_extension_from_signature(header: bytes) -> str:
    for extension in IMAGE_SIGNATURE_EXTENSIONS:
        if _upload_signature_matches(extension, header):
            return extension
    return ""


def _upload_extensions_equivalent(current: str, detected: str) -> bool:
    if current == detected:
        return True
    equivalence_groups = (
        JPEG_UPLOAD_EXTENSIONS,
        PNG_UPLOAD_EXTENSIONS,
        BMP_UPLOAD_EXTENSIONS,
        TIFF_UPLOAD_EXTENSIONS,
        AVIF_UPLOAD_EXTENSIONS,
        HEIF_UPLOAD_EXTENSIONS,
        JPEG2000_UPLOAD_EXTENSIONS,
        PNM_UPLOAD_EXTENSIONS,
    )
    return any({current, detected} <= group for group in equivalence_groups)


def _upload_name_with_extension(filename: str, extension: str) -> str:
    stem = Path(filename or "").stem.strip(" .-_") or "upload"
    return f"{stem}.{extension}"


def _normalize_upload_cache_extension(
    path: str,
    filename: str,
    content_type: object,
) -> tuple[str, str, str]:
    try:
        with open(path, "rb") as handle:
            header = handle.read(128)
    except OSError:
        return path, filename, _normalized_content_type(content_type)
    detected_extension = _upload_extension_from_signature(header)
    current_extension = _upload_extension(filename)
    if not detected_extension or _upload_extensions_equivalent(current_extension, detected_extension):
        return path, filename, _normalized_content_type(content_type)
    corrected_name = _upload_name_with_extension(filename, detected_extension)
    base, _old_extension = os.path.splitext(path)
    corrected_path = f"{base}.{detected_extension}"
    if os.path.normcase(os.path.abspath(corrected_path)) != os.path.normcase(os.path.abspath(path)):
        os.replace(path, corrected_path)
    return corrected_path, corrected_name, UPLOAD_EXTENSION_MIME_TYPE.get(detected_extension, "")


def _validate_upload_signature(path: str, filename: object) -> None:
    upload_staging.validate_upload_signature(path, filename)


def _validate_upload_image_file(path: str, filename: object, max_pixels: int) -> tuple[int, int]:
    return upload_staging.validate_image_file(path, filename, max_pixels)


def _validate_upload_content(
    path: str,
    filename: object,
    content_type: object,
    max_pixels: int,
) -> tuple[int, int]:
    _validate_upload_mime_type(filename, content_type)
    _validate_upload_signature(path, filename)
    return _validate_upload_image_file(path, filename, max_pixels)


def _jpeg_safe_image(image: Any) -> Any:
    if image.mode in {"RGB", "L"}:
        return image
    if image.mode in {"RGBA", "LA"}:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, (0, 0), rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _strip_upload_metadata(path: str, filename: object) -> None:
    extension = _upload_extension(filename)
    if extension not in METADATA_STRIP_UPLOAD_EXTENSIONS or Image is None:
        return
    temp_path = f"{path}.clean-{secrets.token_hex(6)}"
    try:
        with Image.open(path) as image:
            work = image.copy()
        if ImageOps is not None:
            try:
                work = ImageOps.exif_transpose(work)
            except Exception:
                pass
        if extension in JPEG_UPLOAD_EXTENSIONS:
            work = _jpeg_safe_image(work)
            work.save(temp_path, format="JPEG", quality=95, optimize=True)
        else:
            work.save(temp_path, format="PNG", optimize=True)
        os.replace(temp_path, path)
    except Exception as exc:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="Nie mozna wyczyscic metadanych obrazu.") from exc


def _enforce_upload_size(path: str, max_bytes: int) -> int:
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Nie mozna sprawdzic rozmiaru wyslanego pliku.") from exc
    if size > max_bytes:
        _raise_upload_too_large(_upload_limit_message(size, max_bytes))
    return size


def _defender_scan_executable() -> str:
    if os.name != "nt":
        return ""
    candidates: List[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Windows Defender" / "MpCmdRun.exe")
    platform_root = Path(os.environ.get("ProgramData") or r"C:\ProgramData") / "Microsoft" / "Windows Defender" / "Platform"
    try:
        candidates.extend(sorted(platform_root.glob("*/MpCmdRun.exe"), reverse=True))
    except OSError:
        pass
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def _prune_upload_scan_results(now: Optional[float] = None) -> None:
    cutoff = (
        time.time() if now is None else float(now)
    ) - WEB_UPLOAD_CACHE_MAX_AGE_SECONDS
    with _UPLOAD_SCAN_RESULTS_LOCK:
        for path, result in list(_UPLOAD_SCAN_RESULTS.items()):
            try:
                cached_at = float(result.get("_cached_at") or 0)
            except (TypeError, ValueError):
                cached_at = 0
            if not os.path.isfile(path) or cached_at < cutoff:
                _UPLOAD_SCAN_RESULTS.pop(path, None)


def _remember_upload_scan_result(path: str, result: Dict[str, Any]) -> None:
    if not path:
        return
    _prune_upload_scan_results()
    cached_result = dict(result)
    cached_result["_cached_at"] = time.time()
    with _UPLOAD_SCAN_RESULTS_LOCK:
        _UPLOAD_SCAN_RESULTS[os.path.abspath(path)] = cached_result


def _snapshot_upload_scan_result(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    with _UPLOAD_SCAN_RESULTS_LOCK:
        return dict(_UPLOAD_SCAN_RESULTS.get(os.path.abspath(path)) or {})


def _publish_upload_scan_result(path: str, result: Dict[str, Any]) -> None:
    if path and result:
        cached_result = dict(result)
        cached_result["_cached_at"] = time.time()
        with _UPLOAD_SCAN_RESULTS_LOCK:
            _UPLOAD_SCAN_RESULTS[os.path.abspath(path)] = cached_result
    _prune_upload_scan_results()


def _copy_upload_scan_result(source_path: str, target_path: str) -> None:
    if not source_path or not target_path:
        return
    result = _snapshot_upload_scan_result(source_path)
    _publish_upload_scan_result(target_path, result)


async def _preprocess_cached_upload_with_scan_result(
    path: str,
    display_name: str,
    options: Any,
) -> tuple[str, str, bool]:
    scan_result = _snapshot_upload_scan_result(path)
    target_path, target_name, preprocessed = await run_in_threadpool(
        preprocess_cached_upload,
        path,
        display_name,
        options,
    )
    _publish_upload_scan_result(target_path, scan_result)
    return target_path, target_name, preprocessed


def _upload_scan_result(path: str) -> Dict[str, Any]:
    _prune_upload_scan_results()
    with _UPLOAD_SCAN_RESULTS_LOCK:
        result = dict(_UPLOAD_SCAN_RESULTS.get(os.path.abspath(path)) or {})
    result.pop("_cached_at", None)
    return result


def _uploaded_scan_summary(uploaded_slots: List[WebUploadedSlot]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for slot in uploaded_slots:
        result = _upload_scan_result(str(slot.source_path or ""))
        if result:
            item = dict(result)
            item["prefix"] = str(slot.prefix or "")
            item["filename"] = str(slot.original_filename or "")
            results.append(item)
    scanned = [item for item in results if item.get("scanned")]
    enabled = any(item.get("enabled") for item in results)
    return {
        "enabled": enabled,
        "scanned": len(scanned),
        "skipped": sum(1 for item in results if item.get("enabled") and not item.get("scanned")),
        "items": results,
    }


def _scan_uploaded_file(path: str) -> Dict[str, Any]:
    security = _security_settings()
    return upload_staging.scan_uploaded_file(
        path,
        enabled=bool(security.get("antivirus_scan_uploads", False)),
        scanner_executable=_defender_scan_executable(),
        timeout_seconds=ANTIVIRUS_SCAN_TIMEOUT_SECONDS,
        process_runner=subprocess.run,
        on_result=lambda result: _remember_upload_scan_result(path, result),
    )


def _upload_cache_root() -> str:
    return os.path.join(settings.AC, "web_upload_cache")


def _ocr_crop_root() -> str:
    """Durable enlarged crops used by the idle OCR refinement queue."""

    return os.path.join(settings.AC, "ocr_crop_cache")


def _upload_cache_dir(cache_scope: object = "") -> str:
    safe_scope = sanitize_path_segment(cache_scope) or "user-session"
    return os.fspath(build_child_path(_upload_cache_root(), safe_scope))


def _file_token_roots() -> list[str]:
    return [
        settings.l,
        os.path.join(settings.AC, "web_ftp_cache"),
        _upload_cache_root(),
        _ocr_crop_root(),
    ]


def _path_is_under_root(path: str, root: str) -> bool:
    try:
        resolve_path_within_roots(path, [root])
    except PathSecurityError:
        return False
    return True


def _clear_ocr_crop_queue_on_startup() -> int:
    """Discard unfinished OCR crops and their trusted cache files on restart."""

    try:
        crop_paths = list(observability_store().clear_ocr_crop_queue())
    except Exception as exc:
        log_error(f"OCR startup queue cleanup skipped: {exc}")
        return 0
    crop_root = _ocr_crop_root()
    for crop_path in crop_paths:
        if not _path_is_under_root(crop_path, crop_root):
            continue
        try:
            if os.path.isfile(crop_path):
                os.remove(crop_path)
        except OSError as exc:
            log_error(f"OCR startup crop cleanup failed: {exc}")
    return len(crop_paths)


def _purge_expired_ocr_crop_jobs() -> int:
    """Remove short-lived completed queue rows and trusted crop cache files."""

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=OCR_QUEUE_COMPLETED_TTL_SECONDS)).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    try:
        crop_paths = list(observability_store().purge_completed_ocr_crop_jobs(cutoff))
    except Exception as exc:
        log_error(f"OCR completed crop cleanup skipped: {exc}")
        return 0
    crop_root = _ocr_crop_root()
    deleted = 0
    for crop_path in crop_paths:
        if not _path_is_under_root(crop_path, crop_root):
            continue
        try:
            if os.path.isfile(crop_path):
                os.remove(crop_path)
                deleted += 1
        except OSError as exc:
            log_error(f"OCR completed crop cleanup failed: {exc}")
    return deleted


def _is_upload_cache_path(path: str) -> bool:
    return bool(path and _path_is_under_root(path, _upload_cache_root()))


def _delete_upload_cache_files(paths: List[str]) -> Dict[str, Any]:
    root = os.path.abspath(_upload_cache_root())
    deleted = 0
    skipped = 0
    errors: List[str] = []
    touched_dirs: Set[str] = set()
    for raw_path in sorted({os.path.abspath(path) for path in paths if path}):
        if not _path_is_under_root(raw_path, root):
            skipped += 1
            continue
        touched_dirs.add(os.path.dirname(raw_path))
        try:
            if os.path.isfile(raw_path):
                os.remove(raw_path)
                deleted += 1
            else:
                skipped += 1
        except OSError as exc:
            errors.append(f"{raw_path}: {exc}")
    for directory in sorted(touched_dirs, key=len, reverse=True):
        current = os.path.abspath(directory)
        while _path_is_under_root(current, root) and current != root:
            try:
                os.rmdir(current)
            except OSError:
                break
            current = os.path.dirname(current)
    try:
        os.rmdir(root)
    except OSError:
        pass
    return {"deleted": deleted, "skipped": skipped, "errors": errors}


def cleanup_web_upload_cache(
    *,
    max_age_seconds: int = WEB_UPLOAD_CACHE_MAX_AGE_SECONDS,
    min_interval_seconds: int = WEB_UPLOAD_CACHE_CLEAN_INTERVAL_SECONDS,
    force: bool = False,
) -> Dict[str, Any]:
    """Remove stale browser upload cache files."""

    global _UPLOAD_CACHE_LAST_CLEANUP
    now = time.time()
    if not force and now - _UPLOAD_CACHE_LAST_CLEANUP < max(1, int(min_interval_seconds or 1)):
        return {"deleted_files": 0, "deleted_dirs": 0, "skipped": True, "errors": []}
    _UPLOAD_CACHE_LAST_CLEANUP = now
    root = os.path.abspath(_upload_cache_root())
    if not os.path.isdir(root):
        return {"deleted_files": 0, "deleted_dirs": 0, "skipped": False, "errors": []}

    cutoff = now - max(60, int(max_age_seconds or WEB_UPLOAD_CACHE_MAX_AGE_SECONDS))
    deleted_files = 0
    deleted_dirs = 0
    errors: List[str] = []
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


def _file_token(path: str) -> str:
    try:
        # Validate using a case-insensitive canonical path, but retain the
        # filesystem spelling for APIs which return the original local path.
        resolve_path_within_roots(path, _file_token_roots())
        trusted_path = os.path.realpath(os.path.abspath(os.fspath(path)))
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail="Plik poza katalogiem zdjec lub cache.") from exc
    return _FILE_TOKEN_REGISTRY.issue(trusted_path)


def _file_version(path: str) -> str:
    try:
        stat = os.stat(path)
    except OSError:
        return ""
    return f"{int(stat.st_mtime_ns)}-{int(stat.st_size)}"


def _versioned_file_url(path: str, endpoint: str, token: str) -> str:
    url = f"{endpoint}?token={token}"
    version = _file_version(path)
    if version:
        url = f"{url}&v={version}"
    return url


def _image_sha256(path: str) -> str:
    """Return a stable content key without retaining browser-visible paths."""

    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _analyze_image_values_with_configured_profiles(
    path: str, *, profile_ids: list[object] | None = None
) -> ImageOcrDiagnostics:
    """Use the same selected OCR profiles for testing and slot collection."""

    service = _OCR_EXECUTION_SERVICE
    if service is not None:
        payload: dict[str, object] = {
            "job_id": f"scan-{secrets.token_hex(12)}",
            "path": path,
        }
        if profile_ids is not None:
            payload["profile_ids"] = list(profile_ids)
        run_id = service.submit_queue(**payload)
        snapshot = service.wait_for_terminal(run_id, timeout_seconds=30 * 60)
        if snapshot.state != "completed":
            return ImageOcrDiagnostics(False, {}, [], snapshot.error or snapshot.state)
        result = snapshot.result if isinstance(snapshot.result, dict) else {}
        raw_candidates = result.get("candidates") if isinstance(result, dict) else []
        candidates = [
            OcrDiagnosticCandidate(
                text=str(item.get("text") or ""),
                confidence=float(item.get("confidence") or 0),
                bbox=tuple(int(value) for value in list(item.get("bbox") or [])[:4]),
                dimension=(str(item.get("dimension")) if item.get("dimension") else None),
                value=str(item.get("value") or ""),
                accepted=bool(item.get("accepted")),
                reason=str(item.get("reason") or ""),
                selected=bool(item.get("selected")),
            )
            for item in raw_candidates
            if isinstance(item, dict) and len(list(item.get("bbox") or [])) == 4
        ]
        raw_regions = result.get("regions") if isinstance(result, dict) else []
        regions = [dict(item) for item in raw_regions if isinstance(item, dict)]
        timings_ms: dict[str, int] = {}
        raw_timings = result.get("timings_ms") if isinstance(result, dict) else {}
        if isinstance(raw_timings, dict):
            for key, raw_value in raw_timings.items():
                try:
                    timings_ms[str(key)] = max(0, int(raw_value))
                except (TypeError, ValueError):
                    continue
        return ImageOcrDiagnostics(
            available=bool(result.get("available")),
            dimensions=dict(result.get("dimensions") or {}),
            candidates=candidates,
            message=str(result.get("message") or ""),
            regions=regions,
            timings_ms=timings_ms,
        )
    settings = normalize_ocr_settings(config.CONFIG.get(OCR_SETTINGS_KEY, {}))
    selected_profiles = (
        list(profile_ids)
        if profile_ids is not None
        else settings.get("model_profiles", ["fast"])
    )
    return analyze_image_values(path, profile_ids=selected_profiles)


def _schedule_ocr_value_collection(slot: object, path: str) -> str:
    """Queue the fast OCR stage only for an admin-enabled image slot."""

    if not OCR_FEATURE_ENABLED:
        return "disabled"
    enabled_slots = normalize_ocr_settings(
        config.CONFIG.get(OCR_SETTINGS_KEY, {})
    ).get("enabled_slots", [])
    if str(slot or "").strip() not in enabled_slots:
        return "disabled"
    canonical_path = os.path.realpath(os.path.abspath(path))
    image_hash = ""
    try:
        image_hash = image_content_hash(canonical_path)
        cached_scan = observability_store().get_ocr_scan(
            image_hash
        )
        if isinstance(cached_scan, dict):
            cached_state = str(cached_scan.get("state") or "")
            if cached_state in {"queued", "scanning", "refining", "completed"}:
                return cached_state
    except Exception:
        # Cache lookup must not make assigning a slot fail; collection below
        # remains the source of truth and will record any OCR error.
        pass
    store = observability_store()
    try:
        if not image_hash:
            image_hash = image_content_hash(canonical_path)
        store.upsert_ocr_scan(image_hash, [], "queued")
        enqueue_ocr_fast_image_job(
            canonical_path,
            image_hash=image_hash,
            store=store,
            crop_dir=_ocr_crop_root(),
        )
    except Exception as exc:
        log_error(f"OCR fast-stage preview could not be queued: {exc}")
        return "error"
    return "queued"


def _path_from_file_token(token: str, *, require_exists: bool = True) -> str:
    path = _FILE_TOKEN_REGISTRY.resolve(token)
    if path is None:
        raise HTTPException(
            status_code=403,
            detail="Token pliku wygasl. Odswiez liste zdjec i sprobuj ponownie.",
        )
    if require_exists and not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Nie znaleziono pliku.")
    return path


def _image_slot_paths_from_payload(payload: object) -> dict[str, str]:
    raw = payload.get("slot_tokens", {}) if isinstance(payload, dict) else {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Niepoprawna mapa tokenow slotow.")
    return {
        str(slot).strip(): _path_from_file_token(str(token))
        for slot, token in raw.items()
        if str(slot).strip() and str(token).strip()
    }


def _resample_filter() -> Any:
    if Image is not None and hasattr(Image, "Resampling"):
        return Image.Resampling.LANCZOS
    return getattr(Image, "LANCZOS", getattr(Image, "BICUBIC", 3))


def _thumbnail_bytes(path: str, *, width: int = 360, height: int = 260, content_fit: bool = False) -> bytes:
    if Image is None:
        raise HTTPException(status_code=415, detail="Pillow nie jest dostepny dla miniaturek.")
    try:
        with Image.open(path) as image:
            try:
                image.seek(0)
            except Exception:
                pass
            work = image.copy()
    except Exception as exc:
        raise HTTPException(status_code=415, detail="Podglad tego formatu nie jest dostepny.") from exc
    if ImageOps is not None:
        try:
            work = ImageOps.exif_transpose(work)
        except Exception:
            pass
    if content_fit:
        try:
            work = fit_image_to_content(work)
        except Exception:
            pass
    work.thumbnail((max(64, width), max(64, height)), _resample_filter())
    if work.mode not in {"RGB", "L"}:
        background = Image.new("RGB", work.size, (255, 255, 255))
        if work.mode in {"RGBA", "LA"}:
            rgba = work.convert("RGBA")
            background.paste(rgba, (0, 0), rgba.getchannel("A"))
        else:
            background.paste(work.convert("RGB"), (0, 0))
        work = background
    elif work.mode == "L":
        work = work.convert("RGB")
    buffer = io.BytesIO()
    work.save(buffer, format="JPEG", quality=82, optimize=True)
    return buffer.getvalue()


def _image_dimensions(path: str) -> tuple[int, int]:
    if Image is None:
        return 0, 0
    try:
        with Image.open(path) as image:
            if ImageOps is not None:
                try:
                    image = ImageOps.exif_transpose(image)
                except Exception:
                    pass
            return int(image.size[0]), int(image.size[1])
    except Exception:
        return 0, 0


def _validate_upload_image_pixels(path: str, max_pixels: int) -> tuple[int, int]:
    width, height = _image_dimensions(path)
    if width <= 0 or height <= 0:
        return width, height
    pixels = int(width) * int(height)
    if pixels > max_pixels:
        _raise_upload_too_large(
            f"Obraz ma {pixels} pikseli ({width}x{height}), limit uploadu to {max_pixels} pikseli."
        )
    return width, height


async def _save_upload(
    upload: UploadFile,
    temp_dir: str,
    prefix: str,
    *,
    managed_root: str | None = None,
) -> str:
    safe_name = _safe_upload_name(upload.filename, f"{prefix}.upload")
    max_bytes, max_pixels = _upload_limits()
    content_type = getattr(upload, "content_type", "")
    try:
        _validate_upload_extension(safe_name)
    except Exception:
        await upload.close()
        raise

    def validate(path: str, _filename: object, limit: int) -> tuple[int, int]:
        return _validate_upload_content(path, safe_name, content_type, limit)

    try:
        staged = await UploadStagingService(
            max_bytes=max_bytes,
            max_pixels=max_pixels,
            validate_image=validate,
            scan_file=_scan_uploaded_file,
        ).stage(upload, temp_dir, prefix, managed_root=managed_root)
    except UploadSizeLimitExceeded as exc:
        _raise_upload_too_large(_upload_limit_message(exc.size_bytes, exc.max_bytes))
    return staged.path


def _upload_prefix_from_form_key(key: str) -> str:
    text = str(key or "").strip()
    if text.startswith("slot_"):
        text = text[5:]
    return sanitize_path_segment(text) or "slot"


async def _materialize_process_form(form: Any, temp_dir: str) -> _ProcessFormSnapshot:
    os.makedirs(temp_dir, exist_ok=True)
    fields: Dict[str, str] = {}
    uploads: Dict[str, _QueuedUploadFile] = {}
    items = form.multi_items() if hasattr(form, "multi_items") else form.items()
    for key, value in items:
        key_text = str(key)
        if isinstance(value, UploadFile):
            if not value.filename:
                continue
            path = await _save_upload(value, temp_dir, _upload_prefix_from_form_key(key_text))
            uploads[key_text] = _QueuedUploadFile(
                path=path,
                filename=_safe_upload_name(value.filename, os.path.basename(path)),
            )
            continue
        fields[key_text] = str(value)
    return _ProcessFormSnapshot(fields=fields, uploads=uploads, temp_dir=temp_dir)


async def _save_upload_cache_entry(
    upload: UploadFile,
    cache_scope: str,
    prefix: str,
    *,
    normalize_extension: bool = False,
) -> _SavedUploadCache:
    safe_name = _safe_upload_name(upload.filename, f"{prefix}.upload")
    stem = Path(safe_name).stem
    suffix = _safe_file_suffix(safe_name)
    safe_prefix = sanitize_path_segment(prefix) or "slot"
    safe_stem = sanitize_path_segment(stem) or "upload"
    safe_stem = safe_stem[:80].strip(" .-_") or "upload"
    cache_dir = _upload_cache_dir(cache_scope)
    os.makedirs(cache_dir, exist_ok=True)
    target_path = os.fspath(
        build_child_path(
            cache_dir,
            f"{safe_prefix}_{secrets.token_hex(12)}_{safe_stem}{suffix}",
        )
    )
    max_bytes, max_pixels = _upload_limits()
    size = 0
    try:
        _validate_upload_extension(safe_name)
        content_type = getattr(upload, "content_type", "")
        with open(target_path, "wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    _raise_upload_too_large(_upload_limit_message(size, max_bytes))
                handle.write(chunk)
        if normalize_extension:
            target_path, safe_name, content_type = _normalize_upload_cache_extension(
                target_path,
                safe_name,
                content_type,
            )
            _validate_upload_extension(safe_name)
        _validate_upload_content(target_path, safe_name, content_type, max_pixels)
        _strip_upload_metadata(target_path, safe_name)
        size = _enforce_upload_size(target_path, max_bytes)
        _scan_uploaded_file(target_path)
        return _SavedUploadCache(target_path, size, safe_name)
    except Exception:
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except OSError:
                pass
        raise
    finally:
        await upload.close()


async def _save_upload_cache(upload: UploadFile, cache_scope: str, prefix: str) -> tuple[str, int]:
    saved = await _save_upload_cache_entry(upload, cache_scope, prefix, normalize_extension=True)
    return saved.path, saved.size


def _save_web_image_cache(
    image_url: str,
    page_url: str,
    cache_scope: str,
    prefix: str,
) -> tuple[str, int, str, int, int]:
    max_bytes, max_pixels = _upload_limits()
    data, filename, _mime_type, width, height = download_image_bytes(
        image_url,
        page_url,
        max_bytes=max_bytes,
        max_pixels=max_pixels,
    )
    safe_name = _safe_upload_name(filename or filename_from_url(image_url), f"{prefix}.jpg")
    _validate_upload_extension(safe_name)
    stem = Path(safe_name).stem
    suffix = _safe_file_suffix(safe_name) or ".jpg"
    safe_prefix = sanitize_path_segment(prefix) or "slot"
    safe_stem = sanitize_path_segment(stem) or "web_image"
    safe_stem = safe_stem[:80].strip(" .-_") or "web_image"
    cache_dir = _upload_cache_dir(cache_scope)
    os.makedirs(cache_dir, exist_ok=True)
    target_path = os.fspath(
        build_child_path(
            cache_dir,
            f"{safe_prefix}_{secrets.token_hex(12)}_{safe_stem}{suffix}",
        )
    )
    with open(target_path, "wb") as handle:
        handle.write(data)
    return target_path, len(data), safe_name, width, height


def _scan_web_image_page(
    page_url: str,
    *,
    mode: str = "metadata",
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    html = fetch_page_html(page_url)
    scan_mode = str(mode or "metadata").strip().lower()
    probe_images = scan_mode not in {"links", "link", "fast"}
    images = discover_image_candidates(
        page_url,
        html,
        probe_images=probe_images,
        filters=filters or {},
    )
    return {
        "source_url": page_url,
        "images": images,
        "count": len(images),
        "mode": "metadata" if probe_images else "links",
    }


def _record_browser_extension_import(username: str, item: Dict[str, Any]) -> None:
    key = str(username or "").strip().lower() or _admin_username().lower()
    with _BROWSER_EXTENSION_IMPORTS_LOCK:
        queue = _BROWSER_EXTENSION_IMPORTS.setdefault(key, [])
        queue.append(item)
        del queue[:-120]


def _pop_browser_extension_imports(username: str) -> List[Dict[str, Any]]:
    key = str(username or "").strip().lower() or _admin_username().lower()
    with _BROWSER_EXTENSION_IMPORTS_LOCK:
        items = list(_BROWSER_EXTENSION_IMPORTS.get(key, []))
        _BROWSER_EXTENSION_IMPORTS[key] = []
    return items


def _browser_extension_cors_headers(request: Request) -> Dict[str, str]:
    origin = str(request.headers.get("origin") or "")
    if origin.startswith(("chrome-extension://", "edge-extension://")):
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "authorization, content-type",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Vary": "Origin",
        }
    return {}


def _browser_extension_json(request: Request, payload: Dict[str, Any]) -> JSONResponse:
    return JSONResponse(payload, headers=_browser_extension_cors_headers(request))


def _browser_extension_defaults(request: Request, username: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    user = find_user(username) or {}
    payload = {
        "panelUrl": base_url,
        "apiToken": _make_browser_extension_token(username),
        "tokenVersion": int(user.get("extension_token_version") or 0),
        "panelVersion": get_display_version(),
    }
    return "window.PICSYNCRA_EXTENSION_DEFAULTS = " + json.dumps(payload, ensure_ascii=False) + ";\n"


def _browser_extension_zip_bytes(request: Request, username: str) -> bytes:
    if not BROWSER_EXTENSION_DIR.is_dir():
        raise HTTPException(status_code=404, detail="Brak plikow rozszerzenia.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        root_name = "picsyncra-browser-extension"
        for path in sorted(BROWSER_EXTENSION_DIR.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(BROWSER_EXTENSION_DIR).as_posix()
            if relative == "defaults.js":
                continue
            archive.write(path, f"{root_name}/{relative}")
        archive.writestr(
            f"{root_name}/defaults.js",
            _browser_extension_defaults(request, username),
        )
    return buffer.getvalue()


def _result_payload(result: Any) -> Dict[str, Any]:
    return {
        "output_dir": result.output_dir,
        "ean": result.ean,
        "saved_files": [
            {
                "prefix": item.prefix,
                "label": item.label,
                "filename_label": item.filename_label,
                "source_name": item.source_name,
                "filename": item.filename,
                "path": item.path,
                "size_bytes": item.size_bytes,
                "source_size_bytes": getattr(item, "source_size_bytes", 0),
                "elapsed_ms": getattr(item, "elapsed_ms", 0),
                "operation": getattr(item, "operation", ""),
                "preprocessed": bool(getattr(item, "preprocessed", False)),
                "content_fit": bool(getattr(item, "content_fit", False)),
            }
            for item in result.saved_files
        ],
        "skipped_slots": result.skipped_slots,
    }


def _remote_name_for_output(filename: str) -> str:
    parsed = parse_slot_filename(filename)
    if not parsed or not parsed.ean:
        return ""
    return f"{parsed.ean}_{parsed.normalized_label}{parsed.extension}"


def _transfer_slot(filename: object) -> str:
    parts = os.path.basename(str(filename or "")).split("_")
    return parts[1].strip()[:40] if len(parts) > 1 else ""


def _sync_result_to_ftp(
    result: Any,
    delete_candidates: Optional[List[str]] = None,
    *,
    skip_upload_prefixes: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    skip_upload_prefixes = {str(prefix) for prefix in (skip_upload_prefixes or set())}
    all_filenames = [
        item.filename
        for item in result.saved_files
        if getattr(item, "filename", "")
    ]
    filenames = [
        filename
        for filename in all_filenames
        if _transfer_slot(filename) not in skip_upload_prefixes
    ]
    uploaded_remote_names = {_remote_name_for_output(filename) for filename in filenames}
    delete_set = {
        os.path.basename(str(item or ""))
        for item in (delete_candidates or [])
        if os.path.basename(str(item or ""))
    }
    delete_set.difference_update({item for item in uploaded_remote_names if item})
    slot_results: dict[str, dict[str, object]] = {}
    for filename in all_filenames:
        slot = _transfer_slot(filename)
        if not slot:
            continue
        slot_results.setdefault(
            slot,
            {
                "slot": slot,
                "upload_status": "not_requested",
                "delete_status": "not_requested",
                "elapsed_ms": 0,
            },
        )["upload_status"] = "skipped" if slot in skip_upload_prefixes else "pending"
    for filename in sorted(delete_set):
        slot = _transfer_slot(filename)
        if not slot:
            continue
        slot_results.setdefault(
            slot,
            {
                "slot": slot,
                "upload_status": "not_requested",
                "delete_status": "not_requested",
                "elapsed_ms": 0,
            },
        )["delete_status"] = "pending"
    if not bool(config.CONFIG.get(ft, True)):
        for item in slot_results.values():
            if item["upload_status"] == "pending":
                item["upload_status"] = "skipped"
            if item["delete_status"] == "pending":
                item["delete_status"] = "skipped"
        return {
            "enabled": False,
            "uploaded": 0,
            "deleted": 0,
            "elapsed_ms": 0,
            "error": "",
            "slot_results": [slot_results[key] for key in sorted(slot_results)],
        }
    if not filenames and not delete_set:
        return {
            "enabled": True,
            "uploaded": 0,
            "deleted": 0,
            "elapsed_ms": 0,
            "error": "",
            "slot_results": [slot_results[key] for key in sorted(slot_results)],
        }
    try:
        payload = sync_remote_files(
            config.CONFIG.get(H, {}),
            result.output_dir,
            filenames,
            sorted(delete_set),
            set(),
        )
    except Exception as exc:
        payload = {"uploaded": 0, "deleted": 0, "elapsed_ms": 0, "error": str(exc)}
    payload["enabled"] = True
    elapsed_ms = max(0, int(payload.get("elapsed_ms") or 0))
    error = bool(payload.get("error"))
    uploaded_count = max(0, int(payload.get("uploaded") or 0))
    deleted_count = max(0, int(payload.get("deleted") or 0))
    upload_status = (
        "uploaded"
        if uploaded_count == len(filenames)
        else "partial"
        if 0 < uploaded_count < len(filenames)
        else "error"
        if error
        else "skipped"
    )
    delete_status = (
        "deleted"
        if deleted_count == len(delete_set)
        else "partial"
        if 0 < deleted_count < len(delete_set)
        else "error"
        if error
        else "skipped"
    )
    for filename in filenames:
        slot = _transfer_slot(filename)
        if slot not in slot_results:
            continue
        slot_results[slot]["upload_status"] = upload_status
        if upload_status == "partial":
            slot_results[slot].update(
                {
                    "upload_count": uploaded_count,
                    "upload_requested": len(filenames),
                    "provider_error": error,
                }
            )
    for filename in sorted(delete_set):
        slot = _transfer_slot(filename)
        if slot not in slot_results:
            continue
        slot_results[slot]["delete_status"] = delete_status
        if delete_status == "partial":
            slot_results[slot].update(
                {
                    "delete_count": deleted_count,
                    "delete_requested": len(delete_set),
                    "provider_error": error,
                }
            )
    for item in slot_results.values():
        item["elapsed_ms"] = elapsed_ms
    payload["slot_results"] = [slot_results[key] for key in sorted(slot_results)]
    return payload


def _safe_sql_identifier(value: object) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(r"[0-9A-Za-z_\.]+", text) else ""


def _sql_row_exists_query(table: str, where_clause: str, db_type: str) -> str:
    if not table:
        return ""
    if str(db_type or "").lower() == str(K).lower():
        query = f"SELECT 1 FROM {table}{where_clause}".rstrip(";\n\r\t ")
        if " limit " not in query.lower():
            query = f"{query} LIMIT 1"
        return query
    return f"SELECT TOP 1 1 FROM {table}{where_clause}".rstrip(";\n\r\t ")


def _cursor_rowcount(cur: Any) -> int:
    try:
        return int(getattr(cur, "rowcount", -1))
    except (TypeError, ValueError):
        return -1


def _sync_result_to_sql(
    result: Any,
    *,
    clear_prefixes: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    saved_by_prefix = {
        str(item.prefix): item.filename
        for item in result.saved_files
        if getattr(item, "filename", "")
    }
    requested_clears = {
        str(prefix) for prefix in (clear_prefixes or set())
    } - set(saved_by_prefix)
    slot_results: dict[str, dict[str, object]] = {
        prefix: {
            "slot": prefix,
            "operation": "update",
            "status": "skipped",
            "elapsed_ms": 0,
        }
        for prefix in saved_by_prefix
    }
    slot_results.update(
        {
            prefix: {
                "slot": prefix,
                "operation": "clear",
                "status": "skipped",
                "elapsed_ms": 0,
            }
            for prefix in requested_clears
        }
    )
    if not bool(config.CONFIG.get(u, True)):
        return {
            "enabled": False,
            "updated": 0,
            "cleared": 0,
            "rows": 0,
            "elapsed_ms": 0,
            "error": "",
            "skipped": False,
            "reason": "",
            "slot_results": [slot_results[key] for key in sorted(slot_results)],
        }
    started = time.perf_counter()
    ean = str(getattr(result, "ean", "") or "").strip()
    payload = {
        "enabled": True,
        "updated": 0,
        "cleared": 0,
        "rows": 0,
        "elapsed_ms": 0,
        "error": "",
        "skipped": False,
        "reason": "",
        "slot_results": [],
    }
    if not (ean and len(ean) == 13 and ean.isdigit()):
        payload["error"] = "SQL pominiety: brak poprawnego EAN-13."
        for item in slot_results.values():
            item["status"] = "error"
        payload["slot_results"] = [slot_results[key] for key in sorted(slot_results)]
        return payload
    sql_map = config.CONFIG.get(SQL_COLUMN_MAP_KEY, {}) or {}
    context = extract_presence_context(config.CONFIG, ean)
    if not context:
        payload["error"] = "SQL pominiety: nie mozna ustalic tabeli/warunku z zapytania."
        for item in slot_results.values():
            item["status"] = "error"
        payload["slot_results"] = [slot_results[key] for key in sorted(slot_results)]
        return payload
    table, where_clause = context
    clear_prefixes = requested_clears
    if not saved_by_prefix and not clear_prefixes:
        payload["slot_results"] = []
        return payload
    conn = None
    cur = None
    attempted_slots: set[str] = set()
    try:
        conn = connect_db()
        cur = conn.cursor()
        row_exists_query = _sql_row_exists_query(table, where_clause, config.CONFIG.get(p, K))
        if row_exists_query:
            cur.execute(row_exists_query)
            if not cur.fetchone():
                payload["skipped"] = True
                payload["reason"] = "nie znaleziono wiersza produktu dla tego EAN"
                payload["slot_results"] = [slot_results[key] for key in sorted(slot_results)]
                return payload
        template = str(config.CONFIG.get(w, "") or "").strip()
        if not template:
            payload["skipped"] = True
            payload["reason"] = "nie skonfigurowano zapytania SQL"
            payload["slot_results"] = [slot_results[key] for key in sorted(slot_results)]
            return payload
        batch_assignments: dict[str, str] = {}
        batch_operations: dict[str, str] = {}
        for prefix, filename in saved_by_prefix.items():
            column = _safe_sql_identifier(sql_map.get(prefix, ""))
            parsed = parse_slot_filename(filename)
            if not column or not parsed:
                continue
            batch_assignments[column] = f"{ean}_{prefix}{parsed.extension}"
            batch_operations[str(prefix)] = "update"
        for prefix in clear_prefixes:
            column = _safe_sql_identifier(sql_map.get(prefix, ""))
            if not column:
                continue
            batch_assignments[column] = ""
            batch_operations[str(prefix)] = "clear"
        batch = build_photo_sql_batch(
            table,
            where_clause,
            batch_assignments,
            config.CONFIG.get(p, K),
            template,
        )
        if batch is not None:
            attempted_slots.update(batch_operations)
            cur.execute(batch.query, batch.params)
            rowcount = _cursor_rowcount(cur)
            if rowcount != 0:
                for prefix, operation in batch_operations.items():
                    payload["updated" if operation == "update" else "cleared"] += 1
                    slot_results[prefix]["status"] = (
                        "updated" if operation == "update" else "cleared"
                    )
            if rowcount > 0:
                payload["rows"] += rowcount
        else:
            for prefix, filename in saved_by_prefix.items():
                column = _safe_sql_identifier(sql_map.get(prefix, ""))
                if not column:
                    continue
                parsed = parse_slot_filename(filename)
                if not parsed:
                    continue
                short_name = f"{ean}_{prefix}{parsed.extension}"
                query = template.format(col=column, column=column, filename=short_name, ean=ean)
                attempted_slots.add(str(prefix))
                cur.execute(query)
                rowcount = _cursor_rowcount(cur)
                if rowcount != 0:
                    payload["updated"] += 1
                    slot_results[str(prefix)]["status"] = "updated"
                if rowcount > 0:
                    payload["rows"] += rowcount
            for prefix in clear_prefixes:
                column = _safe_sql_identifier(sql_map.get(prefix, ""))
                if not column:
                    continue
                attempted_slots.add(str(prefix))
                cur.execute(f"UPDATE {table} SET {column} = ''{where_clause}")
                rowcount = _cursor_rowcount(cur)
                if rowcount != 0:
                    payload["cleared"] += 1
                    slot_results[str(prefix)]["status"] = "cleared"
                if rowcount > 0:
                    payload["rows"] += rowcount
        if payload["updated"] or payload["cleared"]:
            conn.commit()
    except Exception as exc:
        payload["error"] = str(exc)
        payload["updated"] = 0
        payload["cleared"] = 0
        payload["rows"] = 0
        rollback_succeeded = False
        if conn is not None:
            try:
                conn.rollback()
                rollback_succeeded = True
            except Exception:
                pass
        payload["rolled_back"] = rollback_succeeded
        for slot, item in slot_results.items():
            was_successful = item["status"] in {"updated", "cleared"}
            item.update(
                {
                    "status": "error",
                    "provider": "sql",
                    "reason": str(exc),
                    "attempted": slot in attempted_slots,
                    "rolled_back": rollback_succeeded and was_successful,
                }
            )
    finally:
        payload["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        for item in slot_results.values():
            item["elapsed_ms"] = payload["elapsed_ms"]
        payload["slot_results"] = [slot_results[key] for key in sorted(slot_results)]
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return payload


def _ftp_skip_upload_prefixes(
    result: Any,
    existing_photos: List[Dict[str, Any]],
    *,
    explicit_prefixes: Set[str],
    migrated_prefixes: Set[str],
    ftp_backfill_prefixes: Set[str],
) -> Set[str]:
    """Return saved prefixes that do not need a remote upload."""

    skip = {str(prefix) for prefix in ftp_backfill_prefixes if str(prefix)}
    explicit = {str(prefix) for prefix in explicit_prefixes if str(prefix)}
    migrated = {str(prefix) for prefix in migrated_prefixes if str(prefix)}
    photos_by_prefix = {
        str(photo.get("prefix") or ""): photo
        for photo in existing_photos
        if str(photo.get("prefix") or "")
    }
    for item in getattr(result, "saved_files", []) or []:
        prefix = str(getattr(item, "prefix", "") or "")
        if not prefix or prefix in skip or prefix in explicit or prefix in migrated:
            continue
        if photos_by_prefix.get(prefix, {}).get("ftp"):
            skip.add(prefix)
    return skip


def _ftp_replacement_delete_candidates(
    result: Any,
    existing_photos: List[Dict[str, Any]],
    *,
    explicit_prefixes: Set[str],
) -> List[str]:
    """Return old remote files replaced by explicit slot changes."""

    explicit = {str(prefix) for prefix in explicit_prefixes if str(prefix)}
    photos_by_prefix = {
        str(photo.get("prefix") or ""): photo
        for photo in existing_photos
        if str(photo.get("prefix") or "")
    }
    delete_candidates: List[str] = []
    for item in getattr(result, "saved_files", []) or []:
        prefix = str(getattr(item, "prefix", "") or "")
        if not prefix or prefix not in explicit:
            continue
        current_remote = os.path.basename(
            str(photos_by_prefix.get(prefix, {}).get("ftp_filename") or "")
        )
        if not current_remote:
            continue
        expected_remote = _remote_name_for_output(str(getattr(item, "filename", "") or ""))
        if expected_remote and current_remote != expected_remote:
            delete_candidates.append(current_remote)
    return delete_candidates


def _delete_local_files(delete_requests: List[Dict[str, Any]], saved_paths: Set[str]) -> Dict[str, Any]:
    payload = {"deleted": 0, "skipped": 0, "errors": [], "slot_results": []}
    normalized_saved_paths = {os.path.normcase(os.path.abspath(path)) for path in saved_paths}
    for item in delete_requests:
        slot_started = time.perf_counter()
        slot = str(item.get("prefix") or "").strip()
        path = str(item.get("local_path") or "")
        if not path:
            if slot:
                payload["slot_results"].append(
                    {"slot": slot, "status": "skipped", "elapsed_ms": 0}
                )
            continue
        try:
            abs_path = os.fspath(resolve_path_within_roots(path, _file_token_roots()))
        except PathSecurityError:
            payload["skipped"] += 1
            if slot:
                payload["slot_results"].append(
                    {"slot": slot, "status": "skipped", "elapsed_ms": 0}
                )
            continue
        status = "skipped"
        if os.path.normcase(abs_path) in normalized_saved_paths:
            payload["skipped"] += 1
        else:
            try:
                if os.path.isfile(abs_path):
                    os.remove(abs_path)
                    payload["deleted"] += 1
                    status = "deleted"
                else:
                    payload["skipped"] += 1
            except Exception as exc:
                status = "error"
                payload["errors"].append(f"{os.path.basename(abs_path)}: {exc}")
        if slot:
            payload["slot_results"].append(
                {
                    "slot": slot,
                    "status": status,
                    "elapsed_ms": int((time.perf_counter() - slot_started) * 1000),
                }
            )
    return payload


def _local_slot_results(
    saved_files: List[Dict[str, Any]], local_delete_result: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Keep save and delete evidence as distinct operations for each slot."""

    evidence = [
        {
            "slot": str(item.get("prefix") or ""),
            "operation": "save",
            "status": "saved",
            "elapsed_ms": max(0, int(item.get("elapsed_ms") or 0)),
        }
        for item in saved_files
        if str(item.get("prefix") or "")
    ]
    for item in local_delete_result.get("slot_results", []):
        if not isinstance(item, dict) or not str(item.get("slot") or ""):
            continue
        evidence.append({**item, "operation": "delete"})
    return evidence


def _entry_payload_from_product(product: WebProductForm) -> Dict[str, Any]:
    return {
        "product_id": product.product_id,
        "ean": product.ean,
        "name": product.name,
        "type_name": product.type_name,
        "model": product.model,
        "color1": product.color1,
        "color2": product.color2,
        "color3": product.color3,
        "extra": product.extra,
    }


def _form_from_entry_payload(entry: Dict[str, Any]) -> WebProductForm:
    return WebProductForm(
        name=str(entry.get("name") or ""),
        type_name=str(entry.get("type_name") or ""),
        model=str(entry.get("model") or ""),
        color1=str(entry.get("color1") or ""),
        color2=str(entry.get("color2") or ""),
        color3=str(entry.get("color3") or ""),
        extra=str(entry.get("extra") or ""),
        ean=str(entry.get("ean") or ""),
        product_id=str(entry.get("product_id") or ""),
    )


def _output_identity(form: WebProductForm) -> tuple[str, str]:
    payload = normalized_product_payload(form, _active_product_field_settings())
    output_dir = build_product_directory(
        settings.l,
        payload["name"],
        payload["type_name"],
        payload["model"],
        payload["colors"],
        payload["extra"],
    )
    return os.path.normcase(os.path.abspath(output_dir)), str(payload["ean"] or "").upper()


def _should_migrate_existing_photos(
    existing_entry: Optional[Dict[str, Any]],
    product: WebProductForm,
) -> bool:
    if not existing_entry:
        return False
    return _output_identity(_form_from_entry_payload(existing_entry)) != _output_identity(product)


def _download_ftp_photo_source(
    photo: Dict[str, Any],
    fallback_ean: str,
    *,
    cache_scope: str = "",
) -> str:
    ftp_filename = os.path.basename(str(photo.get("ftp_filename") or ""))
    ftp_ean = str(photo.get("ean") or fallback_ean or "").strip()
    if not ftp_filename or not ftp_ean:
        return ""
    try:
        return cache_ftp_preview(ftp_ean, ftp_filename, cache_scope=cache_scope)
    except ValueError as exc:
        raise ValueError(f"Nie udalo sie pobrac pliku FTP {ftp_filename}: {exc}") from exc


def _same_existing_source(source_path: str, upload: WebUploadedSlot, photo: Dict[str, Any]) -> bool:
    upload_path = str(upload.source_path or "")
    if source_path and upload_path:
        try:
            return os.path.samefile(source_path, upload_path)
        except OSError:
            return os.path.normcase(os.path.abspath(source_path)) == os.path.normcase(
                os.path.abspath(upload_path)
            )
    ftp_filename = os.path.basename(str(photo.get("ftp_filename") or ""))
    return bool(ftp_filename and ftp_filename == os.path.basename(str(upload.original_filename or "")))


def _photo_source_labels(photo: Dict[str, Any]) -> List[str]:
    labels: List[str] = []
    if photo.get("local"):
        labels.append("LOCAL")
    if photo.get("ftp"):
        labels.append("FTP")
    if photo.get("sql"):
        labels.append("SQL")
    return labels or ["nieznane"]


def _photo_has_file_source(photo: Dict[str, Any]) -> bool:
    return bool(
        photo.get("path")
        or photo.get("filename")
        or photo.get("ftp_path")
        or photo.get("ftp_filename")
    )


def _existing_photo_conflicts(
    photos: List[Dict[str, Any]],
    uploaded_slots: List[WebUploadedSlot],
    delete_requests: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    uploaded_by_prefix = {str(slot.prefix): slot for slot in uploaded_slots}
    delete_prefixes = {str(item.get("prefix") or "") for item in delete_requests}
    conflicts: List[Dict[str, Any]] = []
    for photo in photos:
        if not _photo_has_file_source(photo):
            continue
        prefix = str(photo.get("prefix") or "").strip()
        if not prefix or prefix not in uploaded_by_prefix or prefix in delete_prefixes:
            continue
        if photo.get("ftp") and not photo.get("local"):
            continue
        source_path = str(photo.get("path") or "").strip()
        source_path = source_path if source_path and os.path.isfile(source_path) else ""
        upload = uploaded_by_prefix[prefix]
        if _same_existing_source(source_path, upload, photo):
            continue
        conflicts.append(
            {
                "prefix": prefix,
                "sources": _photo_source_labels(photo),
                "filename": photo.get("filename") or photo.get("ftp_filename") or photo.get("sql_value") or "",
            }
        )
    return conflicts


def _format_existing_photo_conflicts(conflicts: List[Dict[str, Any]]) -> str:
    parts = []
    for item in conflicts:
        sources = "/".join(str(source) for source in item.get("sources", []))
        parts.append(f"{item.get('prefix')} ({sources})")
    return (
        "Znaleziono juz istniejace zdjecia dla wpisanych danych w slotach: "
        f"{', '.join(parts)}. Wczytaj istniejace zdjecia albo usun wybrane sloty przed "
        "ponownym przetworzeniem."
    )


def _process_event_details(
    product: WebProductForm,
    uploaded_slots: List[WebUploadedSlot],
    delete_requests: List[Dict[str, Any]],
    **extra: Any,
) -> Dict[str, Any]:
    details: Dict[str, Any] = {
        "product_id": product.product_id,
        "ean": product.ean,
        "name": product.name,
        "type": product.type_name,
        "model": product.model,
        "colors": [product.color1, product.color2, product.color3],
        "extra": product.extra,
        "uploaded_slots": [slot.prefix for slot in uploaded_slots],
        "delete_slots": [str(item.get("prefix") or "") for item in delete_requests],
    }
    details.update(extra)
    return details


def _append_existing_photo_sources(
    *,
    existing_entry: Optional[Dict[str, Any]],
    product: WebProductForm,
    uploaded_slots: List[WebUploadedSlot],
    delete_requests: List[Dict[str, Any]],
    slot_by_prefix: Dict[str, Dict[str, str]],
    existing_photos: Optional[List[Dict[str, Any]]] = None,
    cache_scope: str = "",
) -> List[str]:
    """Add existing local/FTP photos that need to be processed by the web form."""

    source_entry = existing_entry or _entry_payload_from_product(product)
    if not source_entry:
        return []
    identity_changed = bool(existing_entry) and _should_migrate_existing_photos(existing_entry, product)
    occupied_prefixes = {slot.prefix for slot in uploaded_slots}
    delete_prefixes = {str(item.get("prefix") or "") for item in delete_requests}
    appended: List[str] = []
    photos = existing_photos
    if photos is None:
        photos = find_product_photos(
            source_entry,
            include_local=True,
            include_ftp=bool(config.CONFIG.get(ft, True)),
            include_sql=True,
        )
    for photo in photos:
        prefix = str(photo.get("prefix") or "").strip()
        path = str(photo.get("path") or "").strip()
        ftp_filename = os.path.basename(str(photo.get("ftp_filename") or ""))
        if not prefix or prefix in delete_prefixes:
            continue
        slot = slot_by_prefix.get(prefix, {"prefix": prefix, "label": prefix})
        label = str(slot.get("label") or prefix)
        filename_label = str(slot.get("filename_label") or "")
        source_path = path if path and os.path.isfile(path) else ""
        had_local_source = bool(source_path)
        needs_sql_update = bool(photo.get("sql_checked")) and not bool(photo.get("sql"))
        append_delete_request = False
        if prefix in occupied_prefixes:
            if identity_changed:
                delete_requests.append(
                    {
                        "prefix": prefix,
                        "label": label,
                        "local_path": source_path,
                        "ftp_filename": ftp_filename,
                        "sql": False,
                        "migration": True,
                    }
                )
                delete_prefixes.add(prefix)
            continue
        should_process = False
        if identity_changed and source_path:
            should_process = True
        elif source_path and bool(config.CONFIG.get(ft, True)) and not bool(photo.get("ftp")):
            should_process = True
            append_delete_request = True
        elif ftp_filename and not source_path:
            source_path = _download_ftp_photo_source(
                photo,
                str(source_entry.get("ean") or product.ean or ""),
                cache_scope=cache_scope,
            )
            should_process = bool(source_path and os.path.isfile(source_path))
            append_delete_request = should_process
        elif source_path and needs_sql_update:
            should_process = True
        if not should_process:
            continue
        if prefix not in occupied_prefixes and prefix not in delete_prefixes:
            uploaded_slots.append(
                WebUploadedSlot(
                    prefix=prefix,
                    label=label,
                    filename_label=filename_label,
                    source_path=source_path,
                    original_filename=(
                        os.path.basename(source_path)
                        if had_local_source
                        else ftp_filename or os.path.basename(source_path)
                    ),
                )
            )
            occupied_prefixes.add(prefix)
            appended.append(prefix)
        if prefix not in delete_prefixes and (identity_changed or append_delete_request):
            delete_requests.append(
                {
                    "prefix": prefix,
                    "label": label,
                    "local_path": path if path and os.path.isfile(path) else "",
                    "ftp_filename": ftp_filename,
                    "sql": False,
                    "migration": identity_changed,
                    "ftp_backfill": bool(ftp_filename and not had_local_source),
                }
            )
            delete_prefixes.add(prefix)
    return appended


def _append_existing_photo_migrations(
    *,
    existing_entry: Optional[Dict[str, Any]],
    product: WebProductForm,
    uploaded_slots: List[WebUploadedSlot],
    delete_requests: List[Dict[str, Any]],
    slot_by_prefix: Dict[str, Dict[str, str]],
    existing_photos: Optional[List[Dict[str, Any]]] = None,
    cache_scope: str = "",
) -> List[str]:
    """Backward-compatible wrapper for tests and older call sites."""

    return _append_existing_photo_sources(
        existing_entry=existing_entry,
        product=product,
        uploaded_slots=uploaded_slots,
        delete_requests=delete_requests,
        slot_by_prefix=slot_by_prefix,
        existing_photos=existing_photos,
        cache_scope=cache_scope,
    )


def _append_pending_ftp_slots(
    *,
    product: WebProductForm,
    pending_ftp_slots: List[Dict[str, Any]],
    uploaded_slots: List[WebUploadedSlot],
    delete_requests: List[Dict[str, Any]],
    cache_scope: str = "",
) -> List[str]:
    """Download FTP-only selected slots so they can be saved like uploaded files."""

    occupied_prefixes = {slot.prefix for slot in uploaded_slots}
    appended: List[str] = []
    for item in pending_ftp_slots:
        prefix = str(item.get("prefix") or "")
        if not prefix or prefix in occupied_prefixes:
            continue
        ftp_filename = os.path.basename(str(item.get("filename") or ""))
        ftp_ean = str(item.get("ean") or product.ean or "").strip()
        try:
            source_path = cache_ftp_preview(ftp_ean, ftp_filename, cache_scope=cache_scope)
        except ValueError as exc:
            raise ValueError(
                f"Nie udalo sie pobrac pliku FTP {ftp_filename}: {exc}"
            ) from exc
        uploaded_slots.append(
            WebUploadedSlot(
                prefix=prefix,
                label=str(item.get("label") or prefix),
                filename_label=str(item.get("filename_label") or ""),
                source_path=source_path,
                original_filename=ftp_filename,
                content_fit=item.get("content_fit"),
            )
        )
        occupied_prefixes.add(prefix)
        appended.append(prefix)
        if ftp_filename:
            delete_requests.append(
                {
                    "prefix": prefix,
                    "label": str(item.get("label") or prefix),
                    "local_path": "",
                    "ftp_filename": ftp_filename,
                    "sql": False,
                    "ftp_backfill": False,
                }
            )
    return appended


def _read_log_tail(path: str, limit: int = 300) -> Dict[str, Any]:
    line_limit = max(1, min(2000, int(limit or 300)))
    log_path = Path(path)
    payload: Dict[str, Any] = {"path": str(log_path), "exists": log_path.exists(), "lines": []}
    if not log_path.exists():
        return payload
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            payload["lines"] = [_clean_log_line(line.rstrip("\r\n")) for line in handle.readlines()[-line_limit:]]
    except OSError as exc:
        payload["error"] = str(exc)
    return payload


ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
CONTROL_LOG_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
HTTP_ACCESS_RE = re.compile(r'"[A-Z]+ [^"]+ HTTP/[0-9.]+"\s+(\d{3})\s+\w+')
PLAIN_LOG_START_RE = re.compile(r"^(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL):\s+", re.IGNORECASE)
TIMESTAMP_LOG_START_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}")


def _clean_log_line(line: str) -> str:
    text = ANSI_ESCAPE_RE.sub("", str(line))
    return sanitize_free_text(CONTROL_LOG_RE.sub("", text))


def _http_statuses(lines: List[str]) -> List[int]:
    statuses: List[int] = []
    for line in lines:
        for match in HTTP_ACCESS_RE.finditer(line):
            try:
                statuses.append(int(match.group(1)))
            except ValueError:
                pass
    return statuses


def _web_events_log_path() -> Path:
    return Path(settings.LOG_DIR) / "picsyncra_web_events.log"


def _safe_event_detail(value: Any) -> str:
    text = (
        sanitize_free_text(value)
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )
    return re.sub(r"\s+", " ", text)


def _write_web_event(
    *,
    level: str,
    event: str,
    username: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    log_path = _web_events_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_text = str(level or "INFO").strip().upper()
        event_text = _safe_event_detail(event).upper() or "WEB_EVENT"
        user_text = _safe_event_detail(username) or "unknown"
        message_text = _safe_event_detail(message)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] [USER: {user_text}] {level_text}: {event_text} - {message_text}\n")
            safe_details = redact_sensitive_value(details or {})
            if isinstance(safe_details, dict) and safe_details:
                handle.write(
                    "details: "
                    + json.dumps(
                        safe_details,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    )
                    + "\n"
                )
    except OSError:
        pass


def _log_event_summary(line: str) -> str:
    text = _clean_log_line(line)
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    text = re.sub(r"^(DEBUG|ERROR|WARNING|WARN|INFO|CRITICAL):\s*", "", text, flags=re.IGNORECASE)
    return text.strip() or line.strip()


def _log_event_severity(source_key: str, lines: List[str]) -> str:
    text = "\n".join(lines)
    lowered = text.lower()
    first_line = lines[0] if lines else ""
    statuses = _http_statuses(lines)
    if statuses:
        max_status = max(statuses)
        if max_status >= 500:
            return "critical"
        if max_status >= 400:
            return "warning"
    if source_key == "web_events":
        level_match = re.search(
            r"\]\s*(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL):\s*",
            first_line,
            re.IGNORECASE,
        )
        level = level_match.group(1).upper() if level_match else ""
        if level in {"CRITICAL", "ERROR"}:
            return "critical"
        if level in {"WARNING", "WARN"}:
            return "warning"
        return "info"
    if source_key == "web_err" and re.search(
        r"\b(CRITICAL|ERROR|Traceback|Exception|failed)\b", text, re.IGNORECASE
    ):
        return "critical"
    if source_key == "errors":
        if "traceback" in lowered or "exception" in lowered or "web " in lowered:
            return "critical"
        return "warning"
    if any(marker in lowered for marker in (" error", "blad", "failed", "exception")):
        return "warning"
    return "info"


def _parse_log_events(log_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    key = str(log_payload.get("key") or "")
    label = str(log_payload.get("label") or key)
    path = str(log_payload.get("path") or "")
    events: List[Dict[str, Any]] = []
    current: Optional[List[str]] = None

    def _append_current() -> None:
        nonlocal current
        if not current:
            return
        first_line = current[0]
        timestamp_match = re.match(r"^\[([^\]]+)\]", first_line)
        timestamp = timestamp_match.group(1) if timestamp_match else ""
        digest = hashlib.sha1(f"{key}|{first_line}|{len(current)}".encode("utf-8")).hexdigest()
        severity = _log_event_severity(key, current)
        events.append(
            {
                "id": digest,
                "source": key,
                "source_label": label,
                "path": path,
                "time": timestamp,
                "order": len(events),
                "severity": severity,
                "summary": _log_event_summary(first_line),
                "lines": list(current),
            }
        )
        current = None

    for raw_line in log_payload.get("lines", []) or []:
        line = _clean_log_line(str(raw_line))
        if not line.strip():
            continue
        if TIMESTAMP_LOG_START_RE.match(line) or PLAIN_LOG_START_RE.match(line):
            _append_current()
            current = [line]
        elif current is not None:
            current.append(line)
        else:
            current = [line]
    _append_current()
    return events


def _logs_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    latest_critical = next((event for event in events if event.get("severity") == "critical"), None)
    latest_warning = next((event for event in events if event.get("severity") == "warning"), None)
    return {
        "critical_count": sum(1 for event in events if event.get("severity") == "critical"),
        "warning_count": sum(1 for event in events if event.get("severity") == "warning"),
        "latest_critical_id": latest_critical.get("id") if latest_critical else "",
        "latest_warning_id": latest_warning.get("id") if latest_warning else "",
    }


def _log_targets() -> List[Dict[str, Any]]:
    return [
        {"key": "web_events", "label": "Zdarzenia web", "path": _web_events_log_path()},
        {"key": "errors", "label": "Bledy i exception", "path": settings.AM},
        {"key": "changes", "label": "Zmiany systemowe", "path": settings.BM},
        {"key": "web_out", "label": "Web stdout", "path": Path(settings.LOG_DIR) / "picsyncra_web_out.log"},
        {"key": "web_err", "label": "Web stderr", "path": Path(settings.LOG_DIR) / "picsyncra_web_err.log"},
    ]


def _is_system_change_event(event: Dict[str, Any]) -> bool:
    if event.get("source") != "changes":
        return True
    raw_text = "\n".join(str(line) for line in event.get("lines", [])).lower()
    plain_text = unicodedata.normalize("NFKD", raw_text).encode("ascii", "ignore").decode("ascii")
    text = f"{raw_text}\n{plain_text}"
    product_markers = (
        "excel entry",
        "wpis ean",
        " ean ",
        "added value",
        "removed value",
        "dodano wartosc",
        "usunieto wartosc",
        "added/modified image",
        "added/modified file",
        "dodano/zmodyfikowano obraz",
        "dodano/zmodyfikowano plik",
        "renamed file",
        "wysylanie pliku",
        "wysylanie plikow",
        "uploading file",
        "sending files",
    )
    if any(marker in text for marker in product_markers):
        return False
    system_markers = (
        "settings",
        "ustawien",
        "ustawienie",
        "config",
        "konfigur",
        "sql",
        "index",
        "admin",
        "administrator",
        "slot_def",
        "field definition",
        "photo field",
        "pola zdjec",
        "pol zdjec",
        "code_check",
        "ui_check",
        "connection",
        "polaczenie",
        "runtime",
        "local_settings",
    )
    return any(marker in text for marker in system_markers)


def _is_relevant_web_runtime_event(event: Dict[str, Any]) -> bool:
    if event.get("source") not in {"web_out", "web_err"}:
        return True
    text = "\n".join(str(line) for line in event.get("lines", [])).lower()
    routine_markers = (
        "started server process",
        "waiting for application startup",
        "application startup complete",
        "uvicorn running on",
        "press ctrl+c to quit",
    )
    if any(marker in text for marker in routine_markers):
        return False
    statuses = _http_statuses([str(line) for line in event.get("lines", [])])
    if statuses and max(statuses) < 500:
        return False
    return True


def _is_visible_log_event(event: Dict[str, Any]) -> bool:
    return _is_system_change_event(event) and _is_relevant_web_runtime_event(event)


def _log_payloads(limit: int) -> List[Dict[str, Any]]:
    logs: List[Dict[str, Any]] = []
    for target in _log_targets():
        payload = {
            "key": target["key"],
            "label": target["label"],
            **_read_log_tail(target["path"], limit),
        }
        events = [event for event in _parse_log_events(payload) if _is_visible_log_event(event)]
        events.reverse()
        payload["events"] = events
        payload["event_count"] = len(events)
        payload["critical_count"] = sum(1 for event in events if event.get("severity") == "critical")
        payload["warning_count"] = sum(1 for event in events if event.get("severity") == "warning")
        logs.append(payload)
    return logs


def _clear_log_files() -> Dict[str, Any]:
    cleared: List[str] = []
    errors: List[str] = []
    for target in _log_targets():
        path = Path(target["path"])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
            cleared.append(str(path))
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    return {"cleared": cleared, "errors": errors}


def _logs_response(limit: int) -> Dict[str, Any]:
    logs = _log_payloads(limit)
    events = [event for log in logs for event in log.get("events", [])]
    events.sort(
        key=lambda item: (str(item.get("time") or ""), int(item.get("order") or 0)),
        reverse=True,
    )
    return {"logs": logs, "events": events, "summary": _logs_summary(events)}


def _snapshot_entry_payload(form: _ProcessFormSnapshot) -> Dict[str, str]:
    return {
        "product_id": str(form.get("product_id") or ""),
        "name": str(form.get("name") or ""),
        "type_name": str(form.get("type_name") or ""),
        "model": str(form.get("model") or ""),
        "color1": str(form.get("color1") or ""),
        "color2": str(form.get("color2") or ""),
        "color3": str(form.get("color3") or ""),
        "extra": str(form.get("extra") or ""),
        "ean": str(form.get("ean") or ""),
    }


def _process_entry_label(entry: Dict[str, Any]) -> str:
    colors = " / ".join(
        str(entry.get(key) or "").strip()
        for key in ("color1", "color2", "color3")
        if str(entry.get(key) or "").strip()
    )
    parts = [
        str(entry.get("name") or "").strip(),
        str(entry.get("type_name") or "").strip(),
        str(entry.get("model") or "").strip(),
        colors,
        str(entry.get("extra") or "").strip(),
    ]
    suffix = str(entry.get("ean") or entry.get("product_id") or "").strip()
    label = " | ".join(part for part in parts if part)
    return f"{label} - {suffix}" if label and suffix else label or suffix or "bez identyfikatora"


def _process_warning_messages(payload: Dict[str, Any]) -> List[str]:
    messages: List[str] = []
    ftp_payload = payload.get("ftp") if isinstance(payload.get("ftp"), dict) else {}
    sql_payload = payload.get("sql") if isinstance(payload.get("sql"), dict) else {}
    local_delete = payload.get("local_delete") if isinstance(payload.get("local_delete"), dict) else {}
    if ftp_payload.get("error"):
        messages.append(f"FTP: {ftp_payload.get('error')}")
    if sql_payload.get("error"):
        messages.append(f"SQL: {sql_payload.get('error')}")
    local_errors = local_delete.get("errors") if isinstance(local_delete, dict) else []
    if local_errors:
        messages.append("Usuwanie lokalne: " + "; ".join(str(item) for item in local_errors))
    skipped = payload.get("skipped_slots") or []
    if skipped:
        messages.append("Pominiete sloty: " + ", ".join(str(item) for item in skipped))
    return messages


def _snapshot_existing_photos(photos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Copy pre-mutation file metadata, including known local file sizes."""

    snapshot: List[Dict[str, Any]] = []
    for photo in photos:
        item = dict(photo)
        size: Optional[int] = None
        path = str(item.get("path") or "").strip()
        if path and os.path.isfile(path):
            try:
                size = os.path.getsize(path)
            except OSError:
                size = None
        elif isinstance(item.get("size_bytes"), int) and not isinstance(
            item.get("size_bytes"), bool
        ):
            size = max(0, int(item["size_bytes"]))
        item["size_bytes"] = size
        snapshot.append(item)
    return snapshot


def _emit_process_integration_events(
    *,
    username: str,
    job_id: str,
    ean: str,
    ftp_result: Dict[str, Any],
    sql_result: Dict[str, Any],
) -> None:
    for name, result, count_keys in (
        ("ftp", ftp_result, ("uploaded", "deleted")),
        ("sql", sql_result, ("updated", "cleared", "rows")),
    ):
        enabled = bool(result.get("enabled"))
        error = str(result.get("error") or "")
        status = "disabled" if not enabled else "error" if error else "success"
        details = {
            "enabled": enabled,
            "status": status,
            "elapsed_ms": int(result.get("elapsed_ms") or 0),
            "error": error,
        }
        details.update({key: int(result.get(key) or 0) for key in count_keys})
        emit_event(
            severity="error" if enabled and error else "info",
            event_type=f"integration.{name}.completed",
            module="web.process",
            stage=name,
            username=username,
            ean=ean,
            job_id=job_id,
            summary=f"Integracja {name.upper()}: {status}.",
            details=details,
        )


def _emit_process_stage_started_once(
    emitted_stages: Set[str],
    *,
    current_key: str,
    current_label: str,
    percent: int,
    label: str,
    username: str,
    job_id: str,
) -> None:
    if not current_key or current_key in emitted_stages:
        return
    emitted_stages.add(current_key)
    emit_event(
        severity="info",
        event_type="process.stage_started",
        module="web.process",
        stage=current_key,
        username=username,
        job_id=job_id,
        summary=current_label or label,
        details={"percent": percent, "label": label},
    )


def _process_upload_snapshot(
    *,
    username: str,
    cache_scope: str,
    form: _ProcessFormSnapshot,
    job_id: str = "",
    cancel_event: threading.Event | None = None,
    progress: Optional[
        Callable[[int, str, List[Dict[str, Any]], Optional[Dict[str, Any]]], None]
    ] = None,
) -> Dict[str, Any]:
    emitted_stages: Set[str] = set()

    def mark(
        percent: int,
        label: str,
        *,
        current_key: str = "",
        current_label: str = "",
    ) -> None:
        _emit_process_stage_started_once(
            emitted_stages,
            current_key=current_key,
            current_label=current_label,
            percent=percent,
            label=label,
            username=username,
            job_id=job_id,
        )
        if progress:
            current_stage = None
            if current_key:
                current_stage = {
                    "key": current_key,
                    "label": current_label or label,
                    "started_at": time.time(),
                    "elapsed_ms": 0,
                    "running": True,
                }
            progress(percent, label, list(timings), current_stage)

    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise _ProcessJobCancelled()

    check_cancelled()
    process_started = time.perf_counter()
    timings: List[Dict[str, Any]] = []
    stage_started = time.perf_counter()
    mark(4, "Przygotowanie danych", current_key="prepare", current_label="Przygotowanie danych i slotow")
    slots = slot_definitions_from_config(config.CONFIG)
    slot_by_prefix = {slot["prefix"]: slot for slot in slots}
    uploaded_slots: List[WebUploadedSlot] = []
    delete_requests: List[Dict[str, Any]] = []
    pending_ftp_slots: List[Dict[str, Any]] = []
    explicit_slot_prefixes: Set[str] = set()
    product: Optional[WebProductForm] = None
    field_settings = _active_product_field_settings()
    antivirus_scan_result: Dict[str, Any] = {"enabled": False, "scanned": 0, "skipped": 0, "items": []}
    try:
        for prefix, slot in slot_by_prefix.items():
            check_cancelled()
            if str(form.get(f"delete_slot_{prefix}") or "") == "1":
                delete_item: Dict[str, Any] = {
                    "prefix": prefix,
                    "label": slot["label"],
                    "local_path": "",
                    "ftp_filename": os.path.basename(str(form.get(f"delete_ftp_slot_{prefix}") or "")),
                    "sql": str(form.get(f"delete_sql_slot_{prefix}") or "") == "1",
                }
                local_token = str(form.get(f"delete_local_slot_{prefix}") or "").strip()
                if local_token:
                    delete_item["local_path"] = _path_from_file_token(
                        local_token,
                        require_exists=False,
                    )
                delete_requests.append(delete_item)
            token = str(form.get(f"existing_slot_{prefix}") or "").strip()
            if token:
                source_path = _path_from_file_token(token)
                original_filename = _safe_upload_name(
                    str(form.get(f"existing_slot_name_{prefix}") or ""),
                    os.path.basename(source_path),
                )
                preprocessed = str(form.get(f"existing_slot_preprocessed_{prefix}") or "") == "1"
                explicit_slot_prefixes.add(prefix)
                uploaded_slots.append(
                    WebUploadedSlot(
                        prefix=prefix,
                        label=slot["label"],
                        filename_label=slot.get("filename_label", ""),
                        source_path=source_path,
                        original_filename=original_filename,
                        content_fit=_optional_form_bool(form, f"slot_fit_{prefix}"),
                        preprocessed=preprocessed,
                    )
                )
                continue
            ftp_filename = os.path.basename(str(form.get(f"existing_ftp_slot_{prefix}") or ""))
            if ftp_filename:
                explicit_slot_prefixes.add(prefix)
                pending_ftp_slots.append(
                    {
                        "prefix": prefix,
                        "label": slot["label"],
                        "filename_label": slot.get("filename_label", ""),
                        "filename": ftp_filename,
                        "ean": str(form.get(f"existing_ftp_ean_{prefix}") or ""),
                        "content_fit": _optional_form_bool(form, f"slot_fit_{prefix}"),
                    }
                )
                continue
            value = form.get(f"slot_{prefix}")
            if not isinstance(value, _QueuedUploadFile):
                continue
            explicit_slot_prefixes.add(prefix)
            uploaded_slots.append(
                WebUploadedSlot(
                    prefix=prefix,
                    label=slot["label"],
                    filename_label=slot.get("filename_label", ""),
                    source_path=value.path,
                    original_filename=value.filename,
                    content_fit=_optional_form_bool(form, f"slot_fit_{prefix}"),
                )
            )
        product = WebProductForm(
            name=str(form.get("name") or ""),
            type_name=str(form.get("type_name") or ""),
            model=str(form.get("model") or ""),
            color1=str(form.get("color1") or ""),
            color2=str(form.get("color2") or ""),
            color3=str(form.get("color3") or ""),
            extra=str(form.get("extra") or ""),
            ean=str(form.get("ean") or ""),
            product_id=str(form.get("product_id") or ""),
        )
        product = effective_product_form(product, field_settings)
        errors = validate_product_form(product, field_settings)
        if errors:
            raise ValueError(" ".join(errors))
        timings.append(
            _timing_item(
                "prepare",
                "Przygotowanie danych i slotow",
                stage_started,
                uploaded=len(uploaded_slots),
                deleted=len(delete_requests),
                ftp_pending=len(pending_ftp_slots),
            )
        )
        stage_started = time.perf_counter()
        mark(10, "Wyszukiwanie wpisu", current_key="entry_lookup", current_label="Wyszukanie istniejacego wpisu")
        existing_entry = None
        if product.product_id.strip():
            existing_entry = find_entry_by_identity(product_id=product.product_id)
        if existing_entry is None and product.ean.strip() and product.ean.strip().upper() != "BRAK-EAN":
            existing_entry = find_entry_by_identity(ean=product.ean)
        if existing_entry:
            preserved_product_id = product.product_id or str(existing_entry.get("product_id") or "")
            preserved_ean = product.ean
            if field_settings["ean"]["enabled"]:
                preserved_ean = preserved_ean or str(existing_entry.get("ean") or "")
            if preserved_product_id != product.product_id or preserved_ean != product.ean:
                product = WebProductForm(
                    name=product.name,
                    type_name=product.type_name,
                    model=product.model,
                    color1=product.color1,
                    color2=product.color2,
                    color3=product.color3,
                    extra=product.extra,
                    ean=preserved_ean,
                    product_id=preserved_product_id,
                )
        timings.append(
            _timing_item(
                "entry_lookup",
                "Wyszukanie istniejacego wpisu",
                stage_started,
                found=bool(existing_entry),
            )
        )
        stage_started = time.perf_counter()
        mark(20, "Sprawdzanie zdjec", current_key="photo_scan", current_label="Sprawdzenie istniejacych zdjec")
        _append_pending_ftp_slots(
            product=product,
            pending_ftp_slots=pending_ftp_slots,
            uploaded_slots=uploaded_slots,
            delete_requests=delete_requests,
            cache_scope=cache_scope,
        )
        photo_lookup_entry = existing_entry or _entry_payload_from_product(product)
        include_sql_in_existing_photo_scan = existing_entry is not None
        existing_photos = find_product_photos(
            photo_lookup_entry,
            include_local=True,
            include_ftp=bool(config.CONFIG.get(ft, True)),
            include_sql=include_sql_in_existing_photo_scan,
        )
        existing_photos_snapshot = _snapshot_existing_photos(existing_photos)
        existing_file_photos = [photo for photo in existing_photos if _photo_has_file_source(photo)]
        if existing_entry is None:
            conflicts = _existing_photo_conflicts(
                existing_file_photos,
                uploaded_slots,
                delete_requests,
            )
            if conflicts:
                raise ValueError(_format_existing_photo_conflicts(conflicts))
        migrated_prefixes = _append_existing_photo_migrations(
            existing_entry=existing_entry,
            product=product,
            uploaded_slots=uploaded_slots,
            delete_requests=delete_requests,
            slot_by_prefix=slot_by_prefix,
            existing_photos=existing_photos,
            cache_scope=cache_scope,
        )
        if existing_entry is None and existing_file_photos and not uploaded_slots and not delete_requests:
            raise ValueError(
                _format_existing_photo_conflicts(
                    [
                        {
                            "prefix": photo.get("prefix"),
                            "sources": _photo_source_labels(photo),
                        }
                        for photo in existing_file_photos
                    ]
                )
            )
        timings.append(
            _timing_item(
                "photo_scan",
                "Sprawdzenie istniejacych zdjec",
                stage_started,
                found=len(existing_photos),
                migrated=len(migrated_prefixes),
            )
        )
        antivirus_scan_result = _uploaded_scan_summary(uploaded_slots)
        if antivirus_scan_result.get("enabled") or antivirus_scan_result.get("items"):
            timings.append(
                {
                    "key": "antivirus_scan",
                    "label": "Skan antywirusowy uploadu",
                    "elapsed_ms": sum(
                        int(item.get("elapsed_ms") or 0)
                        for item in antivirus_scan_result.get("items", [])
                    ),
                    "details": {
                        "enabled": bool(antivirus_scan_result.get("enabled")),
                        "scanned": int(antivirus_scan_result.get("scanned") or 0),
                        "skipped": int(antivirus_scan_result.get("skipped") or 0),
                    },
                }
            )
        stage_started = time.perf_counter()
        mark(34, "Przetwarzanie plikow", current_key="local_files", current_label="Zapis/przetwarzanie plikow lokalnych")
        check_cancelled()
        result = process_web_uploads(
            base_output_dir=settings.l,
            form=product,
            uploaded_slots=uploaded_slots,
            options=processing_options_from_config(config.CONFIG),
            allow_empty=True,
            field_settings=field_settings,
        )
        timings.append(
            _timing_item(
                "local_files",
                "Zapis/przetwarzanie plikow lokalnych",
                stage_started,
                saved=len(result.saved_files),
            )
        )
        stage_started = time.perf_counter()
        mark(60, "Usuwanie lokalne", current_key="local_delete", current_label="Usuwanie lokalne")
        check_cancelled()
        saved_paths = {os.path.abspath(item.path) for item in result.saved_files}
        local_delete_result = _delete_local_files(delete_requests, saved_paths)
        timings.append(
            _timing_item(
                "local_delete",
                "Usuwanie lokalne",
                stage_started,
                deleted=local_delete_result.get("deleted", 0),
                skipped=local_delete_result.get("skipped", 0),
            )
        )
        stage_started = time.perf_counter()
        mark(70, "Synchronizacja FTP", current_key="ftp", current_label="Synchronizacja FTP")
        check_cancelled()
        ftp_backfill_prefixes = {
            str(item.get("prefix") or "")
            for item in delete_requests
            if item.get("ftp_backfill")
        }
        skip_upload_prefixes = _ftp_skip_upload_prefixes(
            result,
            existing_file_photos,
            explicit_prefixes=explicit_slot_prefixes,
            migrated_prefixes=(
                set(migrated_prefixes)
                if _should_migrate_existing_photos(existing_entry, product)
                else set()
            ),
            ftp_backfill_prefixes=ftp_backfill_prefixes,
        )
        ftp_delete_candidates = [
            item.get("ftp_filename", "")
            for item in delete_requests
            if not item.get("ftp_backfill")
        ]
        ftp_delete_candidates.extend(
            _ftp_replacement_delete_candidates(
                result,
                existing_file_photos,
                explicit_prefixes=explicit_slot_prefixes,
            )
        )
        ftp_result = _sync_result_to_ftp(
            result,
            ftp_delete_candidates,
            skip_upload_prefixes=skip_upload_prefixes,
        )
        timings.append(
            _timing_item(
                "ftp",
                "Synchronizacja FTP",
                stage_started,
                uploaded=ftp_result.get("uploaded", 0),
                deleted=ftp_result.get("deleted", 0),
                skipped=len(skip_upload_prefixes),
            )
        )
        stage_started = time.perf_counter()
        mark(80, "Czyszczenie cache FTP", current_key="ftp_cache", current_label="Czyszczenie cache FTP")
        check_cancelled()
        changed_ftp_names = {
            _remote_name_for_output(str(item.filename or ""))
            for item in result.saved_files
            if getattr(item, "filename", "")
        }
        changed_ftp_names.update(
            os.path.basename(str(name or ""))
            for name in ftp_delete_candidates
            if os.path.basename(str(name or ""))
        )
        changed_ftp_names.discard("")
        ftp_cache_result = invalidate_ftp_preview_cache(
            result.ean,
            changed_ftp_names,
            cache_scope=cache_scope,
        )
        timings.append(
            _timing_item(
                "ftp_cache",
                "Czyszczenie cache FTP",
                stage_started,
                deleted=ftp_cache_result.get("deleted", 0),
            )
        )
        stage_started = time.perf_counter()
        mark(88, "Aktualizacja SQL", current_key="sql", current_label="Aktualizacja SQL")
        check_cancelled()
        sql_result = _sync_result_to_sql(
            result,
            clear_prefixes={
                str(item.get("prefix") or "")
                for item in delete_requests
                if item.get("sql") or item.get("ftp_filename") or item.get("local_path")
            },
        )
        timings.append(
            _timing_item(
                "sql",
                "Aktualizacja SQL",
                stage_started,
                updated=sql_result.get("updated", 0),
                cleared=sql_result.get("cleared", 0),
                skipped=bool(sql_result.get("skipped")),
            )
        )
        stage_started = time.perf_counter()
        mark(94, "Sprzatanie cache", current_key="upload_cache", current_label="Sprzatanie cache uploadu")
        check_cancelled()
        upload_cache_result = _delete_upload_cache_files(
            [
                str(slot.source_path or "")
                for slot in uploaded_slots
                if _is_upload_cache_path(str(slot.source_path or ""))
            ]
        )
        timings.append(
            _timing_item(
                "upload_cache",
                "Sprzatanie cache uploadu",
                stage_started,
                deleted=upload_cache_result.get("deleted", 0),
                skipped=upload_cache_result.get("skipped", 0),
            )
        )
        stage_started = time.perf_counter()
        mark(96, "Zapis wpisu", current_key="entry_save", current_label="Zapis wpisu produktu")
        check_cancelled()
        entry_result = save_web_entry(_entry_payload_from_product(product))
        timings.append(_timing_item("entry_save", "Zapis wpisu produktu", stage_started))
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        details: Dict[str, Any] = {"status_code": exc.status_code}
        if product is not None:
            details.update(_process_event_details(product, uploaded_slots, delete_requests))
        _write_web_event(
            level="warning" if exc.status_code < 500 else "error",
            event="PROCESS_REJECTED",
            username=username,
            message=detail,
            details=details,
        )
        emit_event(
            severity="warning" if exc.status_code < 500 else "error",
            event_type="process.validation_rejected",
            module="web.process",
            username=username,
            job_id=job_id,
            summary=detail,
            details=details,
            exception=exc,
        )
        raise
    except ValueError as exc:
        details = {}
        if product is not None:
            details = _process_event_details(product, uploaded_slots, delete_requests)
        _write_web_event(
            level="warning",
            event="PROCESS_REJECTED",
            username=username,
            message=str(exc),
            details=details,
        )
        emit_event(
            severity="warning",
            event_type="process.validation_rejected",
            module="web.process",
            username=username,
            job_id=job_id,
            summary=str(exc),
            details=details,
            exception=exc,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if form.temp_dir:
            _cleanup_process_job_directory(form.temp_dir)

    payload = _result_payload(result)
    payload["entry"] = entry_result
    payload["migrated_slots"] = migrated_prefixes
    payload["deleted_slots"] = delete_requests
    payload["ftp"] = ftp_result
    payload["ftp_cache"] = ftp_cache_result
    payload["upload_cache"] = upload_cache_result
    payload["sql"] = sql_result
    payload["local_delete"] = local_delete_result
    payload["antivirus_scan"] = antivirus_scan_result
    stage_started = time.perf_counter()
    mark(98, "Odswiezanie indeksu", current_key="file_index", current_label="Odswiezenie indeksu lokalnego")
    check_cancelled()
    payload["file_index"] = refresh_file_index()
    timings.append(_timing_item("file_index", "Odswiezenie indeksu lokalnego", stage_started))
    payload["timing"] = _timing_payload(timings, process_started)
    payload["show_timing_details"] = _show_timing_details()
    saved_entry = _entry_payload_from_product(product)
    if isinstance(entry_result, dict):
        saved_entry["product_id"] = str(entry_result.get("product_id") or saved_entry["product_id"])
    local_slot_results = _local_slot_results(
        payload["saved_files"], local_delete_result
    )
    integrations = {
        "local": {"slot_results": local_slot_results},
        "ftp": ftp_result,
        "sql": sql_result,
    }
    change_set = history_change_set(
        existing_entry=existing_entry,
        saved_entry=saved_entry,
        existing_photos=existing_photos_snapshot,
        saved_files=payload["saved_files"],
        delete_requests=delete_requests,
        migrated_prefixes=migrated_prefixes,
        integrations=integrations,
    )
    record_history(
        username=username,
        action="process",
        ean=product.ean,
        product_id=entry_result.get("product_id", "") if isinstance(entry_result, dict) else "",
        summary=(
            "Zapisano usuniecia produktu."
            if delete_requests and not result.saved_files
            else "Zsynchronizowano produkt bez zmian w plikach."
            if not delete_requests and not result.saved_files
            else "Przetworzono pliki produktu."
        ),
        details={
            "saved_files": payload["saved_files"],
            "deleted_slots": delete_requests,
            "migrated_slots": migrated_prefixes,
            "ftp": ftp_result,
            "ftp_cache": ftp_cache_result,
            "upload_cache": upload_cache_result,
            "antivirus_scan": antivirus_scan_result,
            "sql": sql_result,
            "local_delete": local_delete_result,
            "output_dir": payload["output_dir"],
            "timing": payload["timing"],
            "entry": entry_result.get("entry", {}) if isinstance(entry_result, dict) else {},
            "job_id": job_id,
            "change_set": change_set,
        },
    )
    _emit_process_integration_events(
        username=username,
        job_id=job_id,
        ean=product.ean,
        ftp_result=ftp_result,
        sql_result=sql_result,
    )
    event_level = "info"
    event_name = "PROCESS_COMPLETED"
    if (
        ftp_result.get("error")
        or sql_result.get("error")
        or (local_delete_result.get("errors") if isinstance(local_delete_result, dict) else [])
        or result.skipped_slots
    ):
        event_level = "warning"
        event_name = "PROCESS_COMPLETED_WITH_WARNINGS"
    _write_web_event(
        level=event_level,
        event=event_name,
        username=username,
        message=(
            f"Zapisano {len(result.saved_files)} plikow, "
            f"usunieto lokalnie {local_delete_result.get('deleted', 0)}."
        ),
        details=_process_event_details(
            product,
            uploaded_slots,
            delete_requests,
            saved_files=[item.filename for item in result.saved_files],
            skipped_slots=result.skipped_slots,
            migrated_slots=migrated_prefixes,
            ftp=ftp_result,
            ftp_cache=ftp_cache_result,
            upload_cache=upload_cache_result,
            antivirus_scan=antivirus_scan_result,
            sql=sql_result,
            local_delete=local_delete_result,
        ),
    )
    return payload


def _exception_message(exc: BaseException) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        return detail if isinstance(detail, str) else str(detail)
    return str(exc) or exc.__class__.__name__


def _result_severity(payload: Dict[str, Any]) -> str:
    ftp = payload.get("ftp") if isinstance(payload.get("ftp"), dict) else {}
    sql = payload.get("sql") if isinstance(payload.get("sql"), dict) else {}
    local_delete = (
        payload.get("local_delete")
        if isinstance(payload.get("local_delete"), dict)
        else {}
    )
    blocking = [
        ftp.get("error"),
        sql.get("error"),
        *(local_delete.get("errors") or []),
    ]
    if any(blocking):
        return "error"
    if payload.get("skipped_slots"):
        return "warning"
    return "info"


def _cleanup_process_jobs_locked(now: Optional[float] = None) -> None:
    removed = False
    cutoff = (time.time() if now is None else now) - _PROCESS_JOB_RETENTION_SECONDS
    terminal_jobs: List[tuple[str, Dict[str, Any]]] = []
    for job_id, job in list(_PROCESS_JOBS.items()):
        if job.get("status") not in {"completed", "failed", "cancelled"}:
            continue
        if float(job.get("finished_at") or 0) < cutoff:
            _PROCESS_JOBS.pop(job_id, None)
            _PROCESS_JOB_COMPLETIONS.pop(job_id, None)
            removed = True
            continue
        terminal_jobs.append((job_id, job))
    terminal_jobs.sort(
        key=lambda item: (
            float(item[1].get("finished_at") or 0),
            float(item[1].get("created_at") or 0),
        ),
        reverse=True,
    )
    for job_id, _job in terminal_jobs[_PROCESS_JOB_MAX_COMPLETED:]:
        _PROCESS_JOBS.pop(job_id, None)
        _PROCESS_JOB_COMPLETIONS.pop(job_id, None)
        removed = True
    if removed:
        _advance_process_queue_generation_locked()


def _cleanup_process_jobs(now: Optional[float] = None) -> None:
    with _PROCESS_JOBS_LOCK:
        _cleanup_process_jobs_locked(now=now)
        active_paths = {
            str(job.get("form").temp_dir)
            for job in _PROCESS_JOBS.values()
            if job.get("status") in {"queued", "running"}
            and isinstance(job.get("form"), _ProcessFormSnapshot)
            and job.get("form").temp_dir
        }
    cleanup_expired_job_directories(
        managed_root=str(_PROCESS_JOB_ROOT),
        prefix=_PROCESS_JOB_DIRECTORY_PREFIX,
        max_age_seconds=_PROCESS_JOB_DIRECTORY_TTL_SECONDS,
        active_paths=active_paths,
        now=now,
    )


def _cleanup_process_job_directory(path: str) -> bool:
    return cleanup_job_directory(path, managed_root=str(_PROCESS_JOB_ROOT))


def _advance_process_queue_generation_locked() -> None:
    global _PROCESS_QUEUE_GENERATION
    _PROCESS_QUEUE_GENERATION += 1


async def _stage_process_form(request: Request) -> _ProcessFormSnapshot:
    os.makedirs(_PROCESS_JOB_ROOT, exist_ok=True)
    temp_dir = tempfile.mkdtemp(
        prefix=_PROCESS_JOB_DIRECTORY_PREFIX,
        dir=str(_PROCESS_JOB_ROOT),
    )
    try:
        resolve_path_within_roots(temp_dir, [_PROCESS_JOB_ROOT])
        form = await request.form()
        snapshot = await _materialize_process_form(form, temp_dir)
    except Exception:
        _cleanup_process_job_directory(temp_dir)
        raise
    return snapshot


def _process_job_payload(job: Dict[str, Any], *, include_result: bool = True) -> Dict[str, Any]:
    payload = {
        "job_id": job.get("id", ""),
        "status": job.get("status", "queued"),
        "username": job.get("username", ""),
        "created_at": job.get("created_at", 0),
        "created_time": job.get("created_time", ""),
        "started_at": job.get("started_at", 0),
        "finished_at": job.get("finished_at", 0),
        "entry": dict(job.get("entry") or {}),
        "entry_label": job.get("entry_label", ""),
        "progress": int(job.get("progress") or 0),
        "progress_label": job.get("progress_label", ""),
        "queue_position": int(job.get("queue_position") or 0),
        "timing": _process_job_timing(job),
        "error": job.get("error", ""),
        "warning_messages": list(job.get("warning_messages") or []),
    }
    if include_result and job.get("result") is not None:
        payload["result"] = job.get("result")
    return payload


def _process_job_timing(job: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    now_value = time.time() if now is None else float(now)
    started_at = float(job.get("started_at") or 0)
    finished_at = float(job.get("finished_at") or 0)
    end_at = finished_at if finished_at else now_value
    total_ms = int(max(0, end_at - started_at) * 1000) if started_at else 0
    stages = [dict(stage) for stage in (job.get("timing_stages") or []) if isinstance(stage, dict)]
    current = job.get("current_stage") if isinstance(job.get("current_stage"), dict) else None
    if current and not finished_at:
        current_stage = dict(current)
        current_started = float(current_stage.get("started_at") or 0)
        if current_started:
            current_stage["elapsed_ms"] = int(max(0, now_value - current_started) * 1000)
        current_stage["running"] = True
        stages.append(current_stage)
    return {"total_ms": total_ms, "stages": stages}


def _process_job_record(job: Dict[str, Any]) -> Dict[str, Any]:
    entry = dict(job.get("entry") or {})
    timing = _process_job_timing(job)
    details: Dict[str, Any] = {
        "entry": entry,
        "entry_label": str(job.get("entry_label") or ""),
        "progress": int(job.get("progress") or 0),
        "progress_label": str(job.get("progress_label") or ""),
        "warning_messages": list(job.get("warning_messages") or []),
        "error": str(job.get("error") or ""),
        "timing_total_ms": timing["total_ms"],
    }
    if job.get("result") is not None:
        details["result"] = job.get("result")
    return {
        "id": str(job.get("id") or ""),
        "username": str(job.get("username") or ""),
        "ean": str(entry.get("ean") or ""),
        "status": str(job.get("status") or "queued"),
        "summary": str(job.get("progress_label") or job.get("error") or ""),
        "started_at": job.get("started_at") or job.get("created_at") or time.time(),
        "finished_at": job.get("finished_at") or "",
        "stages": timing["stages"],
        "details": details,
    }


def _persist_process_job(job: Dict[str, Any]) -> None:
    try:
        record_job(_process_job_record(job))
    except Exception:
        # Observability must not change the processing job's business outcome.
        pass


def _process_job_stage(job: Dict[str, Any]) -> str:
    current_stage = job.get("current_stage")
    if isinstance(current_stage, dict):
        return str(
            current_stage.get("key")
            or current_stage.get("label")
            or job.get("progress_label")
            or ""
        )
    return str(job.get("progress_label") or "")


def _persist_process_job_snapshot(
    job: Dict[str, Any], *, force: bool = False, forget: bool = False
) -> None:
    job_id = str(job.get("id") or "")
    if _PROCESS_PROGRESS_GATE.should_persist(
        job_id,
        stage=_process_job_stage(job),
        status=str(job.get("status") or "queued"),
        now=time.monotonic(),
        force=force,
    ):
        _persist_process_job(job)
    if forget:
        _PROCESS_PROGRESS_GATE.forget(job_id)


def _update_process_job_progress(
    job: Dict[str, Any],
    percent: int,
    label: str,
    stages: Optional[List[Dict[str, Any]]] = None,
    current_stage: Optional[Dict[str, Any]] = None,
) -> None:
    job["progress"] = max(0, min(100, int(percent or 0)))
    job["progress_label"] = str(label or "")
    if stages is not None:
        job["timing_stages"] = [
            dict(stage) for stage in stages if isinstance(stage, dict)
        ]
    if current_stage is not None:
        job["current_stage"] = dict(current_stage)


def _set_process_job_progress(
    job_id: str,
    percent: int,
    label: str,
    stages: Optional[List[Dict[str, Any]]] = None,
    current_stage: Optional[Dict[str, Any]] = None,
) -> None:
    with _PROCESS_JOBS_LOCK:
        job = _PROCESS_JOBS.get(job_id)
        if not job:
            return
        _update_process_job_progress(job, percent, label, stages, current_stage)
        _advance_process_queue_generation_locked()
        durable_job = dict(job)
    _persist_process_job_snapshot(durable_job)


def _new_process_job(
    *,
    username: str,
    cache_scope: str,
    form: _ProcessFormSnapshot,
    status: str,
) -> Dict[str, Any]:
    job_id = secrets.token_hex(8)
    entry = _snapshot_entry_payload(form)
    created_at = time.time()
    running = status == "running"
    return {
        "id": job_id,
        "status": status,
        "username": username,
        "cache_scope": cache_scope,
        "form": form,
        "entry": entry,
        "entry_label": _process_entry_label(entry),
        "created_at": created_at,
        "created_time": time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(created_at)
        ),
        "started_at": created_at if running else 0.0,
        "finished_at": 0.0,
        "result": None,
        "progress": 1 if running else 0,
        "progress_label": "Start zadania" if running else "Oczekuje w kolejce",
        "timing_stages": [],
        "current_stage": None,
        "error": "",
        "error_status_code": 0,
        "warning_messages": [],
    }


def _finish_process_job_success(
    job: Dict[str, Any], payload: Dict[str, Any]
) -> List[str]:
    warning_messages = _process_warning_messages(payload)
    job["status"] = "completed"
    job["finished_at"] = time.time()
    job["result"] = payload
    job["progress"] = 100
    job["progress_label"] = "Zakonczono"
    job["timing_stages"] = payload.get("timing", {}).get("stages", [])
    job["current_stage"] = None
    job["warning_messages"] = warning_messages
    job.pop("form", None)
    return warning_messages


def _finish_process_job_failure(
    job: Dict[str, Any], exc: BaseException
) -> tuple[str, int, str]:
    message = _exception_message(exc)
    status_code = int(getattr(exc, "status_code", 500) or 500)
    severity = (
        "warning"
        if isinstance(exc, HTTPException) and status_code < 500
        else "error"
        if isinstance(exc, HTTPException)
        else "critical"
    )
    finished_at = time.time()
    current = job.get("current_stage")
    if isinstance(current, dict):
        failing_stage = dict(current)
        current_started = float(failing_stage.get("started_at") or 0)
        elapsed_ms = (
            int(max(0, finished_at - current_started) * 1000)
            if current_started
            else int(failing_stage.get("elapsed_ms") or 0)
        )
        failing_stage.update(
            {
                "elapsed_ms": max(
                    elapsed_ms, int(failing_stage.get("elapsed_ms") or 0)
                ),
                "running": False,
                "failed": True,
                "error": message,
            }
        )
        stages = [
            dict(stage)
            for stage in (job.get("timing_stages") or [])
            if isinstance(stage, dict)
        ]
        stages.append(failing_stage)
        job["timing_stages"] = stages
    job["status"] = "failed"
    job["finished_at"] = finished_at
    job["error"] = message
    job["error_status_code"] = status_code
    job["progress_label"] = "Blad zadania"
    job["warning_messages"] = [message]
    job["current_stage"] = None
    job.pop("form", None)
    return message, status_code, severity


def _finish_process_job_cancelled(job: Dict[str, Any]) -> str:
    form = job.get("form")
    temp_dir = form.temp_dir if isinstance(form, _ProcessFormSnapshot) else ""
    job["status"] = "cancelled"
    job["finished_at"] = time.time()
    job["progress_label"] = "Anulowano"
    job["current_stage"] = None
    job["warning_messages"] = ["Zadanie zostalo anulowane."]
    job.pop("form", None)
    return temp_dir


def _emit_process_completed(
    job: Dict[str, Any], payload: Dict[str, Any], warning_messages: List[str]
) -> None:
    entry = dict(job.get("entry") or {})
    severity = _result_severity(payload)
    emit_event(
        severity=severity,
        event_type="process.completed",
        module="web.process",
        stage="completed",
        username=str(job.get("username") or ""),
        ean=str(entry.get("ean") or ""),
        product_id=str(entry.get("product_id") or ""),
        job_id=str(job.get("id") or ""),
        summary=(
            "Process completed successfully."
            if severity == "info"
            else "Process completed with integration failures."
            if severity == "error"
            else "Process completed with skipped slots."
        ),
        details={"warnings": warning_messages, "result": payload},
    )


def _emit_process_failed(
    job: Dict[str, Any],
    exc: BaseException,
    *,
    message: str,
    status_code: int,
    severity: str,
) -> None:
    entry = dict(job.get("entry") or {})
    username = str(job.get("username") or "")
    job_id = str(job.get("id") or "")
    _write_web_event(
        level="warning" if status_code < 500 else "error",
        event="PROCESS_JOB_FAILED",
        username=username,
        message=f"{str(job.get('entry_label') or '')}: {message}",
        details={"job_id": job_id, "entry": entry},
    )
    emit_event(
        severity=severity,
        event_type="process.failed",
        module="web.process",
        stage="failed",
        username=username,
        ean=str(entry.get("ean") or ""),
        product_id=str(entry.get("product_id") or ""),
        job_id=job_id,
        summary=message,
        details={"entry": entry, "status_code": status_code},
        exception=exc,
    )


def _queue_process_job(
    *,
    username: str,
    cache_scope: str,
    form: _ProcessFormSnapshot,
    reservation: QueueReservation,
    persist_as_running: bool = False,
) -> Dict[str, Any]:
    _cleanup_process_jobs()
    job = _new_process_job(
        username=username, cache_scope=cache_scope, form=form, status="queued"
    )
    job_id = str(job["id"])
    completion = threading.Event()
    with _PROCESS_JOBS_LOCK:
        _PROCESS_JOBS[job_id] = job
        _PROCESS_JOB_COMPLETIONS[job_id] = completion
        _advance_process_queue_generation_locked()
        persisted_job = dict(job)
        if persist_as_running:
            job["start_persisted"] = True
            persisted_job["status"] = "running"
            persisted_job["started_at"] = time.time()
            persisted_job["progress"] = 1
            persisted_job["progress_label"] = "Start zadania"
    _persist_process_job(persisted_job)
    try:
        queue_position = _PROCESS_QUEUE.submit(reservation, job_id, _run_process_job)
    except Exception:
        with _PROCESS_JOBS_LOCK:
            _PROCESS_JOBS.pop(job_id, None)
            _PROCESS_JOB_COMPLETIONS.pop(job_id, None)
            _advance_process_queue_generation_locked()
        reservation.release()
        _cleanup_process_job_directory(form.temp_dir)
        raise
    with _PROCESS_JOBS_LOCK:
        queued_job = _PROCESS_JOBS.get(job_id)
        if queued_job and queued_job.get("status") == "queued":
            queued_job["queue_position"] = queue_position
            job = queued_job
        durable_job = dict(job)
    return _process_job_payload(durable_job, include_result=False)


def _run_process_job(
    job_id: str,
    cancel_event: threading.Event | None = None,
) -> None:
    try:
        with _PROCESS_JOBS_LOCK:
            job = _PROCESS_JOBS.get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["started_at"] = time.time()
            job["progress"] = max(1, int(job.get("progress") or 0))
            job["progress_label"] = "Start zadania"
            _advance_process_queue_generation_locked()
            username = str(job.get("username") or "")
            cache_scope = str(job.get("cache_scope") or "")
            form = job.get("form")
            staging_dir = form.temp_dir if isinstance(form, _ProcessFormSnapshot) else ""
            start_persisted = bool(job.pop("start_persisted", False))
            durable_job = dict(job)
        if not start_persisted:
            _persist_process_job(durable_job)
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise _ProcessJobCancelled()
            payload = _process_upload_snapshot(
                username=username,
                cache_scope=cache_scope,
                form=form,
                job_id=job_id,
                cancel_event=cancel_event,
                progress=lambda percent, label, stages, current_stage: _set_process_job_progress(
                    job_id,
                    percent,
                    label,
                    stages,
                    current_stage,
                ),
            )
            with _PROCESS_JOBS_LOCK:
                job = _PROCESS_JOBS.get(job_id)
                if not job:
                    return
                warning_messages = _finish_process_job_success(job, payload)
                _advance_process_queue_generation_locked()
                _cleanup_process_jobs_locked(now=float(job["finished_at"]))
                durable_job = dict(job)
            _cleanup_process_job_directory(staging_dir)
            _persist_process_job_snapshot(durable_job, force=True, forget=True)
            _emit_process_completed(durable_job, payload, warning_messages)
        except _ProcessJobCancelled:
            with _PROCESS_JOBS_LOCK:
                job = _PROCESS_JOBS.get(job_id)
                if not job:
                    return
                temp_dir = _finish_process_job_cancelled(job)
                _advance_process_queue_generation_locked()
                _cleanup_process_jobs_locked(now=float(job["finished_at"]))
                durable_job = dict(job)
            _cleanup_process_job_directory(temp_dir)
            _persist_process_job_snapshot(durable_job, force=True, forget=True)
        except Exception as exc:
            with _PROCESS_JOBS_LOCK:
                job = _PROCESS_JOBS.get(job_id)
                if not job:
                    return
                message, status_code, severity = _finish_process_job_failure(job, exc)
                _advance_process_queue_generation_locked()
                _cleanup_process_jobs_locked(now=float(job["finished_at"]))
                durable_job = dict(job)
            _cleanup_process_job_directory(staging_dir)
            _persist_process_job_snapshot(durable_job, force=True, forget=True)
            _emit_process_failed(
                durable_job,
                exc,
                message=message,
                status_code=status_code,
                severity=severity,
            )
    finally:
        with _PROCESS_JOBS_LOCK:
            completion = _PROCESS_JOB_COMPLETIONS.get(job_id)
        if completion is not None:
            completion.set()


def _cancel_process_job_for_user(job_id: str, username: str) -> Optional[Dict[str, Any]]:
    with _PROCESS_JOBS_LOCK:
        job = _PROCESS_JOBS.get(job_id)
        if not job or str(job.get("username") or "") != username:
            return None
        if job.get("status") not in {"queued", "running"}:
            return None
    if not _PROCESS_QUEUE.cancel(job_id):
        return None
    temp_dir = ""
    completion: threading.Event | None = None
    with _PROCESS_JOBS_LOCK:
        job = _PROCESS_JOBS.get(job_id)
        if not job:
            return None
        if job.get("status") == "queued":
            temp_dir = _finish_process_job_cancelled(job)
            completion = _PROCESS_JOB_COMPLETIONS.get(job_id)
        else:
            job["cancel_requested"] = True
            job["progress_label"] = "Anulowanie zadania"
        _advance_process_queue_generation_locked()
        durable_job = dict(job)
    if temp_dir:
        _cleanup_process_job_directory(temp_dir)
    if completion is not None:
        completion.set()
    _persist_process_job_snapshot(durable_job, force=True, forget=bool(temp_dir))
    return _process_job_payload(durable_job, include_result=False)


def _process_job_for_user(job_id: str, username: str) -> Optional[Dict[str, Any]]:
    _cleanup_process_jobs()
    with _PROCESS_JOBS_LOCK:
        job = _PROCESS_JOBS.get(job_id)
        if not job or str(job.get("username") or "") != username:
            return None
        return dict(job)


def _process_jobs_for_user(username: str, limit: int = 20) -> List[Dict[str, Any]]:
    _cleanup_process_jobs()
    with _PROCESS_JOBS_LOCK:
        jobs = [
            dict(job)
            for job in _PROCESS_JOBS.values()
            if str(job.get("username") or "") == username
        ]
    jobs.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
    return [_process_job_payload(job, include_result=False) for job in jobs[: max(1, min(100, limit))]]


def _active_process_jobs_snapshot() -> Dict[str, Any]:
    _cleanup_process_jobs()
    now = time.time()
    with _PROCESS_JOBS_LOCK:
        active_jobs = [
            dict(job)
            for job in _PROCESS_JOBS.values()
            if job.get("status") in {"queued", "running"}
        ]
        queue_generation = _PROCESS_QUEUE_GENERATION
    running = sorted(
        [job for job in active_jobs if job.get("status") == "running"],
        key=lambda item: float(item.get("started_at") or item.get("created_at") or 0),
    )
    queued = sorted(
        [job for job in active_jobs if job.get("status") == "queued"],
        key=lambda item: float(item.get("created_at") or 0),
    )
    ordered = running + queued
    payload_jobs: List[Dict[str, Any]] = []
    queued_position = 0
    for job in ordered:
        item = dict(job)
        if item.get("status") == "running":
            item["queue_position"] = 0
        else:
            queued_position += 1
            item["queue_position"] = queued_position
        payload_jobs.append(_process_job_payload(item, include_result=False))
    return {
        "jobs": payload_jobs,
        "current": payload_jobs[0] if payload_jobs and payload_jobs[0].get("status") == "running" else None,
        "active_count": len(payload_jobs),
        "queued_count": len(queued),
        "generation": queue_generation,
        "server_time": now,
    }


def _runtime_process_queue_summary() -> Dict[str, Any]:
    with _PROCESS_JOBS_LOCK:
        return {
            "generation": _PROCESS_QUEUE_GENERATION,
            "active_count": sum(
                1
                for job in _PROCESS_JOBS.values()
                if job.get("status") in {"queued", "running"}
            ),
        }


def _resource_monitor_context() -> dict[str, int]:
    active = _active_process_jobs_snapshot()
    with _ACTIVE_CLIENT_REGISTRY_LIFECYCLE_LOCK:
        active_clients = len(_active_client_registry_locked().snapshot())
    return {
        "active_jobs": int(active["active_count"]),
        "queued_jobs": int(active["queued_count"]),
        "active_clients": active_clients,
    }


def _emit_resource_event(
    severity: str, event_type: str, details: dict[str, object]
) -> bool:
    event = emit_event(
        severity=severity,
        event_type=event_type,
        module="resource_monitor",
        stage="threshold",
        summary="Backend resource threshold exceeded.",
        details=details,
        strict=True,
    )
    return bool(event)


def _report_real_test_worker_failure(kind: str, report: str) -> None:
    safe_kind = sanitize_free_text(kind, limit=40)
    safe_report = sanitize_free_text(report, limit=32 * 1024)
    error = RuntimeError(safe_report)
    try:
        emit_event(
            severity="error",
            event_type="backend.resource_test_failed",
            module="resource_monitor",
            stage="real_test",
            summary="Real resource test worker failed.",
            details={"test_mode": "real", "kind": safe_kind},
            exception=error,
            strict=True,
        )
    except Exception:
        pass
    log_error(f"Real resource test worker failed ({safe_kind}): {safe_report}")


def _active_clients_log_path() -> Path:
    return Path(settings.LOG_DIR) / "web_active_clients.json"


def _active_client_registry_locked() -> ActiveClientRegistry:
    global _ACTIVE_CLIENT_REGISTRY
    if _ACTIVE_CLIENT_REGISTRY.closed:
        _ACTIVE_CLIENT_REGISTRY.wait_until_idle()
        _ACTIVE_CLIENT_REGISTRY = ActiveClientRegistry(
            _active_clients_log_path(),
            max_age_seconds=ACTIVE_CLIENT_MAX_AGE_SECONDS,
            flush_interval_seconds=ACTIVE_CLIENT_FLUSH_INTERVAL_SECONDS,
        )
    return _ACTIVE_CLIENT_REGISTRY


def _ensure_active_client_registry() -> ActiveClientRegistry:
    with _ACTIVE_CLIENT_REGISTRY_LIFECYCLE_LOCK:
        return _active_client_registry_locked()


def _clean_presence_client_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "", text)[:80]
    return cleaned


def _request_presence_client_id(request: Request) -> str:
    headers = getattr(request, "headers", {}) or {}
    value = headers.get(PRESENCE_CLIENT_ID_HEADER) if hasattr(headers, "get") else ""
    return _clean_presence_client_id(value)


def _active_client_key(item: Dict[str, Any]) -> str:
    client_id = _clean_presence_client_id(item.get("client_id"))
    if client_id:
        return "|".join(
            [
                str(item.get("username") or ""),
                "client",
                client_id,
            ]
        )
    return "|".join(
        [
            str(item.get("username") or ""),
            str(item.get("remote_address") or ""),
            str(item.get("user_agent") or ""),
        ]
    )


def _active_clients_snapshot(now: Optional[float] = None) -> List[Dict[str, Any]]:
    with _ACTIVE_CLIENT_REGISTRY_LIFECYCLE_LOCK:
        registry = _active_client_registry_locked()
        clients = registry.snapshot(now=now)
        registry.schedule_flush()
        return clients


def _remove_active_client(username: str, client_id: str, now: Optional[float] = None) -> int:
    with _ACTIVE_CLIENT_REGISTRY_LIFECYCLE_LOCK:
        registry = _active_client_registry_locked()
        removed = registry.remove(username, client_id, now=now)
        if removed:
            registry.schedule_flush(force=True)
        return removed


def _active_presence_enabled() -> bool:
    return bool(_security_settings().get("show_active_web_users", False))


def _active_presence_payload(
    clients: List[Dict[str, Any]],
    now: Optional[float] = None,
) -> Dict[str, Any]:
    if not _active_presence_enabled():
        return {"enabled": False, "users": []}
    now_value = time.time() if now is None else float(now)
    by_username: Dict[str, Dict[str, Any]] = {}
    for client in clients:
        username = str(client.get("username") or "").strip()
        if not username or username == "niezalogowany":
            continue
        if not _clean_presence_client_id(client.get("client_id")):
            continue
        try:
            last_seen_epoch = float(client.get("last_seen_epoch") or 0)
        except (TypeError, ValueError):
            last_seen_epoch = 0.0
        if now_value - last_seen_epoch > PRESENCE_CLIENT_MAX_AGE_SECONDS:
            continue
        existing = by_username.get(username)
        if existing and float(existing.get("last_seen_epoch") or 0) >= last_seen_epoch:
            continue
        by_username[username] = {
            "username": username,
            "last_seen_epoch": last_seen_epoch,
        }
    users = sorted(
        by_username.values(),
        key=lambda item: float(item.get("last_seen_epoch") or 0),
        reverse=True,
    )[:100]
    return {"enabled": True, "users": users}


def _runtime_active_clients_summary() -> Dict[str, Any]:
    with _ACTIVE_CLIENT_REGISTRY_LIFECYCLE_LOCK:
        registry = _active_client_registry_locked()
        summary = registry.runtime_summary()
        registry.schedule_flush()
        return {
            "generation": summary["generation"],
            "count": summary["active_user_count"],
        }


def _record_active_client(request: Request, status_code: int) -> None:
    path_text = str(request.url.path or "")
    if path_text.startswith("/static/") or path_text in {
        "/api/health",
        "/api/logout",
        "/api/runtime-status",
        "/api/server/presence/leave",
    }:
        return
    try:
        username = _current_user(request) or ""
    except Exception:
        username = ""
    client = getattr(request, "client", None)
    headers = getattr(request, "headers", {}) or {}
    now_value = time.time()
    item = {
        "username": username or "niezalogowany",
        "remote_address": str(getattr(client, "host", "") or ""),
        "remote_port": int(getattr(client, "port", 0) or 0),
        "user_agent": str(headers.get("user-agent", "") if hasattr(headers, "get") else ""),
        "client_id": _request_presence_client_id(request),
        "method": str(request.method or ""),
        "path": path_text,
        "status_code": int(status_code or 0),
        "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_seen_epoch": now_value,
    }
    with _ACTIVE_CLIENT_REGISTRY_LIFECYCLE_LOCK:
        registry = _active_client_registry_locked()
        registry.record(item, now=now_value)
        registry.schedule_flush()


def _optional_form_bool(form: Any, key: str) -> Optional[bool]:
    value = form.get(key)
    if value is None:
        return None
    return str(value).strip() == "1"


def _enrich_photo_payload(photos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for photo in photos:
        item = dict(photo)
        path = str(photo.get("path") or "")
        ftp_path = str(photo.get("ftp_path") or "")
        if path:
            item["ocr_state"] = _schedule_ocr_value_collection(
                photo.get("prefix"), path
            )
            token = _file_token(path)
            item["token"] = token
            item["file_version"] = _file_version(path)
            item["url"] = _versioned_file_url(path, "/api/file", token)
            item["thumb_url"] = _versioned_file_url(path, "/api/thumbnail", token)
        else:
            item["ocr_state"] = "disabled"
            item["token"] = ""
            item["file_version"] = ""
            item["url"] = ""
            item["thumb_url"] = ""
        if ftp_path:
            ftp_token = _file_token(ftp_path)
            item["ftp_token"] = ftp_token
            item["ftp_file_version"] = _file_version(ftp_path)
            item["ftp_url"] = _versioned_file_url(ftp_path, "/api/file", ftp_token)
            item["ftp_thumb_url"] = _versioned_file_url(ftp_path, "/api/thumbnail", ftp_token)
        else:
            item["ftp_token"] = ""
            item["ftp_file_version"] = ""
            item["ftp_url"] = ""
            item["ftp_thumb_url"] = ""
        enriched.append(item)
    return enriched


def _public_similar_candidate(candidate: Any) -> Dict[str, Any]:
    """Return signed, public metadata for one local similar-file candidate."""

    signed = _enrich_photo_payload([{"path": candidate.source_path}])[0]
    return {
        "id": candidate.candidate_id,
        "source_prefix": candidate.source_prefix,
        "target_prefix": candidate.target_prefix,
        "filename": candidate.filename,
        "source_color": candidate.source_color_segment,
        "size_bytes": candidate.size_bytes,
        "is_pdf": candidate.is_pdf,
        "token": signed["token"],
        "url": signed["url"],
        "thumb_url": signed["thumb_url"],
    }


def _run_due_sqlite_backups_once() -> Dict[str, Any]:
    settings_payload = storage_settings.load_backup_settings()
    slots = sqlite_backup.due_schedule_slots(
        settings_payload,
        time_zone_name=_configured_time_zone_name(),
    )
    if not slots:
        return {"created": 0, "slots": []}
    backup_dir = storage_settings.resolve_backup_dir()
    result = sqlite_backup.create_backup(
        storage_settings.resolve_sqlite_path(),
        backup_dir,
        reason="scheduled",
    )
    sqlite_backup.enforce_retention(backup_dir, settings_payload.get("max_copies", 10))
    updated = sqlite_backup.mark_schedule_slots_run(settings_payload, slots)
    storage_settings.save_backup_settings(updated)
    return {"created": 1, "slots": slots, "backup": result}


def _prune_live_events_if_due(*, force: bool = False) -> int:
    global _LIVE_EVENT_LAST_PRUNED
    now = time.monotonic()
    if (
        not force
        and _LIVE_EVENT_LAST_PRUNED
        and now - _LIVE_EVENT_LAST_PRUNED < _LIVE_EVENT_PRUNE_INTERVAL_SECONDS
    ):
        return 0
    removed = max(0, int(prune_live_events() or 0))
    _LIVE_EVENT_LAST_PRUNED = now
    return removed


def _backup_scheduler_loop() -> None:
    while not _BACKUP_SCHEDULER_STOP.wait(60):
        try:
            _run_due_sqlite_backups_once()
        except Exception as exc:
            log_error(f"WEB scheduled SQLite backup failed: {exc}\n{traceback.format_exc()}")
        try:
            _prune_live_events_if_due()
        except Exception as exc:
            log_error(f"WEB observability pruning failed: {exc}\n{traceback.format_exc()}")


def _start_backup_scheduler() -> None:
    global _BACKUP_SCHEDULER_THREAD
    if _BACKUP_SCHEDULER_THREAD is not None and _BACKUP_SCHEDULER_THREAD.is_alive():
        return
    _BACKUP_SCHEDULER_STOP.clear()
    _BACKUP_SCHEDULER_THREAD = threading.Thread(
        target=_backup_scheduler_loop,
        name="picsyncra-sqlite-backup-scheduler",
        daemon=True,
    )
    _BACKUP_SCHEDULER_THREAD.start()


def _stop_backup_scheduler() -> None:
    global _BACKUP_SCHEDULER_THREAD
    _BACKUP_SCHEDULER_STOP.set()
    thread = _BACKUP_SCHEDULER_THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=2)
    _BACKUP_SCHEDULER_THREAD = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _observability_limit(value: object) -> int:
    try:
        parsed = int(value or 20)
    except (TypeError, ValueError):
        parsed = 20
    return max(1, min(100, parsed))


def _validate_observability_cursor(value: object) -> str:
    cursor = str(value or "")
    if not cursor:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", cursor):
        raise HTTPException(status_code=400, detail="Niepoprawny kursor.")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded_bytes = base64.b64decode(
            padded.encode("ascii"), altchars=b"-_", validate=True
        )
        canonical = base64.urlsafe_b64encode(decoded_bytes).decode("ascii").rstrip("=")
        if canonical != cursor:
            raise ValueError("non-canonical cursor")
        decoded = decoded_bytes.decode("utf-8")
        payload = json.loads(decoded)
    except (
        binascii.Error,
        UnicodeDecodeError,
        UnicodeEncodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise HTTPException(status_code=400, detail="Niepoprawny kursor.") from exc
    if (
        not isinstance(payload, list)
        or len(payload) != 2
        or not all(isinstance(item, str) and item.strip() for item in payload)
    ):
        raise HTTPException(status_code=400, detail="Niepoprawny kursor.")
    try:
        parsed_at = datetime.fromisoformat(payload[0].replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Niepoprawny kursor.") from exc
    if parsed_at.tzinfo is None or parsed_at.utcoffset() is None:
        raise HTTPException(status_code=400, detail="Niepoprawny kursor.")
    canonical_timestamp = parsed_at.astimezone(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    if payload[0] != canonical_timestamp:
        raise HTTPException(status_code=400, detail="Niepoprawny kursor.")
    return cursor


def _validated_severities(value: object, *, multiple: bool = True) -> list[str]:
    raw_values = str(value or "").split(",") if multiple else [str(value or "")]
    severities = [item.strip().lower() for item in raw_values if item.strip()]
    if any(item not in SEVERITIES for item in severities):
        raise HTTPException(status_code=400, detail="Niepoprawny poziom zdarzenia.")
    return list(dict.fromkeys(severities))


def _observability_api_payload(
    username: str, page: Dict[str, Any]
) -> Dict[str, Any]:
    store = observability_store()
    safe_items = redact_sensitive_value(
        list(page.get("items") or []), text_limit=32 * 1024
    )
    return {
        "items": safe_items if isinstance(safe_items, list) else [],
        "next_cursor": str(page.get("next_cursor") or ""),
        "unread": store.unread_alert_summary(username),
        "server_time": _utc_now_iso(),
    }


_INTEGRATION_EVENT_NAMES = {
    "integration.ftp.completed": "ftp",
    "integration.sql.completed": "sql",
    "integration.pimcore.completed": "pimcore",
}
_SAFE_INTEGRATION_STATUSES = {
    "completed",
    "disabled",
    "error",
    "failed",
    "ok",
    "online",
    "success",
    "unknown",
    "warning",
}


def _safe_integration_status(event: Dict[str, Any]) -> str:
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    status = str(details.get("status") or "").strip().lower()
    if status in _SAFE_INTEGRATION_STATUSES:
        return status
    if str(event.get("severity") or "") in {"error", "critical"}:
        return "error"
    return "unknown"


def _last_known_integrations(store: Any) -> Dict[str, Any]:
    unknown = {"status": "unknown", "observed_at": ""}
    result: Dict[str, Any] = {
        "ftp": dict(unknown),
        "sql": dict(unknown),
        "sql_profiles": [],
        "pimcore": dict(unknown),
    }
    seen_components: set[str] = set()
    seen_profiles: set[str] = set()
    page = store.query_operational_events(limit=100)
    for event in page.get("items") or []:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "")
        observed_at = str(event.get("created_at") or "")
        status = _safe_integration_status(event)
        component = _INTEGRATION_EVENT_NAMES.get(event_type)
        if component and component not in seen_components:
            result[component] = {"status": status, "observed_at": observed_at}
            seen_components.add(component)
            continue
        if event_type != "integration.sql_profile.completed":
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        profile_id = str(details.get("profile_id") or "").strip()[:200]
        if not profile_id or profile_id in seen_profiles:
            continue
        seen_profiles.add(profile_id)
        result["sql_profiles"].append(
            {
                "profile_id": profile_id,
                "status": status,
                "observed_at": observed_at,
            }
        )
    return result


def _cached_last_known_integrations(store: Any) -> Dict[str, Any]:
    global _HEALTH_INTEGRATION_CACHE
    global _HEALTH_INTEGRATION_CACHE_AT
    global _HEALTH_INTEGRATION_CACHE_PATH
    store_path = str(getattr(store, "path", "") or "")
    now = time.monotonic()
    with _HEALTH_INTEGRATION_CACHE_LOCK:
        if (
            _HEALTH_INTEGRATION_CACHE is not None
            and _HEALTH_INTEGRATION_CACHE_PATH == store_path
            and now - _HEALTH_INTEGRATION_CACHE_AT < _HEALTH_INTEGRATION_CACHE_SECONDS
        ):
            return _HEALTH_INTEGRATION_CACHE
        snapshot = _last_known_integrations(store)
        _HEALTH_INTEGRATION_CACHE = snapshot
        _HEALTH_INTEGRATION_CACHE_PATH = store_path
        _HEALTH_INTEGRATION_CACHE_AT = now
        return snapshot


def _cached_health_store() -> Any:
    """Initialize the health SQLite store once per configured database path."""

    global _HEALTH_STORE_CACHE
    global _HEALTH_STORE_CACHE_PATH
    store_path = str(storage_settings.resolve_sqlite_path())
    with _HEALTH_STORE_CACHE_LOCK:
        if _HEALTH_STORE_CACHE is not None and _HEALTH_STORE_CACHE_PATH == store_path:
            return _HEALTH_STORE_CACHE
        store = observability_store()
        _HEALTH_STORE_CACHE = store
        _HEALTH_STORE_CACHE_PATH = store_path
        return store


def _invalidate_health_integration_cache() -> None:
    global _HEALTH_INTEGRATION_CACHE
    global _HEALTH_INTEGRATION_CACHE_AT
    global _HEALTH_INTEGRATION_CACHE_PATH
    global _HEALTH_STORE_CACHE
    global _HEALTH_STORE_CACHE_PATH
    with _HEALTH_STORE_CACHE_LOCK:
        _HEALTH_STORE_CACHE = None
        _HEALTH_STORE_CACHE_PATH = ""
    with _HEALTH_INTEGRATION_CACHE_LOCK:
        _HEALTH_INTEGRATION_CACHE = None
        _HEALTH_INTEGRATION_CACHE_AT = 0.0
        _HEALTH_INTEGRATION_CACHE_PATH = ""


def _integration_component_status(status: object) -> str:
    value = str(status or "unknown")
    if value in {"success", "ok", "online", "completed"}:
        return "online"
    if value in {"error", "failed", "warning"}:
        return "degraded"
    return value if value == "disabled" else "unknown"


def _canonical_health_observed_at(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        observed_at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if observed_at.tzinfo is None:
        return ""
    return (
        observed_at.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _health_payload() -> Dict[str, Any]:
    server_time = _utc_now_iso()
    components: Dict[str, Dict[str, Any]] = {
        "backend": {"status": "online", "observed_at": server_time},
        "sqlite": {"status": "critical", "observed_at": server_time},
        "job_processor": {
            "status": "critical"
            if bool(getattr(_PROCESS_QUEUE, "_stopping", False))
            else "online",
            "observed_at": server_time,
        },
        "notification_worker": notification_worker_health(),
    }
    integrations: Dict[str, Any] = {
        "ftp": {"status": "unknown", "observed_at": ""},
        "sql": {"status": "unknown", "observed_at": ""},
        "sql_profiles": [],
        "pimcore": {"status": "unknown", "observed_at": ""},
    }
    try:
        store = _cached_health_store()
        with store.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        components["sqlite"] = {"status": "online", "observed_at": server_time}
        integrations = _cached_last_known_integrations(store)
    except Exception:
        pass
    for name in ("ftp", "sql", "pimcore"):
        item = integrations[name]
        components[name] = {
            "status": _integration_component_status(item.get("status")),
            "observed_at": item.get("observed_at", ""),
        }
    profile_items = integrations["sql_profiles"]
    profile_statuses = {
        _integration_component_status(item.get("status")) for item in profile_items
    }
    profile_observed_at = max(
        (
            _canonical_health_observed_at(item.get("observed_at"))
            for item in profile_items
        ),
        default="",
    )
    components["sql_profiles"] = {
        "status": (
            "degraded"
            if "degraded" in profile_statuses
            else "online"
            if profile_items and profile_statuses == {"online"}
            else "unknown"
        ),
        "count": len(profile_items),
        "observed_at": profile_observed_at,
    }
    local_ready = all(
        components[name]["status"] == "online"
        for name in ("backend", "sqlite", "job_processor", "notification_worker")
    )
    return {
        "ok": local_ready,
        "application": brand.PACKAGE_NAME,
        "version": get_display_version(),
        "time": server_time,
        "components": components,
        "integrations": integrations,
        "resources": _RESOURCE_MONITOR.latest_public_snapshot(),
    }


_EMAIL_TEST_ATTEMPT_CODES = frozenset(
    {
        "delivery_failed",
        "message_invalid",
        "partial_routing_unknown",
        "processing_failed",
        "settings_unavailable",
        "test_failed",
        "transport_unavailable",
    }
)

_EMAIL_TEST_SUITE_KINDS = frozenset(
    {
        "pimcore_rejection",
        "ftp_failure",
        "photo_location_unavailable",
        "backend_exception",
        "entra_secret_expiry",
    }
)
_EMAIL_TEST_SUITE_SEVERITIES = frozenset({"info", "warning", "error", "critical"})
_EMAIL_TEST_SUITE_STATUSES = frozenset({"sent", "fallback", "skipped", "error"})


def _redacted_email_test_attempt(raw: object) -> Dict[str, Any]:
    """Project one transport attempt without returning provider diagnostics."""

    item = raw if isinstance(raw, dict) else {}
    channel = str(item.get("channel") or "").strip().lower()
    if channel not in {"entra", "smtp"}:
        channel = ""
    raw_status = str(item.get("status") or "").strip().lower()
    status = (
        raw_status
        if raw_status in {"sent", "partial", "refused"}
        else "error"
    )
    attempt: Dict[str, Any] = {"channel": channel, "status": status}
    for key in ("status_code", "elapsed_ms"):
        value = item.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            attempt[key] = max(0, value)
    if status in {"partial", "refused"}:
        for key in ("accepted_count", "refused_count"):
            value = item.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                attempt[key] = max(0, value)
        raw_codes = item.get("refusal_codes")
        if isinstance(raw_codes, (list, tuple, set)):
            attempt["refusal_codes"] = sorted(
                {
                    max(0, value)
                    for value in raw_codes
                    if isinstance(value, int) and not isinstance(value, bool)
                }
            )[:20]
        return attempt
    if status == "sent":
        return attempt
    category = str(item.get("category") or "delivery").strip().lower()
    if category not in {"configuration", "transport", "message", "delivery", "internal"}:
        category = "delivery"
    code = str(item.get("code") or "delivery_failed").strip().lower()
    if code not in _EMAIL_TEST_ATTEMPT_CODES:
        code = "delivery_failed"
    messages = {
        "configuration": "Niepoprawna lub niedostepna konfiguracja kanalu.",
        "transport": "Kanal wysylki jest niedostepny.",
        "message": "Nie mozna przygotowac wiadomosci.",
        "internal": "Nie mozna zakonczyc testu wysylki.",
        "delivery": "Kanal nie wyslal wiadomosci.",
    }
    attempt.update({"code": code, "category": category, "message": messages[category]})
    return attempt


def _redacted_email_test_suite_scenario(raw: object) -> Dict[str, Any]:
    """Project one test-suite result without messages, recipients or IDs."""

    item = raw if isinstance(raw, dict) else {}
    kind = str(item.get("kind") or "").strip().lower()
    if kind not in _EMAIL_TEST_SUITE_KINDS:
        kind = ""
    severity = str(item.get("severity") or "").strip().lower()
    if severity not in _EMAIL_TEST_SUITE_SEVERITIES:
        severity = "critical" if kind == "entra_secret_expiry" else ""
    status = str(item.get("status") or "").strip().lower()
    if status not in _EMAIL_TEST_SUITE_STATUSES:
        status = "error"
    channel = str(item.get("used_channel") or "").strip().lower()
    if channel not in {"entra", "smtp"}:
        channel = ""
    recipient_count = item.get("recipient_count")
    if not isinstance(recipient_count, int) or isinstance(recipient_count, bool):
        recipient_count = 0
    attempts = item.get("attempts")
    return {
        "kind": kind,
        "severity": severity,
        "status": status,
        "used_channel": channel,
        "recipient_count": max(0, recipient_count),
        "attempts": [
            _redacted_email_test_attempt(attempt)
            for attempt in (attempts if isinstance(attempts, list) else [])[:2]
        ],
    }


_INCIDENT_DELIVERY_STATUSES = frozenset(
    {"pending", "sending", "sent", "fallback", "skipped", "error"}
)


def _public_incident_delivery(raw: object) -> Dict[str, Any]:
    """Return the closed, recipient-free delivery projection used by log cards."""

    item = raw if isinstance(raw, dict) else {}
    status = str(item.get("status") or "").strip().lower()
    if status not in _INCIDENT_DELIVERY_STATUSES:
        status = "error"
    channel = str(item.get("used_channel") or "").strip().lower()
    if channel not in {"entra", "smtp"}:
        channel = ""
    recipients = item.get("recipients")
    raw_attempts = item.get("attempts")
    attempts = raw_attempts if isinstance(raw_attempts, list) else []
    return {
        "id": str(item.get("id") or ""),
        "status": status,
        "used_channel": channel,
        "recipient_count": len(recipients) if isinstance(recipients, list) else 0,
        "created_at": str(item.get("created_at") or ""),
        "updated_at": str(item.get("updated_at") or ""),
        "attempts": [_redacted_email_test_attempt(attempt) for attempt in attempts[:2]],
    }


def _is_ocr_progress_poll(request: Request) -> bool:
    """Return whether a request merely reads the live OCR run status."""

    return (
        request.method.upper() == "GET"
        and request.url.path.startswith("/api/settings/ocr/runs/")
    )


def _is_ocr_blocking_request(request: Request) -> bool:
    """Return whether this request intentionally resets OCR idle time."""

    return (str(request.method or "").upper(), str(request.url.path or "")) in {
        ("POST", "/api/upload-cache"),
        ("POST", "/api/web-images/cache"),
        ("POST", "/api/ocr/slot-assignment"),
        ("POST", "/api/process/background"),
        ("POST", "/api/ocr/activity"),
    }


def create_app() -> FastAPI:
    """Create the LAN web backend."""

    app = FastAPI(title="PicSyncra Web", version=get_app_version())
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    runtime_status_service = RuntimeStatusService(
        health_provider=lambda: _health_payload(),
        file_index_provider=lambda: file_index_status(start=False),
        process_queue_provider=lambda: _runtime_process_queue_summary(),
        active_clients_provider=lambda: _runtime_active_clients_summary(),
        clock=lambda: _utc_now_iso(),
    )
    app.state.ocr_activity_lock = threading.Lock()
    app.state.ocr_active_requests = 0
    app.state.ocr_last_activity = time.monotonic()
    app.state.ocr_queue_stop = threading.Event()
    app.state.ocr_queue_thread = None
    app.state.ocr_execution_service = None
    app.state.ocr_execution_worker = None

    def _ocr_has_active_requests() -> bool:
        with app.state.ocr_activity_lock:
            return bool(app.state.ocr_active_requests)

    def _ocr_last_activity() -> float:
        with app.state.ocr_activity_lock:
            return float(app.state.ocr_last_activity)

    app.state.ocr_queue_lease = OcrQueueLease(last_activity=_ocr_last_activity)

    def _ocr_resource_telemetry() -> ResourceTelemetry:
        snapshot = _RESOURCE_MONITOR.latest_public_snapshot()
        host = snapshot.get("host") if isinstance(snapshot, dict) else {}
        host = host if isinstance(host, dict) else {}

        def number(key: str) -> float:
            try:
                return float(host.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0

        return ResourceTelemetry(
            cpu_percent=number("cpu_percent"),
            memory_used_bytes=int(number("memory_used_bytes")),
            memory_total_bytes=int(number("memory_total_bytes")),
            disk_busy_percent=number("disk_busy_percent"),
        )

    def _ocr_execution_service() -> OcrExecutionService:
        service = app.state.ocr_execution_service
        if service is None:
            raise HTTPException(status_code=503, detail="Proces OCR nie jest jeszcze gotowy.")
        return service

    def _process_ocr_crop_job(job: dict[str, object]) -> None:
        """Process both persisted slot stages through the isolated OCR worker."""

        ocr_settings = normalize_ocr_settings(
            config.CONFIG.get(OCR_SETTINGS_KEY, {})
        )
        process_slot_ocr_queue_job(
            job,
            store=observability_store(),
            analyze=lambda path, profile_ids: _analyze_image_values_with_configured_profiles(
                path, profile_ids=profile_ids
            ),
            enqueue_crops=enqueue_ocr_crop_jobs,
            crop_dir=_ocr_crop_root(),
            settings=ocr_settings,
        )

    def _run_ocr_queue_once() -> str:
        _purge_expired_ocr_crop_jobs()
        ocr_settings = normalize_ocr_settings(
            config.CONFIG.get(OCR_SETTINGS_KEY, {})
        )
        if not bool(ocr_settings.get("background_enabled")):
            return "disabled"
        scheduler = OcrQueueScheduler(
            settings=lambda: ocr_settings,
            has_active_requests=_ocr_has_active_requests,
            last_activity=_ocr_last_activity,
            cpu_percent=_ocr_cpu_percent,
            claim_job=observability_store().claim_ocr_crop_job,
            process_job=_process_ocr_crop_job,
            requeue_job=lambda job: observability_store().requeue_ocr_crop_job(
                str(job.get("id") or "")
            ),
            lease=app.state.ocr_queue_lease,
            now=time.monotonic,
        )
        return scheduler.run_once()

    @app.exception_handler(Exception)
    async def _unhandled_application_error(
        request: Request, exc: Exception
    ) -> JSONResponse:
        correlation_id = f"corr-{secrets.token_hex(12)}"
        emit_event(
            severity="critical",
            event_type="backend.unhandled_error",
            module="web",
            stage="request",
            correlation_id=correlation_id,
            summary="Unhandled application error.",
            details={"method": request.method, "path": request.url.path},
            exception=exc,
        )
        log_error(
            f"[{correlation_id}] WEB {request.method} {request.url.path}: "
            f"{exc}\n{traceback.format_exc()}"
        )
        return JSONResponse(
            {
                "detail": "Wystapil nieoczekiwany blad aplikacji.",
                "correlation_id": correlation_id,
            },
            status_code=500,
        )

    def _runtime_info() -> Dict[str, Any]:
        return {
            "base_dir": settings.AC,
            "processed_dir": settings.l,
            "config_path": config.CONFIG_PATH,
            "warning": settings.BASE_DIR_OVERRIDE_WARNING,
        }

    @app.middleware("http")
    async def _guard_mutating_requests(request: Request, call_next):
        try:
            _validate_mutating_request(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return await call_next(request)

    @app.middleware("http")
    async def _guard_rate_limits(request: Request, call_next):
        try:
            _check_rate_limit(request)
        except HTTPException as exc:
            return JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers=getattr(exc, "headers", None),
            )
        return await call_next(request)

    @app.middleware("http")
    async def _add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'",
        )
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    @app.middleware("http")
    async def _track_active_clients(request: Request, call_next):
        response = await call_next(request)
        _record_active_client(request, getattr(response, "status_code", 0))
        return response

    @app.middleware("http")
    async def _prioritize_interactive_work(request: Request, call_next):
        is_blocking_activity = _is_ocr_blocking_request(request)
        if is_blocking_activity:
            with app.state.ocr_activity_lock:
                app.state.ocr_active_requests += 1
                app.state.ocr_last_activity = time.monotonic()
        try:
            return await call_next(request)
        finally:
            if is_blocking_activity:
                with app.state.ocr_activity_lock:
                    app.state.ocr_active_requests = max(
                        0, app.state.ocr_active_requests - 1
                    )
                    app.state.ocr_last_activity = time.monotonic()

    @app.on_event("startup")
    def _startup() -> None:
        global _OCR_EXECUTION_SERVICE
        os.environ.setdefault("PICSYNCRA_HEADLESS", "1")
        runtime_info = initialize_application_runtime(interactive=False)
        app.state.runtime_info = runtime_info
        _ensure_active_client_registry()
        _RESOURCE_MONITOR.start()
        if OCR_FEATURE_ENABLED:
            _clear_ocr_crop_queue_on_startup()
            ocr_settings = normalize_ocr_settings(config.CONFIG.get(OCR_SETTINGS_KEY, {}))
            ocr_worker = OcrWorkerProcess(
                cpu_percent=int(ocr_settings.get("max_cpu_percent") or 35)
            )
            execution_service = OcrExecutionService(
                worker=ocr_worker,
                registry=OcrProgressRegistry(),
                settings=lambda: normalize_ocr_settings(
                    config.CONFIG.get(OCR_SETTINGS_KEY, {})
                ),
                telemetry=_ocr_resource_telemetry,
                on_worker_ready=(
                    callback
                    if callable(
                        callback := getattr(
                            _RESOURCE_MONITOR, "register_ocr_worker_pid", None
                        )
                    )
                    else None
                ),
            )
            execution_service.start()
            app.state.ocr_execution_worker = ocr_worker
            app.state.ocr_execution_service = execution_service
            _OCR_EXECUTION_SERVICE = execution_service
            app.state.ocr_queue_stop.clear()
            worker = OcrQueueWorker(
                run_once=_run_ocr_queue_once,
                poll_seconds=0.5,
                stop_event=app.state.ocr_queue_stop,
            )
            app.state.ocr_queue_thread = threading.Thread(
                target=worker.run,
                name="picsyncra-ocr-queue",
                daemon=True,
            )
            app.state.ocr_queue_thread.start()
        cleanup_web_ftp_cache(force=True)
        cleanup_web_upload_cache(force=True)
        try:
            _prune_live_events_if_due(force=True)
        except Exception as exc:
            log_error(f"WEB observability pruning failed: {exc}\n{traceback.format_exc()}")
        _start_backup_scheduler()
        start_notification_worker()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        global _OCR_EXECUTION_SERVICE
        app.state.ocr_queue_stop.set()
        worker = app.state.ocr_execution_worker
        if worker is not None:
            worker.stop(timeout=5)
        app.state.ocr_execution_worker = None
        app.state.ocr_execution_service = None
        _OCR_EXECUTION_SERVICE = None
        queue_thread = app.state.ocr_queue_thread
        if queue_thread is not None and queue_thread is not threading.current_thread():
            queue_thread.join(timeout=2.0)
        app.state.ocr_queue_thread = None
        _RESOURCE_MONITOR.stop()
        stop_notification_worker()
        _stop_backup_scheduler()
        with _ACTIVE_CLIENT_REGISTRY_LIFECYCLE_LOCK:
            _ACTIVE_CLIENT_REGISTRY.close(timeout=5.0)
        data_store.reset_active_store_cache()

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return _health_payload()

    runtime_router = build_runtime_router(
        RuntimeApiDependencies(
            current_user_payload=lambda request: _current_user_payload(request),
            require_user=lambda request: _require_user(request),
            require_admin=lambda request: _require_admin(request),
            runtime_status=runtime_status_service.snapshot,
            file_index_status=lambda: file_index_status(start=True),
            refresh_file_index=refresh_file_index,
            active_clients=_active_clients_snapshot,
            presence_payload=_active_presence_payload,
            request_client_id=_request_presence_client_id,
            remove_active_client=_remove_active_client,
        )
    )
    runtime_routes = {route.path: route for route in runtime_router.routes}
    app.routes.append(runtime_routes["/api/runtime-status"])

    @app.post("/api/resource-monitor/simulate-safe")
    def resource_monitor_simulate_safe(request: Request) -> Dict[str, Any]:
        _require_admin(request)
        result = dict(_RESOURCE_MONITOR.record_safe_simulation())
        resources = result.get("resources")
        if not isinstance(resources, dict):
            resources = _RESOURCE_MONITOR.latest_public_snapshot()
        if bool(result.get("ok")):
            message = "Zapisano bezpieczna symulacje zdarzenia zasobow."
        else:
            message = "Nie udalo sie trwale zapisac bezpiecznej symulacji zdarzenia zasobow."
        return {
            "ok": bool(result.get("ok")),
            "message": message,
            "resources": resources,
            "test": result,
        }

    @app.post("/api/resource-monitor/real-test")
    async def resource_monitor_real_test(request: Request) -> Dict[str, Any]:
        _require_admin(request)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        kind = str(payload.get("kind") or "") if isinstance(payload, dict) else ""
        try:
            result = dict(
                await run_in_threadpool(_RESOURCE_MONITOR.start_real_test, kind)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        status = str(result.get("status") or "unknown")
        if bool(result.get("ok")):
            message = "Test zasobow zakonczony: przekroczenie progu wykryte."
        elif status == "persistence_failed":
            message = "Test zasobow nie potwierdzil alertu: nie udalo sie trwale zapisac zdarzenia progu."
        elif status == "not_detected":
            message = "Test zasobow zakonczony bez wykrycia przekroczenia progu."
        else:
            message = f"Test zasobow zakonczony ze statusem: {status}."
        return {
            "ok": bool(result.get("ok")),
            "message": message,
            "resources": _RESOURCE_MONITOR.latest_public_snapshot(),
            "test": result,
        }

    @app.get("/")
    def index(request: Request) -> Response:
        if _auth_enabled() and not _current_user(request):
            return RedirectResponse("/login", status_code=303)
        return _static_file("index.html")

    @app.get("/login")
    def login_page(request: Request) -> Response:
        if not _auth_enabled():
            return RedirectResponse("/", status_code=303)
        if _current_user(request):
            return RedirectResponse("/", status_code=303)
        return _static_file("login.html")

    @app.post("/api/login")
    async def login(request: Request) -> JSONResponse:
        form = await request.form()
        username = str(form.get("username") or "").strip()
        password = str(form.get("password") or "")
        auth_result = authenticate_login(
            username,
            password,
            remote_address=_request_remote_address(request),
            user_agent=str(request.headers.get("user-agent") or ""),
        )
        user = auth_result.get("user") if isinstance(auth_result.get("user"), dict) else None
        if not auth_result.get("ok"):
            failed_count = int(auth_result.get("failed_login_count") or (user or {}).get("failed_login_count") or 0)
            locked = bool((user or {}).get("locked"))
            reason = str(auth_result.get("reason") or "bad_password")
            level = "WARNING"
            if locked and (user or {}).get("lock_manual"):
                message = "Konto administratora zablokowane po blednych probach logowania."
            elif locked:
                message = "Konto zablokowane czasowo po blednych probach logowania."
            elif failed_count > 1:
                message = "Kolejna bledna proba logowania."
            else:
                message = "Bledna proba logowania."
            _write_web_event(
                level=level,
                event="login_failed",
                username=username or "unknown",
                message=message,
                details={
                    "reason": reason,
                    "failed_login_count": failed_count,
                    "limit": auth_result.get("limit"),
                    "locked": locked,
                    "lock_manual": bool((user or {}).get("lock_manual")),
                    "lock_expires_at": (user or {}).get("lock_expires_at", ""),
                    "remote_address": _request_remote_address(request),
                    "user_agent": str(request.headers.get("user-agent") or "")[:200],
                },
            )
            if locked and (user or {}).get("lock_manual"):
                raise HTTPException(
                    status_code=423,
                    detail="Konto jest zablokowane. Odblokuj je w panelu startowym WEB.",
                )
            if locked:
                until = str((user or {}).get("lock_expires_at") or "")
                suffix = f" do {until}" if until else ""
                raise HTTPException(status_code=423, detail=f"Konto jest zablokowane{suffix}.")
            raise HTTPException(status_code=401, detail="Niepoprawny login lub haslo.")
        if not user:
            raise HTTPException(status_code=401, detail="Niepoprawny login lub haslo.")
        session_token = _make_session_token(user)
        response = JSONResponse(
            {"ok": True, "user": user, "csrf_token": _csrf_token_for_session(session_token)}
        )
        response.set_cookie(
            SESSION_COOKIE,
            session_token,
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,
            samesite="strict",
        )
        return response

    @app.post("/api/logout")
    def logout(request: Request) -> JSONResponse:
        username = _current_user(request)
        if username:
            _remove_active_client(username, _request_presence_client_id(request))
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/api/bootstrap")
    def bootstrap(request: Request) -> Dict[str, Any]:
        _require_user(request)
        runtime_info = _runtime_info()
        slots = slot_definitions_from_config(config.CONFIG)
        return {
            "base_dir": runtime_info["base_dir"],
            "processed_dir": settings.l,
            "config_path": runtime_info["config_path"],
            "version": get_display_version(),
            "auto_content_fit": bool(config.CONFIG.get(AUTO_CONTENT_FIT_KEY, False)),
            "processing": _processing_settings(),
            "security": _security_settings(),
            "web_display": config.normalize_web_display_settings(
                config.CONFIG.get(WEB_DISPLAY_SETTINGS_KEY, {})
            ),
            "runtime_warning": runtime_info.get("warning"),
            "slots": slots,
            "admin_user": _admin_username(),
            "auth_enabled": _auth_enabled(),
            "current_user": _current_user_payload(request),
            "csrf_token": _csrf_token(request),
            "ocr_enabled_slots": normalize_ocr_settings(
                config.CONFIG.get(OCR_SETTINGS_KEY, {})
            ).get("enabled_slots", []),
            **load_web_data(),
            "pimcore": pimcore_runtime_capabilities(),
        }

    @app.get("/api/github/repository")
    def github_repository_api(request: Request) -> Dict[str, Any]:
        _require_user(request)
        return github_repository_status(get_display_version())

    @app.get("/api/data")
    def data(request: Request) -> Dict[str, Any]:
        _require_user(request)
        return load_web_data()

    app.routes.append(runtime_routes["/api/file-index/status"])

    @app.get("/api/history")
    def history_api(
        request: Request,
        user: str = "",
        query: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        _require_user(request)
        return history_snapshot(
            user=user,
            query=query,
            page=page,
            page_size=page_size,
        )

    @app.get("/api/history/details")
    def history_details_api(
        request: Request,
        ean: str,
        user: str = "",
        query: str = "",
        page: int = 1,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        _require_user(request)
        payload = history_group_snapshot(
            ean=ean,
            user=user,
            query=query,
            page=page,
            page_size=page_size,
        )
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono historii dla wybranego EAN.",
            )
        return payload

    @app.get("/api/logs")
    def logs_api(request: Request, limit: int = 300) -> Dict[str, Any]:
        _require_admin(request)
        return _logs_response(limit)

    @app.get("/api/observability/events")
    def observability_events_api(
        request: Request,
        live_seed: bool = False,
        severity: str = "",
        cursor: str = "",
        limit: int = 20,
        username: str = "",
        ean: str = "",
        job_id: str = "",
        correlation_id: str = "",
        module: str = "",
        query: str = "",
        since: str = "",
    ) -> Dict[str, Any]:
        current_user = _require_admin(request)
        store = observability_store()
        if live_seed:
            live_severities = _validated_severities(severity)
            seed_since = (
                datetime.now(timezone.utc) - timedelta(hours=24)
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            page = store.snapshot_operational_event_stream(
                since=seed_since,
                limit=200,
                severities=live_severities,
                username=username,
                ean=ean,
                job_id=job_id,
                module=module,
                query=query,
            )
            response = _observability_api_payload(
                str(current_user.get("username") or ""), page
            )
            response["stream_after_id"] = str(page.get("stream_after_id") or "")
            response["archive_since"] = str(page.get("archive_since") or seed_since)
            return response
        severities = _validated_severities(severity)
        page = store.query_operational_events(
            severities=severities,
            username=username,
            ean=ean,
            job_id=job_id,
            correlation_id=correlation_id,
            module=module,
            query=query,
            cursor=_validate_observability_cursor(cursor),
            limit=_observability_limit(limit),
            since=since,
        )
        return _observability_api_payload(str(current_user.get("username") or ""), page)

    @app.get("/api/observability/incidents")
    def observability_incidents_api(
        request: Request,
        severity: str = "",
        cursor: str = "",
        limit: int = 20,
    ) -> Dict[str, Any]:
        current_user = _require_admin(request)
        severities = _validated_severities(severity, multiple=False)
        store = observability_store()
        page = store.query_incidents(
            severity=severities[0] if severities else "",
            cursor=_validate_observability_cursor(cursor),
            limit=_observability_limit(limit),
        )
        incident_items = [
            item for item in page.get("items") or [] if isinstance(item, dict)
        ]
        incident_ids = [str(item.get("id") or "") for item in incident_items]
        deliveries_by_incident: Dict[str, List[Dict[str, Any]]] = {}
        for delivery in store.notification_deliveries_for_incidents(
            incident_ids, per_incident_limit=5
        ):
            incident_id = str(delivery.get("incident_id") or "")
            if incident_id in incident_ids:
                deliveries_by_incident.setdefault(incident_id, []).append(
                    _public_incident_delivery(delivery)
                )
        page["items"] = [
            {
                **item,
                "deliveries": deliveries_by_incident.get(str(item.get("id") or ""), []),
            }
            for item in incident_items
        ]
        return _observability_api_payload(str(current_user.get("username") or ""), page)

    @app.get("/api/observability/incidents/{incident_id}/context")
    def observability_incident_context_api(
        incident_id: str,
        request: Request,
        cursor: str = "",
        limit: int = 20,
    ) -> Dict[str, Any]:
        current_user = _require_admin(request)
        context = observability_store().query_incident_context(
            incident_id,
            problem_cursor=_validate_observability_cursor(cursor),
            problem_limit=_observability_limit(limit),
        )
        if context is None:
            raise HTTPException(status_code=404, detail="Nie znaleziono incydentu.")
        safe_context = redact_sensitive_value(context, text_limit=32 * 1024)
        response = safe_context if isinstance(safe_context, dict) else {}
        response["unread"] = observability_store().unread_alert_summary(
            str(current_user.get("username") or "")
        )
        response["server_time"] = _utc_now_iso()
        return response

    @app.get("/api/observability/jobs")
    def observability_jobs_api(
        request: Request, cursor: str = "", limit: int = 20
    ) -> Dict[str, Any]:
        current_user = _require_admin(request)
        page = observability_store().query_job_runs(
            cursor=_validate_observability_cursor(cursor),
            limit=_observability_limit(limit),
        )
        return _observability_api_payload(str(current_user.get("username") or ""), page)

    @app.get("/api/observability/stream")
    async def observability_stream_api(
        request: Request, after_id: str = ""
    ) -> StreamingResponse:
        _require_admin(request)

        async def generate():
            store = observability_store()
            reconnect_id = str(request.headers.get("last-event-id") or "").strip()
            start = store.start_operational_event_stream(
                after_id=reconnect_id or str(after_id or "").strip(),
                initial_limit=100,
            )
            position = int(start.get("position") or 0)
            next_heartbeat = time.monotonic()
            for item in start.get("items") or []:
                if await request.is_disconnected():
                    return
                safe_item = redact_sensitive_value(item, text_limit=32 * 1024)
                if not isinstance(safe_item, dict):
                    continue
                event_id = str(safe_item.get("id") or "")
                yield (
                    f"id: {event_id}\n"
                    f"data: {json.dumps(safe_item, ensure_ascii=False)}\n\n"
                )
            while not await request.is_disconnected():
                page = store.poll_operational_event_stream(
                    position=position, limit=100
                )
                position = int(page.get("position") or position)
                for item in page.get("items") or []:
                    if await request.is_disconnected():
                        return
                    safe_item = redact_sensitive_value(item, text_limit=32 * 1024)
                    if not isinstance(safe_item, dict):
                        continue
                    event_id = str(safe_item.get("id") or "")
                    yield (
                        f"id: {event_id}\n"
                        f"data: {json.dumps(safe_item, ensure_ascii=False)}\n\n"
                    )
                now = time.monotonic()
                if now >= next_heartbeat:
                    if await request.is_disconnected():
                        return
                    yield ": heartbeat\n\n"
                    next_heartbeat = now + 15
                await asyncio.sleep(1)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post("/api/observability/read")
    async def observability_read_api(request: Request) -> Dict[str, Any]:
        username = _require_user(request)
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Niepoprawne dane odczytu.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Niepoprawne dane odczytu.")
        severities = _validated_severities(payload.get("severity"), multiple=False)
        event_id = str(payload.get("event_id") or "").strip()
        created_at = str(payload.get("created_at") or "").strip()
        if not severities or not event_id or not created_at:
            raise HTTPException(status_code=400, detail="Niepoprawne dane odczytu.")
        try:
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Niepoprawne dane odczytu.") from exc
        store = observability_store()
        store.mark_alerts_read(username, severities[0], event_id, created_at)
        return {
            "ok": True,
            "unread": store.unread_alert_summary(username),
            "server_time": _utc_now_iso(),
        }

    app.routes.append(runtime_routes["/api/server/active-users"])
    app.routes.append(runtime_routes["/api/server/presence"])
    app.routes.append(runtime_routes["/api/server/presence/leave"])

    @app.post("/api/logs/clear")
    async def logs_clear_api(request: Request) -> JSONResponse:
        current_user = _require_admin(request)
        payload = await request.json()
        password = str(payload.get("password") if isinstance(payload, dict) else "")
        username = str(current_user.get("username") or "")
        verified = authenticate_user(username, password)
        if not verified or verified.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Niepoprawne haslo administratora.")
        structured_result = observability_store().clear_operational_data()
        _invalidate_health_integration_cache()
        clear_result = _clear_log_files()
        response = _logs_response(400)
        response["cleared"] = clear_result["cleared"]
        response["clear_errors"] = clear_result["errors"]
        response["structured_cleared"] = structured_result
        return JSONResponse(response)

    app.routes.append(runtime_routes["/api/file-index/refresh"])

    @app.get("/api/suggestions")
    def suggestions_api(
        request: Request,
        field: str,
        name: str = "",
        type_name: str = "",
        model: str = "",
        color1: str = "",
        color2: str = "",
        color3: str = "",
        extra: str = "",
        limit: int = 100,
    ) -> Dict[str, Any]:
        _require_user(request)
        values = field_suggestions(
            field,
            {
                "name": name,
                "type_name": type_name,
                "model": model,
                "color1": color1,
                "color2": color2,
                "color3": color3,
                "extra": extra,
            },
            limit=limit,
        )
        return {"values": values, "file_index": file_index_status(start=True)}

    @app.post("/api/ftp-preview")
    async def ftp_preview_api(request: Request) -> Dict[str, Any]:
        username = _require_user(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
        try:
            path = await run_in_threadpool(
                cache_ftp_preview,
                payload.get("ean"),
                payload.get("filename"),
                _user_cache_scope(request, username),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        token = _file_token(path)
        version = _file_version(path)
        return {
            "token": token,
            "file_version": version,
            "url": _versioned_file_url(path, "/api/file", token),
            "thumb_url": _versioned_file_url(path, "/api/thumbnail", token),
        }

    @app.post("/api/upload-cache")
    async def upload_cache_api(request: Request) -> Dict[str, Any]:
        started = time.perf_counter()
        username = _require_user(request)
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile) or not upload.filename:
            raise HTTPException(status_code=400, detail="Brak pliku do wyslania.")
        original_name = upload.filename
        prefix = str(form.get("prefix") or "slot").strip() or "slot"
        cleanup_web_upload_cache()
        save_started = time.perf_counter()
        saved_cache = await _save_upload_cache_entry(
            upload,
            _user_cache_scope(request, username),
            prefix,
            normalize_extension=True,
        )
        path = saved_cache.path
        size = saved_cache.size
        save_ms = _elapsed_ms(save_started)
        preprocess_ms = 0
        preprocessed = False
        display_name = _safe_upload_name(saved_cache.name or original_name, os.path.basename(path))
        if _upload_processing_mode() == "host":
            preprocess_started = time.perf_counter()
            path, display_name, preprocessed = await _preprocess_cached_upload_with_scan_result(
                path,
                display_name,
                processing_options_from_config(config.CONFIG),
            )
            preprocess_ms = _elapsed_ms(preprocess_started)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
        token = _file_token(path)
        ocr_state = _schedule_ocr_value_collection(prefix, path)
        return {
            "token": token,
            "name": _safe_upload_name(display_name, os.path.basename(path)),
            "size_bytes": size,
            "preprocessed": preprocessed,
            "file_version": _file_version(path),
            "url": _versioned_file_url(path, "/api/file", token),
            "thumb_url": _versioned_file_url(path, "/api/thumbnail", token),
            "timing": {
                "total_ms": _elapsed_ms(started),
                "save_ms": save_ms,
                "preprocess_ms": preprocess_ms,
                "antivirus_scan_ms": int(_upload_scan_result(path).get("elapsed_ms") or 0),
                "mode": _upload_processing_mode(),
            },
            "antivirus_scan": _upload_scan_result(path),
            "ocr_state": ocr_state,
        }

    @app.options("/api/browser-extension/{path:path}")
    def browser_extension_options(request: Request, path: str = "") -> Response:
        return Response(status_code=204, headers=_browser_extension_cors_headers(request))

    @app.get("/api/browser-extension/download")
    def browser_extension_download_api(request: Request) -> Response:
        username = _require_user(request)
        data = _browser_extension_zip_bytes(request, username)
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="picsyncra-browser-extension.zip"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/browser-extension/ping")
    def browser_extension_ping_api(request: Request) -> JSONResponse:
        username = _require_browser_extension_user(request)
        return _browser_extension_json(
            request,
            {
                "ok": True,
                "username": username,
                "version": get_display_version(),
                "token_version": int((find_user(username) or {}).get("extension_token_version") or 0),
            },
        )

    @app.get("/api/browser-extension/imports")
    def browser_extension_imports_api(request: Request) -> Dict[str, Any]:
        username = _require_user(request)
        return {"items": _pop_browser_extension_imports(username)}

    @app.post("/api/browser-extension/upload-cache")
    async def browser_extension_upload_cache_api(request: Request) -> JSONResponse:
        started = time.perf_counter()
        username = _require_browser_extension_user(request)
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile) or not upload.filename:
            raise HTTPException(status_code=400, detail="Brak pliku do wyslania.")
        original_name = upload.filename
        prefix = str(form.get("prefix") or "web").strip() or "web"
        source_url = str(form.get("source_url") or "").strip()
        page_url = str(form.get("page_url") or "").strip()
        cleanup_web_upload_cache()
        save_started = time.perf_counter()
        saved_cache = await _save_upload_cache_entry(
            upload,
            _user_cache_scope(request, username),
            prefix,
            normalize_extension=True,
        )
        path = saved_cache.path
        size = saved_cache.size
        save_ms = _elapsed_ms(save_started)
        preprocess_ms = 0
        preprocessed = False
        display_name = _safe_upload_name(saved_cache.name or original_name, os.path.basename(path))
        if _upload_processing_mode() == "host":
            preprocess_started = time.perf_counter()
            path, display_name, preprocessed = await _preprocess_cached_upload_with_scan_result(
                path,
                display_name,
                processing_options_from_config(config.CONFIG),
            )
            preprocess_ms = _elapsed_ms(preprocess_started)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
        width, height = _image_dimensions(path)
        token = _file_token(path)
        cache_mime_type = UPLOAD_EXTENSION_MIME_TYPE.get(
            _upload_extension(display_name),
            str(upload.content_type or ""),
        )
        cache_payload = {
            "token": token,
            "name": _safe_upload_name(display_name, os.path.basename(path)),
            "size_bytes": size,
            "width": width,
            "height": height,
            "preprocessed": preprocessed,
            "file_version": _file_version(path),
            "url": _versioned_file_url(path, "/api/file", token),
            "thumb_url": _versioned_file_url(path, "/api/thumbnail", token),
            "timing": {
                "total_ms": _elapsed_ms(started),
                "save_ms": save_ms,
                "preprocess_ms": preprocess_ms,
                "antivirus_scan_ms": int(_upload_scan_result(path).get("elapsed_ms") or 0),
                "mode": _upload_processing_mode(),
            },
            "antivirus_scan": _upload_scan_result(path),
            "ocr_state": _schedule_ocr_value_collection(prefix, path),
        }
        item = {
            "source_url": source_url,
            "page_url": page_url,
            "filename": cache_payload["name"],
            "width": width,
            "height": height,
            "size_bytes": size,
            "mime_type": cache_mime_type,
            "source": "browser-extension",
            "kind": "image",
            "cache": cache_payload,
        }
        _record_browser_extension_import(username, item)
        return _browser_extension_json(request, {"ok": True, "item": item})

    @app.post("/api/web-images/scan")
    async def web_images_scan_api(request: Request) -> JSONResponse:
        _require_user(request)
        payload = await request.json()
        page_url = str(payload.get("url") if isinstance(payload, dict) else "").strip()
        if not page_url:
            raise HTTPException(status_code=400, detail="Podaj link do strony.")
        mode = str(payload.get("mode") or payload.get("scan_mode") or "metadata").strip()
        filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
        try:
            result = await run_in_threadpool(
                _scan_web_image_page,
                page_url,
                mode=mode,
                filters=filters,
            )
        except ImageImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result)

    @app.post("/api/web-images/cache")
    async def web_images_cache_api(request: Request) -> Dict[str, Any]:
        started = time.perf_counter()
        username = _require_user(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Niepoprawne dane obrazu.")
        image_url = str(payload.get("url") or "").strip()
        page_url = str(payload.get("page_url") or payload.get("referer") or "").strip()
        prefix = str(payload.get("prefix") or "slot").strip() or "slot"
        if not image_url:
            raise HTTPException(status_code=400, detail="Brak adresu obrazu.")
        cleanup_web_upload_cache()
        save_started = time.perf_counter()
        try:
            path, size, display_name, width, height = await run_in_threadpool(
                _save_web_image_cache,
                image_url,
                page_url,
                _user_cache_scope(request, username),
                prefix,
            )
        except ImageImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        save_ms = _elapsed_ms(save_started)
        preprocess_ms = 0
        preprocessed = False
        if _upload_processing_mode() == "host":
            preprocess_started = time.perf_counter()
            path, display_name, preprocessed = await run_in_threadpool(
                preprocess_cached_upload,
                path,
                display_name,
                processing_options_from_config(config.CONFIG),
            )
            preprocess_ms = _elapsed_ms(preprocess_started)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
        token = _file_token(path)
        ocr_state = _schedule_ocr_value_collection(prefix, path)
        return {
            "token": token,
            "name": _safe_upload_name(display_name, os.path.basename(path)),
            "size_bytes": size,
            "width": width,
            "height": height,
            "preprocessed": preprocessed,
            "file_version": _file_version(path),
            "url": _versioned_file_url(path, "/api/file", token),
            "thumb_url": _versioned_file_url(path, "/api/thumbnail", token),
            "ocr_state": ocr_state,
            "timing": {
                "total_ms": _elapsed_ms(started),
                "save_ms": save_ms,
                "preprocess_ms": preprocess_ms,
                "mode": _upload_processing_mode(),
            },
        }

    @app.get("/api/entries/search")
    def entries_search(
        request: Request,
        ean: str = "",
        product_id: str = "",
        name: str = "",
        type_name: str = "",
        model: str = "",
        query: str = "",
        limit: int = 30,
    ) -> Dict[str, Any]:
        _require_user(request)
        return {
            "entries": search_entries(
                ean=ean,
                product_id=product_id,
                name=name,
                type_name=type_name,
                model=model,
                query=query,
                limit=limit,
            )
        }

    @app.post("/api/entries/save")
    async def entries_save(request: Request) -> JSONResponse:
        username = _require_user(request)
        payload = await request.json()
        try:
            result = save_web_entry(payload if isinstance(payload, dict) else {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result:
            entry = result.get("entry", {}) if isinstance(result, dict) else {}
            record_history(
                username=username,
                action="entry_save",
                ean=(entry.get("EAN") or payload.get("ean")) if isinstance(payload, dict) else "",
                product_id=result.get("product_id", "") if isinstance(result, dict) else "",
                summary="Zapisano wpis produktu.",
                details={
                    "updated": bool(result.get("updated")) if isinstance(result, dict) else False,
                    "entry": entry,
                },
            )
        return JSONResponse({"ok": True, "entry": result})

    @app.post("/api/entries/photos")
    async def entries_photos(
        request: Request,
        source: str = "all",
        prefixes: str = "",
    ) -> JSONResponse:
        _require_user(request)
        payload = await request.json()
        source_key = str(source or "all").strip().lower()
        if source_key not in {"all", "local", "ftp", "sql"}:
            raise HTTPException(status_code=400, detail="Nieznane zrodlo zdjec.")
        photos = await run_in_threadpool(
            find_product_photos,
            payload if isinstance(payload, dict) else {},
            include_local=source_key in {"all", "local"},
            include_ftp=source_key in {"all", "ftp"},
            include_sql=source_key in {"all", "sql"},
        )
        requested_prefixes = {
            item.strip()
            for item in str(prefixes or "").split(",")
            if item.strip()
        }
        if requested_prefixes:
            photos = [
                photo
                for photo in photos
                if str(photo.get("prefix") or "") in requested_prefixes
            ]
        return JSONResponse({"photos": _enrich_photo_payload(photos), "source": source_key})

    @app.post("/api/similar-files")
    async def similar_files_api(request: Request) -> JSONResponse:
        _require_user(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Niepoprawne dane produktu.")
        candidates = await run_in_threadpool(find_web_similar_file_candidates, payload)
        return JSONResponse(
            {"candidates": [_public_similar_candidate(item) for item in candidates]}
        )

    @app.get("/api/file")
    def file_preview(request: Request, token: str) -> FileResponse:
        _require_user(request)
        path = _path_from_file_token(token)
        return FileResponse(path, headers={"Cache-Control": "private, max-age=300"})

    @app.get("/api/thumbnail")
    def file_thumbnail(
        request: Request,
        token: str,
        fit: int = 0,
        width: int = 360,
        height: int = 260,
    ) -> Response:
        _require_user(request)
        path = _path_from_file_token(token)
        content = _thumbnail_bytes(
            path,
            width=max(64, min(900, int(width or 360))),
            height=max(64, min(900, int(height or 260))),
            content_fit=bool(fit),
        )
        return Response(
            content=content,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=900"},
        )

    @app.post("/api/lists/{list_key}")
    async def list_add(request: Request, list_key: str) -> JSONResponse:
        _require_user(request)
        payload = await request.json()
        value = str(payload.get("value") if isinstance(payload, dict) else "")
        try:
            data_payload = add_list_value(list_key, value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(data_payload)

    @app.delete("/api/lists/{list_key}")
    async def list_remove(request: Request, list_key: str) -> JSONResponse:
        _require_user(request)
        payload = await request.json()
        value = str(payload.get("value") if isinstance(payload, dict) else "")
        try:
            data_payload = remove_list_value(list_key, value)
        except ListValueInUseError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(exc),
                    "list_key": exc.list_key,
                    "value": exc.value,
                    "used_by": exc.used_by,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(data_payload)

    @app.get("/api/settings")
    def settings_api(request: Request) -> Dict[str, Any]:
        user = _require_admin(request)
        payload = settings_snapshot()
        payload["ocr_available"] = OCR_FEATURE_ENABLED
        payload["current_user"] = user
        return payload

    @app.get("/api/settings/time-zones")
    def settings_time_zones(request: Request) -> Dict[str, List[str]]:
        _require_admin(request)
        return {"time_zones": config.available_display_time_zones()}

    @app.get("/api/settings/module-status")
    def settings_module_status(request: Request) -> Dict[str, Any]:
        _require_admin(request)
        runtime_root = (
            Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]
        )
        return module_status_snapshot(
            load_packaged_module_manifest(), runtime_root, os.environ
        )

    @app.get("/api/settings/ocr/status")
    def settings_ocr_status(request: Request) -> Dict[str, Any]:
        _require_admin(request)
        _require_ocr_feature()
        return image_ocr_runtime_info()

    @app.post("/api/settings/ocr/analyze")
    async def settings_ocr_analyze(request: Request) -> Dict[str, Any]:
        _require_admin(request)
        _require_ocr_feature()
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Niepoprawne dane testu OCR.")
        token = payload.get("token")
        if not isinstance(token, str) or not token.strip():
            raise HTTPException(status_code=400, detail="Wymagany jest token przeslanego obrazu.")
        path = _path_from_file_token(token.strip())
        diagnostics = await run_in_threadpool(
            _analyze_image_values_with_configured_profiles, path
        )
        result = asdict(diagnostics)
        result["image_url"] = _versioned_file_url(path, "/api/file", token.strip())
        return result

    @app.post("/api/settings/ocr/runs", status_code=202)
    async def settings_ocr_start_run(request: Request) -> Dict[str, Any]:
        """Start an ephemeral OCR tester run and return immediately for live polling."""

        _require_admin(request)
        _require_ocr_feature()
        try:
            payload = await request.json()
        except Exception:
            payload = None
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise HTTPException(status_code=400, detail="Wymagany jest token przeslanego obrazu.")
        path = _path_from_file_token(token.strip())
        run_id = _ocr_execution_service().submit_test(path=path)
        return {
            "run_id": run_id,
            "state": "started",
            "events_url": f"/api/settings/ocr/runs/{run_id}",
            "cancel_url": f"/api/settings/ocr/runs/{run_id}/cancel",
        }

    @app.get("/api/settings/ocr/runs/{run_id}")
    def settings_ocr_run_snapshot(
        request: Request, run_id: str, after_sequence: int = 0
    ) -> Dict[str, Any]:
        _require_admin(request)
        _require_ocr_feature()
        try:
            snapshot = _ocr_execution_service().snapshot(
                run_id, after_sequence=max(0, int(after_sequence))
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Nie znaleziono testu OCR.") from exc
        return asdict(snapshot)

    @app.post("/api/settings/ocr/runs/{run_id}/cancel")
    def settings_ocr_cancel_run(request: Request, run_id: str) -> Dict[str, Any]:
        _require_admin(request)
        _require_ocr_feature()
        try:
            _ocr_execution_service().cancel(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Nie znaleziono testu OCR.") from exc
        return {"run_id": run_id, "state": "cancellation_requested"}

    @app.get("/api/ocr/scan")
    async def ocr_scan(request: Request, token: str) -> Dict[str, Any]:
        """Return cached numeric OCR boxes for a signed slot image."""

        _require_user(request)
        _require_ocr_feature()
        signed_token = str(token or "").strip()
        if not signed_token:
            raise HTTPException(status_code=400, detail="Wymagany jest token obrazu.")
        path = _path_from_file_token(signed_token)
        image_hash = await run_in_threadpool(_image_sha256, path)
        scan = observability_store().get_ocr_scan(image_hash)
        values = list(scan.get("values") or []) if isinstance(scan, dict) else []
        return {
            "state": str(scan.get("state") or "missing") if isinstance(scan, dict) else "missing",
            "values": [
                {
                    "text": str(item.get("text") or ""),
                    "comparison": str(item.get("comparison") or ""),
                    "confidence": float(item.get("confidence") or 0),
                    "bbox": list(item.get("bbox") or []),
                }
                for item in values
                if isinstance(item, dict)
            ],
        }

    @app.post("/api/ocr/slot-assignment")
    async def ocr_slot_assignment(request: Request) -> Dict[str, str]:
        """Queue OCR when an existing signed image becomes a slot's current value."""

        _require_user(request)
        _require_ocr_feature()
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Niepoprawne dane przypisania slotu OCR.")
        prefix = str(payload.get("prefix") or "").strip()
        token = str(payload.get("token") or "").strip()
        if not prefix:
            raise HTTPException(status_code=400, detail="Wymagany jest numer slotu OCR.")
        if not token:
            raise HTTPException(status_code=400, detail="Wymagany jest token obrazu OCR.")
        path = _path_from_file_token(token)
        state = await run_in_threadpool(_schedule_ocr_value_collection, prefix, path)
        return {"state": state}

    @app.post("/api/ocr/validate")
    async def ocr_validate(request: Request) -> Dict[str, Any]:
        """Validate an entered Pimcore value against cached, signed image slots."""

        _require_admin(request)
        _require_ocr_feature()
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Niepoprawne dane walidacji OCR.")
        field_id = str(payload.get("field_id") or "").strip()
        if not field_id:
            raise HTTPException(status_code=400, detail="Wymagany jest identyfikator pola.")
        raw_tokens = payload.get("slot_tokens")
        if not isinstance(raw_tokens, list):
            raise HTTPException(status_code=400, detail="Wymagana jest lista slotow OCR.")
        tokens = [str(token).strip() for token in raw_tokens if str(token).strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail="Wymagany jest co najmniej jeden slot OCR.")
        value = normalize_entered_ocr_value(payload.get("value"))
        comparison = comparison_key(value)
        store = observability_store()
        image_hashes: list[str] = []
        images: list[dict[str, object]] = []
        pending = False
        all_values: list[dict[str, object]] = []
        for ordinal, token in enumerate(tokens):
            path = _path_from_file_token(token)
            image_hash = await run_in_threadpool(_image_sha256, path)
            image_hashes.append(image_hash)
            scan = store.get_ocr_scan(image_hash)
            if scan is None or str(scan.get("state") or "") != "completed":
                pending = True
            values = list(scan.get("values") or []) if isinstance(scan, dict) else []
            safe_values = [
                {
                    "text": str(item.get("text") or ""),
                    "comparison": str(item.get("comparison") or ""),
                    "confidence": float(item.get("confidence") or 0),
                    "bbox": list(item.get("bbox") or []),
                }
                for item in values
                if isinstance(item, dict)
            ]
            all_values.extend(safe_values)
            images.append(
                {
                    "slot_index": ordinal,
                    "state": str(scan.get("state") or "missing") if isinstance(scan, dict) else "missing",
                    "values": safe_values,
                }
            )
        matches = bool(comparison) and any(
            ocr_values_match(value, item["text"])
            for item in all_values
        )
        approved = bool(comparison) and store.has_ocr_approval(
            field_id, comparison, image_hashes
        )
        mismatch = bool(all_values) and not pending and not matches and not approved
        return {
            "value": value,
            "comparison": comparison,
            "matches": matches,
            "approved": approved,
            "pending": pending,
            "mismatch": mismatch,
            "images": images,
        }

    @app.get("/api/ocr/slots")
    def ocr_slots(request: Request) -> Dict[str, Any]:
        _require_admin(request)
        _require_ocr_feature()
        enabled = set(
            normalize_ocr_settings(config.CONFIG.get(OCR_SETTINGS_KEY, {})).get(
                "enabled_slots", []
            )
        )
        return {
            "slots": [
                {
                    "prefix": str(slot.get("prefix") or ""),
                    "label": str(slot.get("label") or ""),
                    "enabled": str(slot.get("prefix") or "") in enabled,
                }
                for slot in config.CONFIG.get(common.SLOT_DEFS_KEY, [])
                if isinstance(slot, dict) and str(slot.get("prefix") or "")
            ]
        }

    @app.get("/api/ocr/jobs")
    def ocr_jobs(request: Request) -> Dict[str, Any]:
        _require_ocr_feature()
        user = _current_user_payload(request)
        ocr_settings = normalize_ocr_settings(config.CONFIG.get(OCR_SETTINGS_KEY, {}))
        if (
            str(user.get("role") or "") != "admin"
            and not bool(ocr_settings.get("background_queue_visible_to_users"))
        ):
            raise HTTPException(status_code=403, detail="Kolejka OCR nie jest widoczna dla tego konta.")
        _purge_expired_ocr_crop_jobs()

        def public_job(job: dict[str, object]) -> dict[str, object]:
            thumbnail_path = str(job.get("thumbnail_path") or "")
            thumbnail_url = ""
            if thumbnail_path and os.path.isfile(thumbnail_path):
                try:
                    token = _file_token(thumbnail_path)
                    thumbnail_url = _versioned_file_url(
                        thumbnail_path, "/api/file", token
                    )
                except HTTPException:
                    pass
            result: list[str] = []
            for value in list(job.get("result") or []):
                if not isinstance(value, dict):
                    continue
                text = str(value.get("text") or "").strip()
                comparison = str(value.get("comparison") or "").strip()
                if not text and not comparison:
                    continue
                result.append(text if not comparison or comparison == text else f"{text} \u2192 {comparison}")
            return {
                "kind": (
                    "fast"
                    if str(job.get("kind") or "").strip().lower() == "fast"
                    else "accurate"
                ),
                "status": str(job.get("status") or ""),
                "result": result,
                "thumbnail_url": thumbnail_url,
            }

        grouped_jobs: dict[str, list[dict[str, object]]] = {}
        for index, job in enumerate(observability_store().list_ocr_crop_jobs()):
            image_hash = str(job.get("image_hash") or "").strip() or f"job-{index}"
            grouped_jobs.setdefault(image_hash, []).append(job)

        def group_rank(group: list[dict[str, object]]) -> int:
            statuses = {str(job.get("status") or "") for job in group}
            if "processing" in statuses:
                return 0
            if "pending" in statuses:
                return 1
            return 2

        def group_updated_at(group: list[dict[str, object]]) -> str:
            return max(
                str(job.get("updated_at") or job.get("created_at") or "")
                for job in group
            )

        ordered_groups = list(grouped_jobs.values())
        ordered_groups.sort(key=group_updated_at, reverse=True)
        ordered_groups.sort(key=group_rank)
        ordered = [job for group in ordered_groups for job in group]
        visible = ordered[:OCR_QUEUE_VISIBLE_LIMIT]
        return {
            "jobs": [public_job(job) for job in visible],
            "remaining_count": max(0, len(ordered) - len(visible)),
        }

    @app.post("/api/ocr/activity")
    async def ocr_activity(request: Request) -> Dict[str, Any]:
        """Record an explicit slot or data-load action for the idle OCR queue."""

        _require_ocr_feature()
        _require_user(request)
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Niepoprawny sygnal aktywnosci OCR.")
        kind = str(payload.get("kind") or "").strip()
        if kind not in {"slot-change", "data-load"}:
            raise HTTPException(status_code=400, detail="Niepoprawny rodzaj aktywnosci OCR.")
        with app.state.ocr_activity_lock:
            app.state.ocr_last_activity = time.monotonic()

        cancelled = 0
        removed_slot_token = str(payload.get("removed_slot_token") or "").strip()
        if removed_slot_token:
            image_path = _path_from_file_token(removed_slot_token)
            image_hash = await run_in_threadpool(_image_sha256, image_path)
            crop_paths = await run_in_threadpool(
                observability_store().cancel_pending_ocr_crop_jobs, image_hash
            )
            cancelled = len(crop_paths)
            crop_root = _ocr_crop_root()
            for crop_path in crop_paths:
                if not _path_is_under_root(crop_path, crop_root):
                    continue
                try:
                    if os.path.isfile(crop_path):
                        os.remove(crop_path)
                except OSError as exc:
                    log_error(f"OCR removed-slot crop cleanup failed: {exc}")
        return {"ok": True, "cancelled": cancelled}

    @app.post("/api/ocr/approval")
    async def ocr_approval(request: Request) -> Dict[str, Any]:
        """Persist an explicit user acceptance for one value and image set."""

        _require_admin(request)
        _require_ocr_feature()
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Niepoprawne dane potwierdzenia OCR.")
        field_id = str(payload.get("field_id") or "").strip()
        if not field_id:
            raise HTTPException(status_code=400, detail="Wymagany jest identyfikator pola.")
        raw_tokens = payload.get("slot_tokens")
        if not isinstance(raw_tokens, list):
            raise HTTPException(status_code=400, detail="Wymagana jest lista slotow OCR.")
        tokens = [str(token).strip() for token in raw_tokens if str(token).strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail="Wymagany jest co najmniej jeden slot OCR.")
        value = normalize_entered_ocr_value(payload.get("value"))
        comparison = comparison_key(value)
        if not comparison:
            raise HTTPException(status_code=400, detail="Wartosc nie zawiera liczby do potwierdzenia.")
        image_hashes = [
            await run_in_threadpool(_image_sha256, _path_from_file_token(token))
            for token in tokens
        ]
        await run_in_threadpool(
            observability_store().record_ocr_approval,
            field_id,
            comparison,
            image_hashes,
        )
        return {"ok": True, "value": value, "comparison": comparison}

    @app.post("/api/settings")
    async def settings_save(request: Request) -> JSONResponse:
        _require_admin(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Niepoprawne ustawienia.")
        previous_session_secret = _session_secret()
        try:
            snapshot = await run_in_threadpool(update_settings, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            log_error(f"WEB settings save failed: {exc}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Nie udalo sie zapisac ustawien: {exc}",
            ) from exc
        app.state.runtime_info = _runtime_info()
        if _auth_enabled() and not hmac.compare_digest(previous_session_secret, _session_secret()):
            snapshot["session_invalidated"] = True
            snapshot["session_message"] = "Zapisano APP_SECRET. Zaloguj sie ponownie."
            response = JSONResponse(snapshot)
            response.delete_cookie(SESSION_COOKIE)
            return response
        snapshot["current_user"] = _current_user_payload(request)
        return JSONResponse(snapshot)

    @app.post("/api/settings/email/test")
    async def settings_email_test(request: Request) -> JSONResponse:
        _require_admin(request)
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return JSONResponse(
                {"ok": False, "status": "invalid", "used_channel": "", "attempts": [], "elapsed_ms": 0},
                status_code=400,
            )
        recipient_value = payload.get("recipient")
        channel_value = payload.get("channel")
        use_fallback = payload.get("use_fallback", False)
        if not isinstance(recipient_value, str) or not recipient_value.strip():
            return JSONResponse(
                {"ok": False, "status": "invalid", "used_channel": "", "attempts": [], "elapsed_ms": 0},
                status_code=400,
            )
        if not isinstance(channel_value, str):
            channel_value = ""
        selected = channel_value.strip().lower()
        if selected not in {"entra", "smtp", "primary"} or not isinstance(use_fallback, bool):
            return JSONResponse(
                {"ok": False, "status": "invalid", "used_channel": "", "attempts": [], "elapsed_ms": 0},
                status_code=400,
            )
        if selected == "primary":
            try:
                email_settings = settings_snapshot().get(EMAIL_SETTINGS_KEY, {})
                selected = str(
                    email_settings.get("primary_channel")
                    if isinstance(email_settings, dict)
                    else ""
                ).strip().lower()
            except Exception:
                selected = ""
            if selected not in {"entra", "smtp"}:
                selected = "entra"

        started = time.perf_counter()
        try:
            result = await run_in_threadpool(
                send_test_message,
                channel=selected,
                recipient=recipient_value.strip(),
                use_fallback=use_fallback,
            )
        except ValueError:
            elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
            return JSONResponse(
                {"ok": False, "status": "invalid", "used_channel": selected, "attempts": [], "elapsed_ms": elapsed_ms},
                status_code=400,
            )
        except Exception:
            result = {
                "status": "error",
                "used_channel": selected,
                "attempts": [
                    {
                        "channel": selected,
                        "status": "error",
                        "code": "test_failed",
                        "category": "internal",
                    }
                ],
            }
        elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
        result = result if isinstance(result, dict) else {}
        status = str(result.get("status") or "error").strip().lower()
        if status not in {"sent", "fallback", "error"}:
            status = "error"
        used_channel = str(result.get("used_channel") or selected).strip().lower()
        if used_channel not in {"entra", "smtp"}:
            used_channel = selected
        raw_attempts = result.get("attempts")
        attempts = [
            _redacted_email_test_attempt(item)
            for item in (raw_attempts if isinstance(raw_attempts, list) else [])[:2]
        ]
        response_payload = {
            "ok": status in {"sent", "fallback"},
            "status": status,
            "used_channel": used_channel,
            "attempts": attempts,
            "elapsed_ms": elapsed_ms,
        }
        if response_payload["ok"] and used_channel == "entra":
            try:
                await run_in_threadpool(refresh_entra_secret_status, force=True)
            except Exception:
                pass
        return JSONResponse(
            response_payload,
            status_code=200 if response_payload["ok"] else 502,
        )

    @app.post("/api/settings/email/test-suite")
    async def settings_email_test_suite(request: Request) -> JSONResponse:
        _require_admin(request)
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return JSONResponse({"ok": False, "scenarios": [], "elapsed_ms": 0}, status_code=400)
        channel_value = payload.get("channel")
        use_fallback = payload.get("use_fallback", False)
        if not isinstance(channel_value, str):
            channel_value = ""
        selected = channel_value.strip().lower()
        if selected not in {"entra", "smtp", "primary"} or not isinstance(use_fallback, bool):
            return JSONResponse({"ok": False, "scenarios": [], "elapsed_ms": 0}, status_code=400)
        if selected == "primary":
            try:
                email_settings = settings_snapshot().get(EMAIL_SETTINGS_KEY, {})
                selected = str(
                    email_settings.get("primary_channel")
                    if isinstance(email_settings, dict)
                    else ""
                ).strip().lower()
            except Exception:
                selected = ""
            if selected not in {"entra", "smtp"}:
                selected = "entra"

        started = time.perf_counter()
        try:
            result = await run_in_threadpool(
                send_test_notification_suite,
                channel=selected,
                use_fallback=use_fallback,
            )
        except ValueError:
            elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
            return JSONResponse(
                {"ok": False, "scenarios": [], "elapsed_ms": elapsed_ms},
                status_code=400,
            )
        except Exception:
            result = {"scenarios": []}
        elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
        values = result.get("scenarios") if isinstance(result, dict) else []
        scenarios = [
            _redacted_email_test_suite_scenario(item)
            for item in (values if isinstance(values, list) else [])[:5]
        ]
        ok = len(scenarios) == 5 and all(
            item["status"] in {"sent", "fallback", "skipped"}
            for item in scenarios
        )
        return JSONResponse(
            {"ok": ok, "scenarios": scenarios, "elapsed_ms": elapsed_ms},
            status_code=200 if ok else 502,
        )

    @app.get("/api/settings/email/entra-expiry")
    def settings_entra_expiry_status(request: Request) -> JSONResponse:
        _require_admin(request)
        return JSONResponse(entra_secret_status())

    @app.post("/api/settings/email/entra-expiry/refresh")
    async def settings_entra_expiry_refresh(request: Request) -> JSONResponse:
        _require_admin(request)
        try:
            status = await run_in_threadpool(refresh_entra_secret_status, force=True)
        except Exception:
            status = entra_secret_status()
        return JSONResponse(status)

    @app.post("/api/settings/sql-profiles/{profile_id}/test")
    async def settings_sql_profile_test(
        request: Request,
        profile_id: str,
    ) -> JSONResponse:
        _require_admin(request)
        result = await run_in_threadpool(test_sql_profile_connection, profile_id)
        return JSONResponse(result)

    @app.post("/api/settings/pimcore/test")
    async def pimcore_settings_test_api(request: Request) -> JSONResponse:
        user = _require_admin(request)
        raw = await request.body()
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        overrides = payload.get("settings") if isinstance(payload, dict) else None
        report = await run_in_threadpool(
            test_pimcore_settings,
            overrides,
            str(user.get("username") or "admin"),
        )
        return JSONResponse(report)

    @app.post("/api/settings/pimcore/template-preview")
    async def pimcore_template_preview_api(request: Request) -> JSONResponse:
        _require_admin(request)
        payload = await request.json()
        try:
            image_slot_paths = _image_slot_paths_from_payload(payload)
            kwargs = {"image_slot_paths": image_slot_paths} if image_slot_paths else {}
            result = await run_in_threadpool(preview_pimcore_template, payload, **kwargs)
        except (TemplateError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": getattr(exc, "code", "invalid_template"),
                    "message": str(exc),
                    "position": getattr(exc, "position", 0),
                },
            ) from exc
        return JSONResponse(result)

    @app.post("/api/settings/pimcore/test-sample")
    async def pimcore_test_sample_api(request: Request) -> JSONResponse:
        _require_admin(request)
        try:
            result = await run_in_threadpool(pimcore_test_sample)
        except (TemplateError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result)

    @app.post("/api/settings/pimcore/discover/classes")
    async def pimcore_discover_classes_api(request: Request) -> JSONResponse:
        _require_admin(request)
        payload = await request.json()
        settings_payload = payload.get("settings") if isinstance(payload, dict) else None
        try:
            result = await run_in_threadpool(discover_pimcore_classes, settings_payload)
        except PimcoreApiError as exc:
            raise HTTPException(status_code=502, detail=exc.as_dict()) from exc
        return JSONResponse(result)

    @app.post("/api/settings/pimcore/discover/fields")
    async def pimcore_discover_fields_api(request: Request) -> JSONResponse:
        _require_admin(request)
        payload = await request.json()
        if not isinstance(payload, dict) or not str(payload.get("class_id") or "").strip():
            raise HTTPException(status_code=400, detail="Wybierz klase Pimcore.")
        try:
            result = await run_in_threadpool(
                discover_pimcore_fields,
                payload.get("settings"),
                payload.get("class_id"),
            )
        except PimcoreApiError as exc:
            raise HTTPException(status_code=502, detail=exc.as_dict()) from exc
        return JSONResponse(result)

    @app.post("/api/settings/pimcore/discover/folders")
    async def pimcore_discover_folders_api(request: Request) -> JSONResponse:
        _require_admin(request)
        payload = await request.json()
        try:
            result = await run_in_threadpool(
                discover_pimcore_folders,
                payload.get("settings") if isinstance(payload, dict) else None,
            )
        except PimcoreApiError as exc:
            return JSONResponse({"items": [], "warning": exc.as_dict()})
        return JSONResponse(result)

    @app.post("/api/settings/pimcore/setup")
    async def pimcore_setup_api(request: Request) -> JSONResponse:
        user = _require_admin(request)
        payload = await request.json()
        settings_payload = payload.get("settings") if isinstance(payload, dict) else None
        result = await run_in_threadpool(
            complete_pimcore_setup,
            settings_payload,
            str(user.get("username") or "admin"),
        )
        return JSONResponse(result, status_code=200 if result.get("saved") else 422)

    @app.post("/api/settings/pimcore/import-csv-headers")
    async def pimcore_csv_headers_api(request: Request) -> JSONResponse:
        _require_admin(request)
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile) or not upload.filename:
            raise HTTPException(status_code=400, detail="Brak pliku CSV.")
        content = await upload.read()
        if len(content) > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Plik CSV jest za duzy.")
        try:
            headers = parse_pimcore_csv_headers(content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"headers": headers})

    @app.post("/api/settings/pimcore/test-create-runs")
    async def pimcore_test_create_start_api(request: Request) -> JSONResponse:
        user = _require_admin(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Niepoprawne dane testu Pimcore.")
        try:
            operation = start_pimcore_test_create(
                payload.get("values"),
                payload.get("cleanup_policy"),
                str(user.get("username") or "admin"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"operation": operation})

    @app.get("/api/settings/pimcore/test-create-runs/{operation_id}")
    def pimcore_test_create_status_api(
        request: Request,
        operation_id: str,
        after_sequence: int = 0,
    ) -> Dict[str, Any]:
        _require_admin(request)
        operation = pimcore_operation_status(operation_id, after_sequence)
        if not operation:
            raise HTTPException(status_code=404, detail="Nie znaleziono operacji Pimcore.")
        return operation

    @app.get("/api/settings/pimcore/operations")
    def pimcore_operations_api(
        request: Request,
        operation_type: str = "",
        result: str = "",
        user: str = "",
        query: str = "",
        date_from: float = 0,
        date_to: float = 0,
        limit: int = 200,
    ) -> Dict[str, Any]:
        _require_admin(request)
        return pimcore_operation_history(
            operation_type=operation_type,
            result=result,
            user=user,
            query=query,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    @app.get("/api/settings/pimcore/submissions/export")
    def pimcore_submissions_export_api(
        request: Request,
        format: str = "json",
        operation_type: str = "",
        status: str = "",
        user: str = "",
        query: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 1000,
    ):
        _require_admin(request)
        result = export_pimcore_submissions(
            export_format=format,
            operation_type=operation_type,
            status=status,
            user=user,
            query=query,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        if result.get("format") == "csv":
            return Response(
                str(result.get("content") or ""),
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": "attachment; filename=pimcore-submissions.csv"
                },
            )
        if result.get("format") == "xlsx":
            content = result.get("content") or b""
            if not isinstance(content, (bytes, bytearray)):
                content = str(content).encode("utf-8")
            return Response(
                bytes(content),
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                headers={
                    "Content-Disposition": "attachment; filename=pimcore-submissions.xlsx"
                },
            )
        return JSONResponse(result)

    @app.get("/api/pimcore/product-status")
    async def pimcore_product_status_api(request: Request, ean: str) -> JSONResponse:
        username = _require_user(request)
        try:
            result = await run_in_threadpool(find_pimcore_product_by_ean, ean)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PimcoreApiError as exc:
            _write_web_event(
                level="warning",
                event="PIMCORE_PRODUCT_LOOKUP",
                username=username,
                message=str(exc),
                details={"ean": ean, "error": exc.as_dict()},
            )
            return JSONResponse(
                {
                    "enabled": True,
                    "available": False,
                    "exists": False,
                    "object": None,
                    "error": exc.as_dict(),
                }
            )
        result["available"] = True
        _write_web_event(
            level="info",
            event="PIMCORE_PRODUCT_LOOKUP",
            username=username,
            message=f"EAN {ean}: {'istnieje' if result.get('exists') else 'brak'}.",
            details={
                "ean": ean,
                "exists": bool(result.get("exists")),
                "object": result.get("object"),
            },
        )
        return JSONResponse(result)

    @app.post("/api/pimcore/render-templates")
    async def pimcore_render_templates_api(request: Request) -> JSONResponse:
        username = _require_user(request)
        payload = await request.json()
        source = payload if isinstance(payload, dict) else {}
        mode = str(source.get("mode") or "create").strip().lower()
        object_id = source.get("object_id")
        if mode not in {"create", "edit"}:
            raise HTTPException(status_code=400, detail="Niepoprawny tryb Pimcore.")
        if mode == "edit":
            try:
                object_id = int(object_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Brak ID obiektu Pimcore.")
            if object_id <= 0:
                raise HTTPException(status_code=400, detail="Brak ID obiektu Pimcore.")
        else:
            object_id = None
        try:
            image_slot_paths = _image_slot_paths_from_payload(source)
            kwargs = {"image_slot_paths": image_slot_paths} if image_slot_paths else {}
            result = await run_in_threadpool(
                render_saved_pimcore_templates,
                source.get("product_values"),
                source.get("values"),
                source.get("targets"),
                mode,
                **kwargs,
            )
        except (TemplateError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        integrations = result.get("integrations") if isinstance(result, dict) else None
        profiles = (
            integrations.get("sql_profiles")
            if isinstance(integrations, dict)
            else None
        )
        if isinstance(profiles, list) and profiles:
            try:
                result["integration_context_id"] = await run_in_threadpool(
                    observability_store().create_pimcore_integration_context,
                    username=username,
                    mode=mode,
                    object_id=object_id,
                    results=integrations,
                )
            except Exception:
                # Calculated values remain usable; unavailable audit evidence must
                # never be replaced by browser-supplied claims.
                pass
        return JSONResponse(result)

    @app.get("/api/pimcore/products/{object_id}")
    async def pimcore_product_edit_data_api(request: Request, object_id: int) -> JSONResponse:
        username = _require_user(request)
        try:
            result = await run_in_threadpool(
                get_pimcore_product_for_edit,
                object_id,
                username,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PimcoreApiError as exc:
            raise HTTPException(status_code=502, detail=exc.as_dict()) from exc
        return JSONResponse(result)

    @app.put("/api/pimcore/products/{object_id}")
    async def pimcore_product_update_api(request: Request, object_id: int) -> JSONResponse:
        username = _require_user(request)
        payload = await request.json()
        values = payload.get("values") if isinstance(payload, dict) else None
        marker = payload.get("marker") if isinstance(payload, dict) else None
        context_id = payload.get("integration_context_id") if isinstance(payload, dict) else None
        if not isinstance(values, dict) or not str(marker or ""):
            raise HTTPException(status_code=400, detail="Brak danych albo wersji produktu Pimcore.")
        integration_results = None
        if isinstance(context_id, str) and 20 <= len(context_id) <= 200:
            try:
                integration_results = await run_in_threadpool(
                    observability_store().consume_pimcore_integration_context,
                    context_id,
                    username=username,
                    mode="edit",
                    object_id=object_id,
                )
            except Exception:
                integration_results = None
        try:
            if integration_results is None:
                result = await run_in_threadpool(
                    update_pimcore_product,
                    object_id,
                    marker,
                    values,
                    username,
                )
            else:
                result = await run_in_threadpool(
                    update_pimcore_product,
                    object_id,
                    marker,
                    values,
                    username,
                    integration_results,
                )
        except PimcoreConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(exc),
                    "object_id": exc.object_id,
                    "expected_marker": exc.expected_marker,
                    "current_marker": exc.current_marker,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PimcoreApiError as exc:
            raise HTTPException(status_code=502, detail=exc.as_dict()) from exc
        return JSONResponse(result)

    @app.post("/api/pimcore/products")
    async def pimcore_product_create_api(request: Request) -> JSONResponse:
        username = _require_user(request)
        payload = await request.json()
        values = payload.get("values") if isinstance(payload, dict) else None
        context_id = payload.get("integration_context_id") if isinstance(payload, dict) else None
        if not isinstance(values, dict):
            raise HTTPException(status_code=400, detail="Brak danych produktu Pimcore.")
        integration_results = None
        if isinstance(context_id, str) and 20 <= len(context_id) <= 200:
            try:
                integration_results = await run_in_threadpool(
                    observability_store().consume_pimcore_integration_context,
                    context_id,
                    username=username,
                    mode="create",
                    object_id=None,
                )
            except Exception:
                integration_results = None
        try:
            if integration_results is None:
                result = await run_in_threadpool(create_pimcore_product, values, username)
            else:
                result = await run_in_threadpool(
                    create_pimcore_product,
                    values,
                    username,
                    integration_results,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PimcoreApiError as exc:
            raise HTTPException(status_code=502, detail=exc.as_dict()) from exc
        return JSONResponse(result)

    @app.post("/api/settings/sqlite/repair")
    async def settings_sqlite_repair(request: Request) -> JSONResponse:
        _require_admin(request)
        database_path = storage_settings.resolve_sqlite_path()
        backup_dir = storage_settings.resolve_backup_dir()
        result = await run_in_threadpool(
            repair_sqlite_database,
            database_path,
            backup_dir,
        )
        config.initialize_config(interactive=False)
        result["settings"] = settings_snapshot()
        return JSONResponse(result)

    @app.post("/api/settings/sqlite/backup")
    async def settings_sqlite_backup(request: Request) -> JSONResponse:
        _require_admin(request)
        result = await run_in_threadpool(
            sqlite_backup.create_backup,
            storage_settings.resolve_sqlite_path(),
            storage_settings.resolve_backup_dir(),
            reason="manual",
        )
        sqlite_backup.enforce_retention(
            storage_settings.resolve_backup_dir(),
            storage_settings.load_backup_settings().get("max_copies", 10),
        )
        return JSONResponse(result)

    @app.get("/api/settings/sqlite/backups")
    def settings_sqlite_backups(request: Request) -> Dict[str, Any]:
        _require_admin(request)
        return {"items": sqlite_backup.list_backups(storage_settings.resolve_backup_dirs())}

    @app.post("/api/settings/sqlite/backup-diff")
    async def settings_sqlite_backup_diff(request: Request) -> JSONResponse:
        _require_admin(request)
        payload = await request.json()
        backup_path = str(payload.get("backup_path") if isinstance(payload, dict) else "")
        try:
            result = await run_in_threadpool(
                sqlite_backup.diff_databases,
                storage_settings.resolve_sqlite_path(),
                backup_path,
                storage_settings.resolve_backup_dirs(),
            )
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result)

    @app.post("/api/settings/sqlite/restore")
    async def settings_sqlite_restore(request: Request) -> JSONResponse:
        _require_admin(request)
        payload = await request.json()
        backup_path = str(payload.get("backup_path") if isinstance(payload, dict) else "")
        try:
            result = await run_in_threadpool(
                sqlite_backup.restore_backup,
                storage_settings.resolve_sqlite_path(),
                backup_path,
                storage_settings.resolve_backup_dir(),
                storage_settings.resolve_backup_dirs(),
            )
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        config.initialize_config(interactive=False)
        result["settings"] = settings_snapshot()
        return JSONResponse(result)

    @app.post("/api/settings/sql-columns/detect")
    def settings_sql_columns_detect(request: Request) -> JSONResponse:
        _require_admin(request)
        result = detect_available_columns(config.CONFIG)
        if result.get("ok"):
            config.CONFIG[SQL_AVAILABLE_COLUMNS_KEY] = list(result.get("columns") or [])
            config.save_config(
                config.CONFIG,
                preserve_secrets={
                    H: {N, M},
                    P: {N, M},
                    K: {N, M},
                    TRANSLATION_SETTINGS_KEY: {TRANSLATION_API_KEY},
                },
            )
            result["settings"] = settings_snapshot()
        return JSONResponse(result)

    @app.post("/api/settings/secrets")
    async def settings_secrets(request: Request) -> JSONResponse:
        current_user = _require_admin(request)
        payload = await request.json()
        password = str(payload.get("password") if isinstance(payload, dict) else "")
        username = str(current_user.get("username") or "")
        verified = authenticate_user(username, password)
        if not verified or verified.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Niepoprawne haslo administratora.")
        return JSONResponse(
            settings_secret_values(),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/users")
    def users_get(request: Request) -> Dict[str, Any]:
        user = _require_admin(request)
        return {"users": load_users(), "current_user": user}

    @app.post("/api/users")
    async def users_add(request: Request) -> JSONResponse:
        _require_admin(request)
        payload = await request.json()
        email = payload.get("email", "") if isinstance(payload, dict) else ""
        email = "" if email is None else str(email)
        try:
            users = add_user(
                str(payload.get("username") if isinstance(payload, dict) else ""),
                str(payload.get("password") if isinstance(payload, dict) else ""),
                str(payload.get("role") if isinstance(payload, dict) else "user"),
                email,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"users": users, "current_user": _current_user_payload(request)})

    @app.patch("/api/users/{username}")
    async def users_update(request: Request, username: str) -> JSONResponse:
        current_user = _require_admin(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
        try:
            users = update_user(
                username,
                enabled=payload.get("enabled") if "enabled" in payload else None,
                role=payload.get("role") if "role" in payload else None,
                password=payload.get("password") if "password" in payload else None,
                email=payload.get("email") if "email" in payload else None,
                unlock=bool(payload.get("unlock")) if "unlock" in payload else None,
                revoke_sessions=bool(payload.get("revoke_sessions")) if "revoke_sessions" in payload else None,
                revoke_extension_token=bool(payload.get("revoke_extension_token"))
                if "revoke_extension_token" in payload
                else None,
                current_username=str(current_user.get("username") or ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if payload.get("unlock"):
            _write_web_event(
                level="INFO",
                event="login_unlocked",
                username=username,
                message=f"Odblokowano konto {username}.",
                details={"by": str(current_user.get("username") or "")},
            )
        current_username = str(current_user.get("username") or "")
        current_session_invalidated = (
            username.lower() == current_username.lower()
            and (
                bool(payload.get("revoke_sessions"))
                or bool(payload.get("password"))
            )
        )
        response_payload: Dict[str, Any] = {
            "users": users,
            "current_user": current_user if current_session_invalidated else _current_user_payload(request),
        }
        if current_session_invalidated:
            response_payload["session_invalidated"] = True
            response_payload["session_message"] = "Sesje konta zostaly uniewaznione. Zaloguj sie ponownie."
            response = JSONResponse(response_payload)
            response.delete_cookie(SESSION_COOKIE)
            return response
        return JSONResponse(response_payload)

    @app.post("/api/diagnostics/{target}")
    def diagnostics(request: Request, target: str) -> JSONResponse:
        _require_admin(request)
        if target == "local":
            return JSONResponse(test_local_paths())
        if target == "ftp":
            return JSONResponse(test_ftp_connection())
        if target == "sql":
            return JSONResponse(test_sql_connection())
        raise HTTPException(status_code=404, detail="Nieznany test diagnostyczny.")

    @app.post("/api/observability/client-errors")
    async def client_errors_api(request: Request) -> Dict[str, bool]:
        username = _require_user(request)
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Niepoprawne dane bledu klienta.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Niepoprawne dane bledu klienta.")
        emit_event(
            severity="critical",
            event_type="frontend.unhandled_error",
            module="web.frontend",
            stage=str(payload.get("kind") or "client"),
            username=username,
            summary=str(payload.get("message") or "Frontend error"),
            details=payload,
            recommended_action="Review the browser stack and correlated backend events.",
        )
        return {"ok": True}

    def process_job_payload_for_user(job_id: str, username: str) -> Dict[str, Any] | None:
        job = _process_job_for_user(job_id, username)
        return _process_job_payload(job) if job else None

    def process_job_completion(job_id: str) -> threading.Event | None:
        with _PROCESS_JOBS_LOCK:
            return _PROCESS_JOB_COMPLETIONS.get(job_id)

    def process_job_snapshot(job_id: str) -> Dict[str, Any]:
        with _PROCESS_JOBS_LOCK:
            return dict(_PROCESS_JOBS.get(job_id) or {})

    process_router = build_process_router(
        ProcessApiDependencies(
            current_user=lambda request: _require_user(request),
            queue=_PROCESS_QUEUE_REFERENCE,
            stage_form=_stage_process_form,
            cache_scope=_user_cache_scope,
            job_store=_queue_process_job,
            job_completion=process_job_completion,
            job_snapshot=process_job_snapshot,
            jobs_for_user=lambda username, limit: _process_jobs_for_user(username, limit=limit),
            active_jobs=_active_process_jobs_snapshot,
            job_for_user=process_job_payload_for_user,
            cancel_job=_cancel_process_job_for_user,
        )
    )
    app.routes.extend(process_router.routes)
    return app


app = create_app()
