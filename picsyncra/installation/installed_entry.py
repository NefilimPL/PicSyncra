"""Stable application EXEs open the selected host without updater UI/network."""
from pathlib import Path
import hashlib
import subprocess
import sys
from contextlib import nullcontext
from ..install_paths import load_registered_install_context
from .module_filesystem import safe_path
from .module_state import read_module_set, module_set_root
from .module_sessions import standalone_session

_APPLICATIONS = {'PicSyncra.exe': 'local', 'PicSyncra-WEB.exe': 'web', 'PicSyncra-Migrator.exe': 'migrator'}


def open_application(executable, installation_id='primary-installation'):
    executable = Path(executable)
    context = load_registered_install_context(installation_id)
    if context is None or executable.name not in _APPLICATIONS:
        raise RuntimeError('Brak poprawnej rejestracji aplikacji PicSyncra. Uruchom instalator Setup.')
    entry = safe_path(context.program_root, 'apps/' + executable.name)
    if not entry.is_file() or entry.resolve(strict=True) != executable.resolve(strict=True):
        raise RuntimeError('Nieprawidłowy plik startowy zarejestrowanej aplikacji.')
    app = _APPLICATIONS[executable.name]
    # Refuse a standalone app during maintenance. The child obtains its own
    # lifetime lease and verifies the selected code before running the app.
    with standalone_session(context) if app != 'web' else nullcontext():
        selected = read_module_set(context)
        path = f'apps/{app}/{executable.name}'
        descriptor = next((file for module in selected.modules for file in module.files if file.path == path), None)
        if descriptor is None: raise RuntimeError('Ta aplikacja nie jest zainstalowana.')
        target = safe_path(module_set_root(context, selected), path)
        with target.open('rb') as stream:
            if target.stat().st_size != descriptor.size or hashlib.file_digest(stream, 'sha256').hexdigest() != descriptor.sha256:
                raise RuntimeError('Plik aplikacji jest uszkodzony. Odzyskaj instalację w aktualizatorze.')
    return subprocess.Popen([str(target)], cwd=target.parent)


def main():
    try: open_application(sys.executable)
    except Exception as exc:
        from tkinter import Tk, messagebox
        root = Tk(); root.withdraw()
        try: messagebox.showerror('PicSyncra — uruchamianie', str(exc), parent=root)
        finally: root.destroy()
        return 1
    return 0
