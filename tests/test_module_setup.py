import json
import pytest
from picsyncra.installation.module_setup import initialize_module_layout
from picsyncra.installation.module_state import read_module_set
from picsyncra.installation.setup_lifecycle import commit_setup
from tests.test_module_state import context, staged


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
