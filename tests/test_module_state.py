import json
from dataclasses import replace
from pathlib import Path
import pytest
from picsyncra.installation.contracts import InstallContext
from picsyncra.installation.module_manifest import parse_module_manifest
from picsyncra.installation.module_state import make_module_set, publish_module_set, read_module_set, activate_module_set, ModuleStateError
from picsyncra.installation.update_helper import read_active_release
from tests.module_fixtures import release_payload


@pytest.fixture
def context(tmp_path):
    root = tmp_path / 'program'
    root.mkdir()
    state = tmp_path / 'state'
    state.mkdir()
    return InstallContext('test', root, state, state / 'config', state / 'db.sqlite')


def staged(context, revision, pinned=frozenset()):
    release = parse_module_manifest(release_payload())
    selected = make_module_set(revision, release.release_id, release.modules, pinned)
    root = context.program_root / 'sets' / selected.set_id
    for module in selected.modules:
        for file in module.files:
            path = root / file.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'code')
    publish_module_set(context, selected)
    return selected


def test_stale_activation_keeps_previous_set_and_pins(context):
    previous = staged(context, 1, frozenset({'core'}))
    activate_module_set(context, previous, expected_revision=0)
    target = staged(context, 2)
    with pytest.raises(ModuleStateError):
        activate_module_set(context, target, expected_revision=0)
    assert read_module_set(context) == previous
    assert read_active_release(context) == 5
    activate_module_set(context, target, expected_revision=1)
    assert read_module_set(context).pinned == frozenset()


def test_legacy_upgrade_is_explicit_and_foreign_marker_rejected(context):
    marker = context.program_root / 'active.json'
    marker.write_text(json.dumps(dict(schema=1, installation_id='foreign', release_id=1)))
    target = staged(context, 1)
    with pytest.raises(ModuleStateError):
        activate_module_set(context, target, expected_revision=0)
    marker.write_text(json.dumps(dict(schema=1, installation_id='test', release_id=1)))
    activate_module_set(context, target, expected_revision=0)
    assert read_module_set(context) == target


def test_missing_or_modified_set_is_never_activated(context):
    target = staged(context, 1)
    metadata = context.program_root / 'sets' / target.set_id / 'module-set.json'
    data = json.loads(metadata.read_text())
    data['pinned'] = ['core']
    metadata.write_text(json.dumps(data))
    with pytest.raises(ModuleStateError):
        activate_module_set(context, target, expected_revision=0)
    assert not (context.program_root / 'active.json').exists()


def test_registry_resolver_accepts_only_active_set_executables(context, monkeypatch):
    from picsyncra import install_paths
    target = staged(context, 1)
    activate_module_set(context, target, expected_revision=0)
    root = context.program_root / 'sets' / target.set_id
    executable = root / 'apps/web/PicSyncra-WEB.exe'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'exe')
    monkeypatch.setattr(install_paths, '_read_hklm_registrations', lambda: [dict(
        installation_id='test', program_root=str(context.program_root),
        state_root=str(context.state_root), database_path=str(context.database_path))])
    assert install_paths.resolve_install_context(executable) == context
    unrelated = context.program_root / 'other.exe'
    unrelated.write_bytes(b'exe')
    assert install_paths.resolve_install_context(unrelated) is None
