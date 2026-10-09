"""Select the first installed module set, retaining existing modular installs."""
import json
from pathlib import Path
from uuid import uuid4
from .contracts import InstallContext
from .database import inspect_database
from .module_filesystem import safe_path, atomic_json
from .module_state import parse_module_set, read_module_set, publish_module_set, activate_module_set
from .module_compatibility import check_module_compatibility
from .module_contracts import ModuleEnvironment
from .module_executor import installation_lock
from .backups import create_operation_backup


def initialize_module_layout(request):
    keys={'installation_id','program_root','state_root','database_path','include_local'}
    if not isinstance(request,dict) or set(request)!=keys or type(request['include_local']) is not bool:
        raise ValueError('Invalid initial module layout request.')
    context=InstallContext(request['installation_id'],Path(request['program_root']),Path(request['state_root']),
                           Path(request['state_root'])/'config',Path(request['database_path']))
    context.config_root.mkdir(parents=True,exist_ok=True)
    with installation_lock(context):
        marker_path=safe_path(context.program_root,'active.json')
        marker=json.loads(marker_path.read_text(encoding='utf-8')) if marker_path.exists() else None
        if marker and marker.get('schema')==2:
            read_module_set(context)
            return  # Infrastructure repair preserves selected versions/pins.
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
        if context.database_path.exists():
            inspection=inspect_database(context.database_path)
            if not inspection.integrity_ok or not inspection.is_picsyncra or check_module_compatibility(selected,ModuleEnvironment(inspection.schema_version,1,'cp313-win-amd64',2,2)):
                raise ValueError('Baza nie jest zgodna z nowym instalatorem. Najpierw użyj Migratora na kopii bazy.')
        if marker:
            if marker.get('installation_id')!=context.installation_id: raise ValueError('Foreign installed marker.')
            receipt=create_operation_backup(context,'module-upgrade-'+uuid4().hex)
            atomic_json(safe_path(context.state_root,'module-initial-backup.json'),dict(marker=marker,backup_id=receipt.backup_id),replace=True)
        publish_module_set(context,selected)
        atomic_json(settings_path,settings,replace=True)
        activate_module_set(context,selected,expected_revision=0)
