from types import SimpleNamespace
import pytest
from tests.test_module_state import context


def test_setup_refuses_to_replace_files_when_backend_stop_fails(context):
    from picsyncra.installation.setup_lifecycle import prepare_existing_installation
    calls = []
    client = SimpleNamespace(snapshot=lambda: {'backend_running': True},
        stop_backend=lambda **kwargs: False)
    with pytest.raises(RuntimeError, match='backend'):
        prepare_existing_installation(context, client=client, stop_task=lambda: calls.append('end'),
                                      processes=lambda: [], quiesce=lambda: None)
    assert calls == []


def test_setup_stops_backend_before_controller_and_verifies_all_executables_exit(context):
    from picsyncra.installation.setup_lifecycle import prepare_existing_installation
    calls = []
    client = SimpleNamespace(snapshot=lambda: {'backend_running': True},
        stop_backend=lambda **kwargs: calls.append('backend') or True)
    prepare_existing_installation(context, client=client,
        stop_task=lambda: calls.append('controller'), processes=lambda: [], quiesce=lambda: None)
    assert calls == ['backend', 'controller']


def test_setup_refuses_running_local_apps_without_stopping_them(context):
    from picsyncra.installation.setup_lifecycle import prepare_existing_installation
    calls = []
    process = SimpleNamespace(info={'exe': str(context.program_root / 'sets' / 'old' / 'apps/local/PicSyncra.exe')})
    with pytest.raises(RuntimeError, match='LOCAL|Migrator|launcher'):
        prepare_existing_installation(context, client=None, processes=lambda: [process],
                                      stop_task=lambda: calls.append('stop'))
    assert not calls


def test_backend_ocr_worker_exits_with_backend_and_does_not_block_setup(context):
    from picsyncra.installation.setup_lifecycle import prepare_existing_installation
    calls = []
    web = SimpleNamespace(info={'exe': str(context.program_root / 'sets/old/apps/web/PicSyncra-WEB.exe')})
    ocr = SimpleNamespace(info={'exe': str(context.program_root / 'sets/old/runtime/ocr/PicSyncra-OCR.exe')})
    running = [web, ocr]
    def stop(**kwargs):
        calls.append('stop'); running.clear(); return True
    client = SimpleNamespace(snapshot=lambda: {'backend_running': True}, stop_backend=stop)
    prepare_existing_installation(context, client=client, processes=lambda: list(running),
        quiesce=lambda: calls.append('drain'), stop_task=lambda: calls.append('controller'))
    assert calls == ['drain', 'stop', 'controller']


def test_setup_cannot_override_pending_module_recovery(context):
    from picsyncra.installation.setup_lifecycle import prepare_existing_installation
    (context.state_root / 'module-operation.json').write_text('{"state":"recovery_required"}')
    calls = []
    with pytest.raises(RuntimeError, match='odzyskaj'):
        prepare_existing_installation(context, client=None, processes=lambda: [], stop_task=lambda: calls.append('stop'))
    assert not calls


def test_setup_cannot_overwrite_pending_setup_receipt(context):
    import json
    from picsyncra.installation.setup_lifecycle import prepare_existing_installation
    path = context.state_root / 'module-setup-result.json'
    path.write_text(json.dumps(dict(state='activating', previous_marker={'schema': 2}, backup_id='retain')))
    original = path.read_bytes()
    with pytest.raises(RuntimeError, match='Setup'):
        prepare_existing_installation(context, client=None, processes=lambda: [], stop_task=lambda: None)
    assert path.read_bytes() == original


def test_failed_repair_restores_autostart_and_manual_backend_state(context, monkeypatch):
    import json
    from picsyncra.installation.setup_lifecycle import run_lifecycle_command, rollback_setup
    from picsyncra.installation.module_setup import initialize_module_layout
    from picsyncra.installation.module_state import read_module_set
    from picsyncra.installation.setup_lifecycle import commit_setup
    from tests.test_module_setup import layout
    initialize_module_layout(layout(context, 'dev'))
    commit_setup(context)
    marker = json.loads((context.program_root / 'active.json').read_text())
    (context.state_root / 'controller-settings.json').write_text('{"autostart":false}')
    (context.state_root / 'setup-preflight-state.json').write_text(json.dumps(dict(
        marker=marker, backend_was_running=True, autostart=False)))
    initialize_module_layout(layout(context, 'dev'))
    monkeypatch.setattr('picsyncra.install_paths.load_registered_install_context', lambda _: context)
    request = dict(installation_id=context.installation_id, enabled=True)
    run_lifecycle_command('configure-startup', request)
    assert json.loads((context.state_root / 'controller-settings.json').read_text())['autostart'] is True
    assert rollback_setup(context) is True
    assert json.loads((context.state_root / 'controller-settings.json').read_text())['autostart'] is False
    calls = []
    client = SimpleNamespace(snapshot=lambda: {'backend_running': bool(calls)},
                             start_backend=lambda: calls.append('start') or True)
    monkeypatch.setattr('picsyncra.installation.launcher.InstallationControlClient', lambda _: client)
    monkeypatch.setattr('picsyncra.installation.controller_host._backend_ready', lambda *a, **k: True)
    run_lifecycle_command('resume-previous', request)
    assert calls == ['start']
    assert read_module_set(context).revision == 1


