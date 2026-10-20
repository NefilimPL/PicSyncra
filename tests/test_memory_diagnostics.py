import json
from types import SimpleNamespace

import pytest

from picsyncra import memory_diagnostics as diagnostics


class Process:
    pid = 123

    def name(self):
        return 'PicSyncra-WEB.exe'

    def ppid(self):
        return 100

    def create_time(self):
        return 1000.0

    def memory_info(self):
        return SimpleNamespace(rss=2000, vms=3000, private=2500)

    def num_threads(self):
        return 4

    def num_handles(self):
        return 17

    def children(self, recursive=False):
        return [ChildProcess()]

    def memory_maps(self, grouped=True):
        return [SimpleNamespace(path=r'C:\private\user\library.dll', rss=1000, private=700)]


class ChildProcess(Process):
    pid = 124

    def name(self):
        return 'PicSyncra-OCR.exe'

    def ppid(self):
        return 123


def reporter(tmp_path, **kwargs):
    return diagnostics.MemoryReporter(tmp_path, 'backend', process=Process(), **kwargs)


def records(tmp_path):
    return [json.loads(line) for path in tmp_path.glob('*.jsonl')
            for line in path.read_text(encoding='utf-8').splitlines()]


def test_records_each_process_and_reports_native_memory_separately(tmp_path):
    monitor = reporter(tmp_path, context=lambda: {'ocr_runs': 51})
    monitor.sample_once()
    record = records(tmp_path)[0]
    assert record['role'] == 'backend'
    assert record['schema'] == 1
    assert record['version']
    assert [item['pid'] for item in record['processes']] == [123, 124]
    assert record['processes'][0]['private_bytes'] == 2500
    assert record['processes'][0]['handles'] == 17
    assert record['application'] == {'ocr_runs': 51}
    assert record['details']['memory_maps'][0]['path'] == 'library.dll'
    assert 'private\\user' not in json.dumps(record)


def test_details_are_periodic_and_growth_triggers_an_early_snapshot(tmp_path):
    now = [0.0]
    monitor = reporter(tmp_path, clock=lambda: now[0], details_interval=600)
    first = monitor.sample_once()
    now[0] = 60
    second = monitor.sample_once()
    assert first['details']
    assert 'details' not in second
    monitor.process.memory_info = lambda: SimpleNamespace(rss=40_000_000, vms=50_000_000, private=40_000_000)
    now[0] = 120
    assert monitor.sample_once()['details']


def test_one_inaccessible_child_does_not_lose_parent_or_other_samples(tmp_path):
    class Inaccessible(ChildProcess):
        def memory_info(self):
            raise diagnostics.psutil.AccessDenied(self.pid)
    monitor = reporter(tmp_path)
    monitor.process.children = lambda recursive: [Inaccessible()]
    record = monitor.sample_once()
    assert record['processes'][0]['rss_bytes'] == 2000
    assert record['processes'][1]['error'] == 'AccessDenied'
    assert records(tmp_path)


def test_rotation_bounds_files_and_each_line_is_complete_json(tmp_path):
    monitor = reporter(tmp_path, max_bytes=2500, backups=2)
    for _ in range(25):
        monitor.sample_once()
    paths = list(tmp_path.iterdir())
    assert len(paths) <= 3
    assert any(path.name.endswith('.1') for path in paths)
    for path in paths:
        for line in path.read_text(encoding='utf-8').splitlines():
            assert json.loads(line)['pid'] == 123


def test_python_details_include_source_and_growth_without_payloads(tmp_path):
    import tracemalloc
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start(1)
    try:
        monitor = reporter(tmp_path, details_interval=0)
        monitor.sample_once()
        retained = [bytearray(8192) for _ in range(100)]
        record = monitor.sample_once()
        python = record['details']['python']
        assert python['traced_bytes'] > 0
        assert python['tracer_bytes'] > 0
        assert any('test_memory_diagnostics.py' in item['source'] and item['bytes'] >= 819200
                   for item in python['top_allocations'])
        assert any(item['bytes_diff'] > 0 for item in python['growth'])
        assert len(retained) == 100
    finally:
        if not was_tracing:
            tracemalloc.stop()


def test_stop_wakes_worker_without_waiting_a_minute(tmp_path):
    import threading
    monitor = reporter(tmp_path)
    sampled = threading.Event()
    original = monitor.sample_once
    def sample():
        result = original()
        sampled.set()
        return result
    monitor.sample_once = sample
    monitor.start()
    try:
        assert sampled.wait(5)
    finally:
        monitor.stop()
    assert not monitor.thread.is_alive()


