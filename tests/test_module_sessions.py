import pytest
from tests.test_module_state import context
from picsyncra.installation.module_executor import installation_lock, ModuleExecutionError


def test_standalone_application_and_update_cannot_overlap(context):
    from picsyncra.installation.module_sessions import standalone_session
    with standalone_session(context):
        with pytest.raises(ModuleExecutionError):
            with installation_lock(context): pass
    with installation_lock(context):
        with pytest.raises(ModuleExecutionError):
            with standalone_session(context): pass


def test_standalone_application_cannot_bypass_durable_recovery_gate(context):
    from picsyncra.installation.module_sessions import standalone_session
    (context.state_root / 'module-operation.json').write_text('{"state":"recovery_required"}')
    with pytest.raises(ModuleExecutionError, match='odzysk'):
        with standalone_session(context): pass


def test_standalone_host_rechecks_active_executable_after_acquiring_lease(context, monkeypatch):
    from installer import installed_host
    from picsyncra import install_paths
    from picsyncra.installation import module_bootstrap
    checks = iter((context, None))
    monkeypatch.setattr(installed_host.sys, 'executable', str(context.program_root / 'PicSyncra.exe'))
    monkeypatch.setattr(install_paths, 'resolve_install_context', lambda executable: next(checks))
    monkeypatch.setattr(module_bootstrap, 'bootstrap_installed_modules', lambda *args: pytest.fail('Stale executable must not import selected code'))
    with pytest.raises(RuntimeError, match='aktywn'):
        installed_host.run_application()
