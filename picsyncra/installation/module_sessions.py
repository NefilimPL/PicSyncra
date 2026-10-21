"""Lifetime lease shared by standalone hosts and module transactions."""
from contextlib import contextmanager
import json
from .module_executor import installation_lock, ModuleExecutionError
from .module_filesystem import safe_path


@contextmanager
def standalone_session(context):
    # Hold the OS-released installation lock for the whole application lifetime,
    # before importing selected code or opening configuration/database files.
    with installation_lock(context):
        path = safe_path(context.state_root, 'module-operation.json')
        if path.exists():
            try:
                state = json.loads(path.read_text(encoding='utf-8'))['state']
            except (ValueError, KeyError) as exc:
                raise ModuleExecutionError('Najpierw odzyskaj przerwaną operację modułów.') from exc
            if state not in {'committed', 'rolled_back', 'failed'}:
                raise ModuleExecutionError('Najpierw odzyskaj przerwaną operację modułów.')
        yield
