import json
import pytest
from picsyncra.installation.module_setup import initialize_module_layout
from picsyncra.installation.module_state import read_module_set
from picsyncra.installation.setup_lifecycle import commit_setup
from tests.test_module_state import context, staged


def strict_layout(context, schema):
    from picsyncra.installation.module_state import make_module_set, publish_module_set
    from picsyncra.installation.module_manifest import parse_module_manifest, module_version_id
    from picsyncra.installation.module_content import ModuleContentStore
    from tests.module_fixtures import module_payload, release_payload
    modules = [module_payload(), module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe')]
    for module in modules:
        module['database_min'] = module['database_max'] = schema
        module['version_id'] = module_version_id(module)
    selected = make_module_set(1, 11, parse_module_manifest(release_payload(11, modules)).modules)
    store = ModuleContentStore(context); store.import_bytes(b'code'); store.assemble(selected)
    publish_module_set(context, selected)
    (context.program_root / 'module-initial-layout.json').write_text(json.dumps(
        dict(schema=1, channel='dev', base=selected.set_id, local=selected.set_id)))
    return dict(installation_id=context.installation_id, program_root=str(context.program_root),
        state_root=str(context.state_root), database_path=str(context.database_path), include_local=False)


def test_fresh_install_creates_real_current_schema_before_activation(context):
    import sqlite3
    from picsyncra.sqlite_store import SCHEMA_VERSION
    from picsyncra.installation.database import inspect_database
    request = strict_layout(context, SCHEMA_VERSION)
    assert not context.database_path.exists()
    initialize_module_layout(request)
    inspection = inspect_database(context.database_path)
    assert inspection.schema_version == SCHEMA_VERSION
    assert inspection.integrity_ok and inspection.is_picsyncra
    with sqlite3.connect(context.database_path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 10
    db.close()
    assert read_module_set(context).release_id == 11


def test_fresh_incompatible_package_does_not_publish_database_or_marker(context):
    from picsyncra.sqlite_store import SCHEMA_VERSION
    request = strict_layout(context, SCHEMA_VERSION + 1)
    with pytest.raises(ValueError, match='Setup'):
        initialize_module_layout(request)
    assert not context.database_path.exists()
    assert not (context.program_root / 'active.json').exists()


def test_existing_incompatible_database_is_not_migrated_or_replaced_by_setup(context):
    import sqlite3
    from picsyncra.sqlite_store import SCHEMA_VERSION
    request = strict_layout(context, SCHEMA_VERSION)
    with sqlite3.connect(context.database_path) as db:
        db.executescript('CREATE TABLE schema_version(version INTEGER); INSERT INTO schema_version VALUES(1);'
                        'CREATE TABLE app_config_values(value TEXT); INSERT INTO app_config_values VALUES("retain");')
    db.close()
    before = context.database_path.read_bytes()
    with pytest.raises(ValueError, match='Setup'):
        initialize_module_layout(request)
    assert context.database_path.read_bytes() == before


def test_first_install_can_retry_activation_failure_without_losing_database(context, monkeypatch):
    from picsyncra.sqlite_store import SCHEMA_VERSION
    from picsyncra.installation import module_setup
    request = strict_layout(context, SCHEMA_VERSION)
    activate = module_setup.activate_module_set
    monkeypatch.setattr(module_setup, 'activate_module_set', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('activation interrupted')))
    with pytest.raises(OSError, match='interrupted'): initialize_module_layout(request)
    before = context.database_path.read_bytes()
    assert not (context.program_root / 'active.json').exists()
    monkeypatch.setattr(module_setup, 'activate_module_set', activate)
    initialize_module_layout(request)
    assert context.database_path.read_bytes() == before
    assert read_module_set(context).release_id == 11


def test_setup_assembles_upgrade_before_creating_new_database(context):
    from picsyncra.sqlite_store import SCHEMA_VERSION
    from picsyncra.installation.module_state import activate_module_set
    request = strict_layout(context, SCHEMA_VERSION)
    initialize_module_layout(request); commit_setup(context)
    previous = read_module_set(context)
    # A later packaged tag causes a merged revision that is not yet assembled.
    from dataclasses import replace
    from picsyncra.installation.module_state import make_module_set, publish_module_set
    from picsyncra.installation.module_content import ModuleContentStore
    packaged = make_module_set(1, 12, tuple(replace(module, source_release_id=12, source_tag='v12') for module in previous.modules))
    store = ModuleContentStore(context); store.import_bytes(b'code'); store.assemble(packaged); publish_module_set(context, packaged)
    (context.program_root / 'module-initial-layout.json').write_text(json.dumps(
        dict(schema=1, channel='dev', base=packaged.set_id, local=packaged.set_id)))
    new_path = context.state_root / 'new-data' / 'new.sqlite'
    (context.state_root / 'setup-preflight-state.json').write_text(json.dumps(dict(
        marker=json.loads((context.program_root / 'active.json').read_text()), database_path=str(context.database_path))))
    initialize_module_layout(dict(request, database_path=str(new_path)))
    assert new_path.exists()
    assert read_module_set(context).revision == previous.revision + 1


def test_failed_upgrade_to_new_database_restores_original_config_and_registration(context, monkeypatch):
    from picsyncra.sqlite_store import SCHEMA_VERSION
    from dataclasses import replace
    from types import SimpleNamespace
    from picsyncra.installation.setup_lifecycle import rollback_setup
    request = strict_layout(context, SCHEMA_VERSION)
    initialize_module_layout(request); commit_setup(context)
    previous = read_module_set(context)
    (context.config_root / 'config.json').write_text('{"retain":"original"}')
    (context.state_root / 'setup-preflight-state.json').write_text(json.dumps(dict(
        marker=json.loads((context.program_root / 'active.json').read_text()), database_path=str(context.database_path))))
    new_path = context.state_root / 'new.sqlite'
    initialize_module_layout(dict(request, database_path=str(new_path)))
    (context.config_root / 'config.json').write_text('{"retain":"candidate-changed"}')
    writes = []
    monkeypatch.setattr('picsyncra.installation.setup_cli.WindowsRegistryWriter',
        lambda: SimpleNamespace(set_value=lambda *args: writes.append(args)))
    assert rollback_setup(replace(context, database_path=new_path))
    assert json.loads((context.config_root / 'config.json').read_text()) == {'retain':'original'}
    assert read_module_set(context) == previous
    assert writes[-1][1:] == ('DatabasePath', str(context.database_path))


def test_existing_install_with_missing_database_does_not_create_empty_replacement(context):
    from picsyncra.sqlite_store import SCHEMA_VERSION
    request = strict_layout(context, SCHEMA_VERSION)
    initialize_module_layout(request); commit_setup(context)
    marker = (context.program_root / 'active.json').read_bytes()
    context.database_path.unlink()
    with pytest.raises(ValueError, match='istniejącej instalacji'): initialize_module_layout(request)
    assert not context.database_path.exists()
    assert (context.program_root / 'active.json').read_bytes() == marker


def test_failed_switch_to_existing_database_restores_both_databases(context, monkeypatch):
    from picsyncra.sqlite_store import SCHEMA_VERSION, SqliteStore
    from dataclasses import replace
    from types import SimpleNamespace
    from picsyncra.installation.setup_lifecycle import rollback_setup
    request = strict_layout(context, SCHEMA_VERSION)
    initialize_module_layout(request); commit_setup(context)
    previous = read_module_set(context)
    original = SqliteStore(str(context.database_path))
    original.save_config({'retain': 'original'})
    selected_path = context.state_root / 'selected.sqlite'
    selected = SqliteStore(str(selected_path)); selected.initialize()
    selected.save_config({'retain': 'selected'})
    (context.config_root / 'config.json').write_text('{"retain":"original"}')
    (context.state_root / 'setup-preflight-state.json').write_text(json.dumps(dict(
        marker=json.loads((context.program_root / 'active.json').read_text()), database_path=str(context.database_path))))
    initialize_module_layout(dict(request, database_path=str(selected_path)))
    selected.save_config({'retain': 'candidate-changed'})
    (context.config_root / 'config.json').write_text('{"retain":"candidate-changed"}')
    writes = []
    monkeypatch.setattr('picsyncra.installation.setup_cli.WindowsRegistryWriter',
        lambda: SimpleNamespace(set_value=lambda *args: writes.append(args)))
    assert rollback_setup(replace(context, database_path=selected_path))
    assert original.load_config() == {'retain': 'original'}
    assert selected.load_config() == {'retain': 'selected'}
    assert json.loads((context.config_root / 'config.json').read_text()) == {'retain': 'original'}
    assert read_module_set(context) == previous
    assert writes[-1][1:] == ('DatabasePath', str(context.database_path))


def test_setup_upgrades_unpinned_modules_and_retains_optional_modules_and_pins(context):
    from picsyncra.installation.module_state import make_module_set, publish_module_set, activate_module_set
    from picsyncra.installation.module_manifest import parse_module_manifest
    from tests.module_fixtures import release_payload, module_payload
    from picsyncra.installation.module_content import ModuleContentStore
    old = staged(context, 1, frozenset({'core'}))
    optional = parse_module_manifest(release_payload(modules=[module_payload(),
        module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe'),
        module_payload('ocr_models', 'models/ocr/model.bin')])).modules[-1]
    old = make_module_set(1, old.release_id, old.modules + (optional,), old.pinned)
    store = ModuleContentStore(context)
    store.import_bytes(b'code')
    store.assemble(old); publish_module_set(context, old)
    activate_module_set(context, old, expected_revision=0)
    request = layout(context, 'dev')
    newer = parse_module_manifest(release_payload(7, modules=[module_payload(source=7),
        module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe', b'new', source=7)])).modules
    packaged = make_module_set(1, 7, newer)
    store.import_bytes(b'new'); store.assemble(packaged); publish_module_set(context, packaged)
    (context.program_root / 'module-initial-layout.json').write_text(json.dumps(
        dict(schema=1, channel='dev', base=packaged.set_id, local=packaged.set_id)))
    initialize_module_layout(request)
    active = read_module_set(context)
    assert active.revision == 2 and active.release_id == 7
    assert active.pinned == old.pinned
    modules = {m.module_id: m for m in active.modules}
    assert modules['core'] == old.modules[0]
    assert modules['ocr_models'] == optional
    assert modules['migrator'].source_tag == 'v7'
    assert (context.program_root / 'sets' / active.set_id / 'apps/migrator/PicSyncra-Migrator.exe').read_bytes() == b'new'
    commit_setup(context)
    initialize_module_layout(request)
    assert read_module_set(context) == active  # Repair is a no-op.


def layout(context, channel):
    # Metadata/upgrade tests use an existing schema-1 fixture. Real fresh DB
    # creation uses the strict current-schema package tested above.
    if not context.database_path.exists():
        import sqlite3
        with sqlite3.connect(context.database_path) as db:
            db.executescript('CREATE TABLE schema_version(version INTEGER); INSERT INTO schema_version VALUES(1);'
                            'CREATE TABLE app_config_values(value TEXT);')
        db.close()
    selected = staged(context, 1, frozenset({'core'}))
    (context.program_root / 'module-initial-layout.json').write_text(json.dumps(
        dict(schema=1, channel=channel, base=selected.set_id, local=selected.set_id)))
    return dict(installation_id=context.installation_id, program_root=str(context.program_root),
                state_root=str(context.state_root), database_path=str(context.database_path), include_local=False)


@pytest.mark.parametrize('channel', ['stable', 'dev'])
def test_first_install_uses_packaged_channel_and_repair_preserves_user_choice(context, channel):
    request = layout(context, channel)
    initialize_module_layout(request)
    path = context.state_root / 'installation-settings.json'
    assert json.loads(path.read_text())['channel'] == channel
    commit_setup(context)
    active = read_module_set(context)
    opposite = 'stable' if channel == 'dev' else 'dev'
    path.write_text(json.dumps(dict(channel=opposite, extra='retain')))
    initialize_module_layout(request)
    assert json.loads(path.read_text()) == dict(channel=opposite, extra='retain')
    assert read_module_set(context) == active


def test_upgrade_preserves_existing_explicit_channel(context):
    request = layout(context, 'dev')
    path = context.state_root / 'installation-settings.json'
    path.write_text('{"channel":"stable","extra":"retain"}')
    initialize_module_layout(request)
    assert json.loads(path.read_text()) == dict(channel='stable', extra='retain')


def test_invalid_packaged_channel_cannot_activate_modules(context):
    request = layout(context, '../invalid')
    with pytest.raises(ValueError, match='channel'):
        initialize_module_layout(request)
    assert not (context.program_root / 'active.json').exists()


def test_repair_does_not_silently_accept_missing_active_file(context):
    request = layout(context, 'dev')
    initialize_module_layout(request)
    commit_setup(context)
    previous = read_module_set(context)
    missing = context.program_root / 'sets' / previous.set_id / previous.modules[0].files[0].path
    missing.unlink()
    with pytest.raises(RuntimeError, match='unavailable'):
        initialize_module_layout(request)
    assert read_module_set(context) == previous


def test_failed_setup_can_restore_previous_set_once_and_success_prevents_stale_rollback(context):
    from picsyncra.installation.module_state import make_module_set, publish_module_set
    from picsyncra.installation.module_manifest import parse_module_manifest
    from picsyncra.installation.module_content import ModuleContentStore
    from picsyncra.installation.setup_lifecycle import rollback_setup, commit_setup
    from tests.module_fixtures import release_payload, module_payload
    request = layout(context, 'dev')
    initialize_module_layout(request)
    commit_setup(context)
    previous = read_module_set(context)
    packaged = make_module_set(1, 8, parse_module_manifest(release_payload(8, modules=[module_payload(source=8),
        module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe', b'new', source=8)])).modules)
    store = ModuleContentStore(context)
    store.import_bytes(b'code'); store.import_bytes(b'new'); store.assemble(packaged)
    publish_module_set(context, packaged)
    (context.program_root / 'module-initial-layout.json').write_text(json.dumps(
        dict(schema=1, channel='dev', base=packaged.set_id, local=packaged.set_id)))
    initialize_module_layout(request)
    assert read_module_set(context).release_id == 8
    assert rollback_setup(context) is True
    assert read_module_set(context) == previous
    assert rollback_setup(context) is False
    initialize_module_layout(request)
    commit_setup(context)
    assert rollback_setup(context) is False
    assert read_module_set(context).release_id == 8


def test_initialize_cannot_erase_pending_setup_recovery(context):
    request = layout(context, 'dev')
    initialize_module_layout(request)
    path = context.state_root / 'module-setup-result.json'
    receipt = path.read_bytes()
    with pytest.raises(RuntimeError, match='Setup'):
        initialize_module_layout(request)
    assert path.read_bytes() == receipt


def test_rollback_accepts_interruption_before_target_activation(context):
    from picsyncra.installation.setup_lifecycle import rollback_setup
    initialize_module_layout(layout(context, 'dev'))
    commit_setup(context)
    marker = json.loads((context.program_root / 'active.json').read_text())
    (context.state_root / 'module-setup-result.json').write_text(json.dumps(dict(
        state='activating', changed=True, previous_marker=marker, target_set_id='not-yet-active',
        previous_autostart=False)))
    assert rollback_setup(context)
    assert json.loads((context.program_root / 'active.json').read_text()) == marker
    assert json.loads((context.state_root / 'controller-settings.json').read_text())['autostart'] is False