@pytest.mark.parametrize('command', ['verify-startup', 'resume-previous'])
def test_setup_restores_manually_running_web_without_enabling_boot_start(context, monkeypatch, command):
    import json
    from picsyncra.installation.setup_lifecycle import run_lifecycle_command
    path = context.state_root / 'module-setup-result.json'
    path.write_text(json.dumps(dict(state='activating', previous_backend_was_running=True)))
    (context.state_root / 'controller-settings.json').write_text('{"autostart":false}')
    calls = []
    client = SimpleNamespace(snapshot=lambda: {'backend_running': bool(calls)},
        start_backend=lambda: calls.append('start') or True)
    monkeypatch.setattr('picsyncra.install_paths.load_registered_install_context', lambda _: context)
    monkeypatch.setattr('picsyncra.installation.launcher.InstallationControlClient', lambda _: client)
    monkeypatch.setattr('picsyncra.installation.controller_host._backend_ready', lambda *a, **k: True)
    run_lifecycle_command(command, dict(installation_id=context.installation_id, enabled=False))
    assert calls == ['start']
    assert json.loads((context.state_root / 'controller-settings.json').read_text())['autostart'] is False
    assert json.loads(path.read_text())['state'] == ('committed' if command == 'verify-startup' else 'activating')


def test_retry_setup_recovers_pending_receipt_before_saving_new_preflight(context, monkeypatch):
    import json
    from picsyncra.installation import setup_lifecycle as lifecycle
    from picsyncra.installation.module_setup import initialize_module_layout
    from tests.test_module_setup import layout
    initialize_module_layout(layout(context, 'dev'))
    lifecycle.commit_setup(context)
    marker = json.loads((context.program_root / 'active.json').read_text())
    (context.state_root / 'setup-preflight-state.json').write_text(json.dumps(dict(
        marker=marker, backend_was_running=True, autostart=False)))
    initialize_module_layout(layout(context, 'dev'))
    (context.state_root / 'controller-settings.json').write_text('{"autostart":true}')
    monkeypatch.setattr('picsyncra.install_paths.load_registered_install_context', lambda _: context)
    client = SimpleNamespace(snapshot=lambda: {'backend_running': False, 'autostart': True})
    monkeypatch.setattr('picsyncra.installation.launcher.InstallationControlClient', lambda _: client)
    calls = []
    monkeypatch.setattr(lifecycle, 'prepare_existing_installation', lambda *a, **k: calls.append(k))
    lifecycle.prepare_setup_request(dict(installation_id=context.installation_id, enabled=False))
    assert calls[0]['allow_setup_recovery'] is True
    saved = json.loads((context.state_root / 'setup-preflight-state.json').read_text())
    assert saved['backend_was_running'] is True and saved['autostart'] is False
    assert json.loads((context.state_root / 'module-setup-result.json').read_text())['state'] == 'prepared'
    initialize_module_layout(layout(context, 'dev'))  # Old receipt is now safely replaceable.


def test_preflight_receipt_recovers_failure_before_module_initialization(context, monkeypatch):
    import json
    from dataclasses import replace
    from picsyncra.installation import setup_lifecycle as lifecycle
    from picsyncra.installation.module_setup import initialize_module_layout
    from tests.test_module_setup import layout
    initialize_module_layout(layout(context, 'dev'))
    lifecycle.commit_setup(context)
    monkeypatch.setattr('picsyncra.install_paths.load_registered_install_context', lambda _: context)
    client = SimpleNamespace(snapshot=lambda: {'backend_running': True, 'autostart': False})
    monkeypatch.setattr('picsyncra.installation.launcher.InstallationControlClient', lambda _: client)
    monkeypatch.setattr(lifecycle, 'prepare_existing_installation', lambda *a, **k: None)
    lifecycle.prepare_setup_request(dict(installation_id=context.installation_id, enabled=True))
    # Simulate Inno changing registration, then inspection failing before
    # initialize-modules. Restore the original DB registration and startup.
    changed_context = replace(context, database_path=context.state_root / 'other.sqlite')
    writes = []
    monkeypatch.setattr('picsyncra.installation.setup_cli.WindowsRegistryWriter',
        lambda: SimpleNamespace(set_value=lambda *args: writes.append(args)))
    assert lifecycle.rollback_setup(changed_context)
    assert writes[0][1:] == ('DatabasePath', str(context.database_path))
    receipt = json.loads((context.state_root / 'module-setup-result.json').read_text())
    assert receipt['state'] == 'rolled_back' and receipt['previous_backend_was_running'] is True
    assert json.loads((context.state_root / 'controller-settings.json').read_text())['autostart'] is False
