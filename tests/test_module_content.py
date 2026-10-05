from io import BytesIO
import pytest
from picsyncra.installation.module_content import ModuleContentStore, ModuleContentError
from picsyncra.installation.module_manifest import parse_module_manifest
from picsyncra.installation.module_state import make_module_set, module_set_root, verify_module_set_files
from tests.module_fixtures import module_payload, release_payload
from tests.test_module_state import context


class Response(BytesIO):
    def __init__(self, data, offset, total, status=206):
        super().__init__(data)
        self.status = status
        self.headers = {'Content-Range': f'bytes {offset}-{offset + len(data) - 1}/{total}', 'Content-Length': str(len(data))}


def test_only_missing_ranges_are_fetched_and_unchanged_content_reused(context):
    raw = b'oldnew'
    modules = [module_payload(), module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe'),
               module_payload('ftp', 'picsyncra/services/ftp_service.py', b'new')]
    modules[-1]['files'][0].update(asset_offset=3, asset_size=6)
    release = parse_module_manifest(release_payload(5, modules))
    requests = []
    def fetch(url, start, size, total):
        requests.append((url, start, size, total))
        return Response(raw[start:start + size], start, total)
    store = ModuleContentStore(context, fetch=fetch)
    store.import_bytes(b'code')
    selected = make_module_set(1, 5, release.modules)
    store.assemble(selected)
    verify_module_set_files(context, selected)
    assert len(requests) == 1
    assert requests[0][1:] == (3, 3, 6)
    assert (module_set_root(context, selected) / 'picsyncra/services/ftp_service.py').read_bytes() == b'new'
    requests.clear()
    store.assemble(make_module_set(2, 5, release.modules, frozenset({'ftp'})))
    assert requests == []


@pytest.mark.parametrize('status,data', [(200, b'code'), (206, b'evil')])
def test_full_pack_fallback_and_hash_changes_are_rejected(context, status, data):
    store = ModuleContentStore(context, fetch=lambda url, start, size, total: Response(data, start, total, status))
    selected = make_module_set(1, 5, parse_module_manifest(release_payload()).modules)
    with pytest.raises(ModuleContentError):
        store.assemble(selected)
    assert not (module_set_root(context, selected) / 'module-set.json').exists()


def test_corrupt_local_cache_is_never_reused(context):
    store = ModuleContentStore(context, fetch=lambda *args: Response(b'code', 0, 4))
    digest = store.import_bytes(b'code')
    (context.program_root / 'content' / digest).write_bytes(b'evil')
    assert digest not in store.available_hashes()
