import pytest
import sys
from picsyncra.installation.module_service import ModuleService
from picsyncra.installation.module_catalog import ModuleCatalogEntry
from picsyncra.installation.module_manifest import parse_module_manifest
from picsyncra.installation.module_state import read_module_set
from tests.module_fixtures import release_payload
from tests.test_module_state import context
from tests.test_module_executor import prepare, Controller


class Source:
    offline = False
    def load(self, channel):
        release = parse_module_manifest(release_payload())
        return (ModuleCatalogEntry(5, 'v5', release.published_at, release),)


def test_access_failure_precedes_catalog_download_and_has_structured_details(context, monkeypatch):
    _, store, _ = prepare(context)
    from pathlib import Path
    original = Path.open
    ack = context.state_root / 'module-maintenance-ready.json'
    ack.write_text('{}')
    def deny(path, *args, **kwargs):
        if path == ack: raise PermissionError(13, 'denied')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', deny)
    source = Source()
    source.load = lambda channel: pytest.fail('must check permissions before network')
    service = ModuleService(context, Controller(), source=source, content=store)
    with pytest.raises(RuntimeError) as failure:
        service.prepare(action='apply', selected={}, excluded=[])
    assert failure.value.details['code'] == 'permission_required'
    assert failure.value.details['location'] == 'maintenance_ready'
    assert not service.busy


