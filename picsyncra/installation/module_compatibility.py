"""Report every declared compatibility failure in a proposed module set."""
from .module_contracts import ActiveModuleSet, ModuleConflict, ModuleEnvironment


def check_module_compatibility(target: ActiveModuleSet, environment: ModuleEnvironment) -> tuple[ModuleConflict, ...]:
    versions = {item.module_id: item for item in target.modules}
    failures = []
    for module in target.modules:
        def report(code, requirement, dependency=None):
            other = versions.get(dependency)
            failures.append(ModuleConflict(code, module.module_id, module.display_version, dependency,
                                           other.display_version if other else None, requirement))
        if not module.database_min <= environment.database_schema <= module.database_max:
            report('database_incompatible', f'Schemat bazy {environment.database_schema}; wymagany {module.database_min}–{module.database_max}.')
        if not module.config_min <= environment.config_schema <= module.config_max:
            report('config_incompatible', f'Format konfiguracji {environment.config_schema}; wymagany {module.config_min}–{module.config_max}.')
        if module.runtime_abi != environment.runtime_abi:
            report('runtime_incompatible', f'Runtime {environment.runtime_abi}; wymagany {module.runtime_abi}.')
        for requirement in module.requirements:
            other = versions.get(requirement.module_id)
            if other is None or not requirement.minimum_api <= other.api <= requirement.maximum_api:
                report('dependency_incompatible', f'Wymagane API {requirement.minimum_api}–{requirement.maximum_api}; obecne {other.api if other else "brak"}.', requirement.module_id)
        for conflict in module.conflicts:
            other = versions.get(conflict.module_id)
            if other is not None and conflict.minimum_api <= other.api <= conflict.maximum_api:
                report('module_conflict', f'Niezgodne API {conflict.minimum_api}–{conflict.maximum_api}.', conflict.module_id)
    return tuple(failures)
