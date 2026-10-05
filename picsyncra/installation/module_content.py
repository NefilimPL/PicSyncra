"""Verified content cache with exact HTTP ranges, independent of release jumps."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import shutil
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPSHandler
from uuid import uuid4
from .contracts import InstallContext
from .module_contracts import ActiveModuleSet, ModuleFile, ModuleVersion
from .module_filesystem import safe_path
from .module_state import module_set_root, publish_module_set
from .downloads import _TrustedGithubRedirect, _trusted_url


class ModuleContentError(RuntimeError):
    pass


def _fetch_range(url, start, size, total):
    _trusted_url(url, initial=True)
    return build_opener(_TrustedGithubRedirect(), HTTPSHandler()).open(Request(url, headers={'Range': f'bytes={start}-{start + size - 1}',
                                        'Accept-Encoding': 'identity', 'User-Agent': 'PicSyncra-installed/2'}), timeout=90)


def _digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class ModuleContentStore:
    def __init__(self, context: InstallContext, *, fetch=_fetch_range):
        self.context = context
        self.fetch = fetch
        self.root = safe_path(context.program_root, 'content')
        self.root.mkdir(exist_ok=True)

    def available_hashes(self) -> frozenset[str]:
        return frozenset(path.name for path in self.root.iterdir()
                         if re.fullmatch('[a-f0-9]{64}', path.name) and path.is_file()
                         and _digest(safe_path(self.root, path.name)) == path.name)

    def import_bytes(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        destination = safe_path(self.root, digest)
        temporary = safe_path(self.root, uuid4().hex + '.part')
        try:
            with temporary.open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return digest

    def local_hashes(self, selected: ActiveModuleSet) -> frozenset[str]:
        root = module_set_root(self.context, selected)
        verified = set()
        for module in selected.modules:
            for file in module.files:
                try:
                    source = safe_path(root, file.path)
                    if source.is_file() and source.stat().st_size == file.size and _digest(source) == file.sha256:
                        verified.add(file.sha256)
                except (OSError, ValueError): continue
        return frozenset(verified)

    def seed(self, selected: ActiveModuleSet, *, allow_incomplete=False) -> None:
        """Import an installed set without fetching historical releases."""
        root = module_set_root(self.context, selected)
        for module in selected.modules:
            for file in module.files:
                try:
                    source = safe_path(root, file.path)
                    valid = source.is_file() and source.stat().st_size == file.size and _digest(source) == file.sha256
                except (OSError, ValueError): valid = False
                destination = safe_path(self.root, file.sha256)
                if destination.is_file() and destination.stat().st_size == file.size and _digest(destination) == file.sha256:
                    continue
                if not valid:
                    if allow_incomplete: continue
                    raise ModuleContentError('Lokalny plik modułu został zmieniony.')
                temporary = safe_path(self.root, uuid4().hex + '.part')
                try:
                    shutil.copyfile(source, temporary)
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)

    def acquire(self, module: ModuleVersion, file: ModuleFile) -> Path:
        destination = safe_path(self.root, file.sha256)
        if destination.is_file() and destination.stat().st_size == file.size and _digest(destination) == file.sha256:
            return destination
        if file.size == 0:
            self.import_bytes(b'')
            return destination
        url = f'https://github.com/NefilimPL/PicSyncra/releases/download/{quote(module.source_tag, safe="")}/{quote(file.asset_name, safe="")}'
        temporary = safe_path(self.root, uuid4().hex + '.part')
        try:
            with self.fetch(url, file.asset_offset, file.size, file.asset_size) as response:
                expected = f'bytes {file.asset_offset}-{file.asset_offset + file.size - 1}/{file.asset_size}'
                if response.status != 206 or response.headers.get('Content-Range') != expected:
                    raise ModuleContentError('Serwer nie potwierdził zakresu pliku; pobranie całej paczki zostało wstrzymane.')
                length = response.headers.get('Content-Length')
                if length is not None and length != str(file.size):
                    raise ModuleContentError('Nieprawidłowy rozmiar pobieranego zakresu.')
                remaining = file.size
                digest = hashlib.sha256()
                with temporary.open('xb') as stream:
                    while remaining:
                        chunk = response.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ModuleContentError('Przerwane pobieranie pliku modułu.')
                        digest.update(chunk)
                        stream.write(chunk)
                        remaining -= len(chunk)
                    if response.read(1) or digest.hexdigest() != file.sha256:
                        raise ModuleContentError('Suma kontrolna pobranego pliku modułu jest niezgodna.')
                    stream.flush()
                    os.fsync(stream.fileno())
            os.replace(temporary, destination)
            return destination
        except (OSError, ValueError) as exc:
            raise ModuleContentError('Nie udało się pobrać zweryfikowanej zawartości modułu.') from exc
        finally:
            temporary.unlink(missing_ok=True)

    def assemble(self, selected: ActiveModuleSet) -> None:
        root = module_set_root(self.context, selected)
        root.mkdir(parents=True, exist_ok=True)
        for module in selected.modules:
            for file in module.files:
                source = self.acquire(module, file)
                destination = safe_path(root, file.path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if destination.stat().st_size != file.size or _digest(destination) != file.sha256:
                        raise ModuleContentError('Istniejący zestaw modułów ma zmienioną zawartość.')
                    continue
                # Separate immutable set copies: modifying one set cannot corrupt
                # every cached version through a writable hard link.
                temporary = destination.with_name('.' + destination.name + '.' + uuid4().hex + '.part')
                try:
                    shutil.copyfile(source, temporary)
                    os.link(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
        publish_module_set(self.context, selected)
