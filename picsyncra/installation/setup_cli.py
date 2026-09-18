"""Installer helper contracts shared by Inno Setup and the installed runtime."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Protocol

from .config_import import copy_configuration
from .database import inspect_database


# This identifier is intentionally stable: Inno uses it to recognise repair,
# upgrade and uninstall as operations on one installed product.
PRODUCT_APP_ID = "{C70B4E13-B158-4E9F-867F-3F0E04DB2283}"
_REGISTRY_ROOT = r"SOFTWARE\PicSyncra\Installations"
_INSTALLATION_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?")


@dataclass(frozen=True)
class InstallerLayout:
    """The component policy for one base installer invocation."""

    product_app_id: str
    required_components: tuple[str, ...]
    optional_components: tuple[str, ...]
    downloadable_components: tuple[str, ...]
    autostart_enabled: bool


@dataclass(frozen=True)
class InstallationRegistration:
    """Machine registration consumed by the installed-runtime path resolver."""

    installation_id: str
    program_root: Path
    state_root: Path
    database_path: Path


class RegistryWriter(Protocol):
    """The small HKLM writing surface used by setup registration."""

    def set_value(self, key_path: str, name: str, value: str) -> None: ...

    def delete_key(self, key_path: str) -> None: ...


class WindowsRegistryWriter:
    """Write the installer-owned registration in the 64-bit HKLM view."""

    def set_value(self, key_path: str, name: str, value: str) -> None:  # pragma: no cover - needs admin
        try:
            import winreg
        except ImportError as exc:
            raise RuntimeError("Windows registry access is unavailable.") from exc
        access = winreg.KEY_WRITE | getattr(winreg, "KEY_WOW64_64KEY", 0)
        key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, access)
        try:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        finally:
            winreg.CloseKey(key)

    def delete_key(self, key_path: str) -> None:  # pragma: no cover - needs admin
        try:
            import winreg
        except ImportError as exc:
            raise RuntimeError("Windows registry access is unavailable.") from exc
        access = getattr(winreg, "KEY_WOW64_64KEY", 0)
        try:
            winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, access, 0)
        except FileNotFoundError:
            return


def build_installer_layout(*, include_local: bool) -> InstallerLayout:
    """Return the base component layout without implicitly enabling OCR or startup."""

    if not isinstance(include_local, bool):
        raise ValueError("include_local must be a boolean.")
    return InstallerLayout(
        product_app_id=PRODUCT_APP_ID,
        required_components=("web", "migrator"),
        optional_components=("local",) if include_local else (),
        downloadable_components=("ocr",),
        autostart_enabled=False,
    )


def register_installation(
    registration: InstallationRegistration,
    *,
    registry: RegistryWriter | None = None,
) -> None:
    """Publish one resolver-compatible installation registration in HKLM."""

    if _INSTALLATION_ID.fullmatch(registration.installation_id) is None:
        raise ValueError("installation_id is invalid.")
    program_root = Path(registration.program_root).resolve(strict=True)
    state_root = Path(registration.state_root).resolve(strict=True)
    if not program_root.is_dir() or not state_root.is_dir():
        raise ValueError("program_root and state_root must be directories.")
    database_path = Path(registration.database_path).resolve(strict=False)
    writer = registry if registry is not None else WindowsRegistryWriter()
    key_path = _REGISTRY_ROOT + "\\" + registration.installation_id
    for name, value in (
        ("InstallationId", registration.installation_id),
        ("ProgramRoot", str(program_root)),
        ("StateRoot", str(state_root)),
        ("DatabasePath", str(database_path)),
    ):
        writer.set_value(key_path, name, value)


def unregister_installation(
    installation_id: str,
    *,
    registry: RegistryWriter | None = None,
) -> None:
    """Remove only one installed-runtime registration from HKLM."""

    if not isinstance(installation_id, str) or _INSTALLATION_ID.fullmatch(installation_id) is None:
        raise ValueError("installation_id is invalid.")
    writer = registry if registry is not None else WindowsRegistryWriter()
    writer.delete_key(_REGISTRY_ROOT + "\\" + installation_id)


def _load_registration_request(path: Path) -> InstallationRegistration:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("The installer request file is not valid JSON.") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "installation_id",
        "program_root",
        "state_root",
        "database_path",
    }:
        raise ValueError("The installer registration request has an invalid schema.")
    installation_id = payload.get("installation_id")
    if not isinstance(installation_id, str):
        raise ValueError("installation_id must be text.")
    return InstallationRegistration(
        installation_id=installation_id,
        program_root=_absolute_path(payload.get("program_root"), field="program_root"),
        state_root=_absolute_path(payload.get("state_root"), field="state_root"),
        database_path=_absolute_path(payload.get("database_path"), field="database_path"),
    )


def _load_unregistration_request(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("The installer request file is not valid JSON.") from exc
    if not isinstance(payload, dict) or set(payload) != {"installation_id"}:
        raise ValueError("The installer unregistration request has an invalid schema.")
    installation_id = payload.get("installation_id")
    if not isinstance(installation_id, str):
        raise ValueError("installation_id must be text.")
    return installation_id


def _absolute_path(value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty path.")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{field} must be an absolute path.")
    return path.resolve(strict=False)


def _load_import_request(path: Path) -> tuple[Path, Path, Path | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("The installer request file is not valid JSON.") from exc
    if not isinstance(payload, dict) or set(payload) - {
        "source_config_root",
        "destination_config_root",
        "database_path",
    }:
        raise ValueError("The installer request has an invalid schema.")
    source = _absolute_path(payload.get("source_config_root"), field="source_config_root")
    destination = _absolute_path(
        payload.get("destination_config_root"), field="destination_config_root"
    )
    database_value = payload.get("database_path")
    database = (
        _absolute_path(database_value, field="database_path")
        if database_value is not None
        else None
    )
    return source, destination, database


def _import_config(request_path: Path) -> None:
    source, destination, database = _load_import_request(request_path)
    copy_configuration(source, destination, database_path=database)


def _inspect_database_request(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("The installer request file is not valid JSON.") from exc
    if not isinstance(payload, dict) or set(payload) != {"database_path"}:
        raise ValueError("The installer inspection request has an invalid schema.")
    try:
        inspection = inspect_database(
            _absolute_path(payload.get("database_path"), field="database_path")
        )
    except sqlite3.Error as exc:
        raise ValueError("Database inspection failed.") from exc
    return {
        "ok": True,
        "database": {
            "schema_version": inspection.schema_version,
            "integrity_ok": inspection.integrity_ok,
            "is_picsyncra": inspection.is_picsyncra,
        },
    }


def _load_access_request(path: Path) -> Path:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("The installer request file is not valid JSON.") from exc
    if not isinstance(payload, dict) or set(payload) != {"path"}:
        raise ValueError("The access-check request has an invalid schema.")
    return _absolute_path(payload.get("path"), field="path")


def verify_access(path: Path) -> dict[str, bool]:
    """Check a directory using the identity of the helper process.

    The result deliberately contains no resource path or operating-system error,
    so it is safe to display in installer logs.  A service can invoke the same
    helper under its configured account to validate UNC access for that account.
    """

    text_path = str(path)
    is_unc = text_path.startswith("\\\\")
    try:
        exists = path.exists()
        is_directory = path.is_dir()
        if is_directory:
            with os.scandir(path):
                pass
    except OSError:
        exists = False
        is_directory = False
    return {
        "exists": exists,
        "is_directory": is_directory,
        "is_unc": is_unc,
    }


def main(argv: list[str] | None = None, *, registry: RegistryWriter | None = None) -> int:
    """Run a setup helper command without accepting secret values as arguments."""

    parser = argparse.ArgumentParser(prog="PicSyncra-SetupHelper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--request", type=Path, required=True)
    import_parser = subparsers.add_parser("import-config")
    import_parser.add_argument("--request", type=Path, required=True)
    register_parser = subparsers.add_parser("register")
    register_parser.add_argument("--request", type=Path, required=True)
    unregister_parser = subparsers.add_parser("unregister")
    unregister_parser.add_argument("--request", type=Path, required=True)
    verify_access_parser = subparsers.add_parser("verify-access")
    verify_access_parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            response = _inspect_database_request(args.request)
        elif args.command == "import-config":
            _import_config(args.request)
            response = {"ok": True}
        elif args.command == "register":
            register_installation(_load_registration_request(args.request), registry=registry)
            response = {"ok": True}
        elif args.command == "unregister":
            unregister_installation(
                _load_unregistration_request(args.request), registry=registry
            )
            response = {"ok": True}
        elif args.command == "verify-access":
            access = verify_access(_load_access_request(args.request))
            response = {"ok": access["exists"] and access["is_directory"], "access": access}
        else:  # pragma: no cover - argparse keeps this unreachable
            parser.error("Unsupported setup helper command.")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Setup helper failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(response), flush=True)
    return 0


__all__ = [
    "InstallationRegistration",
    "InstallerLayout",
    "PRODUCT_APP_ID",
    "RegistryWriter",
    "WindowsRegistryWriter",
    "build_installer_layout",
    "main",
    "register_installation",
    "unregister_installation",
    "verify_access",
]


if __name__ == "__main__":
    raise SystemExit(main())
