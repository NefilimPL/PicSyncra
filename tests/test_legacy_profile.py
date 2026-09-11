"""Tests for selecting one self-contained pre-rebrand data profile."""

from __future__ import annotations

import json
from pathlib import Path

from picsyncra.sqlite_store import SqliteStore


def test_load_legacy_profile_uses_only_direct_files_from_selected_root(tmp_path: Path) -> None:
    """Changing a same-named file outside the profile must not affect its manifest."""

    from picsyncra.legacy_profile import load_legacy_profile

    source_root = tmp_path / "old-server-copy"
    source_root.mkdir()
    SqliteStore(str(source_root / "picorgftp_sql.sqlite")).save_config(
        {"marker": "old-db"}
    )
    (source_root / "web_users.json").write_text(
        json.dumps([{"username": "admin", "role": "admin", "password_hash": "hash"}]),
        encoding="utf-8",
    )
    (source_root / "config.json").write_text(json.dumps({"marker": "old-json"}), encoding="utf-8")
    nested_root = source_root / "nested-current-files"
    nested_root.mkdir()
    (nested_root / "web_users.json").write_text("[]", encoding="utf-8")

    profile = load_legacy_profile(source_root)

    assert profile.root == source_root.resolve()
    assert profile.sqlite_path == source_root / "picorgftp_sql.sqlite"
    assert tuple(path.name for path in profile.source_files) == (
        "picorgftp_sql.sqlite",
        "config.json",
        "web_users.json",
    )
    assert profile.manifest.source_names == (
        "picorgftp_sql.sqlite",
        "config.json",
        "web_users.json",
    )


def test_discovery_returns_separate_profiles_without_cross_root_merge(tmp_path: Path) -> None:
    """Two valid source roots must be two candidates, never one combined profile."""

    from picsyncra.legacy_profile import discover_legacy_profiles

    first_root = tmp_path / "old-application"
    second_root = tmp_path / "old-data"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "config.json").write_text(json.dumps({"origin": "app"}), encoding="utf-8")
    (second_root / "web_users.json").write_text("[]", encoding="utf-8")

    profiles = discover_legacy_profiles((first_root, second_root))

    assert tuple(profile.root for profile in profiles) == (
        first_root.resolve(),
        second_root.resolve(),
    )
    assert tuple(profile.manifest.source_names for profile in profiles) == (
        ("config.json",),
        ("web_users.json",),
    )


def test_profile_with_only_local_settings_is_not_an_importable_legacy_profile(tmp_path: Path) -> None:
    """The new program's bootstrap file alone must never create a blank imported database."""

    from picsyncra.legacy_profile import load_legacy_profile

    source_root = tmp_path / "current-application"
    source_root.mkdir()
    (source_root / "local_settings.json").write_text('{"data_mode": "sqlite"}', encoding="utf-8")

    assert load_legacy_profile(source_root) is None
