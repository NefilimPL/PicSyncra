import json
from picsyncra.installation.module_source import ModuleReleaseSource, MANIFEST_NAME
from tests.test_module_state import context
from tests.module_fixtures import signed, release_payload


def test_offline_catalog_reverifies_signature(context):
    raw, signature, key = signed(release_payload())
    names = {MANIFEST_NAME: raw, MANIFEST_NAME + '.sig': signature, MANIFEST_NAME + '.key-id': b'test'}
    records = [dict(id=5, tag_name='v5', published_at='2026-10-05T00:00:00Z', draft=False, prerelease=False,
                    assets=[dict(name=name, browser_download_url='https://github.com/NefilimPL/PicSyncra/releases/download/v5/' + name) for name in names]),
               dict(id=1, tag_name='v1', draft=False, prerelease=False, assets=[dict(name='content.bin', size=4)])]
    source = ModuleReleaseSource(context, keys={'test': key}, fetch_json=lambda path: records,
                                 fetch_asset=lambda url: names[url.rsplit('/', 1)[1]])
    assert source.load('stable')[0].blocked_reason is None
    source.fetch_json = lambda path: (_ for _ in ()).throw(OSError('offline'))
    assert any(entry.release and not entry.blocked_reason for entry in source.load('stable'))
    assert source.offline
    path = context.state_root / 'module-catalog-stable.json'
    cached = json.loads(path.read_text())
    cached['manifests']['5']['signature'] = 'AAAA'
    path.write_text(json.dumps(cached))
    assert all(entry.blocked_reason for entry in source.load('stable'))
