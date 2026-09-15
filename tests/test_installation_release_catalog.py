"""Catalog selection never makes an incomplete or mismatched release installable."""

from __future__ import annotations

import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from picsyncra.installation.release_catalog import catalog_releases


def manifest(release_id: int, tag: str, *, channel="stable", prerelease=False):
    return {
        "schema": 1, "release_id": release_id, "tag": tag, "commit": "a" * 40,
        "channel": channel, "source_branch": "main" if channel == "stable" else "dev",
        "prerelease": prerelease, "platform": "windows-x64", "minimum_controller": 1,
        "components": [
            {"name": "web", "component_id": f"web-{release_id}", "asset_name": "web.zip", "sha256": "b" * 64, "size": 1},
            {"name": "migrator", "component_id": f"migrator-{release_id}", "asset_name": "migrator.zip", "sha256": "c" * 64, "size": 1},
        ],
    }


def signed_loader():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def loader(release):
        raw = json.dumps(release["manifest"], sort_keys=True, separators=(",", ":")).encode()
        return raw, key.sign(raw), "key-1"

    return loader, {"key-1": public}


def release(release_id: int, tag: str, *, prerelease=False, draft=False, manifest_payload=None):
    return {
        "id": release_id, "tag_name": tag, "prerelease": prerelease, "draft": draft,
        "published_at": f"2026-01-{release_id:02d}T00:00:00Z",
        "manifest": manifest_payload or manifest(release_id, tag, prerelease=prerelease, channel="dev" if prerelease else "stable"),
    }


def test_catalog_returns_only_matching_channel_in_newest_first_order() -> None:
    loader, keys = signed_loader()
    choices = catalog_releases(
        [release(1, "v1.0.0"), release(2, "v1.1.0", prerelease=True), release(3, "v1.2.0")],
        channel="stable", manifest_loader=loader, trusted_keys=keys,
    )
    assert [choice.release_id for choice in choices] == [3, 1]
    assert all(choice.can_install for choice in choices)


def test_catalog_exposes_bad_or_incomplete_release_as_blocked_not_installable() -> None:
    loader, keys = signed_loader()
    broken = manifest(3, "v1.2.0")
    broken["components"] = broken["components"][:1]
    choices = catalog_releases(
        [release(1, "v1.0.0", draft=True), release(2, "v1.1.0", manifest_payload=manifest(99, "v1.1.0")), release(3, "v1.2.0", manifest_payload=broken)],
        channel="stable", manifest_loader=loader, trusted_keys=keys,
    )
    assert [choice.release_id for choice in choices] == [3, 2]
    assert all(not choice.can_install for choice in choices)
    assert {choice.blocked_reason for choice in choices} == {"manifest_invalid", "release_mismatch"}


def test_catalog_never_uses_draft_or_release_from_wrong_channel() -> None:
    loader, keys = signed_loader()
    choices = catalog_releases([release(1, "v1.0.0", draft=True), release(2, "v1.1.0", prerelease=True)], channel="stable", manifest_loader=loader, trusted_keys=keys)
    assert choices == ()
