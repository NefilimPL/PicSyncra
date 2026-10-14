from pathlib import Path
import json
import pytest
from picsyncra.installation.module_definition import module_definitions
from tools.build_installed_modules import build_module_payloads
from tests.test_module_state import context


@pytest.mark.parametrize('with_ocr', [False, True])
def test_setup_payload_variants_include_ocr_only_when_selected(tmp_path, monkeypatch, with_ocr):
    from tools import build_installed_modules as builder
    from picsyncra.installation.module_state import parse_module_set
    source = tmp_path / 'source'; source.mkdir()
    (source / 'picsyncra').mkdir(); (source / 'picsyncra/config.py').write_text('value = 1')
    (source / 'PicSyncra.pyw').write_text('pass')
    (source / 'installer').mkdir()
    import shutil
    shutil.copyfile(builder.ROOT / 'installer/module-compatibility.json', source / 'installer/module-compatibility.json')
    monkeypatch.setattr(builder, 'ROOT', source)
    dist = tmp_path / 'dist'
    for name in ('PicSyncra-WEB', 'PicSyncra-Migrator', 'PicSyncra'):
        directory = dist / name; directory.mkdir(parents=True)
        (directory / (name + '.exe')).write_bytes(b'host')
    if with_ocr:
        directory = dist / 'PicSyncra-OCR'; directory.mkdir()
        (directory / 'PicSyncra-OCR.exe').write_bytes(b'ocr-engine')
        models = directory / '_internal/ocr_models'; models.mkdir(parents=True)
        (models / 'model.bin').write_bytes(b'ocr-model')
    layouts = builder.prepare_layout(dist, release_id=11, tag='v11', commit='a' * 40)
    assert set(layouts) == ({'base', 'local', 'ocr', 'local_ocr'} if with_ocr else {'base', 'local'})
    for variant, set_id in layouts.items():
        root = dist / 'module-sets' / set_id
        selected = parse_module_set(json.loads((root / 'module-set.json').read_text()))
        ids = {m.module_id for m in selected.modules}
        assert ('local' in ids) == variant.startswith('local')
        assert {'ocr_runtime', 'ocr_models'} <= ids if 'ocr' in variant else not {'ocr_runtime', 'ocr_models'} & ids
        if 'ocr' in variant:
            assert (root / 'runtime/ocr/PicSyncra-OCR.exe').read_bytes() == b'ocr-engine'
            assert (root / 'models/ocr/model.bin').read_bytes() == b'ocr-model'
    assert json.loads((dist / 'module-initial-layout.json').read_text())['ocr_management'] == 'setup'


def test_ftp_only_edit_preserves_sql_and_model_identities_and_all_ranges_reconstruct(tmp_path):
    root=tmp_path/'payload'
    contents={'picsyncra/config.py':b'core', 'picsyncra/services/ftp_service.py':b'ftp-1',
              'picsyncra/services/sql_service.py':b'sql', 'apps/migrator/PicSyncra-Migrator.exe':b'host',
              'models/ocr/model.bin':b'model'}
    for relative,data in contents.items():
        path=root/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
    first=build_module_payloads(root,tmp_path/'first',release_id=1,tag='v1')
    (root/'picsyncra/services/ftp_service.py').write_bytes(b'ftp-5')
    second=build_module_payloads(root,tmp_path/'second',release_id=5,tag='v5')
    before={m.module_id:m for m in first}; after={m.module_id:m for m in second}
    assert before['ftp'].version_id != after['ftp'].version_id
    assert before['sql'].version_id == after['sql'].version_id
    assert before['ocr_models'].version_id == after['ocr_models'].version_id
    for module in second:
        for file in module.files:
            with (tmp_path/'second'/file.asset_name).open('rb') as pack:
                pack.seek(file.asset_offset)
                assert pack.read(file.size)==(root/file.path).read_bytes()


def generated_release():
    from tools.build_installed_modules import generate_module_release_manifest
    from picsyncra.installation.module_manifest import parse_module_manifest
    from tests.module_fixtures import release_payload, module_payload
    fixture=release_payload(modules=[module_payload(),
        module_payload('migrator','apps/migrator/PicSyncra-Migrator.exe'),
        module_payload('ocr_runtime','runtime/ocr/PicSyncra-OCR.exe',b'engine'),
        module_payload('ocr_models','models/ocr/model.bin',b'model')])
    release=parse_module_manifest(fixture)
    metadata={key:value for key,value in fixture.items() if key not in {
        'schema','platform','minimum_controller','minimum_launcher','modules','migrations'}}
    return parse_module_manifest(json.loads(generate_module_release_manifest(
        release_metadata=metadata,modules=release.modules)))


