import importlib
import sys
import pytest
from picsyncra.installation.module_bootstrap import SelectedModuleFinder
from picsyncra.installation.module_content import ModuleContentStore
from picsyncra.installation.module_state import make_module_set
from picsyncra.installation.module_manifest import parse_module_manifest
from tests.module_fixtures import module_payload, release_payload
from tests.test_module_state import context


def test_app_start_defers_external_ocr_files_but_never_application_code(context):
    from picsyncra.installation.module_state import verify_module_set_files, ModuleStateError, module_set_root
    modules = [module_payload(), module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe'),
               module_payload('ocr_runtime', 'runtime/ocr/PicSyncra-OCR.exe'),
               module_payload('ocr_models', 'models/ocr/model.bin')]
    selected = make_module_set(1, 5, parse_module_manifest(release_payload(5, modules)).modules)
    store = ModuleContentStore(context); store.import_bytes(b'code'); store.assemble(selected)
    root = module_set_root(context, selected)
    (root / 'models/ocr/model.bin').write_bytes(b'broken')
    verify_module_set_files(context, selected, defer_ocr_payload=True)
    with pytest.raises(ModuleStateError): verify_module_set_files(context, selected)
    (root / 'picsyncra/data_store.py').write_bytes(b'broken')
    with pytest.raises(ModuleStateError): verify_module_set_files(context, selected, defer_ocr_payload=True)


def test_installed_ocr_info_uses_selected_runtime_not_web_packages(context, monkeypatch):
    from picsyncra.services import image_dimensions
    from picsyncra import install_paths
    from picsyncra.installation.module_state import activate_module_set, module_set_root
    modules = [module_payload(), module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe'),
               module_payload('ocr_runtime', 'runtime/ocr/PicSyncra-OCR.exe'),
               module_payload('ocr_models', 'models/ocr/model.bin')]
    selected = make_module_set(1, 5, parse_module_manifest(release_payload(5, modules)).modules)
    store = ModuleContentStore(context); store.import_bytes(b'code'); store.assemble(selected)
    activate_module_set(context, selected, expected_revision=0)
    monkeypatch.setattr(install_paths, 'resolve_install_context', lambda _: context)
    monkeypatch.setattr(image_dimensions.util, 'find_spec', lambda _: pytest.fail('WEB must not inspect its own Paddle packages'))
    monkeypatch.setattr(image_dimensions, '_model_cache_has_profile', lambda path, _: path == str(module_set_root(context, selected) / 'models/ocr'))
    info = image_dimensions.image_ocr_runtime_info()
    assert info['available'] is True
    assert info['engine']['version'] == 'moduł v1'
    assert all(model['status'] == 'ready' for model in info['models'])


def test_mixed_code_loads_selected_sources_and_missing_file_never_falls_back(context):
    modules = [module_payload(), module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe'),
               module_payload('ftp', 'picsyncra/services/ftp_probe.py', b'marker = "ftp-old"'),
               module_payload('sql', 'picsyncra/services/sql_probe.py', b'marker = "sql-current"')]
    selected = make_module_set(1, 5, parse_module_manifest(release_payload(5, modules)).modules)
    store = ModuleContentStore(context)
    for data in (b'code', b'marker = "ftp-old"', b'marker = "sql-current"'): store.import_bytes(data)
    store.assemble(selected)
    finder = SelectedModuleFinder(context, selected)
    sys.meta_path.insert(0, finder)
    try:
        assert importlib.import_module('picsyncra.services.ftp_probe').marker == 'ftp-old'
        assert importlib.import_module('picsyncra.services.sql_probe').marker == 'sql-current'
        sys.modules.pop('picsyncra.services.ftp_probe')
        (context.program_root / 'sets' / selected.set_id / 'picsyncra/services/ftp_probe.py').unlink()
        with pytest.raises(ImportError): importlib.import_module('picsyncra.services.ftp_probe')
        with pytest.raises(ImportError): importlib.import_module('picsyncra.embedded_newer_fallback')
    finally:
        sys.meta_path.remove(finder)
        for name in ('picsyncra.services.ftp_probe', 'picsyncra.services.sql_probe'): sys.modules.pop(name, None)
