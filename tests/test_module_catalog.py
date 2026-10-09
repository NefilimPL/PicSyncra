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


def test_channel_filters_are_enforced_against_signed_manifest_provenance():
    records=[]; manifests={}; keys={}
    for identifier, channel in ((1,'stable'),(5,'dev')):
        from tests.module_fixtures import module_payload
        payload=release_payload(identifier,[module_payload(source=identifier),
            module_payload('migrator','apps/migrator/PicSyncra-Migrator.exe',source=identifier)])
        payload.update(channel=channel,source_branch='dev2' if channel == 'dev' else 'main',prerelease=channel == 'dev')
        raw, sig, key=signed(payload); keys[str(identifier)]=key
        manifests[identifier]=(raw,sig,str(identifier))
        records.append(dict(id=identifier,tag_name=f'v{identifier}',draft=False,prerelease=channel == 'dev',
            published_at=payload['published_at'],assets=[dict(name='content.bin',size=4)]))
    load=lambda record: manifests[record['id']]
    for channel, identifier in (('stable',1),('dev',5)):
        result=catalog_module_releases(records,channel=channel,manifest_loader=load,trusted_keys=keys)
        assert [entry.release_id for entry in result] == [identifier]
        assert result[0].blocked_reason is None
    records[1]['prerelease']=False
    result=catalog_module_releases(records,channel='stable',manifest_loader=load,trusted_keys=keys)
    assert result[0].blocked_reason == 'manifest_unavailable'
