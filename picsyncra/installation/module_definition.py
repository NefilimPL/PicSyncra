"""Disjoint ownership of code and data shipped as installed modules."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re


@dataclass(frozen=True)
class ModuleDefinition:
    module_id: str
    label: str
    optional: bool = False


_MODULES = tuple(ModuleDefinition(*item) for item in (
    ('core', 'Aplikacja i dane', False), ('ftp', 'FTP', False),
    ('sql', 'SQL', False), ('pimcore', 'Pimcore', False), ('slots', 'Sloty', False),
    ('settings', 'Ustawienia', False), ('web_ui', 'Interfejs WEB', False),
    ('ocr', 'Obsługa OCR', False), ('ocr_tester', 'Tester OCR', False),
    ('migrator', 'Migrator', False), ('local', 'LOCAL', True),
    ('ocr_runtime', 'Silnik OCR', True), ('ocr_models', 'Modele OCR', True),
))
_RESERVED = re.compile(r'^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)


def module_definitions() -> tuple[ModuleDefinition, ...]:
    return _MODULES


def validate_payload_path(value: str) -> str:
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('Invalid module file path.')
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        raise ValueError('Module paths must be normalized and relative.')
    if any(part in {'.', '..'} or part.endswith(('.', ' ')) or _RESERVED.match(part)
           or any(ord(char) < 32 or char in '<>"|?*' for char in part) for part in path.parts):
        raise ValueError('Unsafe module file path.')
    return value


def module_owner(relative_path: str) -> str:
    value = validate_payload_path(relative_path)
    if '__pycache__' in PurePosixPath(value).parts:
        raise ValueError('Bytecode cache is not an installed payload.')
    for prefix, owner in (('apps/local/', 'local'), ('apps/migrator/', 'migrator'),
                          ('runtime/ocr/', 'ocr_runtime'), ('models/ocr/', 'ocr_models'),
                          ('apps/web/', 'core'), ('runtime/shared/', 'core')):
        if value.startswith(prefix):
            return owner
    if not value.startswith('picsyncra/') or value.startswith('picsyncra/installation/') or value == 'picsyncra/install_paths.py':
        raise ValueError('File is outside installed application modules.')
    if value.startswith('picsyncra/web/static/'):
        return {'slot-ui.js': 'slots', 'settings-ui.js': 'settings',
                'ocr-diagnostics.js': 'ocr_tester', 'ocr-tester-ui.js': 'ocr_tester'}.get(PurePosixPath(value).name, 'web_ui')
    name = PurePosixPath(value).name
    if value in {'picsyncra/settings.py', 'picsyncra/storage_settings.py'}:
        return 'settings'
    if name.startswith('pimcore_') and value.startswith(('picsyncra/services/', 'picsyncra/pimcore_')):
        return 'pimcore'
    if (name.startswith('ftp_') and value.startswith('picsyncra/services/')) or name == 'desktop_ftp_preview.py':
        return 'ftp'
    if (name.startswith('sql_') and value.startswith('picsyncra/services/')) or name == 'photo_sql_batch.py':
        return 'sql'
    if name == 'image_dimensions.py' or (name.startswith('ocr_') and value.startswith(('picsyncra/services/', 'picsyncra/ocr_'))):
        return 'ocr'
    return 'core'


def validate_owned_paths(paths: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    names: set[str] = set()
    for path in paths:
        owner = module_owner(path)
        if path.casefold() in names:
            raise ValueError('Duplicate or case-colliding module path.')
        names.add(path.casefold())
        result[path] = owner
    return result