@pytest.mark.parametrize('role', ['database', 'configuration'])
def test_existing_data_file_access_is_checked_before_network(context, monkeypatch, role):
    from pathlib import Path
    _, store, _ = prepare(context)
    path = context.database_path if role == 'database' else context.config_root / 'config.json'
    if role == 'configuration': path.write_text('{}')
    original = Path.open
    def deny(candidate, *args, **kwargs):
        if candidate == path and args and args[0] == 'r+b': raise PermissionError(13, 'denied')
        return original(candidate, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', deny)
    source = Source()
    source.load = lambda channel: pytest.fail('must check data file permissions before network')
    service = ModuleService(context, Controller(), source=source, content=store)
    with pytest.raises(RuntimeError) as failure:
        service.prepare(action='apply', selected={}, excluded=[])
    assert failure.value.details['code'] == 'permission_required'
    assert failure.value.details['location'] == role


def test_unchanged_apply_does_not_restart_or_create_backup(context):
    active, store, _ = prepare(context)
    jobs = []
    service = ModuleService(context, Controller(), source=Source(), content=store, schedule=jobs.append)
    plan = service.prepare(action='apply', selected={}, excluded=[])
    assert plan['changes'] == []
    assert plan['has_changes'] is False
    result = service.execute(plan['plan_id'])
    assert result['state'] == 'committed' and result['unchanged'] is True
    assert jobs == [] and read_module_set(context) == active
    assert not (context.state_root / 'backups/operations').exists()


def test_new_tag_with_identical_module_identities_is_not_an_update(context):
    from dataclasses import replace
    active, store, _ = prepare(context)
    class SameContent(Source):
        def load(self, channel):
            release = parse_module_manifest(release_payload())
            release = replace(release, modules=tuple(replace(m, source_release_id=5, source_tag='v5') for m in release.modules))
            return (ModuleCatalogEntry(5, 'v5', release.published_at, release),)
    jobs = []
    service = ModuleService(context, Controller(), source=SameContent(), content=store, schedule=jobs.append)
    plan = service.prepare(action='apply', selected={}, excluded=[])
    assert not plan['has_changes'] and plan['changes'] == []
    service.execute(plan['plan_id'])
    assert jobs == [] and read_module_set(context) == active


def test_unreadable_cleanup_status_publishes_terminal_result_and_releases_busy(context, monkeypatch):
    import json
    _, store, _ = prepare(context)
    jobs = []
    service = ModuleService(context, Controller(), source=Source(), content=store, schedule=jobs.append)
    plan = service.prepare(action='update_all', selected={}, excluded=[])
    service.execute(plan['plan_id'])
    monkeypatch.setattr(service.executor, 'execute', lambda *args, **kwargs: dict(state='failed'))
    monkeypatch.setattr(service.executor, 'status', lambda: (_ for _ in ()).throw(PermissionError(13, 'denied')))
    jobs[0]()
    result = json.loads((context.state_root / 'module-operations' / (plan['plan_id'] + '.json')).read_text())
    assert result['state'] == 'recovery_required' and service.busy is False
    assert result['error_details']['code'] == 'permission_required'


def test_catalog_lists_backup_receipts_but_selected_backup_is_fully_verified(context, monkeypatch):
    from picsyncra.installation.backups import create_operation_backup
    from picsyncra.installation import module_service
    _, store, _ = prepare(context)
    create_operation_backup(context, 'candidate')
    database = context.state_root / 'backups/operations/candidate/database.sqlite'
    database.write_bytes(b'corrupt database')
    service = ModuleService(context, Controller(), source=Source(), content=store)
    original = module_service.verified_backup
    monkeypatch.setattr(module_service, 'verified_backup', lambda *args: pytest.fail('catalog must not hash historical DB'))
    assert service.catalog()['backups'] == [dict(backup_id='candidate', schema_version=1, verification_pending=True)]
    monkeypatch.setattr(module_service, 'verified_backup', original)
    with pytest.raises(RuntimeError):
        service.prepare(action='apply', selected={}, excluded=[], restore_backup_id='candidate')


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows file ACL')
def test_real_windows_ack_acl_denial_is_detected_before_network(context):
    security = pytest.importorskip('win32security')
    import win32api
    import win32con
    _, store, _ = prepare(context)
    path = context.state_root / 'module-maintenance-ready.json'
    path.write_text('{}')
    original = security.GetFileSecurity(str(path), security.DACL_SECURITY_INFORMATION)
    token = security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try: identity = security.GetTokenInformation(token, security.TokenUser)[0]
    finally: token.Close()
    denied = security.SECURITY_DESCRIPTOR()
    acl = security.ACL()
    acl.AddAccessDeniedAce(security.ACL_REVISION, 0x10003, identity)
    acl.AddAccessAllowedAce(security.ACL_REVISION, 0x1f01ff, identity)
    denied.SetSecurityDescriptorDacl(True, acl, False)
    source = Source()
    source.load = lambda channel: pytest.fail('must not download with denied ACK access')
    service = ModuleService(context, Controller(), source=source, content=store)
    try:
        security.SetFileSecurity(str(path), security.DACL_SECURITY_INFORMATION, denied)
        with pytest.raises(RuntimeError) as failure:
            service.prepare(action='apply', selected={}, excluded=[])
        assert failure.value.details['code'] == 'permission_required'
        assert failure.value.details['system_code'] in {5, 13}
        assert failure.value.details['location'] == 'maintenance_ready'
    finally:
        security.SetFileSecurity(str(path), security.DACL_SECURITY_INFORMATION, original)


def test_catalog_exposes_fetch_failure_even_when_no_release_is_cached(context):
    _, store, _ = prepare(context)
    class OfflineSource:
        offline=True
        error={'code':'rate_limit','message':'GitHub: przekroczono limit zapytań.'}
        def load(self, channel): return ()
    service=ModuleService(context, Controller(), source=OfflineSource(), content=store)
    snapshot=service.catalog()
    assert snapshot['offline'] is True
    assert snapshot['blocked_releases'] == []
    assert all(module['latest'] is None for module in snapshot['modules'])
    assert snapshot['catalog_error'] == OfflineSource.error


def test_ocr_preparation_reports_catalog_connection_failure_without_creating_plan(context):
    _, store, _ = prepare(context)
    class OfflineSource:
        offline = True
        error = {'code': 'certificate_error', 'message': 'Nie udało się zweryfikować certyfikatu GitHuba.'}
        def load(self, channel): return ()
    service = ModuleService(context, Controller(), source=OfflineSource(), content=store)
    with pytest.raises(RuntimeError, match='certyfikatu GitHuba'):
        service.prepare(action='install_ocr', selected={}, excluded=[])
    assert not (context.state_root / 'module-plans').exists()
    assert service.busy is False


def test_catalog_and_planning_are_read_only_and_execution_is_deferred(context):
    active, store, _ = prepare(context)
    jobs = []
    service = ModuleService(context, Controller(), source=Source(), content=store, schedule=jobs.append,
                            quiesce=lambda op: None, healthy=lambda: True)
    rows = service.catalog()['modules']
    assert rows[0]['current_release']['tag'] == 'v1'
    assert rows[0]['latest_release']['tag'] == 'v1'
    assert rows[0]['latest_release']['published_at'] is None  # source release absent in fixture
    assert rows[0]['versions'][0]['tag'] == 'v1'
    assert rows[0]['pinned'] is True
    assert rows[0]['versions'][0]['release_url'].startswith('https://github.com/NefilimPL/PicSyncra/releases/tag/')
    planned = service.prepare(action='update_all', selected={}, excluded=[])
    assert read_module_set(context) == active
    accepted = service.execute(planned['plan_id'])
    assert accepted['state'] == 'accepted'
    assert read_module_set(context) == active
    jobs.pop()()
    assert service.operation(planned['plan_id'])['state'] == 'committed'
    assert not read_module_set(context).pinned


def test_catalog_dates_come_from_the_modules_source_release(context):
    _, store, _ = prepare(context)
    release = parse_module_manifest(release_payload())
    class DatedSource(Source):
        def load(self, channel):
            return (ModuleCatalogEntry(1, 'v1', '2026-09-01T00:00:00Z', release),
                    ModuleCatalogEntry(5, 'v5', release.published_at, release))
    snapshot = ModuleService(context, Controller(), source=DatedSource(), content=store).catalog()
    row = snapshot['modules'][0]
    assert row['current_release']['published_at'] == '2026-09-01T00:00:00Z'
    assert row['latest_release']['published_at'] == '2026-09-01T00:00:00Z'
    assert row['versions'][0]['published_at'] == '2026-09-01T00:00:00Z'


def test_shared_operation_reports_download_progress_and_pending_work_after_reopen(context):
    from tests.module_fixtures import module_payload
    from tests.test_module_content import Response
    import json
    _, store, _ = prepare(context)
    raw = release_payload()
    raw['modules'].append(module_payload('ftp', 'picsyncra/services/ftp_service.py', b'new'))
    release = parse_module_manifest(raw)
    class DownloadSource(Source):
        def load(self, channel): return (ModuleCatalogEntry(5, 'v5', release.published_at, release),)
    jobs, observed = [], []
    service = ModuleService(context, Controller(), source=DownloadSource(), content=store, schedule=jobs.append,
                            quiesce=lambda op: None, healthy=lambda: True)
    plan = service.prepare(action='update_all', selected={}, excluded=[])
    operation_id = plan['plan_id']
    class ChunkedResponse(Response):
        def read(self, size=-1):
            observed.append(service.operation(operation_id))
            return super().read(min(size, 1))
    store.fetch = lambda url, start, size, total: ChunkedResponse(b'new', start, total)
    service.execute(operation_id)
    assert service.catalog()['operation']['operation_id'] == operation_id
    assert service.catalog()['operation']['state'] == 'accepted'
    jobs.pop()()
    assert any(item.get('progress', {}).get('downloaded_bytes') == 1 for item in observed)
    completed = service.operation(operation_id)
    assert completed['state'] == 'committed'
    assert completed['progress']['downloaded_bytes'] == completed['progress']['total_bytes'] == 3
    assert service.catalog()['operation'] is None
    assert json.loads((context.state_root / 'module-progress' / (operation_id + '.json')).read_text()) == completed['progress']


def test_plan_survives_service_restart_and_stale_plan_is_rejected(context):
    active, store, _ = prepare(context)
    service = ModuleService(context, Controller(), source=Source(), content=store, schedule=lambda job: job(),
                            quiesce=lambda op: None, healthy=lambda: True)
    first = service.prepare(action='update_all', selected={}, excluded=[])
    second = service.prepare(action='update_all', selected={}, excluded=[])
    service.execute(first['plan_id'])
    restarted = ModuleService(context, Controller(), source=Source(), content=store, schedule=lambda job: job(),
                              quiesce=lambda op: None, healthy=lambda: True)
    with pytest.raises(RuntimeError, match='zmieniła'): restarted.execute(second['plan_id'])


def test_restart_before_deferred_execution_ends_orphaned_accepted_status(context):
    active, store, _ = prepare(context)
    queued = []
    first = ModuleService(context, Controller(), source=Source(), content=store, schedule=queued.append)
    plan = first.prepare(action='update_all', selected={}, excluded=[])
    first.execute(plan['plan_id'])
    assert first.operation(plan['plan_id'])['state'] == 'accepted'
    restarted = ModuleService(context, Controller(), source=Source(), content=store)
    assert restarted.executor.recover() is None
    status = restarted.operation(plan['plan_id'])
    assert status['state'] == 'failed'
    assert 'rozpoczęciem' in status['error']
    assert restarted.catalog()['operation'] is None
    assert read_module_set(context) == active


def test_pipe_rejects_paths_and_arbitrary_selected_identifiers():
    from picsyncra.installation.control_protocol import validate_module_payload, ControlProtocolError
    with pytest.raises(ControlProtocolError):
        validate_module_payload('module_execute', {'plan_id': '../file', 'restore_backup_id': None, 'acknowledge_data_loss': False})
    with pytest.raises(ControlProtocolError):
        validate_module_payload('module_plan', {'action': 'update', 'selected': {'ftp': 'https://attacker'}, 'excluded': [], 'restore_backup_id': None})


def test_durable_recovery_failure_blocks_manual_backend_start(context):
    from picsyncra.installation.control_protocol import ControlDispatcher
    import json
    _, store, _ = prepare(context)
    controller = Controller()
    controller.running = False
    service = ModuleService(context, controller, source=Source(), content=store)
    service.executor.path.write_text('{"state":"recovery_required"}')
    dispatcher = ControlDispatcher(controller, installation_id=context.installation_id,
                                   authorized_identities={'admin'}, module_service=service)
    for command in ('start_backend', 'restart_backend'):
        response = dispatcher.dispatch(json.dumps(dict(version=1, installation_id=context.installation_id,
            command=command, payload={})).encode(), peer_identity='admin')
        assert response['ok'] is False
        assert 'odzysk' in response['error']
    assert not controller.running


def test_configuration_schema_and_malformed_files_are_checked(context):
    _, store, _ = prepare(context)
    service = ModuleService(context, Controller(), source=Source(), content=store)
    (context.config_root / 'module-config-schema.json').write_text('{"schema":2}')
    plan = service.prepare(action='update_all', selected={}, excluded=[])
    assert any(c['code'] == 'config_incompatible' for c in plan['conflicts'])
    (context.config_root / 'config.json').write_text('{broken')
    with pytest.raises(RuntimeError, match='konfigurac'):
        service.prepare(action='update_all', selected={}, excluded=[])


def test_configuration_schema_is_read_from_selected_verified_backup(context):
    from picsyncra.installation.backups import create_operation_backup
    _, store, _ = prepare(context)
    (context.config_root / 'module-config-schema.json').write_text('{"schema":2}')
    create_operation_backup(context, 'config-two')
    (context.config_root / 'module-config-schema.json').write_text('{"schema":1}')
    service = ModuleService(context, Controller(), source=Source(), content=store)
    assert service._environment().config_schema == 1
    assert service._environment('config-two').config_schema == 2


def test_channel_change_is_shared_by_clients_and_preserves_modules_and_settings(context):
    import json
    from picsyncra.installation.control_protocol import ControlDispatcher
    from picsyncra.installation.launcher import InstallationControlClient
    active, store, _ = prepare(context)
    channels = []
    class ChannelSource(Source):
        def load(self, channel):
            channels.append(channel)
            return super().load(channel)
    service = ModuleService(context, Controller(), source=ChannelSource(), content=store)
    dispatcher = ControlDispatcher(Controller(), installation_id='test', authorized_identities={'admin'}, module_service=service)
    class Pipe:
        def request(self, message): return dispatcher.dispatch(message, peer_identity='admin')
    web = InstallationControlClient('test', pipe_client=Pipe())
    launcher = InstallationControlClient('test', pipe_client=Pipe())
    settings = context.state_root / 'installation-settings.json'
    settings.write_text('{"channel":"stable","extra":true}')
    assert web.module_channel('dev') == {'channel':'dev'}
    assert launcher.module_catalog()['channel'] == 'dev'
    assert channels == ['dev']
    assert json.loads(settings.read_text()) == {'channel':'dev', 'extra':True}
    assert read_module_set(context) == active
    service.busy = True
    with pytest.raises(RuntimeError, match='toku'): launcher.module_channel('stable')
    assert json.loads(settings.read_text())['channel'] == 'dev'
    service.busy = False
    with pytest.raises(ValueError): web.module_channel(['dev'])
    with pytest.raises(ValueError): web.module_channel('../invalid')
