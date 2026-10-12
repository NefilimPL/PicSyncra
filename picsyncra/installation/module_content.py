"""Verified content cache with exact HTTP ranges, independent of release jumps."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import shutil
import http.client
import threading
from contextlib import contextmanager
from time import sleep as _sleep
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPSHandler
from uuid import uuid4
from .contracts import InstallContext
from .module_contracts import ActiveModuleSet, ModuleFile, ModuleVersion
from .module_filesystem import safe_path, replace_file
from .module_state import module_set_root, publish_module_set
from .downloads import _TrustedGithubRedirect, _trusted_url
from .https import verified_https_context
from .module_download_diagnostics import download_failure

_RANGE_BATCH_BYTES = 8 * 1024 * 1024
_RANGE_BATCH_FILES = 256


def _range_batches(entries):
    """Combine only adjacent signed ranges from the same release asset."""
    entries = sorted(entries, key=lambda entry: (entry[0].source_tag, entry[1].asset_name,
                                                entry[1].asset_size, entry[1].asset_offset))
    batch, length = [], 0
    for entry in entries:
        module, file = entry
        if batch:
            previous_module, previous_file = batch[-1]
            adjacent = (module.source_tag, file.asset_name, file.asset_size, file.asset_offset) == (
                previous_module.source_tag, previous_file.asset_name, previous_file.asset_size,
                previous_file.asset_offset + previous_file.size)
            if not adjacent or length + file.size > _RANGE_BATCH_BYTES or len(batch) >= _RANGE_BATCH_FILES:
                yield batch
                batch, length = [], 0
        batch.append(entry)
        length += file.size
    if batch:
        yield batch


class ModuleContentError(RuntimeError):
    def __init__(self, message, *, code='content_error', retryable=False, details=None):
        super().__init__(message)
        self.details = details or dict(code=code, message=message, retryable=retryable)


def _fetch_range(url, start, size, total):
    _trusted_url(url, initial=True)
    return build_opener(_TrustedGithubRedirect(), HTTPSHandler(context=verified_https_context())).open(Request(url, headers={'Range': f'bytes={start}-{start + size - 1}',
                                        'Accept-Encoding': 'identity', 'User-Agent': 'PicSyncra-installed/2'}), timeout=90)


def _digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class ModuleContentStore:
    def __init__(self, context: InstallContext, *, fetch=_fetch_range, sleep=_sleep):
        self.context = context
        self.fetch = fetch
        self.sleep = sleep
        self.root = safe_path(context.program_root, 'content')
        self.root.mkdir(exist_ok=True)
        self._inventory = threading.local()

    @contextmanager
    def inventory_scope(self):
        previous = getattr(self._inventory, 'cache', None)
        self._inventory.cache = previous if previous is not None else {}
        try: yield
        finally: self._inventory.cache = previous

    def _inventory_digest(self, path):
        cache = getattr(self._inventory, 'cache', None)
        if cache is None: return _digest(path)
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        cached = cache.get(path)
        if cached and cached[0] == identity: return cached[1]
        digest = _digest(path)
        cache[path] = identity, digest
        return digest

    def available_hashes(self) -> frozenset[str]:
        return frozenset(path.name for path in self.root.iterdir()
                         if re.fullmatch('[a-f0-9]{64}', path.name) and path.is_file()
                         and self._inventory_digest(safe_path(self.root, path.name)) == path.name)

    def import_bytes(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        destination = safe_path(self.root, digest)
        temporary = safe_path(self.root, uuid4().hex + '.part')
        try:
            with temporary.open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            replace_file(temporary, destination)
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
                    if source.is_file() and source.stat().st_size == file.size and self._inventory_digest(source) == file.sha256:
                        verified.add(file.sha256)
                except (OSError, ValueError): continue
        return frozenset(verified)

    def seed(self, selected: ActiveModuleSet, *, allow_incomplete=False) -> None:
        """Import an installed set without fetching historical releases."""
        root = module_set_root(self.context, selected)
        for module in selected.modules:
            for file in module.files:
                destination = safe_path(self.root, file.sha256)
                if destination.is_file() and destination.stat().st_size == file.size and _digest(destination) == file.sha256:
                    continue
                try:
                    source = safe_path(root, file.path)
                    valid = source.is_file() and source.stat().st_size == file.size and _digest(source) == file.sha256
                except (OSError, ValueError): valid = False
                if not valid:
                    if allow_incomplete: continue
                    raise ModuleContentError('Lokalny plik modułu został zmieniony.')
                temporary = safe_path(self.root, uuid4().hex + '.part')
                try:
                    shutil.copyfile(source, temporary)
                    replace_file(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)

    def acquire(self, module: ModuleVersion, file: ModuleFile, *, on_progress=None) -> Path:
        destination = safe_path(self.root, file.sha256)
        if destination.is_file() and destination.stat().st_size == file.size and _digest(destination) == file.sha256:
            return destination
        if file.size == 0:
            self.import_bytes(b'')
            return destination
        url = f'https://github.com/NefilimPL/PicSyncra/releases/download/{quote(module.source_tag, safe="")}/{quote(file.asset_name, safe="")}'
        for attempt in range(1, 4):
            try:
                return self._acquire_once(file, destination, url, on_progress)
            except (ModuleContentError, OSError, ValueError, http.client.HTTPException) as exc:
                details = dict(exc.details) if isinstance(exc, ModuleContentError) else download_failure(exc)
                details.update(module_id=module.module_id, file=file.path, asset=file.asset_name,
                               source_tag=module.source_tag, attempts=attempt)
                if not details['retryable'] or attempt == 3:
                    raise ModuleContentError(f"{details['message']} [{details['code']}] Moduł: {module.module_id}; plik: {file.path}.", details=details) from exc
                if on_progress: on_progress(0)
                delay = attempt
                headers = getattr(exc, 'headers', None)
                retry_after = headers.get('Retry-After', '') if headers else ''
                if retry_after.isdecimal(): delay = min(15, max(delay, int(retry_after)))
                self.sleep(delay)

    def _acquire_once(self, file, destination, url, on_progress):
        self._transfer_range([file], url, lambda current, count: on_progress(count) if on_progress else None)
        return destination

    def _transfer_range(self, files, url, on_progress):
        """Stream one bounded range, verifying/publishing every file separately."""
        file = files[0]
        size = sum(item.size for item in files)
        operation = 'fetch_range'
        try:
            with self.fetch(url, file.asset_offset, size, file.asset_size) as response:
                expected = f'bytes {file.asset_offset}-{file.asset_offset + size - 1}/{file.asset_size}'
                if response.status != 206 or response.headers.get('Content-Range') != expected:
                    raise ModuleContentError('Serwer nie potwierdził zakresu pliku; pobranie całej paczki zostało wstrzymane.', code='range_mismatch')
                length = response.headers.get('Content-Length')
                if length is not None and length != str(size):
                    raise ModuleContentError('Nieprawidłowy rozmiar pobieranego zakresu.', code='size_mismatch')
                for file in files:
                    temporary = safe_path(self.root, uuid4().hex + '.part')
                    try:
                        remaining = file.size
                        digest = hashlib.sha256()
                        operation = 'create_cache_file'
                        with temporary.open('xb') as stream:
                            while remaining:
                                operation = 'read_remote'
                                chunk = response.read(min(1024 * 1024, remaining))
                                if not chunk or len(chunk) > remaining:
                                    raise ModuleContentError('Przerwane pobieranie pliku modułu.', code='interrupted_download', retryable=True)
                                digest.update(chunk)
                                operation = 'write_cache_file'
                                stream.write(chunk)
                                remaining -= len(chunk)
                                operation = 'report_progress'
                                on_progress(file, file.size - remaining)
                            if digest.hexdigest() != file.sha256:
                                raise ModuleContentError('Suma kontrolna pobranego pliku modułu jest niezgodna.', code='hash_mismatch')
                            if file is files[-1]:
                                operation = 'read_remote'
                                if response.read(1):
                                    raise ModuleContentError('Nieprawidłowy rozmiar pobieranego zakresu.', code='size_mismatch')
                            operation = 'flush_cache_file'
                            stream.flush()
                            os.fsync(stream.fileno())
                        operation = 'publish_cache_file'
                        replace_file(temporary, safe_path(self.root, file.sha256))
                    finally:
                        temporary.unlink(missing_ok=True)
        except (ModuleContentError, OSError, ValueError, http.client.HTTPException) as exc:
            details = dict(exc.details) if isinstance(exc, ModuleContentError) else download_failure(exc)
            details.update(file=file.path)
            if operation not in {'fetch_range', 'read_remote'}:
                details.update(operation=operation, storage='content_cache' if operation.endswith('_cache_file') else None)
            error = ModuleContentError(details['message'], details=details)
            error.headers = getattr(exc, 'headers', None)
            raise error from exc

    def _acquire_batch(self, entries, on_progress):
        """Retry the missing suffix, retaining already verified cache files."""
        for attempt in range(1, 4):
            missing = [(module, file) for module, file in entries
                       if not self._cached(file)]
            if not missing:
                return
            try:
                for group in _range_batches(missing):
                    module, first = group[0]
                    url = f'https://github.com/NefilimPL/PicSyncra/releases/download/{quote(module.source_tag, safe="")}/{quote(first.asset_name, safe="")}'
                    owners = {file.path: owner for owner, file in group}
                    self._transfer_range([file for owner, file in group], url,
                                         lambda file, count: on_progress(owners[file.path], file, count))
                return
            except ModuleContentError as exc:
                details = dict(exc.details)
                module, file = next((entry for entry in missing if entry[1].path == details['file']))
                details.update(module_id=module.module_id, asset=file.asset_name,
                               source_tag=module.source_tag, attempts=attempt)
                if not details['retryable'] or attempt == 3:
                    raise ModuleContentError(f"{details['message']} [{details['code']}] Moduł: {module.module_id}; plik: {file.path}.", details=details) from exc
                on_progress(module, file, 0)
                retry_after = exc.headers.get('Retry-After', '') if exc.headers else ''
                delay = min(15, max(attempt, int(retry_after))) if retry_after.isdecimal() else attempt
                self.sleep(delay)

    def _cached(self, file):
        destination = safe_path(self.root, file.sha256)
        return destination.is_file() and destination.stat().st_size == file.size and _digest(destination) == file.sha256

    def assemble(self, selected: ActiveModuleSet, *, on_progress=None) -> None:
        root = module_set_root(self.context, selected)
        root.mkdir(parents=True, exist_ok=True)
        downloaded = {}
        total = 0
        missing = set()
        module_totals = {}
        owners = {}
        entries = []
        cached = self.available_hashes()
        for module in selected.modules:
            for file in module.files:
                if file.sha256 not in cached and file.sha256 not in missing and file.size:
                    missing.add(file.sha256)
                    entries.append((module, file))
                    owners[file.sha256] = module.module_id
                    module_totals[module.module_id] = module_totals.get(module.module_id, 0) + file.size
                    total += file.size
        if on_progress:
            on_progress(dict(downloaded_bytes=0, total_bytes=total, module_id=None))

        def report(module, file, count):
            if on_progress:
                downloaded[file.sha256] = count
                on_progress(dict(downloaded_bytes=sum(downloaded.values()), total_bytes=total, module_id=module.module_id,
                    module_downloaded_bytes=sum(value for digest, value in downloaded.items() if owners.get(digest) == module.module_id),
                    module_total_bytes=module_totals.get(module.module_id, 0)))

        for batch in _range_batches(entries):
            self._acquire_batch(batch, report)
        for module in selected.modules:
            for file in module.files:
                source = self.acquire(module, file, on_progress=lambda count: report(module, file, count))
                destination = safe_path(root, file.path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if destination.stat().st_size != file.size or _digest(destination) != file.sha256:
                        raise ModuleContentError('Istniejący zestaw modułów ma zmienioną zawartość.')
                    continue
                # Separate immutable set copies: modifying one set cannot corrupt
                # every cached version through a writable hard link.
                # The signed payload name can already approach MAX_PATH. Keep
                # scratch files at the set root instead of extending that name.
                # Both paths stay on the same volume for atomic publication.
                temporary = safe_path(root, uuid4().hex + '.part')
                try:
                    shutil.copyfile(source, temporary)
                    os.link(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
        publish_module_set(self.context, selected)
