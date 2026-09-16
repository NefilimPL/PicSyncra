# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller input for the separately downloaded OCR component."""

from PyInstaller.utils.hooks import collect_all
import os
from pathlib import Path


datas, binaries, hiddenimports = collect_all("picsyncra")
for package in ("certifi", "cv2", "numpy", "paddle", "paddleocr"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

model_cache_value = str(os.environ.get("PADDLE_PDX_CACHE_HOME") or "").strip()
model_cache = Path(model_cache_value) if model_cache_value else None
if model_cache is None or not model_cache.is_dir():
    raise RuntimeError("Prepared OCR model cache is required for the installed OCR component.")
datas += [(str(model_cache), "ocr_models")]

a = Analysis(
    ["PicSyncra-OCR.py"],
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
    name="PicSyncra-OCR",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PicSyncra-OCR")
