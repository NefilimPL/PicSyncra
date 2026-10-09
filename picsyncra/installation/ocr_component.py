"""Resolve the separately installed OCR bundle for one managed release."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re

from .contracts import InstallContext


OCR_COMPONENT_PROTOCOL = 1
_COMPONENT_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?")


@dataclass(frozen=True)
class ActiveOcrComponent:
    directory: Path
    build_id: str
    component_id: str


def _load_json(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _active_release(context: InstallContext) -> int | None:
    payload = _load_json(context.program_root / "active.json")
    if not payload or set(payload) != {"schema", "installation_id", "release_id"}:
        return None
    release_id = payload.get("release_id")
    if (
        payload.get("schema") != 1
        or payload.get("installation_id") != context.installation_id
        or isinstance(release_id, bool)
        or not isinstance(release_id, int)
        or release_id <= 0
    ):
        return None
    return release_id


def resolve_active_ocr_component(context: InstallContext) -> ActiveOcrComponent | None:
    """Return verified active OCR metadata only when it matches the build."""

    marker = _load_json(context.program_root / 'active.json')
    if marker and marker.get('schema') == 2:
        from .module_state import read_module_set, module_set_root, verify_module_set_files
        from .module_filesystem import safe_path
        from .module_compatibility import check_module_compatibility
        from .module_contracts import ModuleEnvironment
        from .database import inspect_database
        from .controller_version import CONTROLLER_VERSION
        try:
            selected = read_module_set(context)
            versions = {m.module_id: m for m in selected.modules}
            if not {'ocr_runtime', 'ocr_models'} <= set(versions): return None
            environment = ModuleEnvironment(inspect_database(context.database_path).schema_version, 1,
                                             'cp313-win-amd64', CONTROLLER_VERSION, 2)
            if check_module_compatibility(selected, environment): return None
            verify_module_set_files(context, selected)
            root = safe_path(module_set_root(context, selected), 'runtime/ocr')
            if not safe_path(root, 'PicSyncra-OCR.exe').is_file(): return None
            return ActiveOcrComponent(root, selected.set_id, versions['ocr_runtime'].version_id)
        except (RuntimeError, ValueError, OSError):
            return None
    release_id = _active_release(context)
    if release_id is None:
        return None
    try:
        program_root = context.program_root.resolve(strict=True)
        component_root = (program_root / "components" / "ocr").resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    try:
        component_root.relative_to(program_root)
    except ValueError:
        return None
    payload = _load_json(component_root / "active.json")
    expected_keys = {"schema", "release_id", "component_id", "build_id", "protocol"}
    if not payload or set(payload) != expected_keys:
        return None
    component_id = payload.get("component_id")
    if (
        payload.get("schema") != 1
        or payload.get("release_id") != release_id
        or payload.get("build_id") != f"release-{release_id}"
        or payload.get("protocol") != OCR_COMPONENT_PROTOCOL
        or not isinstance(component_id, str)
        or _COMPONENT_ID.fullmatch(component_id) is None
    ):
        return None
    try:
        component = (component_root / component_id).resolve(strict=True)
        component.relative_to(component_root)
    except (OSError, RuntimeError, ValueError):
        return None
    executable = component / "PicSyncra-OCR.exe"
    return (
        ActiveOcrComponent(
            directory=component,
            build_id=str(payload["build_id"]),
            component_id=component_id,
        )
        if executable.is_file()
        else None
    )


def resolve_ocr_component(context: InstallContext) -> Path | None:
    """Return the active OCR component directory only when it matches the build."""

    active = resolve_active_ocr_component(context)
    return active.directory if active is not None else None


__all__ = [
    "ActiveOcrComponent",
    "OCR_COMPONENT_PROTOCOL",
    "resolve_active_ocr_component",
    "resolve_ocr_component",
]
