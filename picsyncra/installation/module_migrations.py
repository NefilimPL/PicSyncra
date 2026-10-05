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
