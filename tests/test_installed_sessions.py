from __future__ import annotations

from pathlib import Path
import base64
from unittest.mock import patch

from picsyncra.installation.contracts import InstallContext


def context(tmp_path: Path) -> InstallContext:
    program = tmp_path / "program"
    state = tmp_path / "state"
    config = state / "config"
    program.mkdir()
    config.mkdir(parents=True)
    return InstallContext("site-1", program, state, config, state / "data.sqlite")


def test_session_epoch_starts_at_zero_and_is_persisted_outside_database(tmp_path: Path) -> None:
    from picsyncra.installation.session_epoch import advance_session_epoch, read_session_epoch

    value = context(tmp_path)
    assert read_session_epoch(value) == 0
    assert advance_session_epoch(value) == 1
    assert read_session_epoch(value) == 1
    assert (value.state_root / "session-epoch.json").is_file()
    assert not value.database_path.exists()


def test_session_epoch_rejects_corrupt_persisted_state(tmp_path: Path) -> None:
    from picsyncra.installation.session_epoch import SessionEpochError, read_session_epoch

    value = context(tmp_path)
    (value.state_root / "session-epoch.json").write_text('{"epoch":"one"}', encoding="utf-8")
    try:
        read_session_epoch(value)
    except SessionEpochError:
        pass
    else:
        raise AssertionError("A corrupt session epoch must not be accepted")


def test_installed_web_session_is_rejected_after_epoch_changes(tmp_path: Path) -> None:
    from picsyncra.web import app as web_app
    from picsyncra.installation.session_epoch import advance_session_epoch

    value = context(tmp_path)
    user = {"id": "user-1", "username": "operator", "session_version": 2, "enabled": True, "locked": False}
    with (
        patch.object(web_app, "resolve_install_context", return_value=value),
        patch.object(web_app, "find_user_by_id", return_value=user),
    ):
        token = web_app._make_session_token(user)
        payload = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        assert payload.startswith("session-v3|user-1|2|0|")
        assert web_app._read_session_token(token) == "operator"
        advance_session_epoch(value)
        assert web_app._read_session_token(token) is None
