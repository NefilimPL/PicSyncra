# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller input for the installed-package setup helper.

This is source code, not a generated ``.spec`` file.  It remains versioned so
the installer can be rebuilt on a clean CI runner.
"""

from PyInstaller.utils.hooks import collect_all


datas, binaries, hiddenimports = collect_all("picsyncra")
certifi_datas, certifi_binaries, certifi_hiddenimports = collect_all("certifi")
datas += certifi_datas
binaries += certifi_binaries
hiddenimports += certifi_hiddenimports

a = Analysis(
    ["PicSyncra-SetupHelper.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PicSyncra-SetupHelper",
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PicSyncra-SetupHelper")
