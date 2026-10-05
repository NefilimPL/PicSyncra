import importlib
import sys
import pytest
from picsyncra.installation.module_bootstrap import SelectedModuleFinder
from picsyncra.installation.module_content import ModuleContentStore
from picsyncra.installation.module_state import make_module_set
from picsyncra.installation.module_manifest import parse_module_manifest
from tests.module_fixtures import module_payload, release_payload
from tests.test_module_state import context


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
