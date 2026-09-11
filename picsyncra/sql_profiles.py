"""SQL connection profile normalization helpers."""

from __future__ import annotations

import re
from typing import Any

from .common import K, M, N, P, SQL_PROFILES_KEY, b, c, p

DEFAULT_SQL_PROFILE_ID = "default"
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _text(value: object) -> str:
    return str(value or "").strip()


def _slug(value: object) -> str:
    text = _text(value).casefold()
    text = re.sub(r"[^a-z0-9_-]+", "-", text).strip("-_")
    return text[:64]


def _db_type(value: object) -> str:
    return K if _text(value).casefold() == K else "mssql"


def default_sql_profile(config_dict: dict[str, Any]) -> dict[str, Any]:
    db_type = _db_type(config_dict.get(p, K))
    section_key = K if db_type == K else P
    section = config_dict.get(section_key, {})
    if not isinstance(section, dict):
        section = {}
    return {
        "id": DEFAULT_SQL_PROFILE_ID,
        "label": "Domyslny",
        "type": db_type,
        "host": _text(section.get(c)),
        "database": _text(section.get(b)),
        "user": _text(section.get(N)),
        "password": _text(section.get(M)),
        "enabled": True,
        "usage": "slots",
        "locked": True,
    }


def normalize_additional_sql_profile(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    raw_id = _slug(raw.get("id") or raw.get("label"))
    if (
        not raw_id
        or raw_id == DEFAULT_SQL_PROFILE_ID
        or not PROFILE_ID_RE.fullmatch(raw_id)
    ):
        return None
    label = _text(raw.get("label")) or raw_id
    return {
        "id": raw_id,
        "label": label,
        "type": _db_type(raw.get("type", K)),
        "host": _text(raw.get("host") or raw.get("server")),
        "database": _text(raw.get("database")),
        "user": _text(raw.get("user")),
        "password": _text(raw.get("password")),
        "enabled": bool(raw.get("enabled", True)),
        "usage": "pimcore_sql",
        "locked": False,
    }


def additional_sql_profiles(config_dict: dict[str, Any]) -> list[dict[str, Any]]:
    raw_profiles = config_dict.get(SQL_PROFILES_KEY, [])
    if not isinstance(raw_profiles, list):
        return []
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_profiles:
        profile = normalize_additional_sql_profile(raw)
        if profile is None or profile["id"] in seen:
            continue
        cleaned.append(profile)
        seen.add(profile["id"])
    return cleaned


def normalize_sql_profiles(config_dict: dict[str, Any]) -> list[dict[str, Any]]:
    config_source = config_dict if isinstance(config_dict, dict) else {}
    return [default_sql_profile(config_source), *additional_sql_profiles(config_source)]


def public_sql_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public_profiles: list[dict[str, Any]] = []
    for profile in profiles:
        item = {
            key: value
            for key, value in profile.items()
            if key not in {"user", "password"}
        }
        item["user_set"] = bool(_text(profile.get("user")))
        item["password_set"] = bool(_text(profile.get("password")))
        public_profiles.append(item)
    return public_profiles


def resolve_sql_profile(
    profiles: list[dict[str, Any]],
    profile_id: object,
) -> dict[str, Any]:
    wanted = _text(profile_id) or DEFAULT_SQL_PROFILE_ID
    for profile in profiles:
        if profile.get("id") == wanted:
            return profile
    raise KeyError(wanted)
