import os
from pathlib import Path
import subprocess
import sys


def test_portable_web_imports_without_installed_windows_dependencies():
    script = """
import importlib.abc
import sys
class NoWindowsDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'winerror' or fullname.startswith('win32'):
            raise ModuleNotFoundError('Blocked installed dependency: ' + fullname)
sys.meta_path.insert(0, NoWindowsDependencies())
import picsyncra.web.app
from picsyncra.installation.control_pipe import NamedPipeControlClient, ControlPipeError
try:
    NamedPipeControlClient(r'\\\\.\\pipe\\PicSyncra.Control.test').request(b'{}')
except ControlPipeError as exc:
    assert 'pywin32' in str(exc)
else:
    raise AssertionError('Using a Windows pipe without pywin32 must fail explicitly')
"""
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                            env=dict(os.environ, PICSYNCRA_HEADLESS='1', PICSYNCRA_WEB_AUTH='0'),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
