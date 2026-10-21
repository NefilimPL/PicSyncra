"""Immutable installed module catalog, state and operation contracts."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModuleFile:
    path: str
    sha256: str
    size: int
    asset_name: str
    asset_offset: int = 0
    asset_size: int = 0


@dataclass(frozen=True)
class ModuleRequirement:
    module_id: str
    minimum_api: int
    maximum_api: int


@dataclass(frozen=True)
class MigrationStep:
    migration_id: str
    from_schema: int
    to_schema: int
    module_id: str
    entrypoint: str


@dataclass(frozen=True)
class ModuleVersion:
    module_id: str
    version_id: str
    display_version: str
    api: int
    requirements: tuple[ModuleRequirement, ...]
    conflicts: tuple[ModuleRequirement, ...]
    database_min: int
    database_max: int
    config_min: int
    config_max: int
    runtime_abi: str
    files: tuple[ModuleFile, ...]
    source_release_id: int
    source_tag: str


@dataclass(frozen=True)
class ModuleRelease:
    release_id: int
    tag: str
    channel: str
    minimum_controller: int
    minimum_launcher: int
    modules: tuple[ModuleVersion, ...]
    migrations: tuple[MigrationStep, ...] = ()
    published_at: str = ''


@dataclass(frozen=True)
class ActiveModuleSet:
    revision: int
    set_id: str
    release_id: int
    modules: tuple[ModuleVersion, ...]
    pinned: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ModuleEnvironment:
    database_schema: int
    config_schema: int
    runtime_abi: str
    controller_api: int
    launcher_api: int


@dataclass(frozen=True)
class ModuleConflict:
    code: str
    module_id: str
    selected_version: str
    dependency_id: str | None
    dependency_version: str | None
    requirement: str


@dataclass(frozen=True)
class ModulePlan:
    plan_id: str
    action: str
    expected_revision: int
    target: ActiveModuleSet
    conflicts: tuple[ModuleConflict, ...]
    missing_files: tuple[ModuleFile, ...]
    download_bytes: int
    migration_ids: tuple[str, ...] = ()
