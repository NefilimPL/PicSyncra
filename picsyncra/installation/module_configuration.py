"""Inspect managed configuration without importing selected application code."""
import json
from .module_filesystem import safe_path


class ModuleConfigurationError(RuntimeError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate configuration key')
        result[key] = value
    return result


def inspect_configuration(root):
    root = safe_path(root)
    schema = 1  # The validated historic unversioned JSON format.
    try:
        if not root.is_dir(): raise ValueError('Configuration directory is missing')
        for candidate in root.rglob('*'):
            path = safe_path(root, candidate.relative_to(root).as_posix())
            if not path.is_file() or path.suffix.lower() != '.json': continue
            if path.stat().st_size > 64 * 1024 * 1024: raise ValueError('Configuration document is too large')
            value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object,
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))
            relative = path.relative_to(root).as_posix()
            if relative in {'config.json', 'local_settings.json'} and not isinstance(value, dict):
                raise ValueError('Settings must be a JSON object')
            if relative == 'module-config-schema.json':
                if not isinstance(value, dict) or set(value) != {'schema'} or type(value['schema']) is not int or value['schema'] < 1:
                    raise ValueError('Invalid configuration schema descriptor')
                schema = value['schema']
    except (OSError, ValueError, UnicodeError) as exc:
        raise ModuleConfigurationError('Nie można potwierdzić formatu konfiguracji; popraw pliki lub wybierz zweryfikowaną kopię.') from exc
    return schema
