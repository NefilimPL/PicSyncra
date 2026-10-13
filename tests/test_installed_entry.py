from pathlib import Path
import pytest
from tests.test_module_state import context


def test_direct_entry_uses_active_host_without_launcher_or_catalog(context, monkeypatch):
    from picsyncra.installation import installed_entry
    from picsyncra.installation.module_state import module_set_root, make_module_set, activate_module_set
    from picsyncra.installation.module_manifest import parse_module_manifest
    from picsyncra.installation.module_content import ModuleContentStore
    from tests.module_fixtures import module_payload, release_payload
    release = parse_module_manifest(release_payload(modules=[module_payload(path='apps/web/PicSyncra-WEB.exe'),
        module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe')]))
    selected = make_module_set(1, 5, release.modules)
    store = ModuleContentStore(context); store.import_bytes(b'code'); store.assemble(selected)
    activate_module_set(context, selected, expected_revision=0)
    executable = context.program_root / 'apps/PicSyncra.exe'
    executable.parent.mkdir(); executable.write_bytes(b'entry')
    monkeypatch.setattr(installed_entry, 'load_registered_install_context', lambda _: context)
    calls = []
    monkeypatch.setattr(installed_entry.subprocess, 'Popen', lambda args, **kwargs: calls.append((args, kwargs)))
    target = module_set_root(context, selected) / 'apps/web/PicSyncra-WEB.exe'
    web_entry = executable.with_name('PicSyncra-WEB.exe'); web_entry.write_bytes(b'entry')
    installed_entry.open_application(web_entry)
    assert calls == [([str(target)], {'cwd': target.parent})]
    newer = make_module_set(2, 5, release.modules)
    store.assemble(newer); activate_module_set(context, newer, expected_revision=1)
    target = module_set_root(context, newer) / 'apps/web/PicSyncra-WEB.exe'
    installed_entry.open_application(web_entry)
    assert calls[-1][0] == [str(target)]
    target.write_bytes(b'corrupt')
    with pytest.raises(RuntimeError): installed_entry.open_application(web_entry)
    assert len(calls) == 2
    foreign = context.state_root / 'PicSyncra-WEB.exe'; foreign.write_bytes(b'entry')
    with pytest.raises(RuntimeError): installed_entry.open_application(foreign)


def test_shortcuts_point_to_application_entries_not_module_launcher():
    source = (Path(__file__).resolve().parents[1] / 'installer/PicSyncra.iss').read_text(encoding='utf-8')
    icons = source.split('[Icons]')[1].split('[Run]')[0]
    app_icons = [line for line in icons.splitlines() if 'Name:' in line and 'Aktualizator' not in line]
    assert len(app_icons) == 6
    assert all('launcher\\' not in line and '{app}\\apps\\' in line for line in app_icons)
