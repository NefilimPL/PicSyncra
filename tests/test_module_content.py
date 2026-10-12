from io import BytesIO
import pytest
from picsyncra.installation.module_content import ModuleContentStore, ModuleContentError
from picsyncra.installation.module_manifest import parse_module_manifest
from picsyncra.installation.module_state import make_module_set, module_set_root, verify_module_set_files
from tests.module_fixtures import module_payload, release_payload
from tests.test_module_state import context


def test_transient_http_failure_is_retried_and_only_verified_files_are_reused(context):
    from urllib.error import HTTPError
    calls, waits = [], []
    def fetch(url, start, size, total):
        calls.append((start, size))
        if len(calls) == 1: raise HTTPError(url, 503, 'temporary', {}, None)
        return Response(b'code', start, total)
    store = ModuleContentStore(context, fetch=fetch, sleep=waits.append)
    module = parse_module_manifest(release_payload()).modules[0]
    assert store.acquire(module, module.files[0]).read_bytes() == b'code'
    assert len(calls) == 2 and waits == [1]
    store.acquire(module, module.files[0])
    assert len(calls) == 2


def test_exhausted_http_failure_has_bounded_diagnostics_and_no_partial_cache(context):
    from urllib.error import HTTPError
    calls = []
    def fetch(url, *args):
        calls.append(url)
        raise HTTPError(url, 429, 'secret-proxy-credential', {'Retry-After':'2'}, None)
    waits = []
    store = ModuleContentStore(context, fetch=fetch, sleep=waits.append)
    module = parse_module_manifest(release_payload()).modules[0]
    with pytest.raises(ModuleContentError) as caught: store.acquire(module, module.files[0])
    details = caught.value.details
    assert details['code'] == 'http_error' and details['http_status'] == 429
    assert details['attempts'] == 3 and details['retryable'] is True
    assert details['module_id'] == 'core' and details['file'] == 'picsyncra/data_store.py'
    assert details['source_tag'] == 'v1'
    assert 'secret' not in str(caught.value) and 'secret' not in str(details)
    assert len(calls) == 3 and waits == [2, 2]
    assert list(store.root.iterdir()) == []


def test_bad_hash_is_diagnosed_without_retry_or_accepting_content(context):
    calls = []
    def fetch(url, start, size, total):
        calls.append(url)
        return Response(b'evil', start, total)
    store = ModuleContentStore(context, fetch=fetch, sleep=lambda delay: pytest.fail('must not retry a bad hash'))
    module = parse_module_manifest(release_payload()).modules[0]
    with pytest.raises(ModuleContentError) as caught: store.acquire(module, module.files[0])
    assert caught.value.details['code'] == 'hash_mismatch'
    assert caught.value.details['retryable'] is False
    assert len(calls) == 1 and not list(store.root.iterdir())


def test_cache_permission_failure_identifies_operation_without_network_retry(context, monkeypatch):
    from pathlib import Path
    store = ModuleContentStore(context, fetch=lambda url, start, size, total: Response(b'code', start, total),
        sleep=lambda _: pytest.fail('permanent permission failure must not restart the download'))
    original = Path.open
    def open_file(path, *args, **kwargs):
        if path.suffix == '.part':
            error = PermissionError(13, 'private Windows path')
            error.winerror = 5
            raise error
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', open_file)
    module = parse_module_manifest(release_payload()).modules[0]
    with pytest.raises(ModuleContentError) as caught: store.acquire(module, module.files[0])
    details = caught.value.details
    assert details['code'] == 'permission_denied' and details['system_code'] == 5
    assert details['operation'] == 'create_cache_file'
    assert details['storage'] == 'content_cache'
    assert details['attempts'] == 1 and details['retryable'] is False
    assert 'private Windows path' not in str(details)


def test_errno_io_failure_is_not_mistaken_for_windows_access_denial():
    import errno
    from picsyncra.installation.module_download_diagnostics import download_failure
    details = download_failure(OSError(errno.EIO, 'private local path'))
    assert details['code'] == 'local_io_error'
    assert details['retryable'] is False


def test_retry_after_interrupted_read_resets_progress_and_discards_partial_bytes(context):
    calls, progress = [], []
    class Interrupted(Response):
        def read(self, size=-1):
            if self.tell(): raise ConnectionResetError(10054, 'private connection detail')
            return super().read(2)
    def fetch(url, start, size, total):
        calls.append(url)
        return Interrupted(b'code', start, total) if len(calls) == 1 else Response(b'code', start, total)
    store = ModuleContentStore(context, fetch=fetch, sleep=lambda delay: None)
    module = parse_module_manifest(release_payload()).modules[0]
    assert store.acquire(module, module.files[0], on_progress=progress.append).read_bytes() == b'code'
    assert progress == [2, 0, 4]
    assert len(calls) == 2


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


def test_progress_counts_only_unique_missing_content_and_reports_chunks(context):
    modules = [module_payload(), module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe'),
               module_payload('ftp', 'picsyncra/services/ftp_service.py', b'new'),
               module_payload('sql', 'picsyncra/services/sql_service.py', b'new')]
    class ChunkedResponse(Response):
        def read(self, size=-1): return super().read(min(size, 1))
    requests = []
    def fetch(url, start, size, total):
        requests.append(url)
        return ChunkedResponse(b'new', start, total)
    store = ModuleContentStore(context, fetch=fetch)
    store.import_bytes(b'code')
    selected = make_module_set(1, 5, parse_module_manifest(release_payload(5, modules)).modules)
    progress = []
    store.assemble(selected, on_progress=lambda value: progress.append(dict(value)))
    assert len(requests) == 1
    assert progress[0]['downloaded_bytes'] == 0
    assert {item['total_bytes'] for item in progress} == {3}
    assert [item['downloaded_bytes'] for item in progress] == [0, 1, 2, 3]
    assert progress[-1]['module_id'] == 'ftp'
    assert progress[-1]['module_downloaded_bytes'] == progress[-1]['module_total_bytes'] == 3
    verify_module_set_files(context, selected)


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
