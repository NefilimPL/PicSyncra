from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

from picsyncra.web import app as web_app


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_cli_writes_requested_build_variant(tmp_path):
    output = tmp_path / "module_build_manifest.json"

    subprocess.run(
        [
            sys.executable,
            "tools/generate_module_build_manifest.py",
            "--repo-root",
            str(ROOT),
            "--build-variant",
            "web",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
    )

    assert json.loads(output.read_text(encoding="utf-8"))["build_variant"] == "web"


def test_module_status_route_is_admin_only_and_returns_snapshot():
    expected = {"repository_status": "available", "build": {}, "modules": []}
    client = TestClient(web_app.app)

    with (
        patch.object(web_app, "_require_admin", return_value={"role": "admin"}),
        patch.object(web_app, "load_packaged_module_manifest", return_value={}),
        patch.object(web_app, "module_status_snapshot", return_value=expected),
    ):
        response = client.get("/api/settings/module-status")

    assert response.status_code == 200
    assert response.json() == expected


def test_module_status_route_rejects_anonymous_requests():
    with patch.object(web_app, "_auth_enabled", return_value=True):
        response = TestClient(web_app.app).get("/api/settings/module-status")

    assert response.status_code == 401
