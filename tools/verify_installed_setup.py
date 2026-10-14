"""Check fresh installation using the built helper before producing Setup."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from picsyncra.installation.contracts import InstallContext
from picsyncra.installation.database import inspect_database
from picsyncra.installation.module_filesystem import safe_path
from picsyncra.installation.module_state import read_module_set, parse_module_set


def verify_fresh_setup(dist_root: Path, work_root: Path):
    dist_root, work_root = dist_root.resolve(strict=True), work_root.resolve(strict=True)
    layout = json.loads(safe_path(dist_root, 'module-initial-layout.json').read_text(encoding='utf-8'))
    if ('ocr' in layout) != ('local_ocr' in layout): raise ValueError('Incomplete bundled OCR variants.')
    for variant in ('base','local','ocr','local_ocr'):
        if variant in layout: _verify_variant(dist_root, work_root, layout, variant)


def _verify_variant(dist_root, work_root, layout, variant):
    helper = safe_path(dist_root, 'helper/PicSyncra-SetupHelper.exe')
    source = safe_path(dist_root, 'module-sets/' + layout[variant])
    selected = parse_module_set(json.loads(safe_path(source, 'module-set.json').read_text(encoding='utf-8')))
    if selected.set_id != layout[variant]: raise ValueError('Invalid bundled module identity.')
    with tempfile.TemporaryDirectory(prefix='fresh-setup-', dir=work_root) as directory:
        workspace = Path(directory).resolve(strict=True)
        # This checked, newly created directory is the only recursive cleanup
        # target. The probe never registers an installation or starts a task.
        workspace.relative_to(work_root)
        program, state = workspace / 'program', workspace / 'state'
        target = program / 'sets' / selected.set_id
        target.mkdir(parents=True); state.mkdir()
        for item in source.rglob('*'):
            item = safe_path(source, item.relative_to(source).as_posix())
            destination = target / item.relative_to(source)
            if item.is_dir(): destination.mkdir(exist_ok=True)
            elif item.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Inputs are immutable and only read by initialization. Links
                # avoid copying hundreds of MB; fallback supports other volumes.
                try: os.link(item, destination)
                except OSError: shutil.copyfile(item, destination)
        (program / 'module-initial-layout.json').write_text(json.dumps(layout), encoding='utf-8')
        context = InstallContext('build-verification', program, state, state / 'config', state / 'data/picsyncra.sqlite')
        request = workspace / 'request.json'
        payload = dict(installation_id=context.installation_id, program_root=str(program),
            state_root=str(state), database_path=str(context.database_path), include_local=variant.startswith('local'))
        if 'ocr' in variant: payload['include_ocr'] = True
        request.write_text(json.dumps(payload), encoding='utf-8')
        result = subprocess.run([str(helper), 'initialize-modules', '--request', str(request)], cwd=workspace,
            env=dict(os.environ, PICSYNCRA_HEADLESS='1'), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
        if result.returncode:
            error_path = request.with_suffix('.error.txt')
            error = error_path.read_text(encoding='utf-8') if error_path.exists() else result.stderr.decode('utf-8', errors='replace')
            raise RuntimeError('Fresh Setup verification failed: ' + error)
        inspection = inspect_database(context.database_path)
        if not inspection.integrity_ok or not inspection.is_picsyncra:
            raise RuntimeError('Fresh Setup did not create a valid PicSyncra database.')
        if not all(module.database_min <= inspection.schema_version <= module.database_max for module in selected.modules):
            raise RuntimeError('Fresh Setup database schema does not satisfy the bundled modules.')
        if read_module_set(context) != selected:
            raise RuntimeError('Fresh Setup activated an unexpected module selection.')
        print(f'Fresh Setup verification passed ({variant}): database schema {inspection.schema_version}; {len(selected.modules)} modules activated.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist-root', type=Path, required=True)
    parser.add_argument('--work-root', type=Path, required=True)
    args = parser.parse_args()
    verify_fresh_setup(args.dist_root, args.work_root)


if __name__ == '__main__': main()
