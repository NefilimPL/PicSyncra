"""Shared controller facade for WEB and the stable recovery launcher."""
from __future__ import annotations
from dataclasses import asdict, replace
import json
import re
import threading
import time
from urllib.parse import quote
from .controller_version import CONTROLLER_VERSION
from .database import inspect_database
from .module_content import ModuleContentStore
from .module_configuration import inspect_configuration
from .module_contracts import ModuleEnvironment, ModulePlan, MigrationStep
from .module_definition import module_definitions
from .module_compatibility import check_module_compatibility
from .module_executor import ModuleExecutor, ModuleExecutionError, verified_backup
from .module_filesystem import atomic_json, safe_path
from .module_migrations import migration_path
from .module_planner import plan_module_operation
from .module_source import ModuleReleaseSource
from .module_state import read_module_set, module_set_payload, parse_module_set

LAUNCHER_VERSION = 2
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
        self.entries = ()
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

    def backend_start_allowed(self):
        try:
            status = self.executor.status()
            return not self.busy and (not status or status['state'] in {'committed', 'rolled_back', 'failed'})
        except (OSError, ValueError, KeyError):
            return False

    def recover(self):
        with self._lock:
            if self.busy: raise ModuleExecutionError('Inna operacja modułów jest w toku.')
            status = self.executor.status()
            if not status or status['state'] in {'committed', 'rolled_back', 'failed'}:
                raise ModuleExecutionError('Brak przerwanej operacji do odzyskania.')
            operation_id = status['operation_id']
            self._load_plan(operation_id)
            self.busy = True
        def work():
            try:
                self.executor.recover()
            finally:
                with self._lock: self.busy = False
        self.schedule(work)
        return dict(operation_id=operation_id, state='accepted', action='recover', error=None)

    def _environment(self, restore_backup_id=None):
        inspection = inspect_database(self.context.database_path)
        if not inspection.integrity_ok or not inspection.is_picsyncra:
            raise ModuleExecutionError('Baza PicSyncra nie przeszła sprawdzania spójności.')
        if restore_backup_id:
            backup, schema = verified_backup(self.context, restore_backup_id)
            config_schema = inspect_configuration(safe_path(backup, 'config'))
        else:
            schema = inspection.schema_version
            config_schema = inspect_configuration(self.context.config_root)
        return ModuleEnvironment(schema, config_schema, RUNTIME_ABI, CONTROLLER_VERSION, LAUNCHER_VERSION)

    def _catalog(self):
        self.entries = self.source.load(self._channel())
        return tuple(entry.release for entry in self.entries if entry.release and not entry.blocked_reason)

    def catalog(self):
        active = read_module_set(self.context)
        releases = self._catalog()
        latest = max(releases, key=lambda r: r.published_at, default=None)
        labels = {item.module_id: item.label for item in module_definitions()}
        rows = []
        from datetime import datetime
        def published(release): return datetime.fromisoformat(release.published_at.replace('Z', '+00:00'))
        version_dates = {}
        for release in sorted(releases, key=published):
            for item in release.modules: version_dates.setdefault((item.module_id, item.version_id), published(release))
        for module in active.modules:
            versions = {}
            for release in sorted(releases, key=lambda r: r.published_at, reverse=True):
                for item in release.modules:
                    if item.module_id == module.module_id and (module.module_id, module.version_id) in version_dates and version_dates[(item.module_id, item.version_id)] <= version_dates[(module.module_id, module.version_id)]:
                        versions.setdefault(item.version_id, dict(version_id=item.version_id, display_version=item.display_version,
                            release_id=item.source_release_id, release_url=release_link(item.source_tag), available=True))
            # Installed version stays visible, even before the first signed
            # publication. Availability for rollback requires a trusted catalog.
            versions.setdefault(module.version_id, dict(version_id=module.version_id, display_version=module.display_version,
                release_id=module.source_release_id, release_url=release_link(module.source_tag), available=False))
            newest = next((m for m in latest.modules if m.module_id == module.module_id), None) if latest else None
            rows.append(dict(module_id=module.module_id, label=labels[module.module_id], current=module.display_version,
                             current_id=module.version_id, latest=newest.display_version if newest else None,
                             pinned=module.module_id in active.pinned, versions=list(versions.values())[:50]))
        backups = []
        backup_root = safe_path(self.context.state_root, 'backups/operations')
        if backup_root.exists():
            for path in sorted(backup_root.iterdir(), reverse=True):
                if path.name.startswith('.'): continue
                try:
                    _, schema = verified_backup(self.context, path.name)
                    backups.append(dict(backup_id=path.name, schema_version=schema))
                except (RuntimeError, OSError, ValueError): continue
                if len(backups) >= 100: break
        return dict(revision=active.revision, modules=rows, offline=self.source.offline, backups=backups,
                    ocr_installed=all(any(m.module_id == name for m in active.modules) for name in ('ocr_runtime', 'ocr_models')),
                    blocked_releases=[dict(release_id=e.release_id, tag=e.tag, reason=e.blocked_reason) for e in self.entries if e.blocked_reason][:50])

    def prepare(self, *, action, selected, excluded, restore_backup_id=None):
        active = read_module_set(self.context)
        releases = self._catalog()
        environment = self._environment(restore_backup_id)
        plan = plan_module_operation(active, releases, environment, action=action,
                                      selected=selected, excluded=frozenset(excluded),
                                      available_hashes=self.content.available_hashes() | self.content.local_hashes(active))
        if not plan.conflicts:
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
                       restore_backup_id=restore_backup_id, migrations=migrations)
        atomic_json(safe_path(self.context.state_root, 'module-plans/' + plan.plan_id + '.json'), payload)
        old = {m.module_id: m for m in active.modules}
        return dict(plan_id=plan.plan_id, action=plan.action, expected_revision=plan.expected_revision,
                    conflicts=payload['conflicts'], download_bytes=plan.download_bytes,
                    restore_backup_id=restore_backup_id,
                    changes=[dict(module_id=m.module_id, current=old[m.module_id].display_version if m.module_id in old else None,
                                  target=m.display_version, release_url=release_link(m.source_tag)) for m in plan.target.modules
                             if m.module_id not in old or m.version_id != old[m.module_id].version_id],
                    pinned=sorted(plan.target.pinned))

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

    def execute(self, plan_id, *, restore_backup_id=None, acknowledge_data_loss=False):
        payload = self._load_plan(plan_id)
        if payload['restore_backup_id'] != restore_backup_id:
            raise ModuleExecutionError('Wybrana kopia bazy wymaga osobnego planu zgodności.')
        if payload['conflicts']: raise ModuleExecutionError('Plan zawiera konflikty zgodności.')
        if restore_backup_id and acknowledge_data_loss is not True:
            raise ModuleExecutionError('Potwierdź utratę nowszych danych przy odtwarzaniu starszej bazy.')
        target = parse_module_set(payload['target'])
        if read_module_set(self.context).revision != payload['expected_revision']:
            raise ModuleExecutionError('Instalacja zmieniła się. Przygotuj nowy plan; zachowaj swoje wybory.')
        plan = ModulePlan(plan_id, payload['action'], payload['expected_revision'], target, (), (), payload['download_bytes'], tuple(payload['migration_ids']))
        with self._lock:
            if self.busy: raise ModuleExecutionError('Inna operacja modułów jest w toku.')
            self.busy = True
        accepted = dict(operation_id=plan_id, state='accepted', action=plan.action, error=None)
        operation_path = safe_path(self.context.state_root, 'module-operations/' + plan_id + '.json')
        atomic_json(operation_path, accepted, replace=True)
        def work():
            try:
                result = self.executor.execute(plan, restore_backup_id=restore_backup_id, acknowledge_data_loss=acknowledge_data_loss)
            except Exception as exc:
                result = dict(operation_id=plan_id, state='failed', action=plan.action, error=str(exc))
            finally:
                status = self.executor.status()
                if not status or status['state'] in {'committed', 'rolled_back', 'failed'}:
                    self.executor.clear_maintenance()
                with self._lock: self.busy = False
            atomic_json(operation_path, result, replace=True)
        self.schedule(work)
        return accepted

    def operation(self, operation_id):
        self._load_plan(operation_id)
        current = self.executor.status()
        if current and current['operation_id'] == operation_id:
            return {key: current[key] for key in ('operation_id', 'state', 'action', 'error')}
        path = safe_path(self.context.state_root, 'module-operations/' + operation_id + '.json')
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def _healthy(self):
        from .controller_host import _backend_ready
        return _backend_ready(self.controller)

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
