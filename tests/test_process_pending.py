from pathlib import Path
from picsyncra.web.process_models import ProcessFormSnapshot, QueuedUploadFile
from picsyncra.web.process_pending import save_pending, load_pending, mark_started, mark_state


def test_waiting_form_survives_lost_session_cache_and_running_form_is_not_replayed(tmp_path):
    root = tmp_path / 'queue'
    directory = root / 'job-one'
    directory.mkdir(parents=True)
    original = tmp_path / 'cache.jpg'
    original.write_bytes(b'photo')
    upload = directory / 'upload.jpg'
    upload.write_bytes(b'upload')
    form = ProcessFormSnapshot({'name':'draft', 'existing_slot_1':'expired-session-token',
        'existing_slot_preprocessed_1':'1'}, {'slot_2':QueuedUploadFile(str(upload),'upload.jpg')}, str(directory))
    save_pending(dict(id='abc', username='alice', cache_scope='old-session', created_at=1,
                      created_time='today', form=form), root, resolve_token=lambda _: str(original))
    original.unlink()
    issued = []
    def issue(path):
        issued.append(path)
        return 'new-token'
    recovered = list(load_pending(root, issue_token=issue, validate_original=lambda p: p))
    assert len(recovered) == 1
    recovered_form = recovered[0]['form']
    assert recovered_form.fields['name'] == 'draft'
    assert recovered_form.fields['existing_slot_1'] == 'new-token'
    assert recovered_form.fields['existing_slot_preprocessed_1'] == '1'
    assert Path(issued[0]).read_bytes() == b'photo'
    # A failed update can resume without restarting or refreshing any tokens.
    assert Path(form.trusted_paths['existing_slot_1']).read_bytes() == b'photo'
    assert recovered_form.uploads['slot_2'].filename == 'upload.jpg'
    mark_started(recovered_form)
    assert list(load_pending(root, issue_token=issue, validate_original=lambda p: p)) == []


def test_durable_photo_keeps_loaded_local_identity_for_conflict_detection(tmp_path):
    from picsyncra.web import app as web_app
    original = tmp_path / 'original.jpg'
    original.write_bytes(b'photo')
    directory = tmp_path / 'queue' / 'job-one'
    directory.mkdir(parents=True)
    form = ProcessFormSnapshot({'existing_slot_1':'token'}, temp_dir=str(directory))
    save_pending(dict(id='one', username='alice', cache_scope='scope', created_at=1,
                      created_time='today', form=form), directory.parent, resolve_token=lambda _: str(original))
    recovered = next(load_pending(directory.parent, issue_token=lambda _: 'new', validate_original=lambda p:p))['form']
    for selected in (form, recovered):
        slot = web_app.WebUploadedSlot(prefix='1', label='photo', source_path=selected.trusted_paths['existing_slot_1'],
                                      original_source_path=selected.source_paths['existing_slot_1'])
        assert slot.source_path != str(original)
        assert web_app._existing_photo_conflicts([dict(prefix='1', path=str(original), local=True)], [slot], []) == []


def test_unaccepted_and_cancelled_forms_are_not_replayed_if_cleanup_was_blocked(tmp_path):
    directory = tmp_path / 'job-one'
    directory.mkdir()
    form = ProcessFormSnapshot({'name':'draft'}, temp_dir=str(directory))
    save_pending(dict(id='one', username='alice', cache_scope='scope', created_at=1,
                      created_time='today', form=form), tmp_path, resolve_token=lambda _: '', state='staged')
    read = lambda: list(load_pending(tmp_path, issue_token=lambda _: '', validate_original=lambda p:p))
    assert read() == []
    mark_state(form, 'queued')
    assert len(read()) == 1
    mark_state(form, 'cancelled')
    assert read() == []


def test_restored_queue_waits_for_maintenance_before_running(tmp_path, monkeypatch):
    import threading
    from picsyncra.web import app as web_app
    from picsyncra.web.process_queue import ProcessQueueService
    from picsyncra.installation.maintenance import MaintenanceGate
    directory = tmp_path / 'job-one'
    directory.mkdir()
    form = ProcessFormSnapshot({'name':'saved draft'}, temp_dir=str(directory))
    save_pending(dict(id='one', username='alice', cache_scope='scope', created_at=1,
                      created_time='today', form=form), tmp_path, resolve_token=lambda _: '')
    gate = MaintenanceGate()
    gate.begin('update', initiator_id='admin')
    queue = ProcessQueueService(maintenance_gate=gate)
    ran = threading.Event()
    monkeypatch.setattr(web_app, '_PROCESS_QUEUE', queue)
    monkeypatch.setattr(web_app, '_PROCESS_JOB_ROOT', tmp_path)
    monkeypatch.setattr(web_app, '_PROCESS_JOBS', {})
    monkeypatch.setattr(web_app, '_PROCESS_JOB_COMPLETIONS', {})
    monkeypatch.setattr(web_app, '_run_process_job', lambda *_: ran.set())
    try:
        web_app._restore_pending_process_jobs()
        assert queue.position('one') == 1
        assert not ran.wait(.2)
        assert web_app._PROCESS_JOBS['one']['form'].fields['name'] == 'saved draft'
        assert gate.wait_for_drain(timeout=0)
        gate.complete('update')
        assert ran.wait(5)
    finally:
        queue.shutdown()
