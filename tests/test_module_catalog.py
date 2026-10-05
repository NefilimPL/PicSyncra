from picsyncra.installation.module_catalog import catalog_module_releases
from tests.module_fixtures import release_payload, signed


def test_catalog_blocks_incomplete_source_assets_and_uses_publication_order():
    records = [dict(id=5, tag_name='v5', draft=False, prerelease=False,
                    published_at='2026-10-05T00:00:00Z', assets=[]),
               dict(id=1, tag_name='v1', draft=False, prerelease=False,
                    published_at='2026-10-01T00:00:00Z',
                    assets=[dict(name='content.bin', size=4)])]
    raw, sig, key = signed(release_payload())
    def load(record):
        if record['id'] == 1:
            raise ValueError('Legacy release')
        return raw, sig, 'test'
    result = catalog_module_releases(records, channel='stable', manifest_loader=load, trusted_keys={'test': key})
    assert result[0].release.release_id == 5
    assert result[1].blocked_reason == 'manifest_unavailable'
    records[1]['assets'] = []
    result = catalog_module_releases(records, channel='stable', manifest_loader=load, trusted_keys={'test': key})
    assert result[0].blocked_reason == 'content_unavailable'
