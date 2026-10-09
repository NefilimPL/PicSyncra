import json
import pytest
from picsyncra.installation.module_setup import initialize_module_layout
from picsyncra.installation.module_state import read_module_set
from tests.test_module_state import context, staged


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
