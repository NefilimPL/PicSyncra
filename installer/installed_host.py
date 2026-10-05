"""Thin installed host. Portable entrypoints intentionally remain separate."""
import multiprocessing
import sys
from pathlib import Path

if __name__ == '__main__':
    multiprocessing.freeze_support()
    if '--module-migrate' in sys.argv:
        import argparse
        from picsyncra.install_paths import load_registered_install_context
        from picsyncra.installation.module_migrations import run_staged_migrations
        parser = argparse.ArgumentParser()
        parser.add_argument('--module-migrate', required=True)
        parser.add_argument('--installation-id', required=True)
        args = parser.parse_args()
        context = load_registered_install_context(args.installation_id)
        if context is None: raise RuntimeError('Migration requires a registered installation.')
        run_staged_migrations(context, args.module_migrate)
        raise SystemExit(0)
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
