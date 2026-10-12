from picsyncra.installation.module_launcher import ModuleLauncherModel


def test_release_caption_includes_tag_date_and_module_identity():
    from picsyncra.installation.module_launcher import release_caption
    caption = release_caption('1.abc', {'tag':'v0.5.6-dev.3','published_at':'2026-10-12T07:15:12Z'})
    assert 'v0.5.6-dev.3' in caption and '12.10.2026' in caption and '1.abc' in caption


def test_launcher_download_speed_eta_and_error_code_are_readable():
    from picsyncra.installation.module_launcher import operation_message
    text = operation_message({'state':'downloading','action':'install_ocr',
        'progress':{'downloaded_bytes':1048576,'total_bytes':2097152,'bytes_per_second':524288,'eta_seconds':2}})
    assert 'KiB/s' in text and '2 s' in text
    text = operation_message({'state':'rolled_back','error':'Pobieranie przerwane',
        'error_details':{'code':'http_error','http_status':503}})
    assert 'HTTP 503' in text


def test_launcher_restores_catalog_progress_when_operation_has_no_matching_row():
    from picsyncra.installation.module_launcher import ModuleLauncherWindow
    class Widget:
        def __init__(self): self.packed = False
        def stop(self): pass
        def grid(self): pass
        def grid_remove(self): pass
        def pack_forget(self): self.packed = False
        def pack(self, **kwargs): self.packed = True
    window = object.__new__(ModuleLauncherWindow)
    window.catalog_progressbar = Widget()
    window.progress_rows = {'ocr': {'bar':Widget(),'frame':Widget()}}
    window._place_progress('install_ocr')
    assert window.progressbar is window.progress_rows['ocr']['bar']
    window._place_progress('update', None)
    assert window.progressbar is window.catalog_progressbar
    assert window.catalog_progressbar.packed is True


def test_available_version_distinguishes_unknown_offline_from_missing_signed_release():
    from picsyncra.installation.module_launcher import available_version_message
    assert available_version_message({'latest': None}, {'offline': True}) == 'nie sprawdzono — katalog niedostępny'
    assert available_version_message({'latest': None}, {'offline': False}) == 'brak podpisanego wydania'
    assert available_version_message({'latest': '1.abc'}, {'offline': True}) == '1.abc (katalog lokalny)'
    assert available_version_message({'latest': '1.abc'}, {'offline': False}) == '1.abc'


def test_launcher_explains_offline_empty_catalog_instead_of_generic_instruction():
    from picsyncra.installation import module_launcher
    snapshot={'offline':True,'catalog_error':{'code':'rate_limit','message':'GitHub: przekroczono limit zapytań.'}}
    assert 'limit' in module_launcher.catalog_message(snapshot)
    assert 'lokalny' in module_launcher.catalog_message(snapshot)
    assert 'lokalny' in module_launcher.catalog_message({'offline':True})
    assert 'Wybierz' in module_launcher.catalog_message({'offline':False})


def test_launcher_operation_message_shows_ocr_bytes_percent_and_installation_phase():
    from picsyncra.installation import module_launcher
    message = module_launcher.operation_message({'state':'downloading', 'action':'install_ocr',
        'progress':{'downloaded_bytes':1048576, 'total_bytes':2097152}, 'error':None})
    assert 'OCR' in message and '50%' in message and 'MiB' in message
    assert 'Instalowanie' in module_launcher.operation_message({'state':'installing','action':'install_ocr'})
    assert 'Gotowe' in module_launcher.operation_message({'state':'committed','action':'install_ocr'})
    assert 'awaria' in module_launcher.operation_message({'state':'failed','error':'awaria'})


class Client:
    def __init__(self): self.calls=[]
    def module_catalog(self): return {'modules': []}
    def module_plan(self, **payload): self.calls.append(('plan', payload)); return {'plan_id': 'a'*32, 'conflicts':[]}
    def module_execute(self, plan_id, **payload): self.calls.append(('execute',plan_id,payload)); return {'state':'accepted'}
    def module_channel(self, channel): self.calls.append(('channel',channel)); return {'channel':channel}


def test_unified_update_submits_selected_versions_without_exclusions():
    client = Client(); model = ModuleLauncherModel(client)
    model.select('ftp', 'a' * 64)
    model.prepare('apply')
    assert client.calls[-1][1]['selected'] == {'ftp': 'a' * 64}
    assert client.calls[-1][1]['excluded'] == []


def test_authorization_url_accepts_only_installation_and_request_nonce():
    import pytest
    from picsyncra.installation.module_launcher import parse_authorization_url
    assert parse_authorization_url('picsyncra-update://authorize/primary-installation/' + 'a' * 32) == ('primary-installation', 'a' * 32)
    for value in ('https://attacker/test', 'picsyncra-update://authorize/../' + 'a' * 32,
                  'picsyncra-update://authorize/test/' + 'a' * 32 + '?password=secret',
                  'picsyncra-update://authorize/test/' + 'a' * 32 + '" --app local'):
        with pytest.raises(ValueError): parse_authorization_url(value)


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
