"""Installed updates accept only complete signed release descriptions."""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from picsyncra.installation.release_manifest import ManifestError, parse_manifest, verify_manifest


def payload(*, channel="stable", prerelease=False):
    return {
        "schema": 1,
        "release_id": 42,
        "tag": "v1.2.3",
        "commit": "a" * 40,
        "channel": channel,
        "source_branch": "main" if channel == "stable" else "dev",
        "prerelease": prerelease,
        "platform": "windows-x64",
        "minimum_controller": 1,
        "components": [
            {"name": "web", "component_id": "web-42", "asset_name": "web.zip", "sha256": "b" * 64, "size": 12},
            {"name": "migrator", "component_id": "migrator-42", "asset_name": "migrator.zip", "sha256": "c" * 64, "size": 13},
        ],
    }


def signed(raw_payload):
    private = Ed25519PrivateKey.generate()
    raw = json.dumps(raw_payload, sort_keys=True, separators=(",", ":")).encode()
    signature = private.sign(raw)
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return raw, signature, public


def test_valid_stable_manifest_verifies_and_produces_release_choice() -> None:
    raw, signature, public = signed(payload())
    choice = verify_manifest(raw, signature, {"test-key": public}, key_id="test-key")
    assert choice.release_id == 42
    assert choice.channel == "stable"
    assert [component.name for component in choice.components] == ["web", "migrator"]


def test_one_changed_byte_invalidates_the_signature() -> None:
    raw, signature, public = signed(payload())
    with pytest.raises(ManifestError):
        verify_manifest(raw.replace(b"v1.2.3", b"v1.2.4"), signature, {"test-key": public}, key_id="test-key")


@pytest.mark.parametrize(
    ("channel", "prerelease"), [("stable", True), ("dev", False), ("invalid", False)]
)
def test_channel_and_prerelease_must_agree(channel, prerelease) -> None:
    with pytest.raises(ManifestError):
        parse_manifest(payload(channel=channel, prerelease=prerelease))


def test_missing_migrator_or_duplicate_component_is_rejected() -> None:
    incomplete = payload()
    incomplete["components"] = incomplete["components"][:1]
    with pytest.raises(ManifestError):
        parse_manifest(incomplete)
    duplicate = payload()
    duplicate["components"].append(dict(duplicate["components"][0]))
    with pytest.raises(ManifestError):
        parse_manifest(duplicate)


def test_ocr_can_be_optional_but_must_match_release_component_schema() -> None:
    candidate = payload()
    candidate["components"].append({
        "name": "ocr", "component_id": "ocr-42", "asset_name": "ocr.zip",
        "sha256": "d" * 64, "size": 14,
    })
    assert [item.name for item in parse_manifest(candidate).components] == ["web", "migrator", "ocr"]


def test_unknown_key_and_invalid_public_key_are_rejected() -> None:
    raw, signature, _public = signed(payload())
    with pytest.raises(ManifestError):
        verify_manifest(raw, signature, {}, key_id="missing")
    with pytest.raises(ManifestError):
        verify_manifest(raw, signature, {"broken": base64.b64encode(b"short").decode()}, key_id="broken")
