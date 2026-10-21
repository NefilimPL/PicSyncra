from concurrent.futures import ThreadPoolExecutor

from picsyncra.sqlite_store import SqliteStore


def test_critical_operation_event_is_recorded_once_across_pollers_and_reporter_recreation(tmp_path):
    from picsyncra.web.installation_events import InstallationProblemReporter
    store = SqliteStore(tmp_path / 'events.sqlite')
    sent = []
    def emit(**event):
        sent.append(event)
        store.append_operational_event(dict(event, id=event['event_id']))
    report = InstallationProblemReporter(store=lambda: store, emit=emit)
    failure = dict(operation_id='a'*32, state='failed', action='apply', error='Plan zawiera konflikty zgodności.',
        conflicts=[dict(code='controller_outdated', module_id='core', requirement='Wymagany kontroler 6; obecny 5.')])
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(report, [failure] * 8))
    InstallationProblemReporter(store=lambda:store, emit=emit)(failure)
    assert len(sent) == 1
    assert sent[0]['severity'] == 'critical'
    assert 'Wymagany kontroler 6; obecny 5.' in sent[0]['summary']
    assert sent[0]['correlation_id'] == failure['operation_id']
    assert sent[0]['details']['conflicts'] == failure['conflicts']
    report(dict(failure, operation_id='b'*32))
    assert len(sent) == 2


def test_normal_progress_does_not_emit_a_critical_event(tmp_path):
    from picsyncra.web.installation_events import InstallationProblemReporter
    calls = []
    report = InstallationProblemReporter(store=lambda:None, emit=lambda **event:calls.append(event))
    for state in ('preparing','accepted','downloading','committed'):
        report(dict(operation_id='a'*32, state=state))
    assert calls == []


def test_real_critical_logging_updates_alert_counter_without_counting_polls_as_incidents(tmp_path, monkeypatch):
    from picsyncra import observability
    from picsyncra.web.installation_events import InstallationProblemReporter
    store = SqliteStore(tmp_path / 'events.sqlite')
    monkeypatch.setattr(observability, 'observability_store', lambda:store)
    monkeypatch.setattr(store, '_wake_notification_worker', lambda:None)
    report = InstallationProblemReporter(store=lambda:store, emit=observability.emit_event)
    failure = dict(operation_id='a'*32, state='failed', action='apply', error='Brak miejsca na kopię danych.')
    for _ in range(3): report(failure)
    assert store.unread_alert_summary('admin')['critical'] == 1
    assert store.query_incidents()['items'][0]['occurrence_count'] == 1
    assert store.query_operational_events(module='installation.updates')['items'][0]['severity'] == 'critical'


def test_persisted_failure_is_reported_without_any_browser_request(tmp_path, monkeypatch):
    import json
    from picsyncra import observability
    from picsyncra.web.installation_events import InstallationProblemObserver, InstallationProblemReporter
    store = SqliteStore(tmp_path / 'events.sqlite')
    monkeypatch.setattr(observability, 'observability_store', lambda:store)
    monkeypatch.setattr(store, '_wake_notification_worker', lambda:None)
    root = tmp_path / 'module-operations'
    root.mkdir()
    report = InstallationProblemReporter(store=lambda:store, emit=observability.emit_event)
    observer = InstallationProblemObserver(tmp_path, report)
    identifier = 'a'*32
    (root / (identifier + '.json')).write_text(json.dumps(dict(operation_id=identifier, state='failed',
        action='apply', error='Plan zawiera konflikty zgodności.', conflicts=[dict(
            module_id='core', code='controller_outdated', requirement='Wymagany kontroler 6; obecny 5.')])))
    observer.scan()
    observer.scan()
    assert store.unread_alert_summary('admin')['critical'] == 1
    assert store.query_incidents()['items'][0]['occurrence_count'] == 1