def test_explicit_disable_prevents_frozen_reporting(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics.sys, 'frozen', True, raising=False)
    monkeypatch.setenv('PICSYNCRA_MEMORY_REPORT', '0')
    assert diagnostics.start_memory_reporting('backend', directory=tmp_path) is None
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('frozen', [False, True])
def test_reporting_is_off_by_default_for_source_and_frozen_builds(monkeypatch, tmp_path, frozen):
    monkeypatch.setattr(diagnostics.sys, 'frozen', frozen, raising=False)
    monkeypatch.delenv('PICSYNCRA_MEMORY_REPORT', raising=False)
    calls = []
    monkeypatch.setattr(diagnostics.tracemalloc, 'start', lambda _: calls.append('trace'))
    monkeypatch.setattr(diagnostics, 'MemoryReporter', lambda *args, **kwargs: calls.append('reporter'))
    assert diagnostics.start_memory_reporting('backend', directory=tmp_path / 'reports') is None
    assert not calls
    assert not (tmp_path / 'reports').exists()


@pytest.mark.parametrize('frozen', [False, True])
def test_reporting_can_be_explicitly_enabled_in_either_build(monkeypatch, tmp_path, frozen):
    monkeypatch.setattr(diagnostics.sys, 'frozen', frozen, raising=False)
    monkeypatch.setenv('PICSYNCRA_MEMORY_REPORT', '1')
    monkeypatch.setenv('PICSYNCRA_MEMORY_TRACE', '0')
    monkeypatch.delenv('PICSYNCRA_MEMORY_REPORT_DIR', raising=False)
    monkeypatch.setattr(diagnostics, '_reporter', None)
    monitor = diagnostics.start_memory_reporting('backend', directory=tmp_path)
    try:
        assert monitor is not None
        assert monitor.thread.is_alive()
    finally:
        if monitor is not None:
            monitor.stop()


def test_source_runs_require_explicit_enable(monkeypatch, tmp_path):
    monkeypatch.delattr(diagnostics.sys, 'frozen', raising=False)
    monkeypatch.delenv('PICSYNCRA_MEMORY_REPORT', raising=False)
    assert diagnostics.start_memory_reporting('backend', directory=tmp_path) is None


def test_frozen_source_names_keep_module_paths_without_user_profile():
    assert diagnostics._source_name('picsyncra/web/app.py') == 'picsyncra/web/app.py'
    assert diagnostics._source_name(r'C:\Users\private\PicSyncra\picsyncra\web\app.py') == 'picsyncra/web/app.py'


def test_relative_frozen_diagnostic_allocations_are_excluded(tmp_path):
    import tracemalloc
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start(1)
    try:
        namespace = {}
        exec(compile('retained = [bytearray(4096) for _ in range(64)]',
                     'picsyncra/memory_diagnostics.py', 'exec'), namespace)
        record = reporter(tmp_path).sample_once()
        assert not any(item['source'].startswith('picsyncra/memory_diagnostics.py:')
                       for item in record['details']['python']['top_allocations'])
        assert len(namespace['retained']) == 64
    finally:
        if not was_tracing:
            tracemalloc.stop()


def test_context_failure_is_recorded_without_aborting_metrics(tmp_path):
    def broken():
        raise RuntimeError('secret configuration')
    record = reporter(tmp_path, context=broken).sample_once()
    assert record['application_error'] == 'RuntimeError'
    assert 'secret configuration' not in json.dumps(record)


def test_cleanup_removes_old_reports_but_preserves_unrelated_logs(tmp_path):
    import os
    old = tmp_path / 'memory-backend-999-20000101.jsonl'
    old.write_text('{}\n')
    os.utime(old, (1, 1))
    unrelated = tmp_path / 'error.log'
    unrelated.write_text('keep')
    reporter(tmp_path).sample_once()
    assert not old.exists()
    assert unrelated.read_text() == 'keep'


def test_reporter_does_not_grow_its_allocation_baseline_without_bound(tmp_path):
    import tracemalloc
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start(1)
    try:
        monitor = reporter(tmp_path, details_interval=0)
        for _ in range(5):
            monitor.sample_once()
        assert len(monitor._previous_allocations) <= 4096
        assert all(not item['source'].startswith('picsyncra/memory_diagnostics.py:')
                   for item in records(tmp_path)[-1]['details']['python']['top_allocations'])
    finally:
        if not was_tracing:
            tracemalloc.stop()


def test_automatic_start_is_idempotent_and_inherits_report_directory(monkeypatch, tmp_path):
    monkeypatch.setenv('PICSYNCRA_MEMORY_REPORT', '1')
    monkeypatch.setenv('PICSYNCRA_MEMORY_TRACE', '0')
    monkeypatch.delenv('PICSYNCRA_MEMORY_REPORT_DIR', raising=False)
    monkeypatch.setattr(diagnostics, '_reporter', None)
    monitor = diagnostics.start_memory_reporting('backend', directory=tmp_path)
    try:
        assert diagnostics.start_memory_reporting('application', context=lambda: {'jobs': 3}) is monitor
        assert monitor.context() == {'jobs': 3}
        assert diagnostics.os.environ['PICSYNCRA_MEMORY_REPORT_DIR'] == str(tmp_path.resolve())
    finally:
        monitor.stop()


