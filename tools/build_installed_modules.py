"""Build disjoint module payloads and bounded raw content packs for HTTP ranges."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from picsyncra.installation.module_definition import module_definitions, module_owner
from picsyncra.installation.module_manifest import module_version_id, parse_module_version, parse_module_manifest
from picsyncra.installation.module_filesystem import atomic_json
from picsyncra.installation.module_state import make_module_set, module_set_payload


def build_module_payloads(source_root: Path, build_root: Path, *, release_id=1, tag='v1', compatibility_path=None):
    source_root, build_root = Path(source_root), Path(build_root)
    contracts = json.loads(Path(compatibility_path or ROOT/'installer/module-compatibility.json').read_text(encoding='utf-8'))
    if contracts.get('schema') != 1 or set(contracts.get('modules', {})) != {m.module_id for m in module_definitions()}:
        raise ValueError('Missing explicit module compatibility contracts.')
    build_root.mkdir(parents=True, exist_ok=True)
    grouped = {}
    files = []
    for path in sorted(source_root.rglob('*')):
        if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0) & 1024: raise ValueError('Linked build payload is not allowed.')
        if not path.is_file(): continue
        relative = path.relative_to(source_root).as_posix()
        if '__pycache__' in path.parts or path.suffix == '.pyc': continue
        owner = module_owner(relative)
        files.append((owner, relative, path))
    # Pack order and identity depend only on bytes. Locations are signed but do
    # not affect module identity. Max 1 GiB ensures GitHub's <2 GiB asset limit.
    pack_limit = 1024**3
    chunk, length, locations = [], 0, {}
    def flush():
        nonlocal chunk, length
        if not chunk: return
        temporary = build_root / (uuid4().hex + '.pack')
        digest=hashlib.sha256()
        with temporary.open('xb') as stream:
            for sha, path, size, offset in chunk:
                with path.open('rb') as source:
                    while data := source.read(1024*1024): stream.write(data); digest.update(data)
        name='content-'+digest.hexdigest()+'.bin'
        target=build_root/name
        if target.exists(): temporary.unlink()
        else: temporary.rename(target)
        for sha, path, size, offset in chunk: locations[sha]=(name,offset,length)
        chunk=[]; length=0
    descriptors=[]
    for owner, relative, path in files:
        size=path.stat().st_size
        if size > pack_limit: raise ValueError('A module file exceeds the supported content range size.')
        with path.open('rb') as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()
        descriptors.append((owner,relative,sha,size))
        if sha in locations or any(item[0] == sha for item in chunk): continue
        if length+size > pack_limit: flush()
        chunk.append((sha,path,size,length)); length+=size
    flush()
    for owner,relative,sha,size in descriptors:
        name,offset,total=locations[sha]
        grouped.setdefault(owner,[]).append(dict(path=relative,sha256=sha,size=size,asset_name=name,asset_offset=offset,asset_size=total))
    versions=[]
    for owner in sorted(grouped):
        payload=dict(contracts['modules'][owner],module_id=owner,version_id='',display_version='',
                     files=grouped[owner],source_release_id=release_id,source_tag=tag)
        payload['version_id']=module_version_id(payload)
        payload['display_version']=f"{payload['api']}.{payload['version_id'][:12]}"
        versions.append(parse_module_version(payload))
    if not {'core','migrator'} <= set(grouped): raise ValueError('The required hosts are missing.')
    if len(list(build_root.glob('content-*.bin'))) > 900: raise ValueError('Too many GitHub release assets.')
    return tuple(versions)


def generate_module_release_manifest(*, release_metadata, modules, migrations=()):
    versions=[]
    for module in modules:
        payload=asdict(module)
        for key in ('files','requirements','conflicts'): payload[key]=list(payload[key])
        versions.append(payload)
    payload=dict(release_metadata,schema=2,platform='windows-x64',minimum_controller=2,minimum_launcher=2,
                 modules=versions,migrations=list(migrations))
    parse_module_manifest(payload)
    return json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()


def prepare_layout(dist_root, *, release_id, tag, commit, channel='stable', source_branch='main', published_at=None):
    from picsyncra.installation.module_filesystem import safe_path
    dist_root=Path(dist_root).absolute()
    payload=safe_path(dist_root,'module-payload')
    if payload.exists(): shutil.rmtree(payload)
    payload.mkdir()
    for path in (ROOT/'picsyncra').rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix=='.pyc': continue
        relative=path.relative_to(ROOT).as_posix()
        if relative.startswith('picsyncra/installation/') or relative in {'picsyncra/install_paths.py','picsyncra/__init__.py'}: continue
        target=payload/relative; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(path,target)
    for name,folder in (('PicSyncra-WEB','web'),('PicSyncra-Migrator','migrator'),('PicSyncra','local')):
        shutil.copytree(safe_path(dist_root,name),payload/'apps'/folder)
    shutil.copyfile(ROOT/'PicSyncra.pyw',payload/'apps/local/entry.pyw')
    ocr=dist_root/'PicSyncra-OCR'
    if ocr.exists():
        shutil.copytree(ocr,payload/'runtime/ocr',ignore=shutil.ignore_patterns('ocr_models'))
        models=ocr/'_internal/ocr_models'
        if not models.is_dir(): raise ValueError('OCR runtime is missing independently packaged models.')
        shutil.copytree(models,payload/'models/ocr')
    assets=safe_path(dist_root,'module-assets')
    if assets.exists(): shutil.rmtree(assets)
    modules=build_module_payloads(payload,assets,release_id=release_id,tag=tag)
    metadata=dict(release_id=release_id,tag=tag,commit=commit,channel=channel,source_branch=source_branch,
                  prerelease=channel=='dev',published_at=published_at or datetime.now(timezone.utc).isoformat())
    migrations=json.loads((ROOT/'installer/module-compatibility.json').read_text(encoding='utf-8')).get('migrations',[])
    manifest=generate_module_release_manifest(release_metadata=metadata,modules=modules,migrations=migrations)
    (assets/'PicSyncra-modules-manifest.json').write_bytes(manifest)
    base=tuple(m for m in modules if m.module_id not in {'local','ocr_runtime','ocr_models'})
    layouts={}
    for variant, chosen in (('base',base),('local',base+tuple(m for m in modules if m.module_id=='local'))):
        selected=make_module_set(1,release_id,chosen)
        root=safe_path(dist_root,'module-sets/'+selected.set_id)
        if root.exists(): shutil.rmtree(root)
        root.mkdir(parents=True)
        for module in chosen:
            for file in module.files:
                target=root/file.path; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(payload/file.path,target)
        atomic_json(root/'module-set.json',module_set_payload(selected))
        layouts[variant]=selected.set_id
    atomic_json(dist_root/'module-initial-layout.json',dict(schema=1,release_id=release_id,channel=channel,**layouts),replace=True)
    return layouts


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--dist-root',type=Path,required=True)
    parser.add_argument('--release-id',type=int,required=True)
    parser.add_argument('--tag',required=True)
    parser.add_argument('--commit',required=True)
    parser.add_argument('--channel',choices=('stable','dev'),default='stable')
    parser.add_argument('--source-branch',default='main')
    parser.add_argument('--published-at')
    args=parser.parse_args(argv)
    prepare_layout(args.dist_root,release_id=args.release_id,tag=args.tag,commit=args.commit,
                   channel=args.channel,source_branch=args.source_branch,published_at=args.published_at)
    return 0

if __name__=='__main__': raise SystemExit(main())
