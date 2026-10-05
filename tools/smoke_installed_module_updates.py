"""Read-only package verification and reproducible module acceptance smoke."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.verify_installed_modules import verify_assets


def main(argv=None):
    from uuid import uuid4
    parser=argparse.ArgumentParser()
    parser.add_argument('--dist-root',type=Path,default=ROOT/'dist/installed')
    args=parser.parse_args(argv)
    release=verify_assets(args.dist_root/'module-assets')
    print(f'Publication reconstructed: {len(release.modules)} modules, release {release.release_id}.')
    base=ROOT/'build'/('module-acceptance-'+uuid4().hex)
    result=subprocess.run([sys.executable,'-m','pytest','tests/test_module_updates_end_to_end.py',
        'tests/test_module_executor.py','tests/test_module_bootstrap.py','-q','--basetemp',str(base)],cwd=ROOT)
    return result.returncode

if __name__=='__main__': raise SystemExit(main())
