"""Activate bundled updates while retaining pins and optional installed modules."""
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from .contracts import InstallContext
from .database import inspect_database
from .module_filesystem import safe_path, atomic_json
from .module_state import parse_module_set, read_module_set, publish_module_set, activate_module_set, make_module_set, verify_module_set_files
from .module_compatibility import check_module_compatibility
from .module_contracts import ModuleEnvironment
from .module_executor import installation_lock
from .backups import create_operation_backup


def _create_fresh_database(path, expected_schema):
    """Publish a complete current database without ever replacing user data."""
    from ..sqlite_store import SqliteStore
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.picsyncra-db-', suffix='.sqlite', dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        SqliteStore(str(temporary)).initialize()
        # Close/checkpoint WAL before publishing only the main database file.
        with closing(sqlite3.connect(temporary)) as connection:
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            if connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
                raise RuntimeError('Nie można przygotować nowej bazy PicSyncra.')
        inspection = inspect_database(temporary)
        if not inspection.integrity_ok or not inspection.is_picsyncra or inspection.schema_version != expected_schema:
            raise RuntimeError('Nowa baza PicSyncra nie przeszła weryfikacji schematu i spójności.')
        with temporary.open('rb+') as handle: os.fsync(handle.fileno())
        os.link(temporary, path)  # Atomic no-overwrite; fail if a DB appeared meanwhile.
    finally:
        for candidate in (temporary, Path(name + '-wal'), Path(name + '-shm')):
            candidate.unlink(missing_ok=True)


