"""Verified staging downloads for installed release components.

The WEB client selects a release identifier only.  This module takes the
corresponding GitHub API release record and a previously verified manifest;
it never accepts an arbitrary URL or destination from the browser.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import os
from pathlib import Path
import secrets
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

from ..brand import GITHUB_OWNER, GITHUB_REPOSITORY
from .contracts import ComponentRef, ReleaseChoice


class DownloadError(RuntimeError):
    """A release component cannot be safely downloaded or published."""


class DownloadResponse(Protocol):
    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


OpenUrl = Callable[[str], DownloadResponse]
_GITHUB_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"})
_CHUNK_SIZE = 1024 * 1024


def _github_download_path() -> str:
    return "/" + GITHUB_REPOSITORY + "/releases/download/"


def _trusted_url(value: object, *, initial: bool) -> str:
    if not isinstance(value, str) or not value:
        raise DownloadError("Release asset is missing a download URL.")
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in _GITHUB_HOSTS:
        raise DownloadError("Release asset points to an untrusted host.")
    if initial and (host != "github.com" or not parsed.path.startswith(_github_download_path())):
        raise DownloadError("Release asset is not a GitHub release download.")
    return value


class _TrustedGithubRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        _trusted_url(newurl, initial=False)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _open_github_asset(url: str) -> DownloadResponse:
    request = Request(url, headers={"User-Agent": "PicSyncra-Installer"})
    opener = build_opener(_TrustedGithubRedirect(), HTTPSHandler())
    return opener.open(request, timeout=30)  # type: ignore[return-value]


def _safe_staging_root(staging: Path) -> Path:
    root = Path(staging)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise DownloadError("The staging directory is unsafe.")
    try:
        return root.resolve(strict=True)
    except OSError as exc:
        raise DownloadError("The staging directory is unavailable.") from exc


def _asset_name(value: str) -> str:
    candidate = Path(value)
    if (
        not value
        or candidate.name != value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise DownloadError("Component asset must be a plain file name.")
    return value


def _release_assets(release: Mapping[str, object], choice: ReleaseChoice) -> dict[str, Mapping[str, object]]:
    release_id = release.get("id")
    if release_id != choice.release_id or isinstance(release_id, bool):
        raise DownloadError("The release does not match the verified manifest.")
    raw_assets = release.get("assets")
    if not isinstance(raw_assets, list):
        raise DownloadError("The release has no assets.")
    assets: dict[str, Mapping[str, object]] = {}
    for raw in raw_assets:
        if not isinstance(raw, Mapping):
            continue
        name = raw.get("name")
        if not isinstance(name, str) or not name or name.casefold() in assets:
            continue
        assets[name.casefold()] = raw
    return assets


def _component_asset(component: ComponentRef, assets: Mapping[str, Mapping[str, object]]) -> Mapping[str, object]:
    name = _asset_name(component.asset_name)
    asset = assets.get(name.casefold())
    if asset is None:
        raise DownloadError("The signed component is missing from this release.")
    size = asset.get("size")
    if size != component.size or isinstance(size, bool):
        raise DownloadError("Release component size does not match its manifest.")
    _trusted_url(asset.get("browser_download_url"), initial=True)
    return asset


def _response_url(response: DownloadResponse) -> object:
    getter = getattr(response, "geturl", None)
    if callable(getter):
        return getter()
    return getattr(response, "url", None)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _download_component(component: ComponentRef, asset: Mapping[str, object], root: Path, open_url: OpenUrl) -> Path:
    name = _asset_name(component.asset_name)
    target = root / name
    if target.exists() or target.is_symlink():
        raise DownloadError("The staged component already exists.")
    url = _trusted_url(asset.get("browser_download_url"), initial=True)
    temporary = root / f".{name}.{secrets.token_hex(16)}.part"
    response: DownloadResponse | None = None
    try:
        response = open_url(url)
        _trusted_url(_response_url(response), initial=False)
        written = 0
        digest = hashlib.sha256()
        with temporary.open("xb") as handle:
            while True:
                chunk = response.read(min(_CHUNK_SIZE, component.size + 1 - written))
                if not chunk:
                    break
                written += len(chunk)
                if written > component.size:
                    raise DownloadError("Downloaded component exceeds the signed size.")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if written != component.size:
            raise DownloadError("Downloaded component has an unexpected size.")
        if not secrets.compare_digest(digest.hexdigest(), component.sha256):
            raise DownloadError("Downloaded component checksum does not match its manifest.")
        # Publication must not overwrite an earlier, independently verified
        # package.  A hard link provides a no-overwrite operation on one volume.
        os.link(temporary, target)
        if not secrets.compare_digest(_digest(target), component.sha256):
            target.unlink(missing_ok=True)
            raise DownloadError("The staged component changed during verification.")
        return target
    except FileExistsError as exc:
        raise DownloadError("The staged component already exists.") from exc
    except OSError as exc:
        raise DownloadError("Cannot write the downloaded component to staging.") from exc
    finally:
        if response is not None:
            response.close()
        temporary.unlink(missing_ok=True)


def download_release(
    choice: ReleaseChoice,
    release: Mapping[str, object],
    staging: Path,
    *,
    open_url: OpenUrl = _open_github_asset,
) -> dict[str, Path]:
    """Download every signed component and publish them only after verification."""
    if not choice.can_install:
        raise DownloadError("A blocked release cannot be downloaded.")
    root = _safe_staging_root(staging)
    assets = _release_assets(release, choice)
    result: dict[str, Path] = {}
    for component in choice.components:
        asset = _component_asset(component, assets)
        result[component.name] = _download_component(component, asset, root, open_url)
    return result


__all__ = ["DownloadError", "download_release"]
