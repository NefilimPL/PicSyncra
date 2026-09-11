"""Tests for the packaged browser extension files."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import zipfile
from unittest.mock import patch


os.environ.setdefault("PICSYNCRA_HEADLESS", "1")
os.environ.setdefault("PICSYNCRA_WEB_AUTH", "0")

ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = ROOT / "picsyncra" / "browser_extension"


def test_browser_extension_manifest_is_valid_mv3() -> None:
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == 3
    assert manifest["action"]["default_popup"] == "popup.html"
    assert manifest["background"]["service_worker"] == "background.js"
    assert "alarms" in manifest["permissions"]
    assert "activeTab" in manifest["permissions"]
    assert "scripting" in manifest["permissions"]
    assert "http://*/*" in manifest["host_permissions"]
    assert "https://*/*" in manifest["host_permissions"]


def test_browser_extension_popup_uploads_to_panel_endpoint() -> None:
    popup = (EXTENSION_DIR / "popup.js").read_text(encoding="utf-8")
    background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    html = (EXTENSION_DIR / "popup.html").read_text(encoding="utf-8")

    assert "/api/browser-extension/upload-cache" in background
    assert "/api/browser-extension/ping" in popup
    assert "collectImagesFromPage" in popup
    assert "visibleImageEntries" in popup
    assert "imagePassesFilters" in popup
    assert "parseUrlFilterText" in popup
    assert "startUpload" in popup
    assert "retryFailed" in popup
    assert "getUploadStatus" in popup
    assert "FAILED_KEY" in background
    assert "retryFailed" in background
    assert "queueWithoutItem" in background
    assert "UPLOAD_CONCURRENCY = 3" in background
    assert "Promise.all" in background
    assert "withStorageMutation" in background
    assert "responseToProgressBlob" in background
    assert "active:" in background
    assert "queued:" in background
    assert "recent:" in background
    assert "RECENT_TASK_LIMIT = 160" in background
    assert "taskTiming" in background
    assert "uploadProgressNode" in popup
    assert "uploadTaskForImage" in popup
    assert "formatMs" in popup
    assert "backend/cache" in popup
    assert "pobrano" in popup
    assert "chrome.alarms" in background
    assert "onStartup" in background
    assert ".then(() => Promise.all([scanPage(), refreshUploadStatus()]))" in popup
    assert 'id="settingsPanel"' in html
    assert 'id="filtersPanel"' in html
    assert 'id="urlFilter"' in html
    assert 'id="retryFailed"' in html
    assert "&lt;bialy|czarny&gt;" in html
    assert "!thumb" in html
    assert 'type="password"' in html


def test_browser_extension_popup_has_wider_progress_layout() -> None:
    css = (EXTENSION_DIR / "popup.css").read_text(encoding="utf-8")

    assert "width: 620px" in css
    assert ".image-upload-progress" in css
    assert ".progress-fill" in css
    assert ".image-row.queued" in css


def test_browser_extension_knows_supported_image_extensions() -> None:
    popup = (EXTENSION_DIR / "popup.js").read_text(encoding="utf-8")
    background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")

    for extension in (
        "jpe",
        "jfif",
        "apng",
        "dib",
        "avifs",
        "heic",
        "heif",
        "hif",
        "jp2",
        "j2k",
        "jpc",
        "jpx",
        "ico",
        "cur",
        "tga",
        "ppm",
        "pgm",
        "pbm",
        "pnm",
        "pcx",
    ):
        assert extension in popup
        assert extension in background


def test_browser_extension_download_endpoint_returns_zip() -> None:
    from fastapi.testclient import TestClient

    from picsyncra.web import app as web_app

    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.object(web_app.settings, "AC", temp_dir):
            client = TestClient(web_app.app)
            response = client.get("/api/browser-extension/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    zip_path = ROOT / "pytest-temp" / "browser-extension-test.zip"
    zip_path.parent.mkdir(exist_ok=True)
    zip_path.write_bytes(response.content)
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        assert "picsyncra-browser-extension/manifest.json" in names
        assert "picsyncra-browser-extension/popup.js" in names
        assert "picsyncra-browser-extension/background.js" in names
        defaults = archive.read("picsyncra-browser-extension/defaults.js").decode("utf-8")
    assert "window.PICSYNCRA_EXTENSION_DEFAULTS" in defaults
    assert "apiToken" in defaults


def test_web_exe_build_includes_browser_extension_assets() -> None:
    build_script = (ROOT / "Generator exe" / "build_web_exe.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "build-exe.yml").read_text(encoding="utf-8")

    assert "picsyncra\\browser_extension;picsyncra\\browser_extension" in build_script
    assert "picsyncra/browser_extension;picsyncra/browser_extension" in workflow
