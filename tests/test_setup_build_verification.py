"""Check every checkbox combination before packaging an installed release."""
from pathlib import Path
import json
from types import SimpleNamespace
from tests.test_module_state import context


def test_frozen_helper_build_guard_checks_all_bundled_variants(context, monkeypatch):
    from tests.test_module_setup import optional_ocr_layout
    from picsyncra.installation.module_setup import initialize_module_layout
    from tools.verify_installed_setup import verify_fresh_setup
    import shutil
    optional_ocr_layout(context)
    dist = context.state_root / 'dist'; dist.mkdir()
    shutil.copytree(context.program_root / 'sets', dist / 'module-sets')
    shutil.copyfile(context.program_root / 'module-initial-layout.json', dist / 'module-initial-layout.json')
    (dist / 'helper').mkdir(); (dist / 'helper/PicSyncra-SetupHelper.exe').write_bytes(b'helper')
    seen = []
    def run(arguments, **kwargs):
        request = json.loads(Path(arguments[-1]).read_text(encoding='utf-8'))
        seen.append((request['include_local'], request.get('include_ocr',False)))
        initialize_module_layout(request)
        return SimpleNamespace(returncode=0,stderr=b'')
    monkeypatch.setattr('tools.verify_installed_setup.subprocess.run',run)
    verify_fresh_setup(dist,context.state_root)
    assert seen == [(False,False),(True,False),(False,True),(True,True)]
    assert not list(context.state_root.glob('fresh-setup-*'))
