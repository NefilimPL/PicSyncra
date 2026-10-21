"""Verify a completed local publication before uploading any release assets."""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from picsyncra.installation.module_source import MANIFEST_NAME
from picsyncra.installation.module_manifest import parse_module_manifest, verify_module_manifest
from picsyncra.installation.release_keys import trusted_release_keys
from picsyncra.installation.module_filesystem import safe_path


def verify_assets(root, *, signed=False):
    import json
    raw=safe_path(root,MANIFEST_NAME).read_bytes()
    if signed:
        release=verify_module_manifest(raw,safe_path(root,MANIFEST_NAME+'.sig').read_bytes(),trusted_release_keys(),
            key_id=safe_path(root,MANIFEST_NAME+'.key-id').read_text(encoding='ascii').strip())
    else: release=parse_module_manifest(json.loads(raw))
    checked=set()
    for module in release.modules:
        if module.source_release_id!=release.release_id or module.source_tag!=release.tag:
            raise ValueError('This local publisher does not accept unverified historical assets.')
        for file in module.files:
            key=(file.sha256,file.size,file.asset_name,file.asset_offset,file.asset_size)
            if key in checked: continue
            path=safe_path(root,file.asset_name)
            if path.stat().st_size!=file.asset_size: raise ValueError('Content pack size mismatch.')
            digest=hashlib.sha256(); remaining=file.size
            with path.open('rb') as stream:
                stream.seek(file.asset_offset)
                while remaining:
                    data=stream.read(min(1024*1024,remaining))
                    if not data: raise ValueError('Incomplete content pack.')
                    digest.update(data); remaining-=len(data)
            if digest.hexdigest()!=file.sha256: raise ValueError('Content pack hash mismatch.')
            checked.add(key)
    return release


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--signed',action='store_true')
    args=parser.parse_args()
    release=verify_assets(args.assets,signed=args.signed)
    print(f'Verified release {release.release_id}: {len(release.modules)} independently owned modules.')

if __name__=='__main__': main()
