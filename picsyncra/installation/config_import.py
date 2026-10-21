"""Publish independent configuration files without opening or migrating the database.

The caller selects the source and explicit file references in the installer. This
module has no dependency on runtime globals: importing it cannot load defaults or
write to the source database. Existing destination directories are never replaced.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import InstallContext


class ConfigurationImportError(ValueError):
    """Selected configuration cannot be imported without guessing or losing data."""


def _read_json(path: Path) -> dict:
    try:
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ConfigurationImportError("Configuration links are not supported.")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ConfigurationImportError("Cannot read the selected configuration.") from exc
    if not isinstance(value, dict):
        raise ConfigurationImportError("Configuration must be a JSON object.")
    return value


def _xor_text(value: str, key: str) -> str:
    return "".join(chr(ord(char) ^ ord(key[index % len(key)])) for index, char in enumerate(value))


def _normalise_secret(value: object) -> str:
    """Preserve the same-machine legacy key, rejecting malformed encoding.

Legacy XOR is not authenticated. Valid decoding alone cannot prove that an
import from another computer used the correct host key; no such claim is made.
"""
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationImportError("The application secret requires configuration.")
    value = value.strip()
    host_key = platform.node() + "secret_OLD"
    if value.startswith("enc:"):
        try:
            raw = base64.b64decode(value[4:], validate=True).decode("utf-8")
            secret = _xor_text(raw, host_key)
        except (binascii.Error, UnicodeError, ValueError) as exc:
            raise ConfigurationImportError("The application secret has invalid encoding.") from exc
        if not secret or any(ord(char) < 32 for char in secret):
            raise ConfigurationImportError("The application secret cannot be decoded.")
    else:
        secret = value
    return "enc:" + base64.b64encode(_xor_text(secret, host_key).encode("utf-8")).decode("ascii")


def _absolute_source_path(value: str, source_root: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (source_root / path).resolve()


def copy_configuration(
    source_root: Path,
    destination_root: Path,
    *,
    database_path: Path | None = None,
    data_root: Path | None = None,
    configuration_path: Path | None = None,
    file_references: tuple[tuple[str, ...], ...] = (),
) -> list[Path]:
    """Copy selected JSON and explicitly declared file references into a new root.

Each file reference is a tuple such as
``('config.json', 'tls', 'certificate_file')``. Only explicitly selected fields
are rewritten; a photo/FTP path must never be mistaken for a configuration file.
The database is referenced, never copied or mutated by this function.
"""
    source_root = Path(source_root).resolve(strict=True)
    destination_root = Path(destination_root).absolute()
    if not source_root.is_dir():
        raise ConfigurationImportError("The configuration source is not a directory.")
    if destination_root.exists() or destination_root.is_symlink():
        raise FileExistsError("Configuration destination already exists.")
    destination_root = destination_root.resolve()
    if destination_root.is_relative_to(source_root) or source_root.is_relative_to(destination_root):
        raise ConfigurationImportError("Source and destination must be independent directories.")

    payloads = {}
    originals = {}
    source_files = {}
    for name in ("local_settings.json", "config.json"):
        path = Path(configuration_path) if name == "config.json" and configuration_path is not None else source_root / name
        if name == "config.json" and configuration_path is not None and not path.is_file():
            raise ConfigurationImportError("The selected configuration file is missing.")
        if path.exists() or path.is_symlink():
            payloads[name] = _read_json(path)
            originals[name] = path.read_bytes()
            source_files[name] = path.resolve()
    settings = payloads.setdefault("local_settings.json", {})
    if settings.get("app_secret"):
        settings["app_secret"] = _normalise_secret(settings["app_secret"])
        settings.pop("installation_secrets_required", None)
    elif "app_secret" in settings and settings["app_secret"] not in (None, ""):
        raise ConfigurationImportError("The application secret must be text.")
    else:
        settings["installation_secrets_required"] = True

    previous_base = settings.get("base_dir_override")
    if previous_base and not isinstance(previous_base, str):
        raise ConfigurationImportError("The data directory must be text.")
    old_base = _absolute_source_path(previous_base or ".", source_root)
    settings["base_dir_override"] = str(Path(data_root).resolve() if data_root else old_base)
    if database_path is not None:
        selected_database = Path(database_path).resolve()
    elif settings.get("data_mode") == "sqlite":
        mode = settings.get("database_location_mode", "image_dir")
        if mode == "custom":
            raw_path = settings.get("database_path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ConfigurationImportError("The selected database path is missing.")
            selected_database = _absolute_source_path(raw_path, source_root)
        elif mode in ("exe_dir", "image_dir"):
            selected_database = (source_root if mode == "exe_dir" else old_base) / "picsyncra.sqlite"
        else:
            raise ConfigurationImportError("The database location mode is invalid.")
    else:
        selected_database = None
    if selected_database is not None:
        settings.update(data_mode="sqlite", database_location_mode="custom", database_path=str(selected_database))

    destination_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".config-import-", dir=destination_root.parent))
    published_names = []
    modified = {"local_settings.json"}
    try:
        for reference in file_references:
            if len(reference) < 2 or reference[0] not in payloads:
                raise ConfigurationImportError("Invalid selected configuration reference.")
            container = payloads[reference[0]]
            for key in reference[1:-1]:
                if not isinstance(container, dict) or key not in container:
                    raise ConfigurationImportError("The selected reference does not exist.")
                container = container[key]
            value = container.get(reference[-1]) if isinstance(container, dict) else None
            if not isinstance(value, str) or not value.strip():
                raise ConfigurationImportError("The selected file reference is empty.")
            file_path = _absolute_source_path(value, source_files[reference[0]].parent)
            if not file_path.is_file():
                raise ConfigurationImportError("A selected configuration file is missing.")
            digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
            relative = Path("assets") / (digest + file_path.suffix)
            staged_file = staging / relative
            staged_file.parent.mkdir(exist_ok=True)
            shutil.copyfile(file_path, staged_file)
            if hashlib.sha256(staged_file.read_bytes()).hexdigest() != digest:
                raise ConfigurationImportError("A source file changed during import.")
            container[reference[-1]] = str(destination_root / relative)
            modified.add(reference[0])
            if relative not in published_names:
                published_names.append(relative)

        for name, payload in payloads.items():
            content = (
                json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
                if name in modified else originals[name]
            )
            with (staging / name).open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            published_names.append(Path(name))
        # Windows rename refuses an existing target, including one created by a
        # competing importer after the initial check. Never use replace here.
        if destination_root.exists():
            raise FileExistsError("Configuration destination already exists.")
        staging.rename(destination_root)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return [destination_root / name for name in published_names]


def validate_import(context: InstallContext) -> dict[str, str]:
    """Report local file readiness without network tests or exposing secrets."""
    root = Path(context.config_root)
    result = {"configuration": "needs_configuration", "app_secret": "needs_configuration"}
    try:
        settings = _read_json(root / "local_settings.json")
        if settings.get("app_secret"):
            _normalise_secret(settings["app_secret"])
            result["app_secret"] = "ok"
        if (root / "config.json").is_file():
            _read_json(root / "config.json")
            result["configuration"] = "ok"
    except ConfigurationImportError:
        return {"configuration": "needs_configuration", "app_secret": "needs_configuration"}
    return result
