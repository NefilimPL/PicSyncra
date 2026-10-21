"""Strict signed manifests for independently deployable installed modules."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import re
from collections.abc import Mapping
from cryptography.exceptions import InvalidSignature

from .module_contracts import MigrationStep, ModuleFile, ModuleRelease, ModuleRequirement, ModuleVersion
from .module_definition import module_definitions, module_owner, validate_payload_path
from .release_manifest import ManifestError, _public_key

_HASH = re.compile(r'[a-f0-9]{64}')
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
_MODULE_IDS = {item.module_id for item in module_definitions()}


def _object(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ManifestError('Invalid module manifest fields.')
    return value


def _text(value, *, identifier=False):
    if not isinstance(value, str) or not value or len(value) > 256 or value.strip() != value or any(ord(c) < 32 for c in value):
        raise ManifestError('Invalid module manifest text.')
    if identifier and not _ID.fullmatch(value):
        raise ManifestError('Invalid module identifier.')
    return value


def _integer(value, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value < 2**63:
        raise ManifestError('Invalid module manifest integer.')
    return value


def _list(value):
    if not isinstance(value, list):
        raise ManifestError('Module manifest expects an array.')
    return value


def module_version_id(payload: dict | ModuleVersion) -> str:
    data = asdict(payload) if isinstance(payload, ModuleVersion) else payload
    identity = {key: value for key, value in data.items() if key not in
                {'version_id', 'display_version', 'source_release_id', 'source_tag'}}
    identity['files'] = sorted(({key: value for key, value in file.items() if key in {'path', 'size', 'sha256'}}
                                for file in data['files']), key=lambda f: f['path'])
    for key in ('requirements', 'conflicts'):
        identity[key] = sorted(identity[key], key=lambda item: item['module_id'])
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _requirements(value):
    result = []
    names = set()
    for item in _list(value):
        _object(item, ('module_id', 'minimum_api', 'maximum_api'))
        name = _text(item['module_id'])
        lo, hi = _integer(item['minimum_api'], 1), _integer(item['maximum_api'], 1)
        if name not in _MODULE_IDS or name in names or lo > hi:
            raise ManifestError('Invalid or duplicate module dependency.')
        names.add(name)
        result.append(ModuleRequirement(name, lo, hi))
    return tuple(result)


def parse_module_version(payload: object) -> ModuleVersion:
    keys = ModuleVersion.__dataclass_fields__
    item = _object(payload, keys)
    name = _text(item['module_id'])
    if name not in _MODULE_IDS:
        raise ManifestError('Unsupported installed module.')
    files = []
    seen = set()
    for file in _list(item['files']):
        _object(file, ModuleFile.__dataclass_fields__)
        try:
            path = validate_payload_path(file['path'])
            if module_owner(path) != name:
                raise ValueError('File belongs to a different module.')
        except ValueError as exc:
            raise ManifestError(str(exc)) from exc
        checksum = _text(file['sha256'])
        asset = _text(file['asset_name'], identifier=True)
        size, offset, total = (_integer(file[key]) for key in ('size', 'asset_offset', 'asset_size'))
        if not _HASH.fullmatch(checksum) or path.casefold() in seen or offset + size > total or total >= 2 * 1024**3:
            raise ManifestError('Invalid module file identity or content range.')
        if size == 0 and checksum != hashlib.sha256(b'').hexdigest():
            raise ManifestError('Empty file checksum is invalid.')
        seen.add(path.casefold())
        files.append(ModuleFile(path, checksum, size, asset, offset, total))
    if not files:
        raise ManifestError('Module payload is empty.')
    ranges = {}
    for prefix in ('database', 'config'):
        lo, hi = _integer(item[prefix + '_min']), _integer(item[prefix + '_max'])
        if lo > hi:
            raise ManifestError('Invalid supported schema range.')
        ranges[prefix + '_min'], ranges[prefix + '_max'] = lo, hi
    version = ModuleVersion(name, _text(item['version_id']), _text(item['display_version']),
                            _integer(item['api'], 1), _requirements(item['requirements']),
                            _requirements(item['conflicts']), **ranges,
                            runtime_abi=_text(item['runtime_abi'], identifier=True), files=tuple(files),
                            source_release_id=_integer(item['source_release_id'], 1),
                            source_tag=_text(item['source_tag']))
    if not _HASH.fullmatch(version.version_id) or version.version_id != module_version_id(version):
        raise ManifestError('Module identity does not match its payload and compatibility.')
    return version


def parse_module_manifest(payload: object) -> ModuleRelease:
    keys = {'schema', 'release_id', 'tag', 'commit', 'channel', 'source_branch', 'prerelease',
            'platform', 'minimum_controller', 'minimum_launcher', 'published_at', 'modules', 'migrations'}
    data = _object(payload, keys)
    if type(data['schema']) is not int or data['schema'] != 2 or data['platform'] != 'windows-x64':
        raise ManifestError('Unsupported module manifest format or platform.')
    channel, prerelease = data['channel'], data['prerelease']
    if channel not in {'stable', 'dev'} or type(prerelease) is not bool or prerelease != (channel == 'dev'):
        raise ManifestError('Inconsistent module release channel.')
    if (channel == 'stable' and data['source_branch'] != 'main') or not re.fullmatch('[a-f0-9]{40}', _text(data['commit'])):
        raise ManifestError('Invalid module release source.')
    _text(data['source_branch'])
    timestamp = _text(data['published_at'])
    try:
        if datetime.fromisoformat(timestamp.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('Publication timestamp requires timezone.')
    except ValueError as exc:
        raise ManifestError('Invalid publication timestamp.') from exc
    modules = tuple(parse_module_version(item) for item in _list(data['modules']))
    names = [item.module_id for item in modules]
    paths = [file.path.casefold() for item in modules for file in item.files]
    if len(set(names)) != len(names) or len(set(paths)) != len(paths) or not {'core', 'migrator'} <= set(names):
        raise ManifestError('Duplicate payload ownership or missing required modules.')
    steps = []
    step_ids = set()
    for item in _list(data['migrations']):
        _object(item, MigrationStep.__dataclass_fields__)
        identifier = _text(item['migration_id'], identifier=True)
        entrypoint = _text(item['entrypoint'])
        lo, hi = _integer(item['from_schema']), _integer(item['to_schema'])
        if identifier in step_ids or hi <= lo or item['module_id'] not in names or not re.fullmatch(r'picsyncra\.[\w.]+:[A-Za-z_]\w*', entrypoint):
            raise ManifestError('Invalid migration registration.')
        step_ids.add(identifier)
        steps.append(MigrationStep(identifier, lo, hi, item['module_id'], entrypoint))
    return ModuleRelease(_integer(data['release_id'], 1), _text(data['tag']), channel,
                         _integer(data['minimum_controller'], 1), _integer(data['minimum_launcher'], 1),
                         modules, tuple(steps), timestamp)


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError('Duplicate JSON field.')
        result[key] = value
    return result


def verify_module_manifest(raw: bytes, signature: bytes, keys: Mapping[str, bytes | str], *, key_id: str) -> ModuleRelease:
    if not isinstance(raw, bytes) or not isinstance(signature, bytes) or len(raw) > 64 * 1024**2:
        raise ManifestError('Invalid signed module manifest.')
    try:
        _public_key(keys[key_id]).verify(signature, raw)
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_json)
    except (KeyError, InvalidSignature, UnicodeError, ValueError, TypeError) as exc:
        raise ManifestError('Invalid module manifest signature or encoding.') from exc
    return parse_module_manifest(data)
