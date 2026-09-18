from __future__ import annotations

import base64
from pathlib import Path

import pytest


def test_writer_requires_valid_nonempty_public_key_mapping(tmp_path: Path) -> None:
    from tools.write_trusted_release_keys import write_keys

    key = base64.b64encode(b"a" * 32).decode()
    target = tmp_path / "release_keys.py"
    write_keys(target, '{"release-1":"' + key + '"}')
    assert "release-1" in target.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        write_keys(target, "{}")
