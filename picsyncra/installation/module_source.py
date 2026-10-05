"""Signed GitHub module catalogs, also reverified from protected offline cache."""
from __future__ import annotations
import base64
import json
from urllib.request import Request, build_opener, HTTPSHandler
from .repository import fetch_release_json, GITHUB_REPOSITORY
from .downloads import _TrustedGithubRedirect, _trusted_url
from .module_catalog import catalog_module_releases
from .module_filesystem import safe_path, atomic_json
from .release_keys import trusted_release_keys
from .release_source import _asset_url

MANIFEST_NAME = 'PicSyncra-modules-manifest.json'


def fetch_manifest_asset(url, limit=64 * 1024 * 1024):
    _trusted_url(url, initial=True)
    with build_opener(_TrustedGithubRedirect(), HTTPSHandler()).open(Request(url, headers={'User-Agent': 'PicSyncra-installed/2'}), timeout=30) as response:
        raw = response.read(limit + 1)
        if len(raw) > limit: raise ValueError('Manifest modułów jest zbyt duży.')
        return raw


class ModuleReleaseSource:
    def __init__(self, context, *, keys=None, fetch_json=fetch_release_json, fetch_asset=fetch_manifest_asset):
        self.context = context
        self.keys = trusted_release_keys() if keys is None else keys
        self.fetch_json, self.fetch_asset = fetch_json, fetch_asset
        self.offline = False

    def load(self, channel):
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
        except Exception:
            records = cached['records']
            self.offline = True
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