def test_new_release_refuses_old_version_3_infrastructure_before_ocr_download():
    from picsyncra.installation.module_state import make_module_set
    from picsyncra.installation.module_contracts import ModuleEnvironment
    from picsyncra.installation.module_planner import plan_module_operation
    release=generated_release()
    active=make_module_set(1,release.release_id,tuple(m for m in release.modules if m.module_id not in {'ocr_runtime','ocr_models'}))
    plan=plan_module_operation(active,(release,),ModuleEnvironment(1,1,'cp313-win-amd64',3,3),
        action='install_ocr',selected={},excluded=frozenset(),available_hashes=frozenset())
    assert {c.code for c in plan.conflicts} >= {'controller_outdated','launcher_outdated'}


def test_current_setup_versions_accept_same_ocr_release():
    from picsyncra.installation.controller_version import CONTROLLER_VERSION,LAUNCHER_VERSION
    from picsyncra.installation.module_state import make_module_set
    from picsyncra.installation.module_contracts import ModuleEnvironment
    from picsyncra.installation.module_planner import plan_module_operation
    release=generated_release()
    active=make_module_set(1,release.release_id,tuple(m for m in release.modules if m.module_id not in {'ocr_runtime','ocr_models'}))
    plan=plan_module_operation(active,(release,),ModuleEnvironment(1,1,'cp313-win-amd64',CONTROLLER_VERSION,LAUNCHER_VERSION),
        action='install_ocr',selected={},excluded=frozenset(),available_hashes=frozenset())
    assert not plan.conflicts
    assert {'ocr_runtime','ocr_models'} <= {m.module_id for m in plan.target.modules}


def test_manifest_requirements_follow_infrastructure_version_instead_of_literals(monkeypatch):
    from picsyncra.installation import controller_version
    monkeypatch.setattr(controller_version,'CONTROLLER_VERSION',17)
    monkeypatch.setattr(controller_version,'LAUNCHER_VERSION',18,raising=False)
    release=generated_release()
    assert release.minimum_controller==17
    assert release.minimum_launcher==18


def test_service_requires_setup_before_transfer_then_installs_ocr_once(context,monkeypatch):
    from types import SimpleNamespace
    from picsyncra.installation.module_catalog import ModuleCatalogEntry
    from picsyncra.installation.module_contracts import ModuleEnvironment
    from picsyncra.installation.module_service import ModuleService
    from picsyncra.installation.module_state import make_module_set,activate_module_set,read_module_set
    from tests.test_module_executor import prepare,Controller
    from tests.test_module_content import Response
    _,store,_=prepare(context)
    release=generated_release()
    base=make_module_set(2,release.release_id,tuple(m for m in release.modules if m.module_id not in {'ocr_runtime','ocr_models'}))
    store.assemble(base); activate_module_set(context,base,expected_revision=1)
    source=SimpleNamespace(offline=False,load=lambda _: (ModuleCatalogEntry(release.release_id,release.tag,release.published_at,release),))
    service=ModuleService(context,Controller(),source=source,content=store,
        schedule=lambda work:work(),quiesce=lambda _:None,healthy=lambda:True)
    current_environment=service._environment
    monkeypatch.setattr(service,'_environment',lambda _:ModuleEnvironment(1,1,'cp313-win-amd64',3,3))
    transfers=[]
    def fetch(url,start,size,total):
        transfers.append((start,size))
        return Response(b'model' if size==5 else b'engine',start,total)
    store.fetch=fetch
    old=service.prepare(action='install_ocr',selected={},excluded=[])
    assert old['setup_release_url'].endswith('/'+release.tag)
    with pytest.raises(RuntimeError,match='konflikty'): service.execute(old['plan_id'])
    assert transfers==[] and read_module_set(context)==base
    monkeypatch.setattr(service,'_environment',current_environment)
    upgraded=service.prepare(action='install_ocr',selected={},excluded=[])
    assert not upgraded['conflicts']
    service.execute(upgraded['plan_id'])
    assert service.operation(upgraded['plan_id'])['state']=='committed'
    assert len(transfers)==2
    assert {'ocr_runtime','ocr_models'}<={m.module_id for m in read_module_set(context).modules}
