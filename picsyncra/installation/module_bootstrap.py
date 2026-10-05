"""Load only the selected external application code before any app imports."""
from __future__ import annotations
import hashlib
import importlib.abc
import importlib.util
import sys
from pathlib import Path
from .module_filesystem import safe_path
from .module_state import read_module_set, module_set_root, verify_module_set_files


def _stable(name):
    return name in {'picsyncra', 'picsyncra.install_paths', 'picsyncra.installation'} or name.startswith('picsyncra.installation.')


class _SelectedLoader(importlib.abc.SourceLoader):
    def __init__(self, name, path, file): self.name, self.path, self.file = name, path, file
    def get_filename(self, fullname): return str(self.path)
    def get_data(self, path):
        if path != str(self.path): raise ImportError('Uncatalogued module path.')
        data = self.path.read_bytes()
        if len(data) != self.file.size or hashlib.sha256(data).hexdigest() != self.file.sha256:
            raise ImportError('Wybrany plik modułu został zmieniony.')
        return data
    def get_code(self, fullname):
        # Never use __pycache__ or embedded code, including matching timestamps.
        return compile(self.get_data(str(self.path)), str(self.path), 'exec', dont_inherit=True)


class SelectedModuleFinder(importlib.abc.MetaPathFinder):
    def __init__(self, context, selected):
        self.root = module_set_root(context, selected)
        self.files = {}
        self.parents = set()
        for module in selected.modules:
            for file in module.files:
                if not file.path.startswith('picsyncra/') or not file.path.endswith('.py'): continue
                parts = file.path[:-3].split('/')
                package = parts[-1] == '__init__'
                if package: parts.pop()
                name = '.'.join(parts)
                if _stable(name): continue
                self.files[name] = file, package
                self.parents.update('.'.join(parts[:n]) for n in range(1, len(parts)))

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith('picsyncra.') or _stable(fullname): return None
        entry = self.files.get(fullname)
        if entry:
            file, package = entry
            try:
                location = safe_path(self.root, file.path)
                if not location.is_file(): raise ImportError('Brak pliku wybranego modułu.')
            except (ValueError, OSError) as exc:
                raise ImportError('Nieprawidłowy plik wybranego modułu.') from exc
            return importlib.util.spec_from_file_location(fullname, location,
                loader=_SelectedLoader(fullname, location, file),
                submodule_search_locations=[str(location.parent)] if package else None)
        if fullname in self.parents:
            spec = importlib.util.spec_from_loader(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = []
            return spec
        raise ImportError(f'Brak {fullname} w wybranym zestawie; wymagane odzyskanie instalacji.')


def bootstrap_installed_modules(context=None):
    if context is None:
        from ..install_paths import resolve_install_context
        context = resolve_install_context(Path(sys.executable))
    if context is None: raise RuntimeError('Host modułów wymaga zarejestrowanej instalacji.')
    selected = read_module_set(context)
    verify_module_set_files(context, selected)
    if any(name.startswith('picsyncra.') and not _stable(name) for name in sys.modules):
        raise ImportError('Kod aplikacji załadowano przed wyborem zestawu modułów.')
    finder = SelectedModuleFinder(context, selected)
    sys.dont_write_bytecode = True
    sys.meta_path.insert(0, finder)
    return context, selected
