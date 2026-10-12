import pytest
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
