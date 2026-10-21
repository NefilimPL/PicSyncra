import copy
import pytest
from picsyncra.installation.module_manifest import parse_module_manifest, verify_module_manifest, module_version_id
from picsyncra.installation.release_manifest import ManifestError
from tests.module_fixtures import module_payload, release_payload, signed


def test_signed_manifest_retains_module_provenance():
    raw, signature, key = signed(release_payload())
    parsed = verify_module_manifest(raw, signature, {'test': key}, key_id='test')
    assert parsed.release_id == 5
    assert parsed.modules[0].source_release_id == 1
    assert parsed.modules[0].source_tag == 'v1'
    with pytest.raises(ManifestError):
        verify_module_manifest(raw + b' ', signature, {'test': key}, key_id='test')


def test_transport_provenance_does_not_change_module_identity():
    first = module_payload()
    second = copy.deepcopy(first)
    second.update(source_release_id=5, source_tag='v5', display_version='other label')
    second['files'][0].update(asset_name='part-2.bin', asset_offset=200, asset_size=1000)
    assert module_version_id(second) == first['version_id']
    second['api'] = 2
    assert module_version_id(second) != first['version_id']


@pytest.mark.parametrize('mutate', [
    lambda p: p['modules'][0].pop('database_max'),
    lambda p: p['modules'][0].update(api=True),
    lambda p: p['modules'].append(copy.deepcopy(p['modules'][0])),
    lambda p: p['modules'][0]['files'][0].update(path='../unsafe'),
    lambda p: p['modules'][0]['files'][0].update(path='//server/share'),
    lambda p: p['modules'][0]['files'][0].update(asset_offset=10000),
    lambda p: p['modules'][0].update(version_id='b'*64),
    lambda p: p.update(channel='dev'),
    lambda p: p['modules'][0].update(module_id='unknown'),
    lambda p: p.update(published_at='not-a-date'),
])
def test_incomplete_or_unsafe_manifests_are_rejected(mutate):
    payload = release_payload()
    mutate(payload)
    with pytest.raises(ManifestError):
        parse_module_manifest(payload)


def test_case_collision_and_false_file_ownership_are_rejected():
    payload = release_payload()
    payload['modules'][0]['files'].append(dict(payload['modules'][0]['files'][0], path='picsyncra/DATA_STORE.py'))
    payload['modules'][0]['version_id'] = module_version_id(payload['modules'][0])
    with pytest.raises(ManifestError):
        parse_module_manifest(payload)
    payload = release_payload()
    payload['modules'][0]['files'][0]['path'] = 'picsyncra/services/ftp_service.py'
    payload['modules'][0]['version_id'] = module_version_id(payload['modules'][0])
    with pytest.raises(ManifestError):
        parse_module_manifest(payload)


def test_unknown_key_and_duplicate_json_fields_are_rejected():
    raw, signature, key = signed(release_payload())
    with pytest.raises(ManifestError):
        verify_module_manifest(raw, signature, {}, key_id='test')
    with pytest.raises(ManifestError):
        parse_module_manifest(dict(release_payload(), unexpected=True))
