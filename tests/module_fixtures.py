"""Signed test releases with explicit independent module compatibility."""
import hashlib
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def module_payload(module_id='core', path='picsyncra/data_store.py', content=b'code', *, source=1, api=1, requirements=None):
    item = dict(module_id=module_id, display_version='1.0', api=api,
                requirements=requirements or [], conflicts=[], database_min=1, database_max=10,
                config_min=1, config_max=1, runtime_abi='cp313-win-amd64',
                files=[dict(path=path, sha256=hashlib.sha256(content).hexdigest(), size=len(content),
                            asset_name='content.bin', asset_offset=0, asset_size=len(content))],
                source_release_id=source, source_tag=f'v{source}')
    from picsyncra.installation.module_manifest import module_version_id
    item['version_id'] = module_version_id(item)
    return item


def release_payload(release_id=5, modules=None):
    return dict(schema=2, release_id=release_id, tag=f'v{release_id}', commit='a'*40,
                channel='stable', source_branch='main', prerelease=False, platform='windows-x64',
                minimum_controller=2, minimum_launcher=2, published_at=f'2026-10-{release_id:02}T00:00:00Z',
                modules=modules or [module_payload(), module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe')],
                migrations=[])


def signed(payload):
    key = Ed25519PrivateKey.generate()
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return raw, key.sign(raw), public
