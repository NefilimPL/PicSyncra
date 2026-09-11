from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from picsyncra.web.app import app


SERVICE_MODULES = tuple((Path(__file__).parents[1] / "picsyncra" / "services").glob("*.py"))
DESKTOP_FTP_PREVIEW_MODULE = Path(__file__).parents[1] / "picsyncra" / "desktop_ftp_preview.py"
ROUTE_SNAPSHOT_SHA256 = "756f9aab979e265418b7e38d27a40bf74565414d058f59338ce4caf85721ae19"
WEB_STATIC_DIRECTORY = Path(__file__).parents[1] / "picsyncra" / "web" / "static"


def _route_snapshot() -> str:
    return "\n".join(
        f"{','.join(sorted(set(getattr(route, 'methods', set())) - {'HEAD', 'OPTIONS'}))} {route.path}"
        for route in app.routes
        if getattr(route, "path", "")
    )


def test_services_do_not_import_composition_roots() -> None:
    for path in SERVICE_MODULES:
        source = path.read_text(encoding="utf-8")
        assert "picsyncra.web.app" not in source
        assert "picsyncra.app" not in source


def test_desktop_ftp_preview_does_not_import_ui_or_composition_roots() -> None:
    tree = ast.parse(DESKTOP_FTP_PREVIEW_MODULE.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    assert not any(name == "tkinter" or name.startswith("tkinter.") for name in imports)
    assert "picsyncra.web.app" not in imports
    assert "picsyncra.app" not in imports


def test_route_contract_snapshot_is_stable() -> None:
    assert hashlib.sha256(_route_snapshot().encode("utf-8")).hexdigest() == ROUTE_SNAPSHOT_SHA256


def test_frontend_modules_load_before_the_app_composition_root() -> None:
    index_html = (WEB_STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
    scripts = [
        "/static/latest-request.js",
        "/static/autocomplete.js",
        "/static/runtime-status.js",
        "/static/process-jobs.js",
        "/static/app.js",
    ]

    positions = [index_html.index(script) for script in scripts]

    assert positions == sorted(positions)
