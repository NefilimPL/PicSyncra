"""Application version helpers."""

from __future__ import annotations

import os
from importlib import resources

VERSION_ENV_VAR = "PICSYNCRA_VERSION"
VERSION_FILE = "VERSION"
FALLBACK_VERSION = "dev"


def _clean_version(value: object) -> str:
    text = str(value or "").strip()
    return text or FALLBACK_VERSION


def _read_packaged_version() -> str:
    try:
        return (
            resources.files(__package__)
            .joinpath(VERSION_FILE)
            .read_text(encoding="utf-8")
            .strip()
        )
    except Exception:
        return ""


def get_app_version() -> str:
    """Return the build/release version embedded in the package."""

    return _clean_version(os.environ.get(VERSION_ENV_VAR) or _read_packaged_version())


def get_display_version() -> str:
    """Return a user-facing version label."""

    version = get_app_version()
    if version == FALLBACK_VERSION or version.lower().startswith("v"):
        return version
    return f"v{version}"
