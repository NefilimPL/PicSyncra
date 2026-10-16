"""Shared controller facade for WEB and the stable recovery launcher."""
from __future__ import annotations
from dataclasses import asdict, replace
import json
import re
import threading
import time
from urllib.parse import quote
from contextlib import nullcontext
from uuid import uuid4
from .controller_version import CONTROLLER_VERSION, LAUNCHER_VERSION
from .database import inspect_database
from .module_content import ModuleContentStore
from .module_configuration import inspect_configuration
from .module_contracts import ModuleEnvironment, ModulePlan, MigrationStep
from .module_definition import module_definitions
from .module_compatibility import check_module_compatibility
from .module_executor import ModuleExecutor, ModuleExecutionError, verified_backup, backup_receipt_metadata
from .module_filesystem import atomic_json, safe_path
from .module_migrations import migration_path
from .module_planner import plan_module_operation
from .module_source import ModuleReleaseSource
from .module_state import read_module_set, module_set_payload, parse_module_set

RUNTIME_ABI = 'cp313-win-amd64'


def release_link(tag):
    return 'https://github.com/NefilimPL/PicSyncra/releases/tag/' + quote(tag, safe='')


class ModuleService:
    def __init__(self, context, controller, *, source=None, content=None, schedule=None, quiesce=None, healthy=None):
        self.context, self.controller = context, controller
        self.source = source or ModuleReleaseSource(context)
        self.content = content or ModuleContentStore(context)
        self.schedule = schedule or self._defer
        self._lock = threading.Lock()
        self.busy = False
        self.current_operation_id = None
        self.entries = ()
        self._authorization_lock = threading.RLock()
        self._authorization_requests = {}
        self._authorizations = {}
        self.executor = ModuleExecutor(context, controller, content=self.content,
                                       quiesce=quiesce or self._quiesce, healthy=healthy or self._healthy,
                                       revalidate=self._revalidate, migrate=self._migrate)

    @staticmethod
    def _defer(work):
        timer = threading.Timer(1.0, work)
        timer.daemon = True
        timer.start()

    def _channel(self):
        path = safe_path(self.context.state_root, 'installation-settings.json')
        if path.exists():
            value = json.loads(path.read_text(encoding='utf-8')).get('channel', 'stable')
            if value in {'stable', 'dev'}: return value
        return 'stable'

    def _ocr_management(self):
        path = safe_path(self.context.state_root, 'installation-settings.json')
        settings = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        return 'setup' if settings.get('ocr_management') == 'setup' else 'download'

    def backend_start_allowed(self):
        try:
            status = self.executor.status()
            return not self.busy and (not status or status['state'] in {'committed', 'rolled_back', 'failed'})
        except (OSError, ValueError, KeyError):
            return False

    def change_channel(self, channel):
        if not isinstance(channel,str) or channel not in {'stable','dev'}:
            raise ValueError('Niepoprawny kanał wydań.')
        with self._lock:
            if self.busy: raise ModuleExecutionError('Inna operacja modułów jest w toku.')
            path=safe_path(self.context.state_root,'installation-settings.json')
            settings=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            if not isinstance(settings,dict): raise ValueError('Niepoprawne ustawienia instalacji.')
            atomic_json(path,dict(settings,channel=channel),replace=True)
        return dict(channel=channel)

    def recover(self):
        with self._lock:
            if self.busy: raise ModuleExecutionError('Inna operacja modułów jest w toku.')
            status = self.executor.status()
            if not status or status['state'] in {'committed', 'rolled_back', 'failed'}:
                raise ModuleExecutionError('Brak przerwanej operacji do odzyskania.')
            operation_id = status['operation_id']
            self._load_plan(operation_id)
            self.busy = True
            self.current_operation_id = operation_id
        def work():
            try:
                self.executor.recover()
            finally:
                with self._lock: self.busy = False
        self.schedule(work)
        return dict(operation_id=operation_id, state='accepted', action='recover', error=None)

    def _environment(self, restore_backup_id=None, *, check_integrity=True):
        inspection = inspect_database(self.context.database_path, check_integrity=check_integrity)
        if inspection.integrity_ok is False or not inspection.is_picsyncra:
            raise ModuleExecutionError('Baza PicSyncra nie przeszła sprawdzania spójności.')
        if restore_backup_id:
            backup, schema = verified_backup(self.context, restore_backup_id)
            config_schema = inspect_configuration(safe_path(backup, 'config'))
        else:
            schema = inspection.schema_version
            config_schema = inspect_configuration(self.context.config_root)
        return ModuleEnvironment(schema, config_schema, RUNTIME_ABI, CONTROLLER_VERSION, LAUNCHER_VERSION)

    def _catalog(self, channel=None, *, refresh=False):
        loader = self.source.load if refresh else getattr(self.source, 'snapshot', self.source.load)
        self.entries = loader(channel or self._channel())
        return tuple(entry.release for entry in self.entries if entry.release and not entry.blocked_reason)

    def catalog(self):
        active = read_module_set(self.context)
        channel=self._channel()
        catalog_state = None
        if hasattr(self.source, 'catalog_snapshot'):
            self.entries, catalog_state = self.source.catalog_snapshot(channel)
            releases = tuple(entry.release for entry in self.entries if entry.release and not entry.blocked_reason)
        else: releases = self._catalog(channel, refresh=True)
        latest = max(releases, key=lambda r: r.published_at, default=None)
        labels = {item.module_id: item.label for item in module_definitions()}
        rows = []
        release_dates = {entry.release_id: entry.published_at for entry in self.entries}
        def provenance(module):
            return dict(tag=module.source_tag, published_at=release_dates.get(module.source_release_id),
                        release_url=release_link(module.source_tag))
        for module in active.modules:
            versions = {}
            for release in sorted(releases, key=lambda r: r.published_at, reverse=True):
                for item in release.modules:
                    if item.module_id == module.module_id:
                        versions.setdefault(item.version_id, dict(version_id=item.version_id, display_version=item.display_version,
                            release_id=item.source_release_id, **provenance(item), available=True))
            # Installed version stays visible, even before the first signed
            # publication. Availability for rollback requires a trusted catalog.
            versions.setdefault(module.version_id, dict(version_id=module.version_id, display_version=module.display_version,
                release_id=module.source_release_id, **provenance(module), available=False))
            newest = next((m for m in latest.modules if m.module_id == module.module_id), None) if latest else None
            rows.append(dict(module_id=module.module_id, label=labels[module.module_id], installed=True, current=module.display_version,
                             current_id=module.version_id, latest=newest.display_version if newest else None,
                             current_release=provenance(module), latest_release=provenance(newest) if newest else None,
                             pinned=module.module_id in active.pinned, versions=list(versions.values())[:50]))
        ocr_management = self._ocr_management()
        installed_ids = {m.module_id for m in active.modules}
        if ocr_management == 'setup':
            for module_id in ('ocr_runtime','ocr_models'):
                if module_id not in installed_ids:
                    rows.append(dict(module_id=module_id, label=labels[module_id], installed=False,
                        current=None, current_id=None, latest=None, current_release=None, latest_release=None,
                        pinned=False, versions=[]))
        backups = []
        backup_root = safe_path(self.context.state_root, 'backups/operations')
        if backup_root.exists():
            for path in sorted(backup_root.iterdir(), reverse=True):
                if path.name.startswith('.'): continue
                try:
                    backups.append(backup_receipt_metadata(self.context, path.name))
                except (RuntimeError, OSError, ValueError): continue
                if len(backups) >= 100: break
        operation = self.operation(self.current_operation_id) if self.busy and self.current_operation_id else None
        from .ocr_component import installed_ocr_files_present
        return dict(revision=active.revision, channel=channel, modules=rows,
                    background_updates=True,
                    catalog_refreshing=bool(catalog_state and catalog_state['refreshing']),
                    offline=catalog_state['offline'] if catalog_state else self.source.offline,
                    catalog_error=catalog_state['error'] if catalog_state else getattr(self.source, 'error', None), backups=backups, operation=operation,
                    ocr_management=ocr_management,
                    ocr_available=installed_ocr_files_present(self.context,active),
                    ocr_installed={'ocr_runtime','ocr_models'} <= installed_ids,
                    blocked_releases=[dict(release_id=e.release_id, tag=e.tag, reason=e.blocked_reason) for e in self.entries if e.blocked_reason][:50])

    def prepare(self, *, action, selected, excluded, restore_backup_id=None):
        inventory = getattr(self.content, 'inventory_scope', nullcontext)
        with inventory():
            return self._prepare(action=action, selected=selected, excluded=excluded, restore_backup_id=restore_backup_id)

    def _prepare(self, *, action, selected, excluded, restore_backup_id=None, operation_id=None):
        from .module_preflight import check_update_access
        if self.busy and self.current_operation_id != operation_id: raise ModuleExecutionError('Inna operacja modułów jest w toku.')
        if action == 'install_ocr' and self._ocr_management() == 'setup':
            if not {'ocr_runtime','ocr_models'} <= {m.module_id for m in read_module_set(self.context).modules}:
                raise ModuleExecutionError('Moduł OCR nie zainstalowany. Uruchom pełny Setup i zaznacz składnik OCR.')
        check_update_access(self.context)
        active = read_module_set(self.context)
        releases = self._catalog()
        if not releases and self.source.offline:
            error = (getattr(self.source, 'error', None) or {}).get('message')
            raise ModuleExecutionError((error or 'Nie udało się pobrać katalogu GitHuba.') +
                                       ' Brak lokalnego katalogu pozwalającego przygotować operację. Ponów sprawdzenie wersji.')
        environment = self._environment(restore_backup_id, check_integrity=operation_id is None)
        plan = plan_module_operation(active, releases, environment, action=action,
                                      selected=selected, excluded=frozenset(excluded),
                                      available_hashes=(frozenset() if operation_id else
                                          self.content.available_hashes() | self.content.local_hashes(active)))
        if operation_id:
            plan = replace(plan, plan_id=operation_id)
        if not plan.conflicts and operation_id is None:
            from .module_preflight import check_operation_preflight
            check_operation_preflight(self.context, plan.target, active, self.content)
        migrations=[]
        if plan.migration_ids:
            source=next(r for r in releases if r.release_id==plan.target.release_id)
            by_id={s.migration_id:s for s in source.migrations}
            migrations=[asdict(by_id[identifier]) for identifier in plan.migration_ids]
            owners={m.module_id:m.version_id for m in source.modules}
            chosen={m.module_id:m.version_id for m in plan.target.modules}
            if any(owners[s['module_id']] != chosen.get(s['module_id']) for s in migrations):
                from .module_contracts import ModuleConflict
                plan=replace(plan,conflicts=plan.conflicts+(ModuleConflict('migration_module_incompatible','core','',None,None,
                    'Migracja wymaga wersji modułu z docelowego wydania; wybrana blokada ją uniemożliwia.'),))
        payload = dict(plan_id=plan.plan_id, action=plan.action, expected_revision=plan.expected_revision,
                       target=module_set_payload(plan.target), conflicts=[asdict(c) for c in plan.conflicts],
                       download_bytes=plan.download_bytes, migration_ids=list(plan.migration_ids), environment=asdict(environment),
                       restore_backup_id=restore_backup_id, migrations=migrations,
                       has_changes=({m.module_id: m.version_id for m in active.modules} !=
                                    {m.module_id: m.version_id for m in plan.target.modules} or
                                    active.pinned != plan.target.pinned or bool(restore_backup_id) or action == 'install_ocr'))
        entry = next((entry for entry in self.entries if entry.release_id == plan.target.release_id), None)
        if entry and active.release_id != plan.target.release_id:
            payload['release_notice'] = dict(version_id='release:' + str(entry.release_id), release_id=entry.release_id,
                tag=entry.tag, body=entry.release_notes, url=release_link(entry.tag))
        atomic_json(safe_path(self.context.state_root, 'module-plans/' + plan.plan_id + '.json'), payload)
        old = {m.module_id: m for m in active.modules}
        return dict(plan_id=plan.plan_id, action=plan.action, expected_revision=plan.expected_revision,
                    conflicts=payload['conflicts'], download_bytes=plan.download_bytes,
                    restore_backup_id=restore_backup_id,
                    setup_release_url=next((release_link(r.tag) for r in releases if r.release_id == plan.target.release_id), None),
                    has_changes=payload['has_changes'],
                    changes=[dict(module_id=m.module_id, current=old[m.module_id].display_version if m.module_id in old else None,
                                  target=m.display_version, release_url=release_link(m.source_tag)) for m in plan.target.modules
                             if m.module_id not in old or m.version_id != old[m.module_id].version_id],
                    pinned=sorted(plan.target.pinned))

    def authorization_request(self, **payload):
        """Create a short-lived, nonsecret request for the native host launcher."""
        from .module_preflight import check_update_access, ModuleAccessError
        from .module_authorization import AuthorizationError
        from .control_protocol import validate_module_payload
        validate_module_payload('module_plan', payload)
        if self.busy: raise ModuleExecutionError('Inna operacja modułów jest w toku.')
        try: check_update_access(self.context)
        except ModuleAccessError as exc:
            if exc.details['code'] != 'permission_required': raise
        else: raise AuthorizationError('Konto kontrolera ma dostęp. Przygotuj zwykły plan aktualizacji.')
        with self._authorization_lock:
            if len(self._authorization_requests) >= 8:
                raise AuthorizationError('Zbyt wiele oczekujących logowań. Anuluj poprzednią próbę lub zaczekaj na jej wygaśnięcie.')
            identifier = uuid4().hex
            timer = threading.Timer(300, lambda: self._expire_authorization(identifier))
            timer.daemon = True
            self._authorization_requests[identifier] = dict(payload=payload, state='pending', timer=timer,
                                                          expires_at=time.monotonic() + 300)
            timer.start()
        return dict(request_id=identifier, state='pending',
                    launch_url=f'picsyncra-update://authorize/{self.context.installation_id}/{identifier}')

    def _expire_authorization(self, request_id):
        with self._authorization_lock:
            request = self._authorization_requests.pop(request_id, None)
            if request:
                request['timer'].cancel()
                token = self._authorizations.pop(request.get('plan_id'), None)
                if token: token.close()

    def _authorization_request(self, request_id):
        from .module_authorization import AuthorizationError
        request = self._authorization_requests.get(request_id)
        if request and request['state'] != 'executing' and time.monotonic() >= request['expires_at']:
            self._expire_authorization(request_id)
            request = None
        if request is None: raise AuthorizationError('Jednorazowe logowanie wygasło. Ponów aktualizację.')
        return request

    def authorization_status(self, request_id):
        from .module_authorization import AuthorizationError
        with self._authorization_lock:
            request = self._authorization_request(request_id)
            return dict(request_id=request_id, state=request['state'], action=request['payload']['action'],
                        operation_id=request.get('operation_id'), plan_id=request.get('plan_id'))

    def cancel_authorization(self, request_id):
        with self._authorization_lock:
            request = self._authorization_requests.get(request_id)
            if request:
                if request['state'] == 'executing':
                    raise ModuleExecutionError('Instalacja już trwa; logowanie zostanie zwolnione po jej zakończeniu.')
                token = self._authorizations.pop(request.get('plan_id'), None)
                if token: token.close()
                request['state'] = 'cancelled'
        return dict(state='cancelled')

    def authorize(self, request_id, credential_blob):
        from .module_authorization import logon_credentials, AuthorizationError
        with self._authorization_lock:
            request = self._authorization_request(request_id)
            if request['state'] != 'pending':
                raise AuthorizationError('Jednorazowe logowanie wygasło lub zostało już użyte.')
            # Never retain the supplied blob in the request, plan or journal.
            token = logon_credentials(self.context.installation_id, request_id, credential_blob)
            try:
                with token.scope():
                    plan = self.prepare(**request['payload'])
                    path = safe_path(self.context.state_root, 'module-plans/' + plan['plan_id'] + '.json')
                    payload = self._load_plan(plan['plan_id'])
                    payload['requires_authorization'] = True
                    atomic_json(path, payload, replace=True)
                self._authorization_request(request_id)
                request.update(state='prepared', plan_id=plan['plan_id'])
                self._authorizations[plan['plan_id']] = token
                return plan
            except Exception:
                token.close()
                raise

    def _load_plan(self, plan_id):
        if not isinstance(plan_id, str) or not re.fullmatch('[a-f0-9]{32}', plan_id): raise ModuleExecutionError('Nieprawidłowy plan.')
        return json.loads(safe_path(self.context.state_root, 'module-plans/' + plan_id + '.json').read_text(encoding='utf-8'))

    def _revalidate(self, plan, restore_backup_id):
        payload = self._load_plan(plan.plan_id)
        environment = self._environment(restore_backup_id)
        steps=tuple(MigrationStep(**s) for s in payload['migrations'])
        checked=replace(environment,database_schema=steps[-1].to_schema) if steps else environment
        if asdict(environment) != payload['environment'] or check_module_compatibility(plan.target, checked):
            raise ModuleExecutionError('Zgodność bazy lub konfiguracji zmieniła się. Przygotuj nowy plan.')
        # Reverify signatures, provenance and target identities before execution,
        # including offline. Plans are never a substitute for signed catalogs.
        releases = self._catalog()
        if steps:
            source=next((r for r in releases if r.release_id==plan.target.release_id),None)
            if source is None or any(step not in source.migrations for step in steps):
                raise ModuleExecutionError('Migracja nie jest dostępna w podpisanym katalogu.')
        allowed = {(m.module_id, m.version_id) for r in releases for m in r.modules}
        current = {(m.module_id, m.version_id) for m in read_module_set(self.context).modules}
        if any((m.module_id, m.version_id) not in allowed | current for m in plan.target.modules):
            raise ModuleExecutionError('Wersja modułu nie jest dostępna w zweryfikowanym katalogu.')

    def _migrate(self,plan):
        import subprocess
        from .module_state import module_set_root
        host=safe_path(module_set_root(self.context,plan.target),'apps/web/PicSyncra-WEB.exe')
        result=subprocess.run([str(host),'--module-migrate',plan.plan_id,'--installation-id',self.context.installation_id],
                              cwd=host.parent,timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode: raise ModuleExecutionError('Migracja nie przeszła kontroli; przywracanie danych z kopii.')

    def submit(self, *, action, selected, excluded, restore_backup_id=None):
        """Accept work before preparation; the controller owns its entire lifetime."""
        from .module_preflight import check_update_access
        if restore_backup_id:
            raise ModuleExecutionError('Odtworzenie starszej bazy wymaga osobnego potwierdzenia.')
        previous = self.executor.status()
        if previous and previous['state'] not in {'committed', 'rolled_back', 'failed'}:
            raise ModuleExecutionError('Najpierw należy odzyskać poprzednią operację.')
        check_update_access(self.context)
        identifier = uuid4().hex
        path = safe_path(self.context.state_root, 'module-operations/' + identifier + '.json')
        accepted = dict(operation_id=identifier, state='preparing', action=action, error=None)
        with self._lock:
            if self.busy: raise ModuleExecutionError('Inna operacja modułów jest w toku.')
            self.busy, self.current_operation_id = True, identifier
        try:
            atomic_json(path, accepted)
            atomic_json(safe_path(self.context.state_root, 'module-maintenance-request.json'),
                        dict(operation_id=identifier), replace=True)
            def work():
                try:
                    with self.content.inventory_scope():
                        result = self._prepare(action=action, selected=selected, excluded=excluded,
                                               operation_id=identifier)
                    if result['conflicts']:
                        failed = dict(accepted, state='failed', error='Plan zawiera konflikty zgodności.',
                                      conflicts=result['conflicts'], setup_release_url=result['setup_release_url'])
                        atomic_json(path, failed, replace=True)
                    else:
                        _, execute = self._accept_execution(identifier, restore_backup_id=None,
                            acknowledge_data_loss=False, authorized=False, owned=True)
                        if execute: execute()
                except Exception as exc:
                    atomic_json(path, dict(accepted, state='failed', error=str(exc),
                        error_details=getattr(exc, 'details', None)), replace=True)
                finally:
                    try:
                        status = self.executor.status()
                        if not status or status['state'] in {'committed', 'rolled_back', 'failed'}:
                            self.executor.clear_maintenance()
                    except OSError as exc:
                        from .module_preflight import ModuleAccessError
                        error = ModuleAccessError('maintenance_ready', exc)
                        atomic_json(path, dict(accepted, state='recovery_required', error=str(error),
                                              error_details=error.details), replace=True)
                    finally:
                        with self._lock: self.busy = False
            self.schedule(work)
        except Exception:
            self.executor.clear_maintenance()
            with self._lock: self.busy = False
            raise
        return accepted

    def execute(self, plan_id, *, restore_backup_id=None, acknowledge_data_loss=False):
        with self._authorization_lock:
            for identifier, request in tuple(self._authorization_requests.items()):
                if request.get('plan_id') == plan_id:
                    self._authorization_request(identifier)
            token = self._authorizations.pop(plan_id, None)
        try:
            with token.scope() if token else nullcontext():
                accepted, work = self._accept_execution(plan_id, restore_backup_id=restore_backup_id,
                    acknowledge_data_loss=acknowledge_data_loss, authorized=token is not None)
            with self._authorization_lock:
                for request in self._authorization_requests.values():
                    if request.get('plan_id') == plan_id:
                        request.update(state='executing', operation_id=plan_id)
            if work is None:
                if token: token.close()
                return accepted
            def authorized_work():
                try:
                    with token.scope() if token else nullcontext(): work()
                finally:
                    if token: token.close()
            try: self.schedule(authorized_work)
            except Exception:
                with self._lock: self.busy = False
                with self._authorization_lock:
                    for request in self._authorization_requests.values():
                        if request.get('plan_id') == plan_id: request['state'] = 'cancelled'
                raise
            return accepted
        except Exception:
            if token: token.close()
            raise

    def _accept_execution(self, plan_id, *, restore_backup_id, acknowledge_data_loss, authorized, owned=False):
        payload = self._load_plan(plan_id)
        if payload.get('requires_authorization') and not authorized:
            raise ModuleExecutionError('Jednorazowe logowanie wygasło lub zostało już użyte. Przygotuj nowy plan.')
        if payload['restore_backup_id'] != restore_backup_id:
            raise ModuleExecutionError('Wybrana kopia bazy wymaga osobnego planu zgodności.')
        if payload['conflicts']: raise ModuleExecutionError('Plan zawiera konflikty zgodności.')
        if restore_backup_id and acknowledge_data_loss is not True:
            raise ModuleExecutionError('Potwierdź utratę nowszych danych przy odtwarzaniu starszej bazy.')
        target = parse_module_set(payload['target'])
        if read_module_set(self.context).revision != payload['expected_revision']:
            raise ModuleExecutionError('Instalacja zmieniła się. Przygotuj nowy plan; zachowaj swoje wybory.')
        if payload.get('has_changes') is False:
            result = dict(operation_id=plan_id, state='committed', action=payload['action'], error=None, unchanged=True)
            atomic_json(safe_path(self.context.state_root, 'module-operations/' + plan_id + '.json'), result, replace=True)
            return result, None
        plan = ModulePlan(plan_id, payload['action'], payload['expected_revision'], target, (), (), payload['download_bytes'], tuple(payload['migration_ids']))
        with self._lock:
            if self.busy and not (owned and self.current_operation_id == plan_id): raise ModuleExecutionError('Inna operacja modułów jest w toku.')
            self.busy = True
            self.current_operation_id = plan_id
        accepted = dict(operation_id=plan_id, state='accepted', action=plan.action, error=None)
        operation_path = safe_path(self.context.state_root, 'module-operations/' + plan_id + '.json')
        try: atomic_json(operation_path, accepted, replace=True)
        except Exception:
            with self._lock:
                if not owned: self.busy = False
            raise
        def work():
            try:
                result = self.executor.execute(plan, restore_backup_id=restore_backup_id, acknowledge_data_loss=acknowledge_data_loss)
            except Exception as exc:
                result = dict(operation_id=plan_id, state='failed', action=plan.action, error=str(exc), error_details=getattr(exc, 'details', None))
            finally:
                status = None
                try:
                    status = self.executor.status()
                    if not status or status['state'] in {'committed', 'rolled_back', 'failed'}:
                        self.executor.clear_maintenance()
                except OSError as exc:
                    from .module_preflight import ModuleAccessError
                    error = ModuleAccessError('maintenance_ready', exc)
                    result = dict(operation_id=plan_id, state='recovery_required', action=plan.action,
                                  error=str(error), error_details=error.details)
                    if status:
                        self.executor._write(status, 'recovery_required', error=str(error), error_details=error.details)
                finally:
                    with self._lock:
                        if not owned: self.busy = False
            atomic_json(operation_path, result, replace=True)
        return accepted, work

    def operation(self, operation_id):
        if not isinstance(operation_id, str) or not re.fullmatch('[a-f0-9]{32}', operation_id):
            raise ModuleExecutionError('Nieprawidłowa operacja.')
        current = self.executor.status()
        if current and current['operation_id'] == operation_id:
            result = {key: current.get(key) for key in ('operation_id', 'state', 'action', 'error', 'error_details')}
        else:
            path = safe_path(self.context.state_root, 'module-operations/' + operation_id + '.json')
            result = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if result is not None and result['state'] in {'accepted', 'preparing'} and self.current_operation_id != operation_id:
            # Accepted work belongs to this controller instance's worker. A
            # restarted host must not leave old clients polling forever or
            # silently execute a plan whose live preflight may have changed.
            result.update(state='failed', error='Kontroler został uruchomiony ponownie przed rozpoczęciem operacji. Przygotuj i zatwierdź nowy plan.')
        progress_path = safe_path(self.context.state_root, 'module-progress/' + operation_id + '.json')
        if result is not None:
            snapshot = self.executor.progress_snapshot(operation_id)
            if snapshot is not None:
                result['progress'] = snapshot
            elif progress_path.exists():
                result['progress'] = json.loads(progress_path.read_text(encoding='utf-8'))
        return result

    def _healthy(self):
        from .controller_host import _backend_ready
        status = []
        if _backend_ready(self.controller, on_status=status.append): return True
        details = status[-1] if status else dict(code='backend_health_timeout')
        message = ('Backend zakończył pracę podczas uruchamiania.' if details['code']=='backend_exited'
                   else 'Backend nie potwierdził gotowości w wymaganym czasie.')
        if details.get('observation') in {'different_process','different_application'}:
            message = 'Kontrola działania otrzymała odpowiedź innego procesu lub aplikacji.'
        failed = [name for name, state in details.get('components',{}).items() if state!='online']
        if failed: message += ' Niesprawne składniki: ' + ', '.join(failed) + '.'
        raise ModuleExecutionError(message, details=details)

    def _quiesce(self, operation_id):
        if not self.controller.snapshot()['backend_running']: return
        path = safe_path(self.context.state_root, 'module-maintenance-request.json')
        atomic_json(path, dict(operation_id=operation_id), replace=True)
        deadline = time.monotonic() + 900
        ack = safe_path(self.context.state_root, 'module-maintenance-ready.json')
        while time.monotonic() < deadline:
            if not self.controller.snapshot()['backend_running']: return
            if ack.exists():
                state = json.loads(ack.read_text(encoding='utf-8'))
                if state.get('operation_id') == operation_id and state.get('ready') is True: return
            time.sleep(0.25)
        raise ModuleExecutionError('Zadania nie zakończyły się w wymaganym czasie. Aktualizacja została wstrzymana.')
