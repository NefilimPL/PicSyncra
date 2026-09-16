from __future__ import annotations

import json
from pathlib import Path


def test_generator_emits_complete_deterministic_installed_manifest(tmp_path: Path) -> None:
    from tools.generate_installed_release_manifest import generate_manifest

    web = tmp_path / "web.zip"
    migrator = tmp_path / "migrator.zip"
    web.write_bytes(b"web")
    migrator.write_bytes(b"migrator")
    result = generate_manifest(
        release_id=42, tag="v1.2.3", commit="a" * 40, channel="stable", source_branch="main",
        prerelease=False, minimum_controller=1,
        components=[("web", "web-42", web), ("migrator", "migrator-42", migrator)],
    )

    assert result["release_id"] == 42
    assert [item["asset_name"] for item in result["components"]] == ["web.zip", "migrator.zip"]
    assert result["components"][0]["size"] == 3
    assert json.dumps(result, sort_keys=True, separators=(",", ":"))
