"""Signed GitHub module catalogs, also reverified from protected offline cache."""
from __future__ import annotations
import base64
import json
import socket
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler
from .repository import fetch_release_json, GITHUB_REPOSITORY
from .downloads import _TrustedGithubRedirect, _trusted_url
from .module_catalog import catalog_module_releases
from .module_filesystem import safe_path, atomic_json
from .release_keys import trusted_release_keys
from .release_source import _asset_url
from .https import verified_https_context

MANIFEST_NAME = 'PicSyncra-modules-manifest.json'


def _catalog_error(exc):
    if isinstance(exc, HTTPError):
        if exc.code == 429 or (exc.code == 403 and exc.headers and exc.headers.get('X-RateLimit-Remaining') == '0'):
            return dict(code='rate_limit', message='GitHub: przekroczono limit zapytań. Spróbuj ponownie po odnowieniu limitu.')
        return dict(code='http_error', message=f'Nie udało się pobrać wydań z GitHuba (HTTP {exc.code}). Spróbuj ponownie.')
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        return dict(code='certificate_error', message='Nie udało się zweryfikować certyfikatu GitHuba. Sprawdź datę systemową i zaufane certyfikaty komputera.')
    if isinstance(reason, socket.gaierror):
        return dict(code='dns_error', message='Nie udało się odczytać adresu GitHuba (DNS). Sprawdź połączenie sieciowe kontrolera.')
    if isinstance(reason, TimeoutError):
        return dict(code='timeout', message='Przekroczono czas pobierania wydań z GitHuba. Spróbuj ponownie.')
    return dict(code='connection_error', message='Brak połączenia kontrolera z katalogiem GitHuba. Sprawdź sieć, proxy i zaporę dla kontrolera.')


def fetch_manifest_asset(url, limit=64 * 1024 * 1024):
    _trusted_url(url, initial=True)
    with build_opener(_TrustedGithubRedirect(), HTTPSHandler(context=verified_https_context())).open(Request(url, headers={'User-Agent': 'PicSyncra-installed/2'}), timeout=30) as response:
        raw = response.read(limit + 1)
        if len(raw) > limit: raise ValueError('Manifest modułów jest zbyt duży.')
        return raw


class ModuleReleaseSource:
    def __init__(self, context, *, keys=None, fetch_json=fetch_release_json, fetch_asset=fetch_manifest_asset):
        self.context = context
        self.keys = trusted_release_keys() if keys is None else keys
        self.fetch_json, self.fetch_asset = fetch_json, fetch_asset
        self.offline = False
        self.error = None
        self._snapshot = None
        self._lock = threading.RLock()

    def _fingerprint(self, channel):
        path = safe_path(self.context.state_root, 'module-catalog-' + channel + '.json')
        if not path.exists(): return None
        stat = path.stat()
        return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def snapshot(self, channel):
        # Reuse only an already verified, immutable in-memory catalog. A disk
        # change or expiration requires signature verification again. Explicit
        # refresh still calls load(), including its network check.
        with self._lock:
            cached = self._snapshot
            if cached and cached[0] == channel and time.monotonic() < cached[1] and cached[2] == self._fingerprint(channel):
                return cached[3]
            return self.load(channel)

    def load(self, channel):
        with self._lock:
            entries = self._load(channel)
            self._snapshot = (channel, time.monotonic() + 60, self._fingerprint(channel), entries)
            return entries

    def _load(self, channel):
        path = safe_path(self.context.state_root, 'module-catalog-' + channel + '.json')
        cached = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'records': [], 'manifests': {}}
        records = []
        try:
            for page in range(1, 21):
                batch = self.fetch_json(f'/repos/{GITHUB_REPOSITORY}/releases?per_page=100&page={page}')
                if not isinstance(batch, list): raise ValueError('Nieprawidłowa odpowiedź GitHub.')
                records.extend(batch)
                if len(batch) < 100: break
            self.offline = False
            self.error = None
        except Exception as exc:
            records = cached['records']
            self.offline = True
            self.error = _catalog_error(exc)
        manifests = dict(cached['manifests'])
        def loader(record):
            key = str(record['id'])
            if key not in manifests:
                if self.offline: raise ValueError('Brak lokalnego podpisanego manifestu.')
                manifests[key] = dict(raw=base64.b64encode(self.fetch_asset(_asset_url(record, MANIFEST_NAME))).decode(),
                                      signature=base64.b64encode(self.fetch_asset(_asset_url(record, MANIFEST_NAME + '.sig'))).decode(),
                                      key_id=self.fetch_asset(_asset_url(record, MANIFEST_NAME + '.key-id')).decode('ascii').strip())
            item = manifests[key]
            return base64.b64decode(item['raw'], validate=True), base64.b64decode(item['signature'], validate=True), item['key_id']
        entries = catalog_module_releases(records, channel=channel, manifest_loader=loader, trusted_keys=self.keys)
        # Never save an unchecked remote manifest as authoritative offline data.
        accepted = {str(entry.release_id) for entry in entries if entry.release and not entry.blocked_reason}
        if not self.offline:
            atomic_json(path, dict(records=records, manifests={key: value for key, value in manifests.items() if key in accepted}), replace=True)
        return entries
