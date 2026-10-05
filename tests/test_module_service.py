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
