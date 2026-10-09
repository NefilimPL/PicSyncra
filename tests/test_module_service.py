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
