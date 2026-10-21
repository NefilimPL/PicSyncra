"""Include chardet's model data and dynamically imported mypyc extensions."""

from importlib.machinery import EXTENSION_SUFFIXES
from importlib.metadata import distribution

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


# Windows wheels use per-module counterparts in both models and pipeline.
# Collecting only chardet.pipeline misses models._format__mypyc.
hiddenimports = collect_submodules("chardet")
datas = collect_data_files("chardet")

# Some wheels additionally use a hash-named extension outside the package.
# Keep nested names qualified via collect_submodules above; taking only their
# basename from RECORD would create invalid top-level hidden imports.
for entry in distribution("chardet").files or ():
    if (len(entry.parts) == 1 and "__mypyc" in entry.name
            and entry.name.endswith(tuple(EXTENSION_SUFFIXES))):
        hiddenimports.append(entry.name.split(".", 1)[0])
