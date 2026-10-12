import json
import os
import threading

import pytest

from picsyncra.installation.module_filesystem import atomic_json


@pytest.mark.skipif(os.name != 'nt', reason='Windows denies replacement of an open reader')
def test_atomic_snapshot_survives_a_windows_reader(tmp_path):
    path = tmp_path / 'progress.json'
    atomic_json(path, {'bytes': 1}, replace=True)
    reader = path.open('rb')
    timer = threading.Timer(.15, reader.close)
    timer.start()
    try:
        atomic_json(path, {'bytes': 2}, replace=True)
    finally:
        reader.close()
        timer.join()
    assert json.loads(path.read_text()) == {'bytes': 2}
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_snapshot_does_not_bypass_persistent_access_denial(tmp_path, monkeypatch):
    from picsyncra.installation import module_filesystem
    path = tmp_path / 'progress.json'
    atomic_json(path, {'bytes': 1}, replace=True)
    calls = []
    def denied(*args):
        calls.append(args)
        error = PermissionError(13, 'private path')
        error.winerror = 5
        raise error
    monkeypatch.setattr(module_filesystem.os, 'replace', denied)
    monkeypatch.setattr(module_filesystem, 'sleep', lambda _: None, raising=False)
    with pytest.raises(PermissionError): atomic_json(path, {'bytes': 2}, replace=True)
    assert 1 <= len(calls) <= 10
    assert json.loads(path.read_text()) == {'bytes': 1}
    assert list(tmp_path.iterdir()) == [path]
