"""Resolve trusted paths for a managed Windows installation.

Installed mode requires both a machine-wide registration and an executable in
the active version bundle.  A frozen executable, its location, or environment
variables alone never identify a managed installation.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterator, Mapping

from .installation.contracts import InstallContext

_REGISTRY_ROOT = r"SOFTWARE\PicSyncra\Installations"
_INSTALLATION_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?")
_REGISTRY_VALUES = {
    "InstallationId": "installation_id",
    "ProgramRoot": "program_root",
    "StateRoot": "state_root",
    "DatabasePath": "database_path",
}


def _valid_installation_id(value: object) -> bool:
    if not isinstance(value, str) or value in {".", ".."} or ".." in value:
        return False
    return _INSTALLATION_ID.fullmatch(value) is not None


def _read_hklm_registrations() -> tuple[dict[str, str], ...]:
    """Read installer-owned registrations from the 64-bit HKLM view."""

    try:
        import winreg
    except ImportError:
        return ()

    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    registrations: list[dict[str, str]] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REGISTRY_ROOT, 0, access)
    except OSError:
        return ()
    try:
        index = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            try:
                subkey = winreg.OpenKey(root, subkey_name, 0, access)
            except OSError:
                continue
            try:
                values: dict[str, str] = {}
                for registry_name, result_name in _REGISTRY_VALUES.items():
                    try:
                        value, _ = winreg.QueryValueEx(subkey, registry_name)
                    except OSError:
                        values = {}
                        break
                    if not isinstance(value, str):
                        values = {}
                        break
                    values[result_name] = value
                if values and values["installation_id"] == subkey_name:
                    registrations.append(values)
            finally:
                winreg.CloseKey(subkey)
    finally:
        winreg.CloseKey(root)
    return tuple(registrations)


def _absolute_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip())
    if not path.is_absolute():
        return None
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return path != root


def _load_active_release(program_root: Path, installation_id: str) -> int | None:
    marker = program_root / "active.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if set(payload) != {"schema", "installation_id", "release_id"}:
        return None
    if payload.get("schema") != 1:
        return None
    if payload.get("installation_id") != installation_id:
        return None
    release_id = payload.get("release_id")
    if isinstance(release_id, bool) or not isinstance(release_id, int):
        return None
    if release_id <= 0:
        return None
    return release_id


def _registered_context(registration: Mapping[str, object]) -> InstallContext | None:
    installation_id = registration.get("installation_id")
    if not _valid_installation_id(installation_id):
        return None
    program_root = _absolute_path(registration.get("program_root"))
    state_root = _absolute_path(registration.get("state_root"))
    database_path = _absolute_path(registration.get("database_path"))
    if program_root is None or state_root is None or database_path is None:
        return None
    try:
        canonical_program_root = program_root.resolve(strict=True)
        canonical_state_root = state_root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not canonical_program_root.is_dir() or not canonical_state_root.is_dir():
        return None
    release_id = _load_active_release(canonical_program_root, installation_id)
    if release_id is None:
        return None
    active_bundle = canonical_program_root / "versions" / str(release_id)
    try:
        canonical_active_bundle = active_bundle.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not _is_within(canonical_active_bundle, canonical_program_root):
        return None
    config_root = (canonical_state_root / "config").resolve(strict=False)
    if not _is_within(config_root, canonical_state_root):
        return None
    return InstallContext(
        installation_id=installation_id,
        program_root=canonical_program_root,
        state_root=canonical_state_root,
        config_root=config_root,
        database_path=database_path,
    )


def _context_for_registration(
    executable: Path, registration: Mapping[str, object]
) -> InstallContext | None:
    context = _registered_context(registration)
    if context is None:
        return None
    try:
        canonical_executable = executable.resolve(strict=True)
        active_bundle = (
            context.program_root
            / "versions"
            / str(_load_active_release(context.program_root, context.installation_id))
        ).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if (
        not canonical_executable.is_file()
        or canonical_executable.suffix.lower() != ".exe"
        or not _is_within(canonical_executable, active_bundle)
    ):
        return None
    return context


def _matching_contexts(executable: Path) -> Iterator[InstallContext]:
    for registration in _read_hklm_registrations():
        try:
            context = _context_for_registration(executable, registration)
        except (OSError, RuntimeError, ValueError, TypeError):
            continue
        if context is not None:
            yield context


def resolve_install_context(executable: Path) -> InstallContext | None:
    """Return the trusted installed context for ``executable``, if unique."""

    try:
        executable_path = Path(executable)
    except TypeError:
        return None
    matches = list(_matching_contexts(executable_path))
    if len(matches) != 1:
        return None
    return matches[0]


def load_registered_install_context(installation_id: str) -> InstallContext | None:
    """Resolve one registry-owned installation for the independent controller.

    Unlike :func:`resolve_install_context`, the controller itself is outside an
    active release bundle, so there is no executable path to use as evidence.
    The exact HKLM registration and active marker are still both required.
    """

    if not _valid_installation_id(installation_id):
        return None
    matches = [
        context
        for registration in _read_hklm_registrations()
        if registration.get("installation_id") == installation_id
        for context in [_registered_context(registration)]
        if context is not None
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_config_root(executable: Path) -> Path | None:
    """Return the managed configuration root for ``executable`` when installed."""

    context = resolve_install_context(executable)
    return context.config_root if context is not None else None


__all__ = [
    "load_registered_install_context",
    "resolve_config_root",
    "resolve_install_context",
]
