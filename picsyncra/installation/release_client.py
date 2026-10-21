"""Network boundary for the installed, signed GitHub release catalog."""

from __future__ import annotations

from ..github_status import GitHubStatusError, _github_fetch_json
from ..brand import GITHUB_REPOSITORY
from .downloads import _open_github_asset, _trusted_url
from .release_keys import trusted_release_keys
from .release_source import list_signed_releases


class ReleaseSourceError(RuntimeError):
    """GitHub could not provide a trustworthy installed-release catalog."""


def _fetch_asset(url: str) -> bytes:
    """Read only a small manifest asset through the checked redirect handler."""
    _trusted_url(url, initial=True)
    response = None
    try:
        response = _open_github_asset(url)
        _trusted_url(getattr(response, "geturl", lambda: "")(), initial=False)
        data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ReleaseSourceError("Release manifest asset is too large.")
        return data
    except OSError as exc:
        raise ReleaseSourceError("Cannot download the signed release manifest.") from exc
    finally:
        if response is not None:
            response.close()


def list_installed_releases(channel: str) -> tuple[object, ...]:
    """Fetch the catalog using only compiled public keys and fixed endpoints."""
    if channel not in {"stable", "dev"}:
        raise ValueError("channel must be stable or dev")
    try:
        return list_signed_releases(
            channel,
            fetch_json=_github_fetch_json,
            fetch_asset=_fetch_asset,
            trusted_keys=trusted_release_keys(),
        )
    except GitHubStatusError as exc:
        raise ReleaseSourceError("GitHub release catalog is unavailable.") from exc


def read_installed_release_record(release_id: int) -> dict[str, object] | None:
    if isinstance(release_id, bool) or not isinstance(release_id, int) or release_id <= 0:
        raise ValueError("release_id must be positive")
    try:
        payload = _github_fetch_json(f"/repos/{GITHUB_REPOSITORY}/releases/{release_id}")
    except GitHubStatusError as exc:
        raise ReleaseSourceError("GitHub release record is unavailable.") from exc
    return payload if isinstance(payload, dict) and payload.get("id") == release_id else None


__all__ = ["ReleaseSourceError", "list_installed_releases", "read_installed_release_record"]
