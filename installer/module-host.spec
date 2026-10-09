# -*- mode: python ; coding: utf-8 -*-
"""Analyze application dependencies but exclude application code from PYZ."""
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH).parent
NAME = os.environ.get('PICSYNCRA_HOST_NAME', 'PicSyncra-WEB')
if NAME not in {'PicSyncra-WEB', 'PicSyncra-Migrator', 'PicSyncra', 'PicSyncra-OCR'}:
    raise ValueError('Invalid installed host name')
datas = collect_data_files('certifi') + [(str(ROOT / 'pic'), 'pic')]
if NAME == 'PicSyncra-OCR':
    from PyInstaller.utils.hooks import collect_all
    vision_hidden = []
    vision_binaries = []
    for package in ('paddle', 'paddleocr', 'paddlex'):
        package_data, package_binaries, package_hidden = collect_all(package)
        datas += package_data
        vision_binaries += package_binaries
        vision_hidden += package_hidden
    model_cache = os.environ.get('PADDLE_PDX_CACHE_HOME')
    if not model_cache: raise ValueError('OCR build needs a verified model cache')
    datas += [(model_cache, 'ocr_models')]
else:
    vision_hidden, vision_binaries = [], []
a = Analysis([str(ROOT / 'installer' / 'installed_host.py')], pathex=[str(ROOT)],
    binaries=vision_binaries, datas=datas, hiddenimports=collect_submodules('picsyncra') + vision_hidden,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
# Dependency discovery must not silently turn independently installed Python
# modules into embedded application code. The stable importer also fails closed.
def stable(name):
    return name in {'picsyncra', 'picsyncra.install_paths', 'picsyncra.installation'} or name.startswith('picsyncra.installation.')
a.pure = [item for item in a.pure if not item[0].startswith('picsyncra') or stable(item[0])]
a.datas = [item for item in a.datas if not item[0].replace('\\', '/').startswith('picsyncra/')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=NAME == 'PicSyncra-OCR', icon=os.environ.get('PICSYNCRA_HOST_ICON'))
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)
