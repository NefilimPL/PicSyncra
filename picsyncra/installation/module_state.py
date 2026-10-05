"""Immutable selected modules and pins switched through one atomic pointer."""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
from .contracts import InstallContext
from .module_contracts import ActiveModuleSet, ModuleVersion
from .module_filesystem import safe_path, atomic_json
from .module_manifest import parse_module_version, _unique_json


class ModuleStateError(RuntimeError):
    pass


def module_set_payload(selected: ActiveModuleSet) -> dict:
    modules = []
    for module in selected.modules:
        data = asdict(module)
        for field in ('files', 'requirements', 'conflicts'):
            data[field] = list(data[field])
        modules.append(data)
    return dict(revision=selected.revision, set_id=selected.set_id, release_id=selected.release_id,
                modules=modules, pinned=sorted(selected.pinned))


def _identity(data: dict) -> str:
    return hashlib.sha256(json.dumps({key: value for key, value in data.items() if key != 'set_id'},
                                     sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def make_module_set(revision: int, release_id: int, modules: tuple[ModuleVersion, ...], pinned: frozenset[str] = frozenset()) -> ActiveModuleSet:
    selected = ActiveModuleSet(revision, '', release_id, tuple(sorted(modules, key=lambda item: item.module_id)), pinned)
    return ActiveModuleSet(revision, _identity(module_set_payload(selected)), release_id, selected.modules, pinned)


def parse_module_set(data: object) -> ActiveModuleSet:
    if not isinstance(data, dict) or set(data) != {'revision', 'set_id', 'release_id', 'modules', 'pinned'}:
        raise ModuleStateError('Invalid installed module set.')
    if type(data['revision']) is not int or data['revision'] < 1 or type(data['release_id']) is not int or data['release_id'] < 1:
        raise ModuleStateError('Invalid installed module revision.')
    if not isinstance(data['modules'], list) or not isinstance(data['pinned'], list) or not all(isinstance(v, str) for v in data['pinned']):
        raise ModuleStateError('Invalid installed module selection.')
    modules = tuple(parse_module_version(item) for item in data['modules'])
    names = {module.module_id for module in modules}
    paths = [file.path.casefold() for module in modules for file in module.files]
    if len(names) != len(modules) or len(set(paths)) != len(paths) or not {'core', 'migrator'} <= names:
        raise ModuleStateError('Module set has missing or duplicate ownership.')
    pinned = frozenset(data['pinned'])
    if len(pinned) != len(data['pinned']) or not pinned <= names:
        raise ModuleStateError('Invalid pinned modules.')
    selected = make_module_set(data['revision'], data['release_id'], modules, pinned)
    if data['set_id'] != selected.set_id:
        raise ModuleStateError('Installed module set checksum changed.')
    return selected


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_json)
    except (OSError, ValueError) as exc:
        raise ModuleStateError('Installed module state is unreadable.') from exc


def _marker(context: InstallContext) -> dict | None:
    path = safe_path(context.program_root, 'active.json')
    if not path.exists():
        return None
    data = _read(path)
    if not isinstance(data, dict) or data.get('installation_id') != context.installation_id:
        raise ModuleStateError('Module marker belongs to a different installation.')
    return data


def module_set_root(context: InstallContext, selected: ActiveModuleSet) -> Path:
    if not re.fullmatch('[a-f0-9]{64}', selected.set_id):
        raise ModuleStateError('Invalid selected set identifier.')
    return safe_path(context.program_root, 'sets/' + selected.set_id)


def read_module_set(context: InstallContext) -> ActiveModuleSet:
    try:
        marker = _marker(context)
        if marker is None or set(marker) != {'schema', 'installation_id', 'release_id', 'set_id', 'revision'} or type(marker['schema']) is not int or marker['schema'] != 2:
            raise ModuleStateError('This installation requires the complete module-enabled installer upgrade.')
        if not isinstance(marker['set_id'], str) or not re.fullmatch('[a-f0-9]{64}', marker['set_id']):
            raise ModuleStateError('Invalid module set marker.')
        selected = parse_module_set(_read(safe_path(context.program_root, f"sets/{marker['set_id']}/module-set.json")))
        if selected.set_id != marker['set_id'] or selected.release_id != marker['release_id'] or type(marker['revision']) is not int or selected.revision != marker['revision']:
            raise ModuleStateError('Installed module marker does not match its set.')
        return selected
    except ValueError as exc:
        raise ModuleStateError(str(exc)) from exc


def verify_module_set_files(context: InstallContext, selected: ActiveModuleSet) -> None:
    root = module_set_root(context, selected)
    for module in selected.modules:
        for file in module.files:
            path = safe_path(root, file.path)
            try:
                with path.open('rb') as handle:
                    valid = path.stat().st_size == file.size and hashlib.file_digest(handle, 'sha256').hexdigest() == file.sha256
            except OSError as exc:
                raise ModuleStateError('Selected module file is unavailable.') from exc
            if not valid:
                raise ModuleStateError('Selected module content changed.')


def publish_module_set(context: InstallContext, selected: ActiveModuleSet) -> None:
    # Reparse the exact representation; constructors alone are not validators.
    selected = parse_module_set(module_set_payload(selected))
    verify_module_set_files(context, selected)
    root = module_set_root(context, selected)
    metadata = safe_path(root, 'module-set.json')
    if metadata.exists():
        if parse_module_set(_read(metadata)) != selected:
            raise ModuleStateError('Existing module set changed.')
        return
    atomic_json(metadata, module_set_payload(selected))


def activate_module_set(context: InstallContext, target: ActiveModuleSet, *, expected_revision: int) -> None:
    try:
        marker = _marker(context)
        if marker is None:
            revision = 0
        elif marker.get('schema') == 1 and set(marker) == {'schema', 'installation_id', 'release_id'} and type(marker['release_id']) is int and marker['release_id'] > 0:
            revision = 0
        else:
            revision = read_module_set(context).revision
        if type(expected_revision) is not int or revision != expected_revision or target.revision != revision + 1:
            raise ModuleStateError('The installation changed; prepare a new module plan.')
        metadata = safe_path(module_set_root(context, target), 'module-set.json')
        if parse_module_set(_read(metadata)) != target:
            raise ModuleStateError('Selected module metadata changed.')
        verify_module_set_files(context, target)
        atomic_json(safe_path(context.program_root, 'active.json'),
                    dict(schema=2, installation_id=context.installation_id, release_id=target.release_id,
                         set_id=target.set_id, revision=target.revision), replace=True)
    except ValueError as exc:
        raise ModuleStateError(str(exc)) from exc
