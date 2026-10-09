"""Both real client facades share one signed catalog and controller transaction."""
from io import BytesIO
from dataclasses import replace
import hashlib
import json
import sqlite3
from urllib.parse import unquote
from picsyncra.installation.module_source import ModuleReleaseSource, MANIFEST_NAME
from picsyncra.installation.module_content import ModuleContentStore
from picsyncra.installation.module_manifest import parse_module_manifest
from picsyncra.installation.module_state import make_module_set, activate_module_set, read_module_set
from picsyncra.installation.module_service import ModuleService
from picsyncra.installation.module_launcher import ModuleLauncherModel
from picsyncra.installation.launcher import InstallationControlClient
from picsyncra.installation.control_protocol import ControlDispatcher
from tests.module_fixtures import module_payload, release_payload, signed
from tests.test_module_state import context
from tests.test_module_executor import Controller
from tests.test_module_content import Response


def test_both_clients_share_atomic_rollback_pins_offline_cache_and_stale_plans(context):
    context.config_root.mkdir()
    (context.config_root/'config.json').write_text('{}')
    db=sqlite3.connect(context.database_path)
    db.executescript('CREATE TABLE schema_version(version INTEGER); INSERT INTO schema_version VALUES(1); CREATE TABLE app_config_values(value TEXT);')
    db.close()
    records=[]; assets={}; payloads={}; trusted={}
    for identifier in (1,5):
        common=[module_payload(),module_payload('migrator','apps/migrator/PicSyncra-Migrator.exe')]
        content=b'old' if identifier==1 else b'new'
        modules=common+[module_payload('ftp','picsyncra/services/ftp_service.py',content,source=identifier),
                        module_payload('sql','picsyncra/services/sql_service.py',b'code')]
        # FTP has a separate asset; common code remains in release 1.
        modules[-2]['files'][0]['asset_name']='ftp.bin'
        payload=release_payload(identifier,modules); payloads[identifier]=payload
        raw,sig,key=signed(payload)
        trusted[f'test-{identifier}']=key
        names={MANIFEST_NAME:raw,MANIFEST_NAME+'.sig':sig,MANIFEST_NAME+'.key-id':f'test-{identifier}'.encode(),'ftp.bin':content,'content.bin':b'code'}
        for name,data in names.items(): assets[(f'v{identifier}',name)]=data
        records.append(dict(id=identifier,tag_name=f'v{identifier}',published_at=payload['published_at'],draft=False,prerelease=False,
                            assets=[dict(name=name,size=len(data),browser_download_url=f'https://github.com/NefilimPL/PicSyncra/releases/download/v{identifier}/{name}') for name,data in names.items()]))
    transfers=[]
    def fetch(url,start,size,total):
        tag,name=map(unquote,url.rsplit('/',2)[-2:])
        transfers.append((tag,name,start,size))
        return Response(assets[(tag,name)][start:start+size],start,total)
    store=ModuleContentStore(context,fetch=fetch)
    for data in (b'code',b'old'): store.import_bytes(data)
    first=parse_module_manifest(payloads[1]); active=make_module_set(1,1,first.modules)
    store.assemble(active); activate_module_set(context,active,expected_revision=0)
    source=ModuleReleaseSource(context,keys=trusted,fetch_json=lambda path:records,
        fetch_asset=lambda url:assets[tuple(map(unquote,url.rsplit('/',2)[-2:]))])
    service=ModuleService(context,Controller(),source=source,content=store,schedule=lambda work:work(),quiesce=lambda op:None,healthy=lambda:True)
    dispatcher=ControlDispatcher(Controller(),installation_id='test',authorized_identities={'admin'},module_service=service)
    class Pipe:
        def request(self,message): return dispatcher.dispatch(message,peer_identity='admin')
    web=InstallationControlClient('test',pipe_client=Pipe())
    launcher=ModuleLauncherModel(InstallationControlClient('test',pipe_client=Pipe()))
    plan=web.module_plan(action='update',selected={},excluded=[])
    assert plan['download_bytes']==3
    web.module_execute(plan['plan_id'])
    assert transfers==[('v5','ftp.bin',0,3)]
    assert web.module_operation(plan['plan_id'])['state']=='committed'
    old_ftp=next(m for m in first.modules if m.module_id=='ftp')
    launcher.select('ftp',old_ftp.version_id)
    assert read_module_set(context).pinned==frozenset()
    stale=web.module_plan(action='update_all',selected={},excluded=[])
    rollback=launcher.prepare('rollback_modules')
    launcher.execute(rollback['plan_id'])
    assert read_module_set(context).pinned==frozenset({'ftp'})
    assert next(row for row in web.module_catalog()['modules'] if row['module_id']=='ftp')['pinned']
    # A plan from the other client cannot replace the newly pinned revision.
    import pytest
    with pytest.raises(RuntimeError,match='zmieniła'): web.module_execute(stale['plan_id'])
    pinned_update=web.module_plan(action='update',selected={},excluded=[])
    assert pinned_update['changes']==[] and pinned_update['download_bytes']==0
    source.fetch_json=lambda path: (_ for _ in ()).throw(OSError('offline'))
    restarted=ModuleService(context,Controller(),source=source,content=store,schedule=lambda work:work(),quiesce=lambda op:None,healthy=lambda:True)
    assert restarted.catalog()['offline']
    offline=restarted.prepare(action='rollback_modules',selected={'ftp':old_ftp.version_id},excluded=[])
    assert offline['download_bytes']==0
    restarted.execute(offline['plan_id'])
    assert restarted.operation(offline['plan_id'])['state']=='committed'
    assert transfers==[('v5','ftp.bin',0,3)]
