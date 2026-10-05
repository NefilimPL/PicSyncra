"""Controller-owned, journaled module transaction and restart recovery."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4
from .backups import create_operation_backup
from .database import inspect_database
from .module_content import ModuleContentStore
from .module_filesystem import atomic_json, safe_path
from .module_state import read_module_set, module_set_payload, parse_module_set, activate_module_set


class ModuleExecutionError(RuntimeError):
    pass


@contextmanager
def installation_lock(context):
    """OS released cross-process lock, including recovery after power loss."""
    path = safe_path(context.state_root, 'module-lock.sqlite')
    connection = sqlite3.connect(path, timeout=0)
    try:
        connection.execute('BEGIN EXCLUSIVE')
        yield
    except sqlite3.OperationalError as exc:
        raise ModuleExecutionError('Inna operacja używa instalacji lub bazy. Spróbuj ponownie.') from exc
    finally:
        connection.close()


def _config_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*'), key=lambda item: item.as_posix()):
        path = safe_path(root, path.relative_to(root).as_posix())
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(b'\0')
            with path.open('rb') as stream:
                while chunk := stream.read(1024 * 1024): digest.update(chunk)
    return digest.hexdigest()


def verified_backup(context, backup_id):
    import re
    if not isinstance(backup_id, str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}', backup_id):
        raise ModuleExecutionError('Nieprawidłowy identyfikator kopii bazy.')
    root = safe_path(context.state_root, 'backups/operations/' + backup_id)
    receipt = json.loads(safe_path(root, 'receipt.json').read_text(encoding='utf-8'))
    database = safe_path(root, 'database.sqlite')
    with database.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    inspection = inspect_database(database)
    if receipt.get('backup_id') != backup_id or receipt.get('verified') is not True or receipt.get('database_sha256') != digest or receipt.get('config_sha256') != _config_digest(safe_path(root, 'config')) or not inspection.integrity_ok or not inspection.is_picsyncra or receipt.get('schema_version') != inspection.schema_version:
        raise ModuleExecutionError('Kopia bazy lub konfiguracji nie przeszła weryfikacji.')
    return root, inspection.schema_version


def _assert_database_idle(path):
    if not path.is_file(): raise ModuleExecutionError('Brak zarządzanej bazy danych.')
    connection = sqlite3.connect(path, timeout=0)
    try:
        # Convert WAL to a single main file before any restoration. This also
        # refuses a busy reader/writer instead of deleting a live WAL.
        if connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
            raise ModuleExecutionError('Baza jest nadal używana przez inny proces.')
        mode = connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
        if mode.lower() != 'delete': raise ModuleExecutionError('Baza jest nadal używana.')
        connection.execute('BEGIN EXCLUSIVE')
        connection.rollback()
    finally:
        connection.close()


def restore_backup(context, backup_id):
    root, schema = verified_backup(context, backup_id)
    _assert_database_idle(context.database_path)
    config = safe_path(context.config_root)
    staging = safe_path(context.state_root, 'module-restore-' + uuid4().hex)
    shutil.copytree(safe_path(root, 'config'), staging)
    temporary = context.database_path.with_name('.module-restore-' + uuid4().hex + '.sqlite')
    try:
        shutil.copyfile(safe_path(root, 'database.sqlite'), temporary)
        with temporary.open('rb+') as stream: os.fsync(stream.fileno())
        os.replace(temporary, context.database_path)
        # Idempotent copy plus removal of files absent from the snapshot. A
        # recovery repeats this phase if interrupted before its journal commit.
        config.mkdir(parents=True, exist_ok=True)
        originals = {p.relative_to(staging).as_posix() for p in staging.rglob('*') if p.is_file()}
        for path in list(config.rglob('*')):
            path = safe_path(config, path.relative_to(config).as_posix())
            if path.is_file() and path.relative_to(config).as_posix() not in originals: path.unlink()
        for relative in originals:
            target = safe_path(config, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_path(staging, relative), target)
    finally:
        temporary.unlink(missing_ok=True)
        shutil.rmtree(staging)
    return schema


class ModuleExecutor:
    def __init__(self, context, controller, *, content=None, quiesce, healthy, migrate=None, revalidate=None):
        self.context = context
        self.controller = controller
        self.content = content or ModuleContentStore(context)
        self.quiesce = quiesce
        self.healthy = healthy
        self.migrate = migrate
        self.revalidate = revalidate
        self.path = safe_path(context.state_root, 'module-operation.json')

    def status(self):
        return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else None

    def _write(self, record, state, **changes):
        record.update(changes, state=state)
        atomic_json(self.path, record, replace=True)

    def execute(self, plan, *, restore_backup_id=None, acknowledge_data_loss=False):
        if plan.conflicts:
            raise ModuleExecutionError('Plan zawiera konflikty zgodności.')
        if restore_backup_id is not None and acknowledge_data_loss is not True:
            raise ModuleExecutionError('Odtworzenie starszej bazy wymaga osobnego potwierdzenia utraty nowszych danych.')
        with installation_lock(self.context):
            active = read_module_set(self.context)
            if active.revision != plan.expected_revision:
                raise ModuleExecutionError('Instalacja zmieniła się. Przygotuj nowy plan; wybory pozostają zachowane.')
            previous = self.status()
            if previous and previous['state'] not in {'committed', 'rolled_back', 'failed'}:
                raise ModuleExecutionError('Najpierw należy odzyskać poprzednią operację.')
            if self.revalidate: self.revalidate(plan, restore_backup_id)
            if plan.migration_ids and self.migrate is None:
                raise ModuleExecutionError('Brak zweryfikowanego wykonawcy migracji bazy.')
            if restore_backup_id: verified_backup(self.context, restore_backup_id)
            marker = json.loads(safe_path(self.context.program_root, 'active.json').read_text(encoding='utf-8'))
            record = dict(operation_id=plan.plan_id, action=plan.action, previous=module_set_payload(active),
                          previous_marker=marker, target=module_set_payload(plan.target), backup_id=None,
                          data_changed=False, backend_was_running=bool(self.controller.snapshot()['backend_running']), error=None)
            self._write(record, 'downloading')
            try:
                self.content.assemble(plan.target)
                self._write(record, 'draining')
                self.quiesce(plan.plan_id)
                self._write(record, 'stopping')
                if not self.controller.stop_backend(force=False): raise ModuleExecutionError('Backend nadal pracuje.')
                _assert_database_idle(self.context.database_path)
                # Schema may have changed while downloading/draining.
                if self.revalidate: self.revalidate(plan, restore_backup_id)
                self._write(record, 'backing_up')
                receipt = create_operation_backup(self.context, plan.plan_id)
                self._write(record, 'installing', backup_id=receipt.backup_id)
                if restore_backup_id:
                    self._write(record, 'restoring', data_changed=True)
                    restore_backup(self.context, restore_backup_id)
                if plan.migration_ids:
                    self._write(record, 'migrating', data_changed=True)
                    self.migrate(plan)
                activate_module_set(self.context, plan.target, expected_revision=plan.expected_revision)
                # Starting selected code can itself migrate the DB. Journal the
                # need to restore data before launching any application code.
                self._write(record, 'validating', data_changed=True)
                self.controller.start_backend()
                if not self.healthy(): raise ModuleExecutionError('Nowy backend nie przeszedł kontroli działania.')
                self._write(record, 'committed')
            except Exception as exc:
                self._rollback(record, str(exc))
            return {k: record[k] for k in ('operation_id', 'state', 'action', 'error')}

    def _rollback(self, record, error):
        try:
            self._write(record, 'rolling_back', error=error)
            if not self.controller.stop_backend(force=False): raise ModuleExecutionError('Nie można zatrzymać backendu do odzyskania.')
            previous = parse_module_set(record['previous'])
            marker = record['previous_marker']
            if marker != dict(schema=2, installation_id=self.context.installation_id, release_id=previous.release_id,
                              set_id=previous.set_id, revision=previous.revision):
                raise ModuleExecutionError('Dziennik odzyskiwania ma niezgodny zestaw.')
            if record['data_changed']:
                if not record['backup_id']: raise ModuleExecutionError('Brak kopii do odzyskania danych.')
                restore_backup(self.context, record['backup_id'])
            atomic_json(safe_path(self.context.program_root, 'active.json'), marker, replace=True)
            if record['backend_was_running']: self.controller.start_backend()
            self._write(record, 'rolled_back')
        except Exception as exc:
            self._write(record, 'recovery_required', error=f'{error}; odzyskiwanie: {exc}')

    def recover(self):
        with installation_lock(self.context):
            record = self.status()
            if not record or record['state'] in {'committed', 'rolled_back', 'failed'}: return None
            self._rollback(record, 'Operacja została przerwana; przywracanie poprzedniego zestawu.')
            return record['state']
