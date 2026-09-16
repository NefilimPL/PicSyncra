from __future__ import annotations

from pathlib import Path

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
