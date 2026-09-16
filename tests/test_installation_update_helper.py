from __future__ import annotations

import json
from pathlib import Path

import pytest

from picsyncra.installation.contracts import InstallContext


def context(tmp_path: Path) -> InstallContext:
    program = tmp_path / "program"
    state = tmp_path / "state"
    config = state / "config"
    (program / "versions" / "41").mkdir(parents=True)
    config.mkdir(parents=True)
    (program / "active.json").write_text(
        json.dumps({"schema": 1, "installation_id": "site-1", "release_id": 41}), encoding="utf-8"
    )
    return InstallContext("site-1", program, state, config, state / "data.sqlite")


def test_activate_release_only_switches_to_an_existing_version_bundle(tmp_path: Path) -> None:
    from picsyncra.installation.update_helper import activate_release, read_active_release

    value = context(tmp_path)
    (value.program_root / "versions" / "42").mkdir()
    assert read_active_release(value) == 41
    assert activate_release(value, 42) == 42
    assert read_active_release(value) == 42


def test_activate_release_does_not_replace_active_pointer_for_missing_bundle(tmp_path: Path) -> None:
    from picsyncra.installation.update_helper import ActiveReleaseError, activate_release

    value = context(tmp_path)
    before = (value.program_root / "active.json").read_bytes()
    with pytest.raises(ActiveReleaseError, match="bundle"):
        activate_release(value, 42)
    assert (value.program_root / "active.json").read_bytes() == before


def test_active_release_rejects_marker_for_another_installation(tmp_path: Path) -> None:
    from picsyncra.installation.update_helper import ActiveReleaseError, read_active_release

    value = context(tmp_path)
    (value.program_root / "active.json").write_text(
        json.dumps({"schema": 1, "installation_id": "other", "release_id": 41}), encoding="utf-8"
    )
    with pytest.raises(ActiveReleaseError, match="active"):
        read_active_release(value)
