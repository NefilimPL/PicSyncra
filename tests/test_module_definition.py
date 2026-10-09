from pathlib import Path

import pytest

from picsyncra.installation.module_definition import module_definitions, module_owner, validate_owned_paths


def test_independent_service_ownership():
    assert module_owner('picsyncra/services/ftp_service.py') == 'ftp'
    assert module_owner('picsyncra/services/sql_service.py') == 'sql'
    assert module_owner('picsyncra/services/pimcore_service.py') == 'pimcore'
    assert module_owner('picsyncra/services/image_dimensions.py') == 'ocr'
    assert module_owner('picsyncra/web/static/slot-ui.js') == 'slots'
    assert module_owner('picsyncra/web/static/settings-ui.js') == 'settings'
    assert module_owner('picsyncra/web/static/ocr-diagnostics.js') == 'ocr_tester'
    assert module_owner('picsyncra/web/static/app.js') == 'web_ui'
    assert module_owner('picsyncra/data_store.py') == 'core'
    assert module_owner('picsyncra/offline_migrator_gui.py') == 'migrator'
    assert module_owner('picsyncra/offline_legacy_sqlite_migrator.py') == 'migrator'
    assert module_owner('picsyncra/offline_legacy_profile_migrator.py') == 'migrator'
    assert module_owner('picsyncra/offline_migrator_processes.py') == 'migrator'
    assert module_owner('picsyncra/app.py') == 'local'
    assert module_owner('picsyncra/desktop_data_loader.py') == 'local'


def test_stable_infrastructure_and_generators_are_not_payload():
    for path in ('picsyncra/installation/controller.py', 'picsyncra/install_paths.py',
                 'Generator exe/build_web_exe.ps1', 'picsyncra/__pycache__/app.pyc'):
        with pytest.raises(ValueError):
            module_owner(path)


def test_every_source_payload_has_one_registered_owner():
    root = Path(__file__).parents[1]
    identifiers = {item.module_id for item in module_definitions()}
    assert len(identifiers) == 13
    for path in (root / 'picsyncra').rglob('*'):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and path.suffix == '.py' and '/installation/' not in relative and '__pycache__' not in relative and path.name != 'install_paths.py':
            assert module_owner(relative) in identifiers


@pytest.mark.parametrize('paths', [
    ['picsyncra/settings.py', 'picsyncra/settings.py'],
    ['picsyncra/settings.py', 'picsyncra/SETTINGS.py'],
    ['../outside.py'], ['//server/share/code.py'], ['picsyncra/web/static/CON'],
])
def test_ambiguous_or_unsafe_payload_paths_are_rejected(paths):
    with pytest.raises(ValueError):
        validate_owned_paths(paths)
