"""Strict schema and Ed25519 verification for installed release manifests."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .contracts import ComponentRef, ReleaseChoice


class ManifestError(ValueError):
    """A release cannot safely be offered to an installed client."""


_HEX40 = re.compile(r"[0-9a-f]{40}", re.IGNORECASE)
_HEX64 = re.compile(r"[0-9a-f]{64}", re.IGNORECASE)
_COMPONENT_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?")
_EXPECTED_KEYS = {
    "schema", "release_id", "tag", "commit", "channel", "source_branch", "prerelease",
    "platform", "minimum_controller", "components",
}
_REQUIRED_COMPONENTS = frozenset({"web", "migrator"})
_ALLOWED_COMPONENTS = _REQUIRED_COMPONENTS | {"local", "ocr"}


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{field} must be non-empty text")
    return value.strip()


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{field} must be a positive integer")
    return value


def _components(value: object) -> tuple[ComponentRef, ...]:
    if not isinstance(value, list):
        raise ManifestError("components must be a list")
    result: list[ComponentRef] = []
    names: set[str] = set()
    identifiers: set[str] = set()
    assets: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"name", "component_id", "asset_name", "sha256", "size"}:
            raise ManifestError("component has an invalid schema")
        name = _text(item.get("name"), "component name")
        component_id = _text(item.get("component_id"), "component_id")
        asset_name = _text(item.get("asset_name"), "asset_name")
        checksum = _text(item.get("sha256"), "sha256").lower()
        size = _positive_int(item.get("size"), "size")
        if name not in _ALLOWED_COMPONENTS or not _COMPONENT_ID.fullmatch(component_id):
            raise ManifestError("component is not supported")
        if "/" in asset_name or "\\" in asset_name or asset_name in {".", ".."}:
            raise ManifestError("asset_name must be a file name")
        if not _HEX64.fullmatch(checksum) or name in names or component_id in identifiers or asset_name.casefold() in assets:
            raise ManifestError("component identifiers must be unique and checksummed")
        names.add(name)
        identifiers.add(component_id)
        assets.add(asset_name.casefold())
        result.append(ComponentRef(name, component_id, asset_name, checksum, size))
    if not _REQUIRED_COMPONENTS.issubset(names):
        raise ManifestError("web and migrator are required")
    return tuple(result)


def parse_manifest(payload: object) -> ReleaseChoice:
    """Parse only the exact schema emitted by the trusted release workflow."""
    if not isinstance(payload, dict) or set(payload) != _EXPECTED_KEYS:
        raise ManifestError("manifest has an invalid schema")
    if payload.get("schema") != 1 or payload.get("platform") != "windows-x64":
        raise ManifestError("manifest platform or schema is unsupported")
    release_id = _positive_int(payload.get("release_id"), "release_id")
    tag = _text(payload.get("tag"), "tag")
    commit = _text(payload.get("commit"), "commit").lower()
    channel = _text(payload.get("channel"), "channel")
    branch = _text(payload.get("source_branch"), "source_branch")
    prerelease = payload.get("prerelease")
    if not _HEX40.fullmatch(commit) or channel not in {"stable", "dev"} or not isinstance(prerelease, bool):
        raise ManifestError("manifest release metadata is invalid")
    if (channel == "stable" and (prerelease or branch != "main")) or (channel == "dev" and not prerelease):
        raise ManifestError("channel and prerelease metadata disagree")
    minimum_controller = _positive_int(payload.get("minimum_controller"), "minimum_controller")
    components = _components(payload.get("components"))
    return ReleaseChoice(
        release_id=release_id, tag=tag, commit=commit, channel=channel, source_branch=branch,
        manifest_sha256="", components=components, can_install=True, blocked_reason=None,
        minimum_controller=minimum_controller,
    )


def _public_key(value: bytes | str) -> Ed25519PublicKey:
    try:
        raw = base64.b64decode(value, validate=True) if isinstance(value, str) else value
        if not isinstance(raw, bytes) or len(raw) != 32:
            raise ValueError
        return Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise ManifestError("trusted release key is invalid") from exc


def verify_manifest(
    raw_manifest: bytes,
    signature: bytes,
    trusted_keys: Mapping[str, bytes | str],
    *,
    key_id: str,
) -> ReleaseChoice:
    """Verify exact received bytes before parsing their schema or asset list."""
    if not isinstance(raw_manifest, bytes) or not isinstance(signature, bytes) or not isinstance(key_id, str):
        raise ManifestError("manifest verification inputs are invalid")
    try:
        public_key = _public_key(trusted_keys[key_id])
        public_key.verify(signature, raw_manifest)
        payload = json.loads(raw_manifest.decode("utf-8"))
    except (KeyError, InvalidSignature, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest signature or encoding is invalid") from exc
    parsed = parse_manifest(payload)
    return ReleaseChoice(
        release_id=parsed.release_id, tag=parsed.tag, commit=parsed.commit, channel=parsed.channel,
        source_branch=parsed.source_branch, manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        components=parsed.components, can_install=True, blocked_reason=None,
        minimum_controller=parsed.minimum_controller,
    )
