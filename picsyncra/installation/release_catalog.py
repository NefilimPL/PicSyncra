"""Turn GitHub release metadata into a safe selectable installed-release catalog."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Literal

from .controller_version import CONTROLLER_VERSION
from .contracts import ReleaseChoice
from .release_manifest import ManifestError, verify_manifest


Channel = Literal["stable", "dev"]
ManifestLoader = Callable[[dict[str, object]], tuple[bytes, bytes, str]]


def _release_id(item: dict[str, object]) -> int | None:
    value = item.get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _blocked(item: dict[str, object], reason: str) -> ReleaseChoice | None:
    release_id = _release_id(item)
    tag = item.get("tag_name")
    if release_id is None or not isinstance(tag, str) or not tag.strip():
        return None
    return ReleaseChoice(
        release_id=release_id, tag=tag.strip(), commit="", channel="stable",
        source_branch="", manifest_sha256="", components=(), can_install=False, blocked_reason=reason,
    )


def catalog_releases(
    releases: Sequence[object],
    *,
    channel: Channel,
    manifest_loader: ManifestLoader,
    trusted_keys: Mapping[str, bytes | str],
) -> tuple[ReleaseChoice, ...]:
    """Return published releases in descending publication order.

    Drafts and releases explicitly assigned to another channel remain invisible.
    A release that claims this channel but has an invalid manifest stays visible
    as blocked so an administrator can distinguish it from an older version.
    """
    if channel not in {"stable", "dev"}:
        raise ValueError("channel must be stable or dev")
    expected_prerelease = channel == "dev"
    candidates: list[dict[str, object]] = []
    for raw in releases:
        if not isinstance(raw, dict) or raw.get("draft") is True:
            continue
        if raw.get("prerelease") is not expected_prerelease:
            continue
        if _release_id(raw) is None or not isinstance(raw.get("tag_name"), str):
            continue
        candidates.append(raw)
    candidates.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)

    choices: list[ReleaseChoice] = []
    for release in candidates:
        try:
            raw_manifest, signature, key_id = manifest_loader(release)
            choice = verify_manifest(raw_manifest, signature, trusted_keys, key_id=key_id)
        except (ManifestError, OSError, ValueError, TypeError):
            blocked = _blocked(release, "manifest_invalid")
            if blocked is not None:
                choices.append(blocked)
            continue
        if (
            choice.release_id != release["id"]
            or choice.tag != str(release["tag_name"]).strip()
            or choice.channel != channel
            or bool(release["prerelease"]) is not expected_prerelease
        ):
            blocked = _blocked(release, "release_mismatch")
            if blocked is not None:
                choices.append(blocked)
            continue
        if choice.minimum_controller > CONTROLLER_VERSION:
            choices.append(
                replace(choice, can_install=False, blocked_reason="controller_outdated")
            )
            continue
        choices.append(choice)
    return tuple(choices)
