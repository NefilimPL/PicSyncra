"""Stop a registered installation before Setup replaces stable executables."""
from pathlib import Path
import subprocess
import time
import json
import os
from uuid import uuid4

from .module_executor import installation_lock
from .module_filesystem import safe_path, atomic_json


def drain_backend(context, client, *, timeout=120):
    operation_id = 'setup-' + uuid4().hex
    request = safe_path(context.state_root, 'module-maintenance-request.json')
    ready = safe_path(context.state_root, 'module-maintenance-ready.json')
    atomic_json(request, dict(operation_id=operation_id), replace=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not client.snapshot()['backend_running']:
            return
        if ready.exists():
            state = json.loads(ready.read_text(encoding='utf-8'))
            if state.get('operation_id') == operation_id and state.get('ready') is True:
                return
        time.sleep(0.25)
    raise RuntimeError('Backend wykonuje zadania lub nie potwierdził gotowości do instalacji. '
                       'Poczekaj na ich zakończenie, zatrzymaj backend w launcherze i ponów Setup.')


def installed_processes(context):
    import psutil
    root = context.program_root.resolve(strict=True)
    result = []
    for process in psutil.process_iter(['exe']):
        try:
            executable = process.info['exe']
            if process.pid != os.getpid() and executable and Path(executable).resolve().is_relative_to(root):
                result.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return result


def pending_setup(context):
    path = safe_path(context.state_root, 'module-setup-result.json')
    if not path.exists():
        return None
    result = json.loads(path.read_text(encoding='utf-8'))
    return result if result.get('state') not in {'committed', 'rolled_back'} else None


def prepare_existing_installation(context, *, client, stop_task=None, processes=None, timeout=30, quiesce=None,
                                  allow_setup_recovery=False):
    processes = processes or (lambda: installed_processes(context))
    stop_task = stop_task or (lambda: subprocess.run([
        'schtasks.exe', '/End', '/TN', 'PicSyncra Controller ' + context.installation_id],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW))
    with installation_lock(context):
        if not allow_setup_recovery and pending_setup(context):
            raise RuntimeError('Przerwana instalacja Setup wymaga odzyskania przed wymianą plików. Uruchom ponownie Setup.')
        journal = safe_path(context.state_root, 'module-operation.json')
        if journal.exists():
            record = json.loads(journal.read_text(encoding='utf-8'))
            if record.get('state') not in {'committed', 'rolled_back', 'failed'}:
                raise RuntimeError('Najpierw dokończ lub odzyskaj przerwaną aktualizację modułów w launcherze. '
                                   'Setup nie zastąpi aktywnej transakcji.')
        running = processes()
        interactive = [p for p in running if Path(p.info['exe']).name.casefold()
                       not in {'picsyncra-controller.exe', 'picsyncra-web.exe', 'picsyncra-ocr.exe'}]
        if interactive:
            raise RuntimeError('Zamknij launcher (także ikonę w trayu), LOCAL i Migrator przed instalacją. '
                               'Setup nie zmieni plików działającej aplikacji.')
        if client is not None:
            if client.snapshot()['backend_running']:
                try:
                    (quiesce or (lambda: drain_backend(context, client)))()
                    if not client.stop_backend(force=False):
                        raise RuntimeError('Nie można zatrzymać backendu. Poczekaj na koniec aktualizacji i ponów Setup.')
                finally:
                    for name in ('module-maintenance-request.json', 'module-maintenance-ready.json'):
                        safe_path(context.state_root, name).unlink(missing_ok=True)
        elif running:
            raise RuntimeError('Kontroler nie odpowiada. Zamknij PicSyncra i ponów Setup; pliki nie zostały zmienione.')
        stop_task()
        deadline = time.monotonic() + timeout
        while processes():
            if time.monotonic() >= deadline:
                raise RuntimeError('Procesy PicSyncra nadal działają. Setup wstrzymany przed wymianą plików.')
            time.sleep(0.1)
        # A completed/aborted drain must not pause the newly installed backend.
        for name in ('module-maintenance-request.json', 'module-maintenance-ready.json'):
            safe_path(context.state_root, name).unlink(missing_ok=True)


def prepare_setup_request(request, *, capture=True):
    from ..install_paths import load_registered_install_context
    from .launcher import InstallationControlClient
    context = load_registered_install_context(request['installation_id'])
    if context is None:
        # A registered but damaged installation must not bypass the process
        # checks simply because its active marker cannot be read.
        from ..install_paths import _read_hklm_registrations
        if any(r.get('installation_id') == request['installation_id'] for r in _read_hklm_registrations()):
            raise RuntimeError('Rejestracja instalacji jest uszkodzona. Najpierw odzyskaj instalację w launcherze.')
        return
    marker = json.loads(safe_path(context.program_root, 'active.json').read_text(encoding='utf-8'))
    if marker.get('schema') == 1 and safe_path(context.program_root, 'components/ocr/active.json').exists():
        raise RuntimeError('Ta instalacja używa starszego osobnego pakietu OCR. Konwersja do modułów '
                           'wymaga migracji OCR; Setup wstrzymano przed wymianą plików, aby go nie wyłączyć.')
    recovery = pending_setup(context)
    from .controller_host import ActiveBackendSupervisor
    startup = dict(backend_running=False, autostart=ActiveBackendSupervisor(context).autostart_enabled())
    client = InstallationControlClient(context.installation_id)
    try:
        startup = client.snapshot()
    except (OSError, RuntimeError):
        client = None
    prepare_existing_installation(context, client=client, allow_setup_recovery=True)
    if capture:
        if recovery:
            rollback_setup(context)
            # Recover original availability even though preflight stopped the
            # candidate process. A manually started WEB need not autostart.
            startup = dict(backend_running=recovery.get('previous_backend_was_running', False),
                           autostart=recovery.get('previous_autostart', startup['autostart']))
            context = load_registered_install_context(request['installation_id'])
            marker = json.loads(safe_path(context.program_root, 'active.json').read_text(encoding='utf-8'))
        atomic_json(safe_path(context.state_root, 'setup-preflight-state.json'), dict(
            marker=marker, backend_was_running=startup['backend_running'], autostart=startup['autostart'],
            database_path=str(context.database_path)), replace=True)
        # Inno writes registration before its post-install database inspection.
        # Keep this attempt recoverable even if inspection/validation fails
        # before initialize-modules publishes an activation receipt.
        atomic_json(safe_path(context.state_root, 'module-setup-result.json'), setup_receipt(context, dict(
            state='prepared', changed=False, previous_marker=marker, target_set_id=marker.get('set_id'))), replace=True)


def rollback_setup(context):
    from .module_state import parse_module_set, verify_module_set_files, read_module_set
    from .module_executor import restore_backup
    path = safe_path(context.state_root, 'module-setup-result.json')
    if not path.exists(): return False
    result = json.loads(path.read_text(encoding='utf-8'))
    marker = result.get('previous_marker')
    if result.get('state') in {'committed', 'rolled_back'}:
        return False
    with installation_lock(context):
        active_path = safe_path(context.program_root, 'active.json')
        active_marker = json.loads(active_path.read_text(encoding='utf-8')) if active_path.exists() else None
        # Setup may stop between saving its receipt and activating the target.
        still_previous = active_marker == marker
        if not still_previous and read_module_set(context).set_id != result['target_set_id']:
            raise RuntimeError('Instalacja zmieniła się od uruchomienia Setup. Automatyczne cofnięcie wstrzymano.')
        if result.get('changed') and marker and marker.get('schema') == 2:
            old = parse_module_set(json.loads(safe_path(context.program_root,
                'sets/' + marker['set_id'] + '/module-set.json').read_text(encoding='utf-8')))
            verify_module_set_files(context, old)
        if result.get('changed') and marker and not still_previous:
            if result.get('selected_database_backup_id'):
                from dataclasses import replace
                selected_database = Path(result['selected_database_backup_path'])
                if not selected_database.is_absolute(): raise RuntimeError('Invalid Setup selected database backup path.')
                restore_backup(replace(context, database_path=selected_database), result['selected_database_backup_id'])
            if result.get('backup_id'):
                from dataclasses import replace
                database = Path(result.get('backup_database_path') or context.database_path)
                if not database.is_absolute(): raise RuntimeError('Invalid Setup backup database path.')
                restore_backup(replace(context, database_path=database), result['backup_id'])
            atomic_json(safe_path(context.program_root, 'active.json'), marker, replace=True)
        if type(result.get('previous_autostart')) is bool:
            atomic_json(safe_path(context.state_root, 'controller-settings.json'),
                        dict(autostart=result['previous_autostart']), replace=True)
        if result.get('previous_database_path') and result['previous_database_path'] != str(context.database_path):
            from .setup_cli import WindowsRegistryWriter, _REGISTRY_ROOT
            WindowsRegistryWriter().set_value(_REGISTRY_ROOT + '\\' + context.installation_id,
                                             'DatabasePath', result['previous_database_path'])
        atomic_json(path, dict(result, state='rolled_back'), replace=True)
    return True


def run_lifecycle_command(command, request):
    if not isinstance(request, dict) or set(request) != {'installation_id', 'enabled'} or type(request['enabled']) is not bool:
        raise ValueError('Invalid installer lifecycle request.')
    from .launcher import InstallationControlClient
    client = InstallationControlClient(request['installation_id'])  # Validate fixed pipe identity.
    if command == 'prepare-upgrade':
        prepare_setup_request(request)
        return
    from ..install_paths import load_registered_install_context
    context = load_registered_install_context(request['installation_id'])
    if context is None:
        raise RuntimeError('Brak poprawnej rejestracji instalacji po instalacji.')
    if command == 'rollback-upgrade':
        # No pointer/database switch while a child can still be writing data.
        prepare_setup_request(request, capture=False)
        rollback_setup(context)
        return
    if command == 'configure-startup':
        from .controller_host import ActiveBackendSupervisor
        path = safe_path(context.state_root, 'module-setup-result.json')
        result = json.loads(path.read_text(encoding='utf-8'))
        atomic_json(path, setup_receipt(context, result), replace=True)
        ActiveBackendSupervisor(context).set_autostart(request['enabled'])
        return
    result_path = safe_path(context.state_root, 'module-setup-result.json')
    result = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
    needs_backend = result.get('previous_backend_was_running', False)
    if command == 'verify-startup':
        needs_backend = needs_backend or request['enabled']
    elif command != 'resume-previous':
        raise ValueError('Unsupported installer lifecycle command.')
    from .controller_host import BACKEND_START_TIMEOUT
    deadline = time.monotonic() + BACKEND_START_TIMEOUT
    while time.monotonic() < deadline:
        try:
            state = client.snapshot()
            if not needs_backend:
                if command == 'verify-startup': commit_setup(context)
                return
            if not state['backend_running']:
                client.start_backend()
                time.sleep(0.25)
                continue
            if state['backend_running']:
                from .controller_host import _backend_ready
                if _backend_ready(client, timeout_seconds=min(3,max(0.01,deadline-time.monotonic()))):
                    if command == 'verify-startup': commit_setup(context)
                    return
        except (OSError, RuntimeError):
            pass
        time.sleep(0.25)
    raise RuntimeError('Nie udało się potwierdzić uruchomienia PicSyncra. Otwórz launcher i sprawdź backend; '
                       'baza i konfiguracja zostały zachowane.')


def commit_setup(context):
    path = safe_path(context.state_root, 'module-setup-result.json')
    if path.exists():
        result = json.loads(path.read_text(encoding='utf-8'))
        atomic_json(path, dict(result, state='committed'), replace=True)


def setup_receipt(context, result):
    """Keep recovery state before changing startup settings or activating files."""
    if 'previous_autostart' in result:
        return result
    from .controller_host import ActiveBackendSupervisor
    path = safe_path(context.state_root, 'setup-preflight-state.json')
    saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    previous = saved if saved and saved.get('marker') == result.get('previous_marker') else {}
    return dict(result,
        previous_autostart=previous.get('autostart', ActiveBackendSupervisor(context).autostart_enabled()
                                       if result.get('previous_marker') else False),
        previous_backend_was_running=previous.get('backend_was_running', False),
        previous_database_path=previous.get('database_path'))
