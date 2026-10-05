from pathlib import Path
from picsyncra.installation.module_definition import module_definitions
from tools.build_installed_modules import build_module_payloads


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
