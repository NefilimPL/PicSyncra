"""Bounded paths and durable JSON publication in controller-owned directories."""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
from uuid import uuid4
from .module_definition import validate_payload_path


def safe_path(root: Path, relative: str = '') -> Path:
    root = Path(root).absolute()
    if relative:
        validate_payload_path(relative)
    path = root / relative
    current = path
    while True:
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if current.is_symlink() or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('Installed module path contains a reparse point.')
        if current == root:
            break
        if current.parent == current:
            raise ValueError('Module path escaped its root.')
        current = current.parent
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Module path escaped its root.')
    return path


def atomic_json(path: Path, value: object, *, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
