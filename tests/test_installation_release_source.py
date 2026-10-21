from __future__ import annotations

import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _manifest(release_id: int, tag: str) -> bytes:
    return json.dumps({
        "schema": 1, "release_id": release_id, "tag": tag, "commit": "a" * 40,
        "channel": "stable", "source_branch": "main", "prerelease": False,
        "platform": "windows-x64", "minimum_controller": 1,
        "components": [
            {"name": "web", "component_id": "web-1", "asset_name": "web.zip", "sha256": "b" * 64, "size": 1},
            {"name": "migrator", "component_id": "migrator-1", "asset_name": "migrator.zip", "sha256": "c" * 64, "size": 1},
        ],
    }, sort_keys=True, separators=(",", ":")).encode()


def test_source_paginates_github_releases_and_verifies_manifest_assets() -> None:
    from picsyncra.installation.release_source import list_signed_releases

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    raw = _manifest(7, "v1.2.3")
    release = {"id": 7, "tag_name": "v1.2.3", "draft": False, "prerelease": False, "published_at": "2026-09-16T00:00:00Z", "assets": [
        {"name": "PicSyncra-installed-manifest.json", "browser_download_url": "https://github.com/NefilimPL/PicSyncra/releases/download/v1.2.3/PicSyncra-installed-manifest.json"},
        {"name": "PicSyncra-installed-manifest.sig", "browser_download_url": "https://github.com/NefilimPL/PicSyncra/releases/download/v1.2.3/PicSyncra-installed-manifest.sig"},
        {"name": "PicSyncra-installed-manifest.key-id", "browser_download_url": "https://github.com/NefilimPL/PicSyncra/releases/download/v1.2.3/PicSyncra-installed-manifest.key-id"},
    ]}
    calls: list[str] = []
    def fetch_json(path: str):
        calls.append(path)
        return [release] if "page=1" in path else []
    assets = {"manifest.json": raw, "manifest.sig": private.sign(raw), "manifest.key": b"release-1\n"}
    def fetch_asset(url: str) -> bytes:
        return assets["manifest." + ("json" if url.endswith(".json") else "sig" if url.endswith(".sig") else "key")]

    choices = list_signed_releases("stable", fetch_json=fetch_json, fetch_asset=fetch_asset, trusted_keys={"release-1": public})
    assert [item.release_id for item in choices] == [7]
    assert len(calls) == 1


def test_source_blocks_release_when_manifest_asset_is_missing() -> None:
    from picsyncra.installation.release_source import list_signed_releases

    release = {"id": 7, "tag_name": "v1.2.3", "draft": False, "prerelease": False, "published_at": "2026-09-16T00:00:00Z", "assets": []}
    choices = list_signed_releases("stable", fetch_json=lambda _path: [release], fetch_asset=lambda _url: b"", trusted_keys={})
    assert choices[0].can_install is False
    assert choices[0].blocked_reason == "manifest_invalid"
