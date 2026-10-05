"""Forward-only schema paths; database downgrade always needs a backup restore."""
from collections import deque
from .module_contracts import MigrationStep


def migration_path(current: int, minimum: int, maximum: int,
                   steps: tuple[MigrationStep, ...]) -> tuple[MigrationStep, ...] | None:
    queue = deque([(current, ())])
    visited = {current}
    while queue:
        schema, path = queue.popleft()
        if minimum <= schema <= maximum:
            return path
        for step in steps:
            if step.from_schema == schema and schema < step.to_schema <= maximum and step.to_schema not in visited:
                visited.add(step.to_schema)
                queue.append((step.to_schema, path + (step,)))
    return None


def run_staged_migrations(context, plan_id):
    """Runs inside a fresh frozen host, never inside the controller interpreter."""
    import importlib
    import json
    import re
    import sys
    from pathlib import Path
    from .module_filesystem import safe_path
    from .module_state import read_module_set, parse_module_set, module_set_root
    from .module_definition import module_owner
    from .module_bootstrap import bootstrap_installed_modules
    from .database import inspect_database
    if not re.fullmatch('[a-f0-9]{32}',plan_id): raise ValueError('Invalid migration plan.')
    payload=json.loads(safe_path(context.state_root,'module-plans/'+plan_id+'.json').read_text(encoding='utf-8'))
    target=parse_module_set(payload['target'])
    if read_module_set(context).revision != payload['expected_revision']: raise RuntimeError('Stale migration plan.')
    host=safe_path(module_set_root(context,target),'apps/web/PicSyncra-WEB.exe')
    if Path(sys.executable).resolve()!=host.resolve(): raise RuntimeError('Migration host does not match selected target.')
    bootstrap_installed_modules(context,selected=target)
    versions={m.module_id:m for m in target.modules}
    for data in payload['migrations']:
        step=MigrationStep(**data)
        module_name,function_name=step.entrypoint.split(':')
        relative=module_name.replace('.','/')+'.py'
        if module_owner(relative)!=step.module_id or not any(f.path==relative for f in versions[step.module_id].files):
            raise RuntimeError('Migration entrypoint does not belong to selected module.')
        before=inspect_database(context.database_path)
        if not before.integrity_ok or before.schema_version!=step.from_schema: raise RuntimeError('Migration source schema mismatch.')
        function=getattr(importlib.import_module(module_name),function_name)
        function(context.database_path)
        after=inspect_database(context.database_path)
        if not after.integrity_ok or not after.is_picsyncra or after.schema_version!=step.to_schema:
            raise RuntimeError('Migration target schema mismatch.')