def initialize_module_layout(request):
    keys={'installation_id','program_root','state_root','database_path','include_local'}
    if not isinstance(request,dict) or set(request)!=keys or type(request['include_local']) is not bool:
        raise ValueError('Invalid initial module layout request.')
    context=InstallContext(request['installation_id'],Path(request['program_root']),Path(request['state_root']),
                           Path(request['state_root'])/'config',Path(request['database_path']))
    context.config_root.mkdir(parents=True,exist_ok=True)
    with installation_lock(context):
        from .setup_lifecycle import pending_setup, setup_receipt
        marker_path=safe_path(context.program_root,'active.json')
        marker=json.loads(marker_path.read_text(encoding='utf-8')) if marker_path.exists() else None
        pending = pending_setup(context)
        if pending and marker is None and pending.get('state') == 'activating' and 'previous_marker' in pending and pending['previous_marker'] is None:
            # The first attempt never activated any application code. Preserve
            # its database/configuration and permit a new validated Setup plan.
            atomic_json(safe_path(context.state_root, 'module-setup-result.json'), dict(pending, state='rolled_back'), replace=True)
            pending = None
        if pending and (pending.get('state') != 'prepared' or pending.get('previous_marker') != marker):
            raise RuntimeError('Przerwana instalacja Setup wymaga odzyskania. Uruchom ponownie Setup.')
        previous = read_module_set(context) if marker and marker.get('schema') == 2 else None
        prior_database = setup_receipt(context, dict(previous_marker=marker)).get('previous_database_path') if marker else None
        backup_database = Path(prior_database) if prior_database else context.database_path
        if not backup_database.is_absolute(): raise ValueError('Invalid previous database path.')
        database_changed = bool(marker and backup_database.resolve() != context.database_path.resolve())
        layout=json.loads(safe_path(context.program_root,'module-initial-layout.json').read_text(encoding='utf-8'))
        channel=layout.get('channel','stable')
        if not isinstance(channel,str) or channel not in {'stable','dev'}:
            raise ValueError('Invalid initial module channel.')
        settings_path=safe_path(context.state_root,'installation-settings.json')
        settings=json.loads(settings_path.read_text(encoding='utf-8')) if settings_path.exists() else {}
        if not isinstance(settings,dict): raise ValueError('Invalid installation settings.')
        if 'channel' not in settings: settings['channel']=channel
        selected_id=layout['local' if request['include_local'] else 'base']
        selected=parse_module_set(json.loads(safe_path(context.program_root,'sets/'+selected_id+'/module-set.json').read_text(encoding='utf-8')))
        if selected.set_id!=selected_id: raise ValueError('Initial set identity mismatch.')
        packaged = selected
        changed = True
        if previous:
            chosen = {m.module_id: m for m in previous.modules}
            # Older Setup is a repair, never an implicit downgrade. Optional
            # OCR/LOCAL modules absent from the package remain installed.
            if packaged.release_id >= previous.release_id:
                chosen.update({m.module_id: m for m in packaged.modules if m.module_id not in previous.pinned})
            if chosen == {m.module_id: m for m in previous.modules}:
                changed = False
                selected = previous
            else:
                selected = make_module_set(previous.revision + 1, packaged.release_id,
                                           tuple(chosen.values()), previous.pinned)
            if not changed and database_changed:
                changed = True
                selected = make_module_set(previous.revision + 1, previous.release_id, previous.modules, previous.pinned)
        from .module_configuration import inspect_configuration
        from .controller_version import CONTROLLER_VERSION
        from .module_service import LAUNCHER_VERSION
        fresh_database = not context.database_path.exists()
        if fresh_database and marker and not database_changed:
            raise ValueError('Nie znaleziono bazy istniejącej instalacji. Przywróć jej kopię lub wybierz inną bazę; Setup nie utworzy pustej bazy w jej miejsce.')
        if fresh_database:
            from ..sqlite_store import SCHEMA_VERSION
            schema = SCHEMA_VERSION
        else:
            inspection=inspect_database(context.database_path)
            schema = inspection.schema_version
            if not inspection.integrity_ok or not inspection.is_picsyncra:
                raise ValueError('Baza nie jest zgodna z nowym instalatorem. Najpierw użyj Migratora na kopii bazy.')
        conflicts = check_module_compatibility(selected, ModuleEnvironment(schema,
            inspect_configuration(context.config_root), 'cp313-win-amd64', CONTROLLER_VERSION, LAUNCHER_VERSION))
        if conflicts:
            raise ValueError('Nie można aktywować zestawu z Setup: ' + '; '.join(dict.fromkeys(c.requirement for c in conflicts)))
        if not changed:
            verify_module_set_files(context, previous)
            if fresh_database: _create_fresh_database(context.database_path, schema)
            atomic_json(safe_path(context.state_root, 'module-setup-result.json'),
                        setup_receipt(context, dict(changed=False, target_set_id=previous.set_id,
                                                   previous_marker=marker, state='activating')), replace=True)
            return
        backup_id = None
        selected_database_backup_id = None
        if marker:
            if marker.get('installation_id')!=context.installation_id: raise ValueError('Foreign installed marker.')
            if not backup_database.exists(): raise ValueError('Brak poprzedniej bazy do utworzenia kopii przed zmianą instalacji.')
            receipt=create_operation_backup(replace(context, database_path=backup_database),'module-upgrade-'+uuid4().hex)
            backup_id = receipt.backup_id if receipt else None
            if database_changed and not fresh_database:
                selected_receipt = create_operation_backup(context, 'module-selected-db-' + uuid4().hex)
                selected_database_backup_id = selected_receipt.backup_id
            atomic_json(safe_path(context.state_root,'module-initial-backup.json'),dict(marker=marker,backup_id=receipt.backup_id if receipt else None),replace=True)
        if previous:
            from .module_content import ModuleContentStore
            content = ModuleContentStore(context)
            content.seed(packaged)
            content.seed(previous)
            content.assemble(selected)
        publish_module_set(context,selected)
        if fresh_database: _create_fresh_database(context.database_path, schema)
        atomic_json(settings_path,settings,replace=True)
        atomic_json(safe_path(context.state_root, 'module-setup-result.json'),
                    setup_receipt(context, dict(changed=True, target_set_id=selected.set_id, previous_marker=marker,
                         backup_id=backup_id, backup_database_path=str(backup_database) if backup_id else None,
                         selected_database_backup_id=selected_database_backup_id,
                         selected_database_backup_path=str(context.database_path) if selected_database_backup_id else None,
                         state='activating')), replace=True)
        activate_module_set(context,selected,expected_revision=previous.revision if previous else 0)
