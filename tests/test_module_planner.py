from dataclasses import replace
import pytest
from picsyncra.installation.module_contracts import ModuleEnvironment
from picsyncra.installation.module_manifest import parse_module_manifest
from picsyncra.installation.module_state import make_module_set
from picsyncra.installation.module_planner import plan_module_operation
from tests.module_fixtures import module_payload, release_payload

ENV = ModuleEnvironment(1, 1, 'cp313-win-amd64', 2, 2)


def releases():
    common = [module_payload(), module_payload('sql', 'picsyncra/services/sql_service.py'),
              module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe')]
    first = parse_module_manifest(release_payload(1, common + [module_payload('ftp', 'picsyncra/services/ftp_service.py', b'old')]))
    latest = parse_module_manifest(release_payload(5, common + [module_payload('ftp', 'picsyncra/services/ftp_service.py', b'new', source=5)]))
    return first, latest


def by_id(selected):
    return {module.module_id: module for module in selected.modules}


def test_rollback_batch_preserves_unselected_sql():
    old, latest = releases()
    active = make_module_set(4, 5, latest.modules)
    plan = plan_module_operation(active, (old, latest), ENV, action='rollback_modules',
                                 selected={'ftp': by_id(make_module_set(1, 1, old.modules))['ftp'].version_id},
                                 excluded=frozenset(), available_hashes=frozenset())
    assert by_id(plan.target)['sql'] == by_id(active)['sql']
    assert by_id(plan.target)['ftp'].source_release_id == 1
    assert plan.target.pinned == frozenset({'ftp'})
    assert not plan.conflicts


def test_skipping_intermediate_releases_downloads_only_changed_ftp():
    old, latest = releases()
    active = make_module_set(1, 1, old.modules)
    owned = frozenset(file.sha256 for module in active.modules for file in module.files)
    plan = plan_module_operation(active, (old, latest), ENV, action='update', selected={},
                                 excluded=frozenset(), available_hashes=owned)
    assert len(plan.missing_files) == 1
    assert plan.missing_files[0].path.endswith('ftp_service.py')
    assert plan.download_bytes == 3
    assert by_id(plan.target)['sql'].version_id == by_id(active)['sql'].version_id


def test_draft_exclusion_preserves_current_version_without_applying_rollback():
    old, latest = releases()
    active = make_module_set(1, 1, old.modules, frozenset({'sql'}))
    plan = plan_module_operation(active, (old, latest), ENV, action='update', selected={},
                                 excluded=frozenset({'ftp'}), available_hashes=frozenset())
    assert by_id(plan.target)['ftp'] == by_id(active)['ftp']
    assert plan.target.pinned == frozenset({'sql'})
    all_plan = plan_module_operation(active, (old, latest), ENV, action='update_all', selected={},
                                     excluded=frozenset(), available_hashes=frozenset())
    assert all_plan.target.pinned == frozenset()
    assert active.pinned == frozenset({'sql'})


def test_all_conflicts_are_reported_and_invalid_selections_rejected():
    old, latest = releases()
    active = make_module_set(1, 1, old.modules)
    plan = plan_module_operation(active, (latest,), replace(ENV, database_schema=50, runtime_abi='other'),
                                 action='update', selected={}, excluded=frozenset(), available_hashes=frozenset())
    assert {'database_incompatible', 'runtime_incompatible'} <= {item.code for item in plan.conflicts}
    with pytest.raises(ValueError):
        plan_module_operation(active, (old,), ENV, action='rollback_modules', selected={'ftp': 'missing'},
                              excluded=frozenset(), available_hashes=frozenset())


def test_forward_schema_path_and_dependency_conflicts_are_checked_together():
    old, latest = releases()
    from picsyncra.installation.module_contracts import MigrationStep, ModuleRequirement
    modules = tuple(replace(m, database_min=3, requirements=(ModuleRequirement('sql', 2, 2),) if m.module_id == 'ftp' else ()) for m in latest.modules)
    latest = replace(latest, modules=modules, migrations=(
        MigrationStep('one-two', 1, 2, 'core', 'picsyncra.sqlite_store:migrate'),
        MigrationStep('two-three', 2, 3, 'core', 'picsyncra.sqlite_store:migrate')))
    plan = plan_module_operation(make_module_set(1, 1, old.modules), (latest,), ENV,
                                 action='update', selected={}, excluded=frozenset(), available_hashes=frozenset())
    assert plan.migration_ids == ('one-two', 'two-three')
    assert {c.code for c in plan.conflicts} == {'dependency_incompatible'}
    assert plan.conflicts[0].dependency_version is not None


def test_optional_ocr_is_not_added_by_full_update():
    old, latest = releases()
    optional = parse_module_manifest(release_payload(5, [module_payload(), module_payload('migrator', 'apps/migrator/PicSyncra-Migrator.exe'),
        module_payload('ocr_runtime', 'runtime/ocr/python.dll'), module_payload('ocr_models', 'models/ocr/model.bin')]))
    plan = plan_module_operation(make_module_set(1, 1, old.modules), (optional,), ENV,
                                 action='update_all', selected={}, excluded=frozenset(), available_hashes=frozenset())
    assert not {'ocr_runtime', 'ocr_models'} & set(by_id(plan.target))
