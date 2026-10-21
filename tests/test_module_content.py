from io import BytesIO
import pytest
from picsyncra.installation.module_content import ModuleContentStore, ModuleContentError
from picsyncra.installation.module_manifest import parse_module_manifest
from picsyncra.installation.module_state import make_module_set, module_set_root, verify_module_set_files
from tests.module_fixtures import module_payload, release_payload
from tests.test_module_state import context


def test_new_content_downloads_while_local_seed_is_waiting(context, monkeypatch):
    import threading
    fetched = threading.Event()
    def fetch(url, start, size, total):
        fetched.set()
        return Response(b'new-code', start, total)
    store = ModuleContentStore(context, fetch=fetch)
    store.import_bytes(b'code')
    active = make_module_set(1, 1, parse_module_manifest(release_payload()).modules)
    target = make_module_set(2, 5, parse_module_manifest(release_payload(5,
        [module_payload(content=b'new-code', source=5), module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe')])).modules)
    def slow_seed(*args, **kwargs):
        assert fetched.wait(5), 'download waited for local verification'
    monkeypatch.setattr(store, 'seed', slow_seed)
    store.stage_update(active, target, on_progress=lambda _: None)
    verify_module_set_files(context, target)


def test_planning_inventory_reuses_unchanged_hash_but_transfer_still_verifies(context, monkeypatch):
    from picsyncra.installation import module_content
    store = ModuleContentStore(context)
    digest = store.import_bytes(b'code')
    calls = []
    original = module_content._digest
    monkeypatch.setattr(module_content, '_digest', lambda path: calls.append(path) or original(path))
    with store.inventory_scope():
        assert digest in store.available_hashes()
        assert digest in store.available_hashes()
    assert len(calls) == 1
    module = parse_module_manifest(release_payload()).modules[0]
    store.acquire(module, module.files[0])
    assert len(calls) == 2
    (store.root / digest).write_bytes(b'bad!')
    assert digest not in store.available_hashes()


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


def test_ocr_assembly_keeps_temporary_paths_below_windows_limit(context, monkeypatch):
    from dataclasses import replace
    from pathlib import Path
    import shutil
    from uuid import uuid4
    from picsyncra.installation import module_content

    # Match the reported 229-character destination / 268-character temporary
    # path. Python itself opts into long paths; emulate a controller process
    # without that opt-in at the file creation boundary.
    build_root = (Path.cwd() / 'build').resolve()
    build_root.mkdir(exist_ok=True)
    program = build_root / ('ocr-stage-' + uuid4().hex[:8])
    assert program.resolve().is_relative_to(build_root)
    program.mkdir()
    context = replace(context, program_root=program)
    prefix = program / 'sets' / ('0' * 64) / 'runtime' / 'ocr'
    padding = 198 - len(str(prefix)) - 1
    assert padding > 0
    relative = 'runtime/ocr/' + 'p' * padding + '/cache_grad_op_symbolic_shape.h'
    modules = [module_payload(), module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe'),
               module_payload('ocr_runtime', relative)]
    selected = make_module_set(1, 5, parse_module_manifest(release_payload(5, modules)).modules)
    destination = module_set_root(context, selected) / relative
    assert len(str(destination)) == 229
    assert len(str(destination.with_name('.' + destination.name + '.' + 'a' * 32 + '.part'))) == 268
    original = module_content.shutil.copyfile
    created = []
    def legacy_copy(source, target):
        created.append(Path(target))
        if len(str(target)) >= 260: raise FileNotFoundError(2, 'No such file or directory', str(target))
        return original(source, target)
    monkeypatch.setattr(module_content.shutil, 'copyfile', legacy_copy)
    try:
        store = ModuleContentStore(context, fetch=lambda *args: pytest.fail('verified content must be reused'))
        digest = store.import_bytes(b'code')
        store.assemble(selected)
        verify_module_set_files(context, selected)
        assert destination.read_bytes() == b'code'
        assert all(len(str(path)) < 260 for path in created)
        assert not list(program.rglob('*.part'))
        destination.write_bytes(b'evil')
        assert (store.root / digest).read_bytes() == b'code'
    finally:
        shutil.rmtree(program)


def test_failed_assembly_cleans_scratch_and_retry_reuses_verified_content(context, monkeypatch):
    from pathlib import Path
    from picsyncra.installation import module_content
    store = ModuleContentStore(context, fetch=lambda *args: pytest.fail('must reuse downloaded content'))
    digest = store.import_bytes(b'code')
    selected = make_module_set(1, 5, parse_module_manifest(release_payload()).modules)
    root = module_set_root(context, selected)
    original = module_content.shutil.copyfile
    def interrupted(source, target):
        Path(target).write_bytes(b'co')
        raise OSError('copy interrupted')
    monkeypatch.setattr(module_content.shutil, 'copyfile', interrupted)
    with pytest.raises(OSError, match='copy interrupted'): store.assemble(selected)
    assert not list(root.rglob('*.part'))
    assert not (root / 'module-set.json').exists()
    assert (store.root / digest).read_bytes() == b'code'
    monkeypatch.setattr(module_content.shutil, 'copyfile', original)
    store.assemble(selected)
    verify_module_set_files(context, selected)


def packed_files(context, contents):
    import hashlib
    from dataclasses import replace
    module = parse_module_manifest(release_payload()).modules[0]
    template = module.files[0]
    raw = b''.join(contents)
    files = []
    offset = 0
    for index, content in enumerate(contents):
        files.append(replace(template, path=f'runtime/ocr/header{index}.h', size=len(content),
            sha256=hashlib.sha256(content).hexdigest(), asset_offset=offset, asset_size=len(raw)))
        offset += len(content)
    from picsyncra.installation.module_manifest import module_version_id
    module = replace(module, module_id='ocr_runtime', files=tuple(files))
    return replace(module, version_id=module_version_id(module)), raw


def packed_selection(context, module, store):
    required = parse_module_manifest(release_payload(5, [module_payload(),
        module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe')])).modules
    store.import_bytes(b'code')
    return make_module_set(1, 5, required + (module,))


def test_adjacent_missing_ocr_files_share_one_verified_range_request(context):
    module, raw = packed_files(context, [b'header'+bytes([index]) for index in range(20)])
    calls, progress = [], []
    def fetch(url, start, size, total):
        calls.append((start, size, total))
        return Response(raw[start:start+size], start, total)
    store = ModuleContentStore(context, fetch=fetch)
    selected = packed_selection(context, module, store)
    store.assemble(selected, on_progress=lambda value: progress.append(dict(value)))
    assert calls == [(0, len(raw), len(raw))]
    verify_module_set_files(context, selected)
    assert progress[-1]['downloaded_bytes'] == progress[-1]['total_bytes'] == len(raw)


def test_batched_ranges_do_not_download_cached_gaps_and_deduplicate_hashes(context):
    from dataclasses import replace
    module, raw = packed_files(context, [b'first', b'cached', b'third', b'fourth'])
    module = replace(module, files=module.files + (replace(module.files[0], path='runtime/ocr/same.h'),))
    from picsyncra.installation.module_manifest import module_version_id
    module = replace(module, version_id=module_version_id(module))
    calls = []
    def fetch(url, start, size, total):
        calls.append((start, size))
        return Response(raw[start:start+size], start, total)
    store = ModuleContentStore(context, fetch=fetch)
    store.import_bytes(b'cached')
    selected = packed_selection(context, module, store)
    store.assemble(selected)
    assert calls == [(0, 5), (11, 11)]
    verify_module_set_files(context, selected)


def test_batch_retry_reuses_verified_prefix_and_discards_interrupted_file(context):
    module, raw = packed_files(context, [b'first', b'second', b'third'])
    calls, waits = [], []
    class Interrupted(Response):
        def read(self, size=-1):
            if self.tell() >= 5: raise ConnectionResetError('interrupted')
            return super().read(size)
    def fetch(url, start, size, total):
        calls.append((start, size))
        return (Interrupted if len(calls)==1 else Response)(raw[start:start+size], start, total)
    store = ModuleContentStore(context, fetch=fetch, sleep=waits.append)
    selected = packed_selection(context, module, store)
    progress = []
    store.assemble(selected, on_progress=lambda value: progress.append(dict(value)))
    assert calls == [(0, len(raw)), (5, len(raw)-5)]
    assert waits == [1]
    assert not list(store.root.glob('*.part'))
    assert progress[-1]['downloaded_bytes'] == len(raw)
    verify_module_set_files(context, selected)


def test_bad_file_in_batch_cannot_be_published_or_activate_a_set(context):
    module, raw = packed_files(context, [b'first', b'second', b'third'])
    corrupted = raw[:5] + b'xxxxxx' + raw[11:]
    calls = []
    def fetch(url, start, size, total):
        calls.append((start, size))
        return Response(corrupted[start:start+size], start, total)
    store = ModuleContentStore(context, fetch=fetch)
    selected = packed_selection(context, module, store)
    with pytest.raises(ModuleContentError) as caught: store.assemble(selected)
    assert caught.value.details['code'] == 'hash_mismatch'
    assert caught.value.details['file'] == module.files[1].path
    assert calls == [(0, len(raw))]
    assert (store.root / module.files[0].sha256).read_bytes() == b'first'
    assert not (store.root / module.files[1].sha256).exists()
    assert not (module_set_root(context, selected) / 'module-set.json').exists()
    assert not list(store.root.glob('*.part'))


def test_batches_respect_size_and_count_limits_and_release_boundaries(context, monkeypatch):
    from dataclasses import replace
    from picsyncra.installation import module_content
    module, raw = packed_files(context, [b'first', b'second', b'third', b'fourth'])
    calls = []
    def fetch(url, start, size, total):
        calls.append((url, start, size))
        return Response(raw[start:start+size], start, total)
    store = ModuleContentStore(context, fetch=fetch)
    monkeypatch.setattr(module_content, '_RANGE_BATCH_BYTES', 12)
    monkeypatch.setattr(module_content, '_RANGE_BATCH_FILES', 2)
    store.assemble(packed_selection(context, module, store))
    assert [(start,size) for _,start,size in calls] == [(0,11), (11,11)]
    # Adjacent offsets from different tags/assets must remain independent.
    entries = [(module, module.files[0]), (replace(module, source_tag='v2'), module.files[1])]
    assert len(list(module_content._range_batches(entries))) == 2
    entries = [(module, module.files[0]), (module, replace(module.files[1], asset_name='other.bin'))]
    assert len(list(module_content._range_batches(entries))) == 2


@pytest.mark.parametrize('kind', ['status', 'range', 'length', 'trailing'])
def test_batch_rejects_unconfirmed_or_overlong_ranges_before_activation(context, kind):
    module, raw = packed_files(context, [b'first', b'second'])
    def fetch(url, start, size, total):
        response = Response(raw + (b'extra' if kind=='trailing' else b''), start, total)
        response.headers.update({'Content-Length':str(size), 'Content-Range':f'bytes {start}-{start+size-1}/{total}'})
        if kind=='status': response.status=200
        if kind=='range': response.headers['Content-Range']='bytes 1-2/3'
        if kind=='length': response.headers['Content-Length']=str(size+1)
        return response
    store = ModuleContentStore(context, fetch=fetch)
    selected = packed_selection(context, module, store)
    with pytest.raises(ModuleContentError): store.assemble(selected)
    assert not (module_set_root(context, selected)/'module-set.json').exists()
    assert not (store.root/module.files[-1].sha256).exists()
    assert not list(store.root.glob('*.part'))
