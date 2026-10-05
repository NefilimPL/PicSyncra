"""Pure planning: choices and exclusions never mutate an installation."""
from __future__ import annotations
from collections.abc import Mapping
from uuid import uuid4
from datetime import datetime
from dataclasses import replace
from .module_contracts import ActiveModuleSet, ModuleConflict, ModuleEnvironment, ModulePlan, ModuleRelease
from .module_compatibility import check_module_compatibility
from .module_definition import module_definitions
from .module_state import make_module_set
from .module_migrations import migration_path


def plan_module_operation(active: ActiveModuleSet, releases: tuple[ModuleRelease, ...],
                          environment: ModuleEnvironment, *, action: str,
                          selected: Mapping[str, str], excluded: frozenset[str],
                          available_hashes: frozenset[str]) -> ModulePlan:
    if action not in {'update', 'update_all', 'rollback_modules', 'install_ocr'}:
        raise ValueError('Nieznana operacja modułów.')
    if not releases:
        raise ValueError('Brak kompletnych podpisanych wydań modułów.')
    installed = {item.module_id: item for item in active.modules}
    known = {item.module_id: item for item in module_definitions()}
    if not set(excluded) <= set(installed) or not set(selected) <= set(installed):
        raise ValueError('Wybrano niezainstalowany moduł.')
    def published(release):
        return datetime.fromisoformat(release.published_at.replace('Z', '+00:00'))
    newest = max(releases, key=published)
    source = newest
    target = dict(installed)
    pinned = active.pinned
    if action == 'rollback_modules':
        if not selected:
            raise ValueError('Wybierz wersje modułów do cofnięcia.')
        available = {(module.module_id, module.version_id): module for release in sorted(releases, key=published, reverse=True) for module in release.modules}
        dates = {release.release_id: published(release) for release in releases}
        for module_id, version_id in selected.items():
            chosen = available.get((module_id, version_id))
            if chosen is None:
                raise ValueError(f'Wybrana wersja modułu {module_id} jest niedostępna.')
            current = installed[module_id]
            if chosen.source_release_id not in dates or current.source_release_id not in dates:
                raise ValueError('Brak zweryfikowanej chronologii wydania modułu.')
            if dates[chosen.source_release_id] > dates[current.source_release_id]:
                raise ValueError('Cofanie nie może wybierać nowszej wersji modułu.')
            target[module_id] = chosen
        pinned = pinned | frozenset(selected)
        release_id = active.release_id
        source = next((r for r in releases if r.release_id == active.release_id), newest)
    else:
        if selected:
            raise ValueError('Aktualizacja nie zatwierdza przygotowanych cofnięć.')
        release_id = newest.release_id
        if action == 'install_ocr':
            # Choose a signed combination matching the active base; never silently
            # upgrade the rest of the application while adding optional OCR.
            source = next((release for release in releases if release.release_id == active.release_id), None)
            if source is None:
                raise ValueError('Brak podpisanego OCR dla aktywnego zestawu.')
            release_id = active.release_id
            additions = {module.module_id: module for module in source.modules if module.module_id in {'ocr_runtime', 'ocr_models'}}
            if set(additions) != {'ocr_runtime', 'ocr_models'}:
                raise ValueError('Wydanie nie zawiera silnika i modeli OCR.')
            target.update(additions)
        else:
            proposed = {module.module_id: module for module in newest.modules
                        if module.module_id in installed or not known[module.module_id].optional}
            if action == 'update_all':
                target = proposed
                pinned = frozenset()
            else:
                for module_id, version in proposed.items():
                    if module_id not in (pinned | excluded):
                        target[module_id] = version
    selected_set = make_module_set(active.revision + 1, release_id, tuple(target.values()), pinned)
    steps = migration_path(environment.database_schema,
                           max(m.database_min for m in selected_set.modules),
                           min(m.database_max for m in selected_set.modules), source.migrations)
    checked_environment = replace(environment, database_schema=steps[-1].to_schema) if steps else environment
    conflicts = list(check_module_compatibility(selected_set, checked_environment))
    if source.minimum_controller > environment.controller_api:
        conflicts.append(ModuleConflict('controller_outdated', 'core', '', None, None,
                                        f'Wymagany kontroler {source.minimum_controller}; obecny {environment.controller_api}.'))
    if source.minimum_launcher > environment.launcher_api:
        conflicts.append(ModuleConflict('launcher_outdated', 'core', '', None, None,
                                        f'Wymagany launcher {source.minimum_launcher}; obecny {environment.launcher_api}.'))
    unique = {}
    for module in selected_set.modules:
        for file in module.files:
            if file.sha256 not in available_hashes and file.size:
                unique.setdefault(file.sha256, file)
    missing = tuple(unique.values())
    return ModulePlan(uuid4().hex, action, active.revision, selected_set, tuple(conflicts),
                      missing, sum(file.size for file in missing), tuple(step.migration_id for step in steps or ()))
