"""The active module selection gates features before application imports."""
from pathlib import Path
import os
import runpy
import sys
from types import ModuleType, SimpleNamespace
import pytest
from tests.test_module_state import context


@pytest.mark.parametrize('modules,expected', [([], '0'), (['ocr_runtime'], '0'),
    (['ocr_models'], '0'), (['ocr_runtime','ocr_models'], '1')])
def test_installed_host_sets_ocr_feature_from_active_components_before_web_start(context, monkeypatch, modules, expected):
    from picsyncra import install_paths
    from picsyncra.installation import module_bootstrap
    selected = staged_host_features(context,modules)
    monkeypatch.setattr(install_paths, 'resolve_install_context', lambda _: context)
    monkeypatch.setattr(module_bootstrap, 'bootstrap_installed_modules', lambda *args, **kwargs: (context, selected))
    monkeypatch.setattr(sys, 'executable', 'PicSyncra-WEB.exe')
    monkeypatch.setenv('PICSYNCRA_OCR_ENABLED', '1' if expected == '0' else '0')
    observed = []
    web = ModuleType('picsyncra.web_manager')
    web.main = lambda: observed.append(os.environ.get('PICSYNCRA_OCR_ENABLED'))
    monkeypatch.setitem(sys.modules, 'picsyncra.web_manager', web)
    host = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'installer/installed_host.py'))
    host['run_application']()
    assert observed == [expected]


def staged_host_features(context, modules):
    from tests.module_fixtures import module_payload, release_payload
    from picsyncra.installation.module_manifest import parse_module_manifest
    from picsyncra.installation.module_state import make_module_set
    from picsyncra.installation.module_content import ModuleContentStore
    payload = [module_payload(),module_payload('migrator','apps/migrator/PicSyncra-Migrator.exe')]
    for name in modules:
        payload.append(module_payload(name,'runtime/ocr/PicSyncra-OCR.exe' if name == 'ocr_runtime' else 'models/ocr/model.bin'))
    selected = make_module_set(1,5,parse_module_manifest(release_payload(5,payload)).modules)
    store = ModuleContentStore(context); store.import_bytes(b'code'); store.assemble(selected)
    return selected


def test_ocr_host_separates_installed_models_from_writable_runtime_cache(context, monkeypatch):
    from picsyncra import install_paths
    from picsyncra.installation import module_bootstrap, module_state, ocr_entrypoint
    selected = staged_host_features(context, ['ocr_runtime', 'ocr_models'])
    monkeypatch.setattr(install_paths, 'resolve_install_context', lambda _: context)
    monkeypatch.setattr(module_bootstrap, 'bootstrap_installed_modules', lambda *a, **kw: (context, selected))
    monkeypatch.setattr(sys, 'executable', 'PicSyncra-OCR.exe')
    for key in ('PICSYNCRA_OCR_ENABLED', 'PICSYNCRA_OCR_MODEL_ROOT', 'PADDLE_PDX_CACHE_HOME'):
        monkeypatch.setenv(key, 'old-value')
    observed = {}
    monkeypatch.setattr(ocr_entrypoint, 'main', lambda: observed.update(os.environ))
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'installer/installed_host.py'))['run_application']()
    assert observed['PICSYNCRA_OCR_MODEL_ROOT'] == str(module_state.module_set_root(context, selected) / 'models/ocr')
    assert Path(observed['PADDLE_PDX_CACHE_HOME']).is_relative_to(context.state_root / 'cache')


@pytest.mark.parametrize('missing', ['runtime/ocr/PicSyncra-OCR.exe','models/ocr/model.bin'])
def test_missing_ocr_payload_hides_feature_even_when_manifest_lists_components(context, monkeypatch, missing):
    from picsyncra import install_paths
    from picsyncra.installation import module_bootstrap
    from picsyncra.installation.module_state import module_set_root
    selected = staged_host_features(context,['ocr_runtime','ocr_models'])
    (module_set_root(context,selected) / missing).unlink()
    monkeypatch.setattr(install_paths,'resolve_install_context',lambda _:context)
    monkeypatch.setattr(module_bootstrap,'bootstrap_installed_modules',lambda *args,**kwargs:(context,selected))
    monkeypatch.setattr(sys,'executable','PicSyncra-WEB.exe')
    monkeypatch.setenv('PICSYNCRA_OCR_ENABLED','1')
    observed = []
    web = ModuleType('picsyncra.web_manager')
    web.main = lambda: observed.append(os.environ['PICSYNCRA_OCR_ENABLED'])
    monkeypatch.setitem(sys.modules,'picsyncra.web_manager',web)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'installer/installed_host.py'))['run_application']()
    assert observed == ['0']