def test_directory_override_applies_to_desktop_bootstrap_defaults(monkeypatch, tmp_path):
    preferred = tmp_path / 'chosen'
    monkeypatch.setenv('PICSYNCRA_MEMORY_REPORT', '1')
    monkeypatch.setenv('PICSYNCRA_MEMORY_TRACE', '0')
    monkeypatch.setenv('PICSYNCRA_MEMORY_REPORT_DIR', str(preferred))
    monkeypatch.setattr(diagnostics, '_reporter', None)
    monitor = diagnostics.start_memory_reporting('application', directory=tmp_path / 'default')
    try:
        assert monitor.directory == preferred
    finally:
        monitor.stop()


def test_failed_reporter_start_releases_only_its_own_tracer(monkeypatch, tmp_path):
    operations = []
    monkeypatch.setenv('PICSYNCRA_MEMORY_REPORT', '1')
    monkeypatch.setenv('PICSYNCRA_MEMORY_TRACE', '1')
    monkeypatch.delenv('PICSYNCRA_MEMORY_REPORT_DIR', raising=False)
    monkeypatch.setattr(diagnostics, '_reporter', None)
    monkeypatch.setattr(diagnostics.tracemalloc, 'is_tracing', lambda: False)
    monkeypatch.setattr(diagnostics.tracemalloc, 'start', lambda _: operations.append('start'))
    monkeypatch.setattr(diagnostics.tracemalloc, 'stop', lambda: operations.append('stop'))
    def failed(*args, **kwargs):
        raise OSError('cannot create reporter')
    monkeypatch.setattr(diagnostics, 'MemoryReporter', failed)
    assert diagnostics.start_memory_reporting('backend', directory=tmp_path) is None
    assert operations == ['start', 'stop']


def test_ocr_counter_snapshot_keeps_payloads_private():
    from picsyncra.services.ocr_progress import OcrProgressRegistry
    registry = OcrProgressRegistry()
    run = registry.create_run(kind='queue', job_id='private-job')
    registry.publish(run, 'result', text='private OCR text')
    registry.finalize(run, state='completed', result={'text': 'private OCR text'})
    assert registry.diagnostic_counts() == {
        'ocr_retained_runs': 1, 'ocr_retained_events': 1, 'ocr_retained_results': 1,
    }


def test_tracer_budget_stops_own_tracing_but_continues_process_metrics(monkeypatch, tmp_path):
    stopped = []
    monkeypatch.setattr(diagnostics.tracemalloc, 'is_tracing', lambda: not stopped)
    monkeypatch.setattr(diagnostics.tracemalloc, 'get_tracemalloc_memory', lambda: 65 * 1024 * 1024)
    monkeypatch.setattr(diagnostics.tracemalloc, 'stop', lambda: stopped.append(True))
    monitor = reporter(tmp_path)
    monitor.owns_tracer = True
    record = monitor.sample_once()
    assert stopped == [True]
    assert record['tracing_disabled_reason'] == 'tracer_budget_exceeded_64_mib'
    assert record['processes'][0]['private_bytes'] == 2500
    assert not record['details']['python']['enabled']


def test_frozen_report_includes_its_own_bootloader_not_an_unrelated_parent(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics.sys, 'frozen', True, raising=False)
    parent = ChildProcess()
    parent.exe = lambda: r'C:\PicSyncra\PicSyncra-WEB.exe'
    monitor = reporter(tmp_path)
    monitor.process.exe = lambda: r'C:\PicSyncra\PicSyncra-WEB.exe'
    monitor.process.parent = lambda: parent
    processes = monitor.sample_once()['processes']
    assert processes[-1]['relationship'] == 'parent_bootloader'
    parent.exe = lambda: r'C:\Windows\explorer.exe'
    assert len(monitor.sample_once()['processes']) == 2


def test_backend_context_counts_ocr_and_caches_without_exporting_values(monkeypatch):
    from picsyncra.web import app as web
    monkeypatch.setattr(web, '_resource_monitor_context', lambda: {'active_clients': 0})
    monkeypatch.setattr(web, '_PROCESS_JOBS', {'secret-job': {'ean': 'private-product'}})
    monkeypatch.setattr(web, '_UPLOAD_SCAN_RESULTS', {'secret-file': {'text': 'private-text'}})
    monkeypatch.setattr(web, '_OCR_EXECUTION_SERVICE', SimpleNamespace(
        diagnostic_counts=lambda: {'ocr_retained_runs': 17}))
    result = web._memory_diagnostic_context()
    assert result['retained_process_jobs'] == 1
    assert result['upload_scan_results'] == 1
    assert result['ocr_retained_runs'] == 17
    assert 'private' not in json.dumps(result)
    assert 'secret' not in json.dumps(result)
