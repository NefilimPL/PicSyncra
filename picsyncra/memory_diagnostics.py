"""Bounded, local memory reports for long-running frozen application processes.

No object contents, command lines, credentials, or configuration are collected.
Python allocation tracing cannot attribute allocations made inside native OCR
libraries; OS private memory and memory maps provide complementary evidence.
"""

from __future__ import annotations

import atexit
from datetime import datetime, timezone
import gc
import json
import os
from pathlib import Path
import platform
import re
import sys
import threading
import time
import tracemalloc
from typing import Callable

import psutil


MIB = 1024 * 1024
_reporter: MemoryReporter | None = None
_lifecycle_lock = threading.RLock()


def _source_name(filename: str) -> str:
    normalized = filename.replace('\\', '/')
    if normalized.startswith('picsyncra/'):
        return normalized
    if '/picsyncra/' in normalized:
        return 'picsyncra/' + normalized.rsplit('/picsyncra/', 1)[1]
    if '/site-packages/' in normalized:
        return normalized.rsplit('/site-packages/', 1)[1]
    return normalized.rsplit('/', 1)[-1]


class MemoryReporter:
    """Persist minute samples and occasional allocation details, without history in RAM."""

    def __init__(
        self, directory: Path, role: str, *, process=None,
        context: Callable[[], dict[str, int]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        interval: float = 60, details_interval: float = 600,
        max_bytes: int = 4 * MIB, backups: int = 2,
    ):
        self.directory = Path(directory)
        self.role = re.sub(r'[^a-zA-Z0-9_-]', '_', role)[:40]
        self.process = process if process is not None else psutil.Process()
        self.context = context
        self.clock = clock
        self.interval = max(1, interval)
        self.details_interval = details_interval
        self.max_bytes = max_bytes
        self.backups = backups
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        self.path = self.directory / f'memory-{self.role}-{self.process.pid}-{stamp}.jsonl'
        self.started_at = clock()
        self._last_details_at: float | None = None
        self._last_details_memory = 0
        self._previous_allocations: dict[str, tuple[int, int]] = {}
        self._baseline_truncated = False
        self._tracing_disabled_reason = ''
        self.owns_tracer = False
        self._last_cleanup_at: float | None = None
        self._sample_lock = threading.Lock()
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name='PicSyncra-memory-report', daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()
        if self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(timeout=5)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.sample_once()
            except Exception:
                # A diagnostic failure must not interrupt the application or spin.
                pass
            self._stop.wait(self.interval)

    @staticmethod
    def _process_sample(process):
        record = {'pid': process.pid}
        try:
            memory = process.memory_info()
            record.update(
                name=process.name(), ppid=process.ppid(), created_at=process.create_time(),
                rss_bytes=memory.rss, virtual_bytes=memory.vms,
                threads=process.num_threads(),
            )
            record['private_bytes'] = getattr(memory, 'private', None)
            if hasattr(process, 'num_handles'):
                record['handles'] = process.num_handles()
        except (psutil.Error, OSError) as exc:
            record['error'] = type(exc).__name__
        return record

    def sample_once(self):
        with self._sample_lock:
            return self._sample_once()

    def _sample_once(self):
        started = self.clock()
        record = {
            'schema': 1, 'at': datetime.now(timezone.utc).isoformat(),
            'pid': self.process.pid, 'role': self.role,
            'version': self._version(), 'python': platform.python_version(),
            'platform': platform.system(), 'frozen': bool(getattr(sys, 'frozen', False)),
            'uptime_seconds': round(started - self.started_at, 3),
            'processes': [self._process_sample(self.process)],
            'gc_counts': gc.get_count(), 'gc_stats': gc.get_stats(),
        }
        try:
            record['processes'].extend(self._process_sample(child)
                                       for child in self.process.children(recursive=True))
        except (psutil.Error, OSError) as exc:
            record['children_error'] = type(exc).__name__
        if getattr(sys, 'frozen', False):
            try:
                # In onefile builds the bootloader is the app's parent. Do not
                # include the unrelated shell or service that launched the EXE.
                parent = self.process.parent()
                if parent is not None and parent.exe().casefold() == self.process.exe().casefold():
                    bootloader = self._process_sample(parent)
                    bootloader['relationship'] = 'parent_bootloader'
                    record['processes'].append(bootloader)
            except (psutil.Error, OSError) as exc:
                record['bootloader_error'] = type(exc).__name__
        host = psutil.virtual_memory()
        record['host_memory'] = {'total_bytes': host.total, 'available_bytes': host.available}
        if self.context is not None:
            try:
                # Only numeric counters cross this boundary; never object values.
                record['application'] = {str(key): value for key, value in self.context().items()
                                         if isinstance(value, (int, float, bool))}
            except Exception as exc:
                record['application_error'] = type(exc).__name__
        own = record['processes'][0]
        if self.owns_tracer and tracemalloc.is_tracing() and tracemalloc.get_tracemalloc_memory() > 64 * MIB:
            tracemalloc.stop()
            self._previous_allocations.clear()
            self._tracing_disabled_reason = 'tracer_budget_exceeded_64_mib'
        if self._tracing_disabled_reason:
            record['tracing_disabled_reason'] = self._tracing_disabled_reason
        memory = own.get('private_bytes') or own.get('rss_bytes') or 0
        detailed = (self._last_details_at is None
                    or started - self._last_details_at >= self.details_interval
                    or memory - self._last_details_memory >= 32 * MIB)
        if detailed:
            record['details'] = self._details()
            self._last_details_at = started
            self._last_details_memory = memory
        if tracemalloc.is_tracing():
            current, peak = tracemalloc.get_traced_memory()
            record['python_traced_bytes'] = current
            record['python_peak_bytes'] = peak
            record['tracer_bytes'] = tracemalloc.get_tracemalloc_memory()
        record['sample_duration_ms'] = round((self.clock() - started) * 1000, 3)
        self._write(record)
        if self._last_cleanup_at is None or started - self._last_cleanup_at >= 3600:
            self._cleanup()
            self._last_cleanup_at = started
        return record

    @staticmethod
    def _version():
        from .version import get_display_version
        return get_display_version()

    def _details(self):
        details = {'python': {'enabled': tracemalloc.is_tracing()}}
        if tracemalloc.is_tracing():
            try:
                snapshot = tracemalloc.take_snapshot()
                # Frozen code can use a relative co_filename even though its
                # module __file__ points into the onefile extraction directory.
                snapshot = snapshot.filter_traces(tuple(tracemalloc.Filter(False, pattern)
                    for pattern in (__file__, 'picsyncra/memory_diagnostics.py',
                                    '*/picsyncra/memory_diagnostics.py',
                                    tracemalloc.__file__, 'tracemalloc.py', '*/tracemalloc.py')))
                statistics = snapshot.statistics('lineno')
                allocations = []
                growth = []
                baseline = {}
                for index, stat in enumerate(statistics):
                    frame = stat.traceback[0]
                    source = f'{_source_name(frame.filename)}:{frame.lineno}'
                    key = f'{frame.filename}:{frame.lineno}'
                    previous = self._previous_allocations.get(key)
                    if index < 20:
                        allocations.append({'source': source, 'bytes': stat.size, 'count': stat.count})
                    if previous is not None or not self._baseline_truncated:
                        size, count = previous or (0, 0)
                        if stat.size > size:
                            growth.append({'source': source, 'bytes_diff': stat.size - size,
                                           'count_diff': stat.count - count})
                    if index < 4096:
                        baseline[key] = (stat.size, stat.count)
                growth.sort(key=lambda item: item['bytes_diff'], reverse=True)
                current, peak = tracemalloc.get_traced_memory()
                details['python'].update(
                    traced_bytes=current, peak_bytes=peak,
                    tracer_bytes=tracemalloc.get_tracemalloc_memory(),
                    top_allocations=allocations, growth=growth[:20],
                    previous_baseline_truncated=self._baseline_truncated,
                    baseline_entries=len(baseline),
                )
                self._previous_allocations = baseline
                self._baseline_truncated = len(statistics) > 4096
            except Exception as exc:
                details['python']['error'] = type(exc).__name__
        try:
            maps = self.process.memory_maps(grouped=True)
            entries = [{'path': _source_name(item.path), 'rss_bytes': item.rss,
                        'private_bytes': getattr(item, 'private', None)} for item in maps]
            entries.sort(key=lambda item: item['private_bytes'] or item['rss_bytes'], reverse=True)
            details['memory_maps'] = entries[:20]
            details['memory_map_count'] = len(entries)
        except (psutil.Error, OSError, NotImplementedError) as exc:
            details['memory_maps_error'] = type(exc).__name__
        return details

    def _write(self, record):
        self.directory.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n'
        size = self.path.stat().st_size if self.path.exists() else 0
        if size and size + len(line.encode('utf-8')) > self.max_bytes:
            for index in range(self.backups, 0, -1):
                target = Path(f'{self.path}.{index}')
                source = self.path if index == 1 else Path(f'{self.path}.{index - 1}')
                if source.exists():
                    source.replace(target)
        with self.path.open('a', encoding='utf-8') as handle:
            handle.write(line)

    def _cleanup(self):
        # Only diagnostic reports are eligible; recently written files can be
        # owned by another live process and are left alone.
        now = time.time()
        files = []
        for path in self.directory.glob('memory-*.jsonl*'):
            try:
                stat = path.stat()
                files.append((stat.st_mtime, stat.st_size, path))
            except OSError:
                pass
        total = sum(size for _, size, _ in files)
        for modified, size, path in sorted(files):
            if now - modified < 3600 or path == self.path:
                continue
            if now - modified > 14 * 86400 or total > 256 * MIB:
                try:
                    path.unlink()
                    total -= size
                except OSError:
                    pass


def start_memory_reporting(role: str, *, directory=None, context=None):
    """Start once per process: frozen builds default on, source runs opt in."""
    global _reporter
    enabled = os.environ.get('PICSYNCRA_MEMORY_REPORT', '').strip().lower()
    if enabled in {'0', 'false', 'off', 'no'}:
        return None
    if enabled not in {'1', 'true', 'on', 'yes'} and not getattr(sys, 'frozen', False):
        return None
    owns_tracer = False
    try:
        with _lifecycle_lock:
            if _reporter is not None:
                if context is not None:
                    _reporter.context = context
                return _reporter
            directory = os.environ.get('PICSYNCRA_MEMORY_REPORT_DIR') or directory
            if directory is None:
                from . import settings
                directory = Path(settings.LOG_DIR) / 'memory'
            directory = Path(directory).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            os.environ['PICSYNCRA_MEMORY_REPORT_DIR'] = str(directory)
            if os.environ.get('PICSYNCRA_MEMORY_TRACE', '1').strip().lower() not in {'0', 'false', 'off'}:
                if not tracemalloc.is_tracing():
                    tracemalloc.start(1)
                    owns_tracer = True
            reporter = MemoryReporter(directory, role, context=context)
            reporter.owns_tracer = owns_tracer
            reporter.start()
            _reporter = reporter
            atexit.register(reporter.stop)
            return reporter
    except Exception:
        # Read-only locations, unavailable process APIs, and profiling failures
        # must never prevent startup. The normal app log remains usable.
        if owns_tracer:
            tracemalloc.stop()
        return None
