from picsyncra.installation.module_launcher import ModuleLauncherModel


class Client:
    def __init__(self): self.calls=[]
    def module_catalog(self): return {'modules': []}
    def module_plan(self, **payload): self.calls.append(('plan', payload)); return {'plan_id': 'a'*32, 'conflicts':[]}
    def module_execute(self, plan_id, **payload): self.calls.append(('execute',plan_id,payload)); return {'state':'accepted'}
    def module_channel(self, channel): self.calls.append(('channel',channel)); return {'channel':channel}


def test_selection_is_draft_until_shared_button_and_update_skips_choices():
    client=Client(); model=ModuleLauncherModel(client)
    model.select('ftp','a'*64); model.select('sql','b'*64)
    assert client.calls == []
    plan=model.prepare('rollback_modules')
    assert client.calls[-1][1]['selected'] == {'ftp':'a'*64, 'sql':'b'*64}
    assert all(call[0] != 'execute' for call in client.calls)
    model.prepare('update')
    assert client.calls[-1][1]['excluded'] == ['ftp','sql']
    assert client.calls[-1][1]['selected'] == {}
    model.execute(plan['plan_id'])
    assert client.calls[-1][0] == 'execute'


def test_full_update_replans_without_losing_draft_on_cancellation():
    client=Client(); model=ModuleLauncherModel(client)
    model.select('ftp','a'*64)
    model.prepare('update_all')
    assert client.calls[-1][1]['selected'] == {} and client.calls[-1][1]['excluded'] == []
    assert model.selected == {'ftp':'a'*64}


def test_channel_switch_keeps_rollback_drafts_and_does_not_execute():
    client=Client(); model=ModuleLauncherModel(client)
    model.select('ftp','a'*64)
    model.change_channel('dev')
    assert client.calls == [('channel','dev')]
    assert model.selected == {'ftp':'a'*64}


def test_draft_retains_its_version_and_release_when_missing_in_new_channel():
    client=Client(); model=ModuleLauncherModel(client)
    original={'version_id':'a'*64,'display_version':'1','release_url':'https://github.com/NefilimPL/PicSyncra/releases/tag/v1','available':True}
    model.snapshot={'modules':[{'module_id':'ftp','versions':[original]}]}
    model.select('ftp',original['version_id'])
    model.change_channel('dev'); model.refresh()
    assert model.selected_versions['ftp'] == original
    model.select('ftp',None)
    assert 'ftp' not in model.selected_versions
