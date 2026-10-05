"""Thin installed host. Portable entrypoints intentionally remain separate."""
import multiprocessing
import sys
from pathlib import Path

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from picsyncra.installation.module_bootstrap import bootstrap_installed_modules
    context, selected = bootstrap_installed_modules()
    name = Path(sys.executable).stem
    if name == 'PicSyncra-WEB':
        from picsyncra.web_manager import main
        main()
    elif name == 'PicSyncra-Migrator':
        from picsyncra.offline_migrator_gui import main
        main()
    elif name == 'PicSyncra-OCR':
        import os
        from picsyncra.installation.module_state import module_set_root
        os.environ['PADDLE_PDX_CACHE_HOME'] = str(module_set_root(context, selected) / 'models/ocr')
        from picsyncra.installation.ocr_entrypoint import main
        main()
    elif name == 'PicSyncra':
        import runpy
        from picsyncra.installation.module_state import module_set_root
        runpy.run_path(str(module_set_root(context, selected) / 'apps/local/entry.pyw'), run_name='__main__')
    else:
        raise RuntimeError('Nieznany host instalacji.')
