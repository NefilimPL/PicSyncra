from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from typing import Mapping


@dataclass(frozen=True)
class ModuleDefinition:
    id: str
    label: str
    paths: tuple[str, ...]


MODULES = (
    ModuleDefinition("application_data", "Aplikacja i dane", ("picsyncra",)),
    ModuleDefinition("slots", "Sloty", ("picsyncra/web/static/app.js",)),
    ModuleDefinition("ftp", "FTP", ("picsyncra/services/ftp_service.py",)),
    ModuleDefinition("sql", "SQL", ("picsyncra/services/sql_service.py",)),
    ModuleDefinition("pimcore", "Pimcore", ("picsyncra/services/pimcore_service.py",)),
    ModuleDefinition("ocr", "OCR", ("picsyncra/services/image_dimensions.py",)),
    ModuleDefinition("ocr_tester", "Tester OCR", ("picsyncra/web/static/ocr-diagnostics.js",)),
    ModuleDefinition("settings", "Ustawienia", ("picsyncra/web",)),
    ModuleDefinition("web_ui", "Interfejs web", ("picsyncra/web/static",)),
    ModuleDefinition("generator_local", "Generator lokalny", ("Generator exe/build_local_exe.ps1",)),
    ModuleDefinition("generator_web", "Generator web", ("Generator exe/build_web_exe.ps1",)),
)
MODULES_BY_ID = {module.id: module for module in MODULES}


def _git(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _revision_and_date(value: str) -> tuple[str, str]:
    commit, separator, committed_at = value.partition("|")
    return commit.strip(), committed_at.strip() if separator else ""


def _manifest_module(repo_root: Path, module: ModuleDefinition) -> dict[str, str]:
    commit, committed_at = _revision_and_date(
        _git(repo_root, "log", "-1", "--format=%H|%cI", "--", *module.paths)
    )
    return {
        "id": module.id,
        "label": module.label,
        "commit": commit,
        "committed_at": committed_at,
    }


def build_manifest(
    repo_root: Path, *, build_variant: str, now: datetime
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "build_variant": build_variant,
        "generated_at": now.astimezone(UTC).isoformat(),
        "repository_commit": _git(repo_root, "rev-parse", "HEAD"),
        "modules": [_manifest_module(repo_root, module) for module in MODULES],
    }


def load_packaged_module_manifest() -> dict[str, object] | None:
    manifest_path = Path(__file__).resolve().parents[1] / "module_build_manifest.json"
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _find_repo_root(runtime_root: Path, configured_root: str) -> Path | None:
    candidates = []
    if configured_root:
        candidates.append(Path(configured_root))
    candidates.extend((runtime_root, *runtime_root.parents))
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return None


def _module_git_state(
    repo_root: Path, module: ModuleDefinition
) -> tuple[str, str, bool]:
    commit, committed_at = _revision_and_date(
        _git(repo_root, "log", "-1", "--format=%H|%cI", "--", *module.paths)
    )
    dirty = bool(_git(repo_root, "status", "--porcelain", "--", *module.paths))
    return commit, committed_at, dirty


def _manifest_is_valid(manifest: Mapping[str, object] | None) -> bool:
    return bool(
        manifest
        and manifest.get("schema_version") == 1
        and isinstance(manifest.get("modules"), list)
    )


def _build_details(manifest: Mapping[str, object]) -> dict[str, str]:
    return {
        "build_variant": str(manifest.get("build_variant") or ""),
        "generated_at": str(manifest.get("generated_at") or ""),
        "repository_commit": str(manifest.get("repository_commit") or ""),
    }


def _public_module_row(
    item: Mapping[str, object],
    *,
    local_commit: str,
    local_committed_at: str,
    status: str,
) -> dict[str, str]:
    return {
        "id": str(item.get("id") or ""),
        "label": str(item.get("label") or ""),
        "build_commit": str(item.get("commit") or ""),
        "build_committed_at": str(item.get("committed_at") or ""),
        "local_commit": local_commit,
        "local_committed_at": local_committed_at,
        "status": status,
    }


def module_status_snapshot(
    manifest: Mapping[str, object] | None,
    runtime_root: Path,
    env: Mapping[str, str],
) -> dict[str, object]:
    if not _manifest_is_valid(manifest):
        return {
            "build": None,
            "repository_status": "unavailable",
            "modules": [],
            "status": "build_metadata_missing",
        }

    assert manifest is not None
    module_items = [item for item in manifest["modules"] if isinstance(item, Mapping)]
    repo_root = _find_repo_root(
        runtime_root, env.get("PICSYNCRA_REPOSITORY_ROOT", "")
    )
    if repo_root is None:
        return {
            "build": _build_details(manifest),
            "repository_status": "unavailable",
            "modules": [
                _public_module_row(
                    item,
                    local_commit="",
                    local_committed_at="",
                    status="repository_unavailable",
                )
                for item in module_items
            ],
        }

    rows = []
    for item in module_items:
        module = MODULES_BY_ID.get(str(item.get("id") or ""))
        if module is None:
            rows.append(
                _public_module_row(
                    item,
                    local_commit="",
                    local_committed_at="",
                    status="repository_unavailable",
                )
            )
            continue
        local_commit, local_committed_at, dirty = _module_git_state(repo_root, module)
        build_commit = str(item.get("commit") or "")
        status = (
            "uncommitted_changes"
            if dirty
            else "matching"
            if local_commit == build_commit
            else "rebuild_required"
        )
        rows.append(
            _public_module_row(
                item,
                local_commit=local_commit,
                local_committed_at=local_committed_at,
                status=status,
            )
        )
    return {
        "build": _build_details(manifest),
        "repository_status": "available",
        "modules": rows,
    }
