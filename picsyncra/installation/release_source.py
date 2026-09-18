"""GitHub Releases source for the verified installed-release catalog."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal
from urllib.parse import urlparse

from ..brand import GITHUB_REPOSITORY
from .contracts import ReleaseChoice
from .release_catalog import catalog_releases


FetchJson = Callable[[str], object]
FetchAsset = Callable[[str], bytes]
_MANIFEST = "PicSyncra-installed-manifest.json"
_SIGNATURE = "PicSyncra-installed-manifest.sig"
_KEY_ID = "PicSyncra-installed-manifest.key-id"


def _asset_url(release: dict[str, object], name: str) -> str:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("release assets are missing")
    for item in assets:
        if isinstance(item, dict) and item.get("name") == name:
            url = item.get("browser_download_url")
            parsed = urlparse(url if isinstance(url, str) else "")
            if parsed.scheme == "https" and parsed.hostname == "github.com" and parsed.path.startswith(f"/{GITHUB_REPOSITORY}/releases/download/"):
                return str(url)
    raise ValueError("release manifest asset is missing")


def _manifest_loader(fetch_asset: FetchAsset):
    def load(release: dict[str, object]) -> tuple[bytes, bytes, str]:
        raw = fetch_asset(_asset_url(release, _MANIFEST))
        signature = fetch_asset(_asset_url(release, _SIGNATURE))
        key_id = fetch_asset(_asset_url(release, _KEY_ID)).decode("ascii").strip()
        if not raw or not signature or not key_id or len(key_id) > 128:
            raise ValueError("release manifest assets are invalid")
        return raw, signature, key_id
    return load


def list_signed_releases(channel: Literal["stable", "dev"], *, fetch_json: FetchJson, fetch_asset: FetchAsset, trusted_keys: Mapping[str, bytes | str]) -> tuple[ReleaseChoice, ...]:
    if channel not in {"stable", "dev"}:
        raise ValueError("channel must be stable or dev")
    releases: list[object] = []
    for page in range(1, 21):
        raw = fetch_json(f"/repos/{GITHUB_REPOSITORY}/releases?per_page=100&page={page}")
        if not isinstance(raw, list):
            raise ValueError("GitHub releases response is invalid")
        releases.extend(raw)
        if len(raw) < 100:
            break
    return catalog_releases(releases, channel=channel, manifest_loader=_manifest_loader(fetch_asset), trusted_keys=trusted_keys)


__all__ = ["list_signed_releases"]
