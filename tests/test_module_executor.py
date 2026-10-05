from dataclasses import replace
import sqlite3
import pytest
from picsyncra.installation.module_executor import ModuleExecutor, ModuleExecutionError
from picsyncra.installation.module_content import ModuleContentStore
from picsyncra.installation.module_planner import plan_module_operation
from picsyncra.installation.module_state import read_module_set, activate_module_set
from tests.test_module_state import context, staged
from tests.test_module_planner import ENV
from picsyncra.installation.module_manifest import parse_module_manifest
from tests.module_fixtures import release_payload


class Controller:
    def __init__(self): self.running = True
    def snapshot(self): return {'backend_running': self.running}
    def stop_backend(self, force=False): self.running = False; return True
    def start_backend(self): self.running = True


def prepare(context):
    context.config_root.mkdir()
    (context.config_root / 'config.json').write_text('{"value":1}')
    with sqlite3.connect(context.database_path) as db:
        db.executescript('CREATE TABLE schema_version(version INTEGER); INSERT INTO schema_version VALUES(1); CREATE TABLE app_config_values(value TEXT); INSERT INTO app_config_values VALUES("before");')
    db.close()
    active = staged(context, 1, frozenset({'core'}))
    activate_module_set(context, active, expected_revision=0)
    store = ModuleContentStore(context)
    store.seed(active)
    release = parse_module_manifest(release_payload())
    plan = plan_module_operation(active, (release,), ENV, action='update_all', selected={}, excluded=frozenset(), available_hashes=store.available_hashes())
    return active, store, plan


def test_success_atomically_commits_set_and_unpins_after_backup(context):
    active, store, plan = prepare(context)
    executor = ModuleExecutor(context, Controller(), content=store, quiesce=lambda op: None, healthy=lambda: True)
    result = executor.execute(plan)
    assert result['state'] == 'committed'
    assert read_module_set(context) == plan.target
    assert (context.state_root / 'backups/operations' / plan.plan_id / 'database.sqlite').is_file()


def test_failed_health_and_crash_recovery_restore_exact_previous_pins(context):
    active, store, plan = prepare(context)
    health_results = iter((False, True))
    executor = ModuleExecutor(context, Controller(), content=store, quiesce=lambda op: None, healthy=lambda: next(health_results))
    result = executor.execute(plan)
    assert result['state'] == 'rolled_back'
    assert read_module_set(context) == active
    assert executor.recover() is None


def test_stale_plan_cannot_backup_or_switch(context):
    active, store, plan = prepare(context)
    executor = ModuleExecutor(context, Controller(), content=store, quiesce=lambda op: None, healthy=lambda: True)
    executor.execute(plan)
    with pytest.raises(ModuleExecutionError): executor.execute(plan)


def test_unacknowledged_database_restore_is_blocked_before_changes(context):
    active, store, plan = prepare(context)
    executor = ModuleExecutor(context, Controller(), content=store, quiesce=lambda op: None, healthy=lambda: True)
    with pytest.raises(ModuleExecutionError): executor.execute(plan, restore_backup_id='old')
    assert read_module_set(context) == active


def test_restart_after_power_loss_restores_database_config_and_marker(context, monkeypatch):
    active, store, plan = prepare(context)
    def interrupted():
        (context.state_root / 'module-maintenance-request.json').write_text('{"operation_id":"stale"}')
        (context.state_root / 'module-maintenance-ready.json').write_text('{"operation_id":"stale","ready":true}')
        db = sqlite3.connect(context.database_path)
        db.execute('UPDATE app_config_values SET value="after"')
        db.commit()
        db.close()
        (context.config_root / 'config.json').write_text('{"value":2}')
        raise SystemExit('power loss')
    executor = ModuleExecutor(context, Controller(), content=store, quiesce=lambda op: None, healthy=interrupted)
    with pytest.raises(SystemExit): executor.execute(plan)
    assert read_module_set(context) == plan.target
    import shutil
    from picsyncra import install_paths
    from picsyncra.installation.module_state import module_set_root
    shutil.rmtree(module_set_root(context, plan.target))
    registration = dict(installation_id=context.installation_id, program_root=str(context.program_root),
        state_root=str(context.state_root), database_path=str(context.database_path))
    monkeypatch.setattr(install_paths, '_read_hklm_registrations', lambda: (registration,))
    assert install_paths.load_registered_install_context(context.installation_id) == context
    recovered = ModuleExecutor(context, Controller(), content=store, quiesce=lambda op: None, healthy=lambda: True)
    assert recovered.recover() == 'rolled_back'
    assert read_module_set(context) == active
    db = sqlite3.connect(context.database_path)
    assert db.execute('SELECT value FROM app_config_values').fetchone() == ('before',)
    db.close()
    assert (context.config_root / 'config.json').read_text() == '{"value":1}'
    assert not (context.state_root / 'module-maintenance-request.json').exists()
    assert not (context.state_root / 'module-maintenance-ready.json').exists()


def test_failed_restored_backend_health_keeps_recovery_gate_closed(context):
    _, store, plan = prepare(context)
    controller = Controller()
    executor = ModuleExecutor(context, controller, content=store, quiesce=lambda op: None, healthy=lambda: False)
    assert executor.execute(plan)['state'] == 'recovery_required'
    assert not controller.running


def test_drain_failure_never_stops_a_busy_backend(context):
    active,store,plan=prepare(context)
    class Busy(Controller):
        def stop_backend(self,force=False): raise AssertionError('Busy backend must remain alive')
    def blocked(op): raise RuntimeError('Writers are still busy')
    executor=ModuleExecutor(context,Busy(),content=store,quiesce=blocked,healthy=lambda:True)
    result=executor.execute(plan)
    assert result['state']=='rolled_back'
    assert read_module_set(context)==active


def test_terminal_recovery_does_not_take_running_standalone_lease(context):
    from picsyncra.installation.module_sessions import standalone_session
    _, store, _ = prepare(context)
    executor = ModuleExecutor(context, Controller(), content=store, quiesce=lambda op: None, healthy=lambda: True)
    with standalone_session(context):
        assert executor.recover() is None


def test_lost_active_payload_can_be_repaired_from_protected_metadata_and_cache(context):
    import shutil
    from picsyncra.installation.module_state import module_set_root
    active, store, plan = prepare(context)
    shutil.rmtree(module_set_root(context, active))
    assert read_module_set(context) == active
    executor = ModuleExecutor(context, Controller(), content=store, quiesce=lambda op: None, healthy=lambda: True)
    assert executor.execute(plan)['state'] == 'committed'


def test_no_disk_space_blocks_download_backup_and_backend_stop(context, monkeypatch):
    from collections import namedtuple
    from picsyncra.installation import module_preflight
    active, store, plan = prepare(context)
    monkeypatch.setattr(module_preflight.shutil, 'disk_usage', lambda path: namedtuple('Usage', 'total used free')(100,100,0))
    store.assemble = lambda target: pytest.fail('No download or staging before preflight')
    class Running(Controller):
        def stop_backend(self, force=False): pytest.fail('No stop before preflight')
    executor = ModuleExecutor(context, Running(), content=store, quiesce=lambda op: None, healthy=lambda: True)
    with pytest.raises(ModuleExecutionError, match='miejsca'):
        executor.execute(plan)
    assert read_module_set(context) == active
    assert not executor.path.exists()
