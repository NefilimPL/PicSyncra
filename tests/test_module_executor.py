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
    executor = ModuleExecutor(context, Controller(), content=store, quiesce=lambda op: None, healthy=lambda: False)
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


def test_restart_after_power_loss_restores_database_config_and_marker(context):
    active, store, plan = prepare(context)
    def interrupted():
        db = sqlite3.connect(context.database_path)
        db.execute('UPDATE app_config_values SET value="after"')
        db.commit()
        db.close()
        (context.config_root / 'config.json').write_text('{"value":2}')
        raise SystemExit('power loss')
    executor = ModuleExecutor(context, Controller(), content=store, quiesce=lambda op: None, healthy=interrupted)
    with pytest.raises(SystemExit): executor.execute(plan)
    assert read_module_set(context) == plan.target
    recovered = ModuleExecutor(context, Controller(), content=store, quiesce=lambda op: None, healthy=lambda: True)
    assert recovered.recover() == 'rolled_back'
    assert read_module_set(context) == active
    db = sqlite3.connect(context.database_path)
    assert db.execute('SELECT value FROM app_config_values').fetchone() == ('before',)
    db.close()
    assert (context.config_root / 'config.json').read_text() == '{"value":1}'
