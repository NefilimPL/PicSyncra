"""Critical update diagnostics with durable deduplication for status polling."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import threading
import time
from uuid import uuid4

from ..observability import emit_event, observability_store, LIVE_EVENT_RETENTION
from ..installation.module_filesystem import safe_path

_REPORT_LOCK = threading.RLock()


class InstallationProblemReporter:
    def __init__(self, *, store=observability_store, emit=emit_event):
        self._store, self._emit = store, emit

    def __call__(self, snapshot):
        conflicts = snapshot.get('conflicts') or []
        state = snapshot.get('state')
        if not conflicts and not snapshot.get('error') and state not in {'failed', 'recovery_required'}:
            return True
        kind = 'conflict' if conflicts else 'recovery_required' if state == 'recovery_required' else 'failed'
        identifier = str(snapshot.get('operation_id') or snapshot.get('plan_id') or uuid4().hex)
        event_id = 'evt-update-' + hashlib.sha256((identifier + ':' + kind).encode()).hexdigest()
        summary = str(snapshot.get('error') or 'Nie można wykonać aktualizacji.')
        if conflicts:
            summary += ' ' + ' '.join(str(item.get('requirement') or '') for item in conflicts)
        details = {key: snapshot[key] for key in ('operation_id', 'plan_id', 'action', 'state', 'conflicts',
                                                  'error_details', 'setup_release_url', 'suppress_notifications') if key in snapshot}
        needs_setup = any(item.get('code') in {'controller_outdated', 'launcher_outdated'} for item in conflicts)
        action = ('Uruchom pełny instalator Setup na istniejącej instalacji.' if needs_setup else
                  'Sprawdź szczegóły błędu w panelu aktualizacji i ponów operację po usunięciu przyczyny.')
        try:
            with _REPORT_LOCK:
                existing = self._store().query_operational_events(correlation_id=identifier, module='installation.updates', limit=100)
                if any(event['id'] == event_id for event in existing['items']):
                    return True
                self._emit(severity='critical', event_type='installation.update.' + kind,
                           module='installation.updates', stage=str(state or 'planning'), summary=summary,
                           correlation_id=identifier, event_id=event_id, details=details,
                           username=str(snapshot.get('username') or ''), recommended_action=action, strict=True)
                return True
        except Exception:
            # Logging must not turn an actionable conflict into a generic API 500.
            logging.getLogger(__name__).exception('Nie udało się zapisać diagnostyki aktualizacji.')
            return False


class InstallationProblemObserver:
    """Reconcile recent durable outcomes even when every browser is closed."""
    def __init__(self, state_root, report):
        self._root = Path(state_root) / 'module-operations'
        self._report = report
        self._seen = {}
        self._started_at = time.time()
        self._stop = threading.Event()
        self._thread = None

    def scan(self):
        if not self._root.exists():
            return
        cutoff = time.time() - LIVE_EVENT_RETENTION.total_seconds()
        for candidate in self._root.glob('*.json'):
            try:
                path = safe_path(self._root, candidate.name)
                stat = path.stat()
                fingerprint = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                if stat.st_mtime < cutoff or self._seen.get(path.name) == fingerprint:
                    continue
                snapshot = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(snapshot, dict):
                    continue
                if stat.st_mtime < self._started_at:
                    # Recovery should restore logs without sending old alerts again.
                    snapshot['suppress_notifications'] = True
                if self._report(snapshot):
                    self._seen[path.name] = fingerprint
            except (OSError, ValueError, KeyError, TypeError):
                # An incomplete/replaced record must not hide other outcomes.
                continue

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        def watch():
            while not self._stop.is_set():
                try:
                    self.scan()
                except OSError:
                    pass
                self._stop.wait(2)
        self._thread = threading.Thread(target=watch, name='InstallationProblemObserver', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
