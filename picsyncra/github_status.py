"""GitHub repository status helpers for the web panel."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .brand import GITHUB_OWNER, GITHUB_REPOSITORY
from .version import get_display_version

GITHUB_REPO_OWNER = GITHUB_OWNER
GITHUB_REPO_NAME = GITHUB_REPOSITORY.rsplit("/", 1)[-1]
GITHUB_REPO_FULL_NAME = GITHUB_REPOSITORY
GITHUB_API_ROOT = "https://api.github.com"
GITHUB_STATUS_CACHE_SECONDS = 15 * 60

_CACHE: dict[str, object] = {"payload": None, "expires_at": 0.0}


class GitHubStatusError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = int(status_code)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _empty_payload(
    available: bool,
    private: bool,
    message: str,
    current_version: str,
) -> dict[str, object]:
    return {
        "available": available,
        "private": private,
        "message": message,
        "repository": {},
        "latest_release": {},
        "license": {},
        "owner": {},
        "contributors": [],
        "current_version": current_version,
        "update_available": False,
        "checked_at": _utc_now(),
    }


def _github_fetch_json(path: str) -> object:
    request = Request(
        f"{GITHUB_API_ROOT}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "PicSyncra-Web",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read()
    except HTTPError as exc:
        raise GitHubStatusError(exc.code, str(exc.reason or exc)) from exc
    except URLError as exc:
        raise GitHubStatusError(0, str(exc.reason or exc)) from exc
    except TimeoutError as exc:
        raise GitHubStatusError(0, str(exc)) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise GitHubStatusError(0, "GitHub returned invalid JSON.") from exc


def _semantic_tuple(value: str) -> tuple[int, int, int] | None:
    text = str(value or "").strip().lower()
    if text.startswith("v"):
        text = text[1:]
    parts = text.split(".")
    if len(parts) != 3:
        return None
    try:
        numbers = tuple(int(part) for part in parts)
    except ValueError:
        return None
    if any(number < 0 for number in numbers):
        return None
    return numbers


def github_update_available(current_version: str, latest_tag: str) -> bool:
    current = str(current_version or "").strip()
    latest = str(latest_tag or "").strip()
    if not latest:
        return False
    if current.lower() == "dev":
        return True
    current_tuple = _semantic_tuple(current)
    latest_tuple = _semantic_tuple(latest)
    if current_tuple is None or latest_tuple is None:
        return False
    return latest_tuple > current_tuple


def _owner_payload(raw: dict[str, Any]) -> dict[str, object]:
    owner = raw.get("owner") if isinstance(raw.get("owner"), dict) else {}
    return {
        "login": str(owner.get("login") or ""),
        "html_url": str(owner.get("html_url") or ""),
        "type": str(owner.get("type") or ""),
    }


def _license_payload(raw: dict[str, Any]) -> dict[str, object]:
    license_data = raw.get("license") if isinstance(raw.get("license"), dict) else {}
    return {
        "name": str(license_data.get("name") or "Brak informacji"),
        "spdx_id": str(license_data.get("spdx_id") or ""),
    }


def _repository_payload(raw: dict[str, Any]) -> dict[str, object]:
    return {
        "full_name": str(raw.get("full_name") or GITHUB_REPO_FULL_NAME),
        "html_url": str(raw.get("html_url") or f"https://github.com/{GITHUB_REPO_FULL_NAME}"),
        "description": str(raw.get("description") or ""),
    }


def _release_payload(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    return {
        "tag_name": str(raw.get("tag_name") or ""),
        "name": str(raw.get("name") or raw.get("tag_name") or ""),
        "html_url": str(raw.get("html_url") or ""),
        "published_at": str(raw.get("published_at") or ""),
        "prerelease": bool(raw.get("prerelease")),
        "draft": bool(raw.get("draft")),
    }


def _contributors_payload(raw: object, owner_login: str) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    contributors: list[dict[str, object]] = []
    owner_key = owner_login.lower()
    for item in raw:
        if not isinstance(item, dict):
            continue
        login = str(item.get("login") or "")
        if not login or login.lower() == owner_key:
            continue
        contributors.append(
            {
                "login": login,
                "html_url": str(item.get("html_url") or ""),
                "contributions": int(item.get("contributions") or 0),
            }
        )
    return contributors


def _load_uncached_status(current_version: str) -> dict[str, object]:
    try:
        repo_raw = _github_fetch_json(f"/repos/{GITHUB_REPO_FULL_NAME}")
    except GitHubStatusError as exc:
        if exc.status_code == 404:
            return _empty_payload(
                False,
                True,
                "Repozytorium jest prywatne albo niedostepne.",
                current_version,
            )
        return _empty_payload(False, False, "Nie udalo sie pobrac danych GitHub.", current_version)
    if not isinstance(repo_raw, dict):
        return _empty_payload(
            False,
            False,
            "GitHub zwrocil niepoprawne dane repozytorium.",
            current_version,
        )
    try:
        release_raw = _github_fetch_json(f"/repos/{GITHUB_REPO_FULL_NAME}/releases/latest")
    except GitHubStatusError:
        release_raw = {}
    try:
        contributors_raw = _github_fetch_json(f"/repos/{GITHUB_REPO_FULL_NAME}/contributors")
    except GitHubStatusError:
        contributors_raw = []
    owner = _owner_payload(repo_raw)
    latest_release = _release_payload(release_raw)
    latest_tag = str(latest_release.get("tag_name") or "")
    return {
        "available": True,
        "private": bool(repo_raw.get("private")),
        "message": "",
        "repository": _repository_payload(repo_raw),
        "latest_release": latest_release,
        "license": _license_payload(repo_raw),
        "owner": owner,
        "contributors": _contributors_payload(contributors_raw, str(owner.get("login") or "")),
        "current_version": current_version,
        "update_available": github_update_available(current_version, latest_tag),
        "checked_at": _utc_now(),
    }


def github_repository_status(
    current_version: str | None = None,
    force_refresh: bool = False,
) -> dict[str, object]:
    version = str(current_version or get_display_version() or "dev")
    now = time.time()
    cached = _CACHE.get("payload")
    if not force_refresh and isinstance(cached, dict) and float(_CACHE.get("expires_at") or 0) > now:
        payload = dict(cached)
        payload["current_version"] = version
        latest = payload.get("latest_release") if isinstance(payload.get("latest_release"), dict) else {}
        payload["update_available"] = github_update_available(version, str(latest.get("tag_name") or ""))
        return payload
    payload = _load_uncached_status(version)
    _CACHE["payload"] = dict(payload)
    _CACHE["expires_at"] = now + GITHUB_STATUS_CACHE_SECONDS
    return payload
