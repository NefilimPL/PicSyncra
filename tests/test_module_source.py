import json
import socket
import ssl
from urllib.error import HTTPError, URLError
import pytest
from picsyncra.installation.module_source import ModuleReleaseSource, MANIFEST_NAME
from tests.test_module_state import context
from tests.module_fixtures import signed, release_payload


def test_verified_snapshot_avoids_repeated_network_but_invalidates_changed_cache(context):
    calls = []
    source = ModuleReleaseSource(context, keys={}, fetch_json=lambda path: calls.append(path) or [])
    source.load('dev')
    source.snapshot('dev')
    source.snapshot('dev')
    assert len(calls) == 1
    (context.state_root / 'module-catalog-dev.json').write_text('{"records":[],"manifests":{},"changed":true}')
    source.snapshot('dev')
    assert len(calls) == 2
    source.load('dev')
    assert len(calls) == 3


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


@pytest.mark.parametrize('failure,code,fragment', [
    (HTTPError('https://api.github.com', 403, 'Forbidden', {'X-RateLimit-Remaining':'0'}, None), 'rate_limit', 'limit'),
    (HTTPError('https://api.github.com', 429, 'Too Many Requests', {}, None), 'rate_limit', 'limit'),
    (HTTPError('https://api.github.com', 500, 'Server Error', {}, None), 'http_error', '500'),
    (URLError(ssl.SSLCertVerificationError('certificate')), 'certificate_error', 'certyfikat'),
    (URLError(socket.gaierror('DNS')), 'dns_error', 'DNS'),
    (TimeoutError('timed out'), 'timeout', 'czas'),
    (OSError('potentially sensitive proxy details'), 'connection_error', 'połączenia'),
])
def test_offline_catalog_reports_cause_and_clears_it_after_success(context, failure, code, fragment):
    def fail(path): raise failure
    source=ModuleReleaseSource(context, keys={}, fetch_json=fail)
    assert source.load('dev') == ()
    assert source.offline is True
    assert source.error['code'] == code
    assert fragment in source.error['message']
    assert 'sensitive' not in source.error['message']
    source.fetch_json=lambda path: []
    assert source.load('dev') == ()
    assert source.offline is False and source.error is None
