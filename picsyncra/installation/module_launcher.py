"""Stable GUI model and recovery window, independent of selected app code."""
from __future__ import annotations
import argparse
import ctypes
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
from .launcher import InstallationControlClient


_OPERATION_LABELS = {
    'accepted': 'Operacja przyjęta — oczekiwanie na rozpoczęcie.',
    'downloading': 'Pobieranie', 'draining': 'Oczekiwanie na zakończenie zadań.',
    'stopping': 'Zatrzymywanie backendu.', 'backing_up': 'Tworzenie kopii bazy i konfiguracji.',
    'installing': 'Instalowanie', 'restoring': 'Odtwarzanie bazy i konfiguracji.',
    'migrating': 'Migracja bazy.', 'validating': 'Sprawdzanie działania modułów.',
    'committed': 'Gotowe — instalacja zakończona.', 'rolling_back': 'Przywracanie poprzednich wersji.',
    'rolled_back': 'Przywrócono poprzednie wersje.', 'failed': 'Operacja nie powiodła się.',
    'recovery_required': 'Wymagane odzyskiwanie instalacji.',
}


def operation_message(operation):
    phase = operation.get('state', 'accepted')
    label = _OPERATION_LABELS.get(phase, phase)
    if phase in {'downloading', 'installing'}:
        label += ' OCR' if operation.get('action') == 'install_ocr' else ' modułów'
    progress = operation.get('progress') or {}
    total = progress.get('total_bytes', 0)
    downloaded = progress.get('downloaded_bytes', 0)
    if phase == 'downloading' and total > 0:
        label += f': {downloaded / 1048576:.1f} / {total / 1048576:.1f} MiB ({min(100, int(downloaded * 100 / total))}%)'
        rate = progress.get('bytes_per_second', 0)
        if rate > 0:
            label += f" · {rate / 1048576:.1f} MiB/s" if rate >= 1048576 else f" · {rate / 1024:.1f} KiB/s"
            eta = progress.get('eta_seconds')
            if eta is not None: label += f" · pozostało {eta // 60} min {eta % 60} s" if eta >= 60 else f" · pozostało {eta} s"
        else: label += ' · obliczanie prędkości i czasu…'
    if operation.get('error'): label += ' — ' + str(operation['error'])
    details = operation.get('error_details') or {}
    if details.get('http_status'): label += f" (HTTP {details['http_status']})"
    elif details.get('code'): label += f" ({details['code']})"
    return label


def catalog_message(snapshot):
    error = (snapshot.get('catalog_error') or {}).get('message')
    if snapshot.get('offline'):
        return (error or 'Nie udało się pobrać katalogu GitHuba.') + ' Pokazywany jest katalog lokalny; brakujące pliki wymagają połączenia.'
    return 'Wybierz moduły i zatwierdź operację.'


def conflict_guidance(conflicts):
    if any(c.get('code') in {'controller_outdated', 'launcher_outdated'} for c in conflicts):
        return ('To wydanie wymaga nowszego launchera i kontrolera. Pobierz pełny instalator Setup z wydania GitHub '
                'i uruchom go na istniejącej instalacji. Setup zachowa bazę, konfigurację i blokady modułów. '
                'Sama aktualizacja modułów nie wymienia kontrolera.')
    return 'Zmień wybory wersji wskazanych modułów i ponów aktualizację. Blokady pozostają zachowane.'


def restart_and_wait(client, *, timeout=180):
    previous = client.snapshot()
    old_pid = previous.get('backend_pid')
    if previous['backend_running'] and old_pid is None:
        raise RuntimeError('Starszy kontroler nie potwierdza zmiany procesu. Zaktualizuj launcher i kontroler pełnym Setup.')
    if not client.restart_backend():
        raise RuntimeError('Nie udało się uruchomić ponownie backendu.')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.snapshot()
        if state['backend_running'] and state.get('backend_pid') is not None and state['backend_pid'] != old_pid:
            from .controller_host import _backend_ready
            if _backend_ready(client, timeout_seconds=max(0.01,deadline-time.monotonic())):
                return client.snapshot()
            break
        time.sleep(0.2)
    raise RuntimeError('Nowy proces backendu nie potwierdził gotowości po ponownym uruchomieniu.')


def available_version_message(module, snapshot):
    latest = module.get('latest')
    if snapshot.get('offline'):
        return latest + ' (katalog lokalny)' if latest else 'nie sprawdzono — katalog niedostępny'
    return latest or 'brak podpisanego wydania'


def release_caption(version, release):
    from datetime import datetime
    if not release or not release.get('tag'): return version
    date = ''
    if release.get('published_at'):
        try: date = datetime.fromisoformat(release['published_at'].replace('Z', '+00:00')).astimezone().strftime('%d.%m.%Y')
        except ValueError: pass
    return release['tag'] + (f' · {date}' if date else '') + f' ({version})'


class ModuleLauncherModel:
    def __init__(self, client):
        self.client = client
        self.selected = {}
        self.selected_versions = {}
        self.snapshot = {}

    def refresh(self):
        self.snapshot = self.client.module_catalog()
        if hasattr(self.client, 'snapshot'):
            self.snapshot['backend'] = self.client.snapshot()
        return self.snapshot

    def change_channel(self, channel):
        result=self.client.module_channel(channel)
        self.snapshot['channel']=result['channel']
        return result

    def select(self, module_id, version_id):
        from .module_definition import module_definitions
        if module_id not in {m.module_id for m in module_definitions()}: raise ValueError('Nieznany moduł.')
        if version_id is None:
            self.selected.pop(module_id, None)
            self.selected_versions.pop(module_id, None)
        elif isinstance(version_id, str) and re.fullmatch('[a-f0-9]{64}', version_id):
            self.selected[module_id] = version_id
            versions=next((m['versions'] for m in self.snapshot.get('modules',[]) if m['module_id'] == module_id),[])
            version=next((v for v in versions if v['version_id'] == version_id),None)
            if version is not None: self.selected_versions[module_id]=dict(version)
        else: raise ValueError('Nieprawidłowa wersja modułu.')

    def prepare(self, action, *, restore_backup_id=None):
        return self.client.module_plan(action=action,
            selected=dict(self.selected) if action in {'apply', 'rollback_modules'} else {},
            excluded=list(self.selected) if action == 'update' else [], restore_backup_id=restore_backup_id)

    def execute(self, plan_id, *, restore_backup_id=None, acknowledge_data_loss=False):
        return self.client.module_execute(plan_id, restore_backup_id=restore_backup_id, acknowledge_data_loss=acknowledge_data_loss)


def _elevate(installation_id, app, authorize_url=None):
    if sys.platform != 'win32' or ctypes.windll.shell32.IsUserAnAdmin(): return False
    arguments = ['--installation-id', installation_id]
    if app: arguments += ['--app', app]
    if authorize_url: arguments += ['--authorize-url', authorize_url]
    if not getattr(sys, 'frozen', False): arguments.insert(0, str(Path(sys.argv[0]).absolute()))
    result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', sys.executable, subprocess.list2cmdline(arguments), None, 1)
    if result <= 32: raise RuntimeError('Launcher wymaga uprawnień administratora do sterowania instalacją.')
    return True


class ModuleLauncherWindow:
    def __init__(self, root, context, model, *, app=None, authorization_request_id=None):
        import tkinter as tk
        from tkinter import ttk, messagebox
        self.root, self.context, self.model = root, context, model
        self.ttk, self.messagebox = ttk, messagebox
        self.callbacks = queue.Queue()
        self.busy = False
        self.operation_id = None
        self.terminal_message = None
        self.last_operation = None
        self.progress_rows = {}
        self.retry_action = None
        self.authorization_request_id = None
        self.pending_authorization = authorization_request_id
        self.app = app
        self.tray = None
        self.closed = False
        self.tray_ready = False
        self.backend_status = tk.StringVar(value='Odczyt stanu backendu…')
        self.autostart = tk.BooleanVar(value=False)
        root.title('PicSyncra — launcher i odzyskiwanie modułów')
        root.geometry('1060x740')
        ttk.Label(root, text='Aktualizuj zatwierdza wybrane wersje i aktualizuje pozostałe niezablokowane moduły. Bez zmiany oznacza najnowszą dostępną wersję, z zachowaniem blokady.', wraplength=1000).pack(padx=12, pady=12)
        toolbar = ttk.Frame(root); toolbar.pack(fill='x', padx=12)
        self.buttons=[]
        actions = [('Uruchom panel', self.open_panel), ('Uruchom Migrator', lambda: self.open_app('migrator')),
                              ('Uruchom LOCAL', lambda: self.open_app('local')), ('Sprawdź wersje', self.refresh),
                              ('Aktualizuj', lambda: self.prepare('apply')), ('Pobierz OCR', lambda: self.prepare('install_ocr')),
                              ('Zatrzymaj backend', self.stop_backend), ('Uruchom ponownie backend', self.restart_backend),
                              ('Ponów odzyskiwanie', lambda: self._run(self.model.client.module_recover, self.accepted))]
        for index, (label, action) in enumerate(actions):
            button=ttk.Button(toolbar,text=label,command=action)
            button.grid(row=index//3,column=index%3,padx=3,pady=3,sticky='ew'); self.buttons.append(button)
        for column in range(3): toolbar.columnconfigure(column,weight=1)
        backend_frame = ttk.Frame(root); backend_frame.pack(fill='x', padx=12, pady=6)
        ttk.Label(backend_frame, textvariable=self.backend_status).pack(side='left')
        self.autostart_control = ttk.Checkbutton(backend_frame, text='Uruchamiaj WEB w tle po starcie Windows',
            variable=self.autostart, command=self.change_autostart)
        self.autostart_control.pack(side='left', padx=12)
        ttk.Button(backend_frame, text='Zamknij launcher', command=self.quit_launcher).pack(side='right')
        self.tray_status = tk.StringVar(value='Zamknięcie okna ukrywa je w trayu. Backend zatrzymasz przyciskiem powyżej lub z menu ikony.')
        ttk.Label(root, textvariable=self.tray_status, wraplength=1000).pack(fill='x', padx=12)
        channel_frame=ttk.Frame(root); channel_frame.pack(fill='x',padx=12,pady=6)
        ttk.Label(channel_frame,text='Kanał aktualizacji:').pack(side='left')
        self.channel=ttk.Combobox(channel_frame,state='readonly',values=['Stable','Dev'],width=12)
        self.channel.set('Stable'); self.channel.pack(side='left',padx=8)
        self.channel.bind('<<ComboboxSelected>>',lambda event: self.change_channel())
        self.status=tk.StringVar(value='Odczyt kontrolera…')
        ttk.Label(root,textvariable=self.status,wraplength=1000).pack(fill='x',padx=12,pady=10)
        self.progressbar=ttk.Progressbar(root,mode='indeterminate')
        self.progressbar.pack(fill='x',padx=12,pady=(0,8))
        self.catalog_progressbar = self.progressbar
        canvas=tk.Canvas(root,highlightthickness=0)
        scrollbar=ttk.Scrollbar(root,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y'); canvas.pack(fill='both',expand=True,padx=12)
        self.rows=ttk.Frame(canvas)
        window_id=canvas.create_window((0,0),window=self.rows,anchor='nw')
        self.rows.bind('<Configure>',lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda event: canvas.itemconfigure(window_id,width=event.width))
        backup_frame=ttk.Frame(root); backup_frame.pack(fill='x',padx=12,pady=8)
        ttk.Label(backup_frame,text='Awaryjne odtworzenie bazy:').pack(side='left')
        self.backup=ttk.Combobox(backup_frame,state='readonly',values=['Zachowaj obecną bazę'],width=65)
        self.backup.current(0); self.backup.pack(side='left',padx=8)
        self.backup_ids={'Zachowaj obecną bazę': None}
        self.conflicts=ttk.Frame(root); self.conflicts.pack(fill='x',padx=12,pady=8)
        root.after(100,self._callbacks)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Destroy>', self._destroyed, add='+')
        self._init_tray()
        root.after(5000, self.refresh_backend)
        if authorization_request_id:
            self.pending_authorization = None
            root.after(1, lambda: self.begin_authorization(authorization_request_id))
        else: self.refresh()

    def close(self):
        if self.tray_ready:
            self.root.withdraw()
            return
        self.quit_launcher()

    def _destroyed(self, event):
        if event.widget is self.root and not self.closed:
            self.closed = True
            if self.tray:
                self.tray.visible = False
                self.tray.stop()

    def quit_launcher(self):
        if self.busy or self.operation_id:
            self.messagebox.showinfo('PicSyncra', 'Poczekaj na zakończenie operacji. Okno możesz schować w trayu.', parent=self.root)
            return
        if self.authorization_request_id and not self.operation_id:
            try: self.model.client.module_authorization_cancel(self.authorization_request_id)
            except RuntimeError: pass
        if self.tray:
            self.tray.visible = False
            self.tray.stop()
        self.closed = True
        self.root.destroy()

    def show_from_tray(self):
        self.root.deiconify(); self.root.lift()

    def _init_tray(self):
        try:
            import pystray
            from PIL import Image
            icon_path = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2])) / 'local.ico'
            if not icon_path.is_file():
                icon_path = Path(__file__).resolve().parents[2] / 'pic/PIC9_LOCAL.png'
            with Image.open(icon_path) as source:
                image = source.convert('RGBA')
            def invoke(action):
                return lambda *_: self.callbacks.put(action)
            self.tray = pystray.Icon('PicSyncra-' + self.context.installation_id, image, 'PicSyncra — launcher',
                menu=pystray.Menu(
                    pystray.MenuItem('Otwórz launcher', invoke(self.show_from_tray), default=True),
                    pystray.MenuItem('Otwórz panel WEB', invoke(self.open_panel)),
                    pystray.MenuItem('Zatrzymaj backend', invoke(self.stop_backend)),
                    pystray.MenuItem('Uruchom ponownie backend', invoke(self.restart_backend)),
                    pystray.MenuItem('Zatrzymaj backend i zamknij launcher', invoke(lambda: self.stop_backend(quit_after=True))),
                    pystray.MenuItem('Zamknij tylko launcher (backend pozostaje)', invoke(self.quit_launcher))))
            def ready(icon):
                icon.visible = True
                self.callbacks.put(lambda: setattr(self, 'tray_ready', True))
            self.tray.run_detached(setup=ready)
        except Exception:
            self.tray_ready = False
            if self.tray:
                self.tray.stop()
            self.tray = None
            self.tray_status.set('Ikona w trayu jest niedostępna. Backend możesz zatrzymać przyciskiem „Zatrzymaj backend” w tym oknie.')

    def _callbacks(self):
        while True:
            try: callback=self.callbacks.get_nowait()
            except queue.Empty: break
            callback()
            if self.closed: return
        self.root.after(100,self._callbacks)

    def _run(self, work, finished, *, on_error=None):
        if self.busy:
            return
        self.busy=True
        for button in self.buttons: button.configure(state='disabled')
        for widget in self.rows.winfo_children():
            if isinstance(widget,self.ttk.Combobox): widget.configure(state='disabled')
        self.backup.configure(state='disabled')
        self.channel.configure(state='disabled')
        self.autostart_control.configure(state='disabled')
        def worker():
            try:
                result=work()
                self.callbacks.put(lambda: self._finish(finished,result))
            except Exception as exc:
                failure=(str(exc), getattr(exc, 'details', None))
                def failed(value):
                    if on_error:
                        on_error(*value)
                        return
                    self.status.set(value[0])
                    self.channel.set('Dev' if self.model.snapshot.get('channel') == 'dev' else 'Stable')
                    if self.operation_id: self.root.after(2000,self.poll)
                self.callbacks.put(lambda: self._finish(failed,failure))
        threading.Thread(target=worker,daemon=True,name='PicSyncraLauncherIO').start()

    def _finish(self, callback, result):
        self.busy=False
        callback(result)
        if self.closed: return
        self._synchronize_controls()
        if self.pending_authorization:
            identifier, self.pending_authorization = self.pending_authorization, None
            self.root.after(1, lambda: self.begin_authorization(identifier))
        if not self.busy and not self.operation_id: self.progressbar.stop()

    def _synchronize_controls(self):
        locked = self.busy or bool(self.operation_id)
        for button in self.buttons: button.configure(state='disabled' if locked else 'normal')
        for widget in self.rows.winfo_children():
            if isinstance(widget,self.ttk.Combobox): widget.configure(state='disabled' if locked else 'readonly')
        self.backup.configure(state='disabled' if locked else 'readonly')
        self.channel.configure(state='disabled' if locked else 'readonly')
        self.autostart_control.configure(state='disabled' if locked else 'normal')

    def refresh(self):
        self.status.set('Pobieranie katalogu wersji z GitHuba…')
        self.progressbar.start()
        self._run(self.model.refresh,self.render)

    def change_channel(self):
        if self.busy or self.operation_id: return
        channel='dev' if self.channel.get() == 'Dev' else 'stable'
        def work():
            self.model.change_channel(channel)
            return self.model.refresh()
        self._run(work,self.render)

    def render(self,snapshot):
        if snapshot.get('backend'):
            self.render_backend(snapshot['backend'])
        if snapshot.get('operation') and not self.operation_id:
            self.accepted(snapshot['operation'])
        self.channel.set('Dev' if snapshot.get('channel') == 'dev' else 'Stable')
        self.progressbar.stop()
        self.progressbar = self.catalog_progressbar
        for widget in self.rows.winfo_children(): widget.destroy()
        self.progress_rows.clear()
        if self.app and not self.authorization_request_id and not self.operation_id:
            app, self.app = self.app, None
            self.callbacks.put(self.open_panel if app == 'web' else lambda: self.open_app(app))
        for index,module in enumerate(snapshot.get('modules',[])):
            row_index = index * 2
            self.ttk.Label(self.rows,text=module['label']).grid(row=row_index,column=0,padx=5,pady=10,sticky='w')
            versions = self.ttk.Frame(self.rows)
            versions.grid(row=row_index,column=1,sticky='w',padx=5)
            for caption, version, release in [('Obecna', module['current'], module.get('current_release')),
                ('Dostępna', available_version_message(module, snapshot), module.get('latest_release'))]:
                url = (release or {}).get('release_url', '')
                label = self.ttk.Label(versions,text=f'{caption}: {release_caption(version, release)}',wraplength=400,
                                      cursor='hand2' if url else '')
                label.pack(anchor='w',pady=2)
                if url:
                    label.configure(foreground='#2677bd',takefocus=True)
                    label.bind('<Button-1>',lambda event, value=url: self.open_release(value))
                    label.bind('<Return>',lambda event, value=url: self.open_release(value))
            text=''
            if module['pinned']: text+='  [wyłączony z aktualizacji]'
            if module['module_id'] in self.model.selected: text+='  [wybrana konkretna wersja]'
            chosen=self.model.selected.get(module['module_id'])
            if chosen and not any(v['version_id']==chosen and v['available'] for v in module['versions']):
                text+='  [wybrana wersja niedostępna w tym kanale]'
            if text: self.ttk.Label(versions,text=text,wraplength=400).pack(anchor='w')
            values={'Bez zmiany':None}
            links={}
            for version in module['versions']:
                if not version['available']: continue
                label=release_caption(version['display_version'],version)
                values[label]=version['version_id']; links[label]=version['release_url']
            combo=self.ttk.Combobox(self.rows,state='readonly',values=list(values),width=25)
            chosen=self.model.selected.get(module['module_id'])
            if chosen and chosen not in values.values():
                version=self.model.selected_versions.get(module['module_id'],{})
                label=f"{version.get('display_version',chosen[:8])} — niedostępna w tym kanale"
                values[label]=chosen; links[label]=version.get('release_url','')
                combo.configure(values=list(values))
            combo.set(next((key for key,value in values.items() if value==chosen),'Bez zmiany'))
            combo.grid(row=row_index,column=2,padx=5)
            combo.bind('<<ComboboxSelected>>',lambda event,mid=module['module_id'],box=combo,options=values: self.select_version(mid,options[box.get()]))
            if chosen:
                link = self.ttk.Label(self.rows,text='Wybrane wydanie ↗',foreground='#2677bd',cursor='hand2')
                link.grid(row=row_index,column=3,padx=5)
                link.bind('<Button-1>',lambda event, box=combo, urls=links: self.open_release(urls.get(box.get(),'')))
            self._make_progress_row(module['module_id'], row_index + 1)
        if 'ocr' not in self.progress_rows:
            index = len(snapshot.get('modules',[])) * 2
            self.ttk.Label(self.rows,text='Silnik i modele OCR').grid(row=index,column=0,pady=10,sticky='w')
            self._make_progress_row('ocr',index + 1)
        self.backup_ids={'Zachowaj obecną bazę':None}
        for backup in snapshot.get('backups',[]):
            self.backup_ids[f"{backup['backup_id']} · schemat {backup['schema_version']}"]=backup['backup_id']
        self.backup.configure(values=list(self.backup_ids))
        if self.backup.get() not in self.backup_ids: self.backup.current(0)
        if not self.operation_id:
            self.status.set(self.terminal_message or catalog_message(snapshot))
        if self.last_operation: self._show_progress(self.last_operation)
        self._synchronize_controls()

    def _make_progress_row(self, module_id, row_index):
        frame = self.ttk.Frame(self.rows)
        frame.grid(row=row_index,column=0,columnspan=4,sticky='ew',padx=5,pady=6)
        self.ttk.Label(frame,textvariable=self.status,wraplength=950).pack(anchor='w')
        bar = self.ttk.Progressbar(frame,mode='indeterminate')
        bar.pack(fill='x',pady=5)
        buttons = self.ttk.Frame(frame); buttons.pack(anchor='w')
        retry = self.ttk.Button(buttons,text='Ponów pobieranie',command=lambda:self.prepare(self.retry_action))
        details = self.ttk.Button(buttons,text='Szczegóły błędu',command=self.show_error_details)
        frame.grid_remove()
        self.progress_rows[module_id] = dict(frame=frame,bar=bar,retry=retry,details=details)

    def _place_progress(self, action, module_id=None):
        selected = self.progress_rows.get('ocr' if action == 'install_ocr' else module_id)
        for row in self.progress_rows.values():
            row['bar'].stop()
            row['frame'].grid_remove()
        self.catalog_progressbar.stop()
        if selected:
            self.catalog_progressbar.pack_forget()
            selected['frame'].grid()
            self.progressbar = selected['bar']
        else:
            self.catalog_progressbar.pack(fill='x',padx=12,pady=(0,8))
            self.progressbar = self.catalog_progressbar
        return selected

    def show_error_details(self):
        import json
        details = (self.last_operation or {}).get('error_details')
        self.messagebox.showinfo('Szczegóły błędu pobierania',json.dumps(details,ensure_ascii=False,indent=2) if details else self.status.get(),parent=self.root)

    def select_version(self,module_id,version_id):
        self.model.select(module_id,version_id)
        self.render(self.model.snapshot)

    @staticmethod
    def open_release(url):
        from urllib.parse import urlparse
        parsed=urlparse(url)
        if parsed.scheme=='https' and parsed.hostname=='github.com' and parsed.path.startswith('/NefilimPL/PicSyncra/releases/tag/'):
            webbrowser.open(url)

    def prepare(self,action):
        if self.busy or self.operation_id: return
        self._place_progress(action)
        for row in self.progress_rows.values():
            row['retry'].pack_forget(); row['details'].pack_forget()
        self.status.set('Sprawdzanie zgodności i przygotowanie instalacji OCR…' if action == 'install_ocr' else 'Sprawdzanie zgodności i przygotowanie planu…')
        self.progressbar.configure(mode='indeterminate',value=0)
        self.progressbar.start()
        restore=self.backup_ids.get(self.backup.get())
        self._run(lambda: self.model.prepare(action,restore_backup_id=restore),lambda plan:self.confirm_plan(plan,restore),
                  on_error=lambda message, details: self.prepare_failed(action, restore, message, details))

    def prepare_failed(self, action, restore, message, details):
        self.status.set(message)
        if (details or {}).get('code') == 'permission_required':
            selected = dict(self.model.selected) if action in {'apply', 'rollback_modules'} else {}
            excluded = list(self.model.selected) if action == 'update' else []
            self._run(lambda: self.model.client.module_authorization_request(action=action, selected=selected,
                        excluded=excluded, restore_backup_id=restore),
                      lambda request: self.begin_authorization(request['request_id'], restore))

    def begin_authorization(self, request_id, restore=None):
        def ready(request):
            self.authorization_request_id = request_id
            if request['state'] != 'pending':
                self.status.set('Ta próba logowania wygasła lub została już użyta.')
                return
            from .module_authorization import prompt_credentials
            try:
                blob = prompt_credentials(self.context.installation_id, request_id, parent=self.root.winfo_id())
            except RuntimeError as exc:
                self.status.set(str(exc)); self.cancel_authorization(); return
            if blob is None:
                self.status.set('Logowanie anulowane przed pobieraniem.'); self.cancel_authorization(); return
            # Keep the encrypted credential buffer only in this worker closure.
            # The controller checks the selected account before any download.
            self._run(lambda: self.model.client.module_authorize(request_id, blob),
                      lambda plan: self.confirm_plan(plan, plan.get('restore_backup_id', restore)),
                      on_error=lambda message, details: self.authorization_failed(message, details))
        self._run(lambda: self.model.client.module_authorization_status(request_id), ready)

    def authorization_failed(self, message, details):
        self.status.set(message + (f" (kod {details['system_code']})" if (details or {}).get('system_code') else ''))
        self.cancel_authorization()

    def cancel_authorization(self):
        identifier, self.authorization_request_id = self.authorization_request_id, None
        if identifier:
            self._run(lambda: self.model.client.module_authorization_cancel(identifier), lambda _: None)

    def confirm_plan(self,plan,restore):
        for widget in self.conflicts.winfo_children(): widget.destroy()
        if plan['conflicts']:
            self.cancel_authorization()
            text='\n'.join(f"{c['module_id']} {c['selected_version']} ↔ {c['dependency_id'] or 'baza/runtime'} {c['dependency_version'] or ''}: {c['requirement']}" for c in plan['conflicts'])
            self.ttk.Label(self.conflicts,text=text,wraplength=1000).pack(anchor='w')
            self.ttk.Label(self.conflicts,text=conflict_guidance(plan['conflicts']),wraplength=1000).pack(anchor='w')
            if any(c.get('code') in {'controller_outdated','launcher_outdated'} for c in plan['conflicts']):
                self.ttk.Button(self.conflicts,text='Pobierz pełny instalator Setup',
                    command=lambda:webbrowser.open(plan.get('setup_release_url') or 'https://github.com/NefilimPL/PicSyncra/releases')).pack(side='left')
            self.ttk.Button(self.conflicts,text='Nie aktualizuj',command=lambda:[widget.destroy() for widget in self.conflicts.winfo_children()]).pack(side='left')
            return
        if plan.get('has_changes') is False:
            self.status.set('Wszystkie wybrane moduły są aktualne. Blokady zostały zachowane.')
            self.cancel_authorization()
            return
        changes='\n'.join(f"{c['module_id']}: {c['current'] or 'brak'} → {c['target']}" for c in plan['changes'])
        if plan['action'] == 'update_all':
            overridden = set(self.model.selected) | {m['module_id'] for m in (self.model.snapshot or {}).get('modules',[]) if m['pinned']}
            if overridden: changes += '\nAktualizacje zostaną włączone, a wybory cofnięcia pominięte dla: ' + ', '.join(sorted(overridden)) + '.'
        if not self.messagebox.askyesno('Zatwierdź plan',f"{changes or 'Zgodny zestaw modułów.'}\nDo pobrania: {plan['download_bytes']:,} bajtów.\nZatwierdzić operację?",parent=self.root):
            self.cancel_authorization(); return
        acknowledge=False
        if restore:
            acknowledge=self.messagebox.askyesno('Utrata nowszych danych','Odtworzenie starszej bazy usunie dane zapisane po wykonaniu kopii. Potwierdzasz utratę tych nowszych danych?',parent=self.root)
            if not acknowledge:
                self.cancel_authorization(); return
        self._run(lambda:self.model.execute(plan['plan_id'],restore_backup_id=restore,acknowledge_data_loss=acknowledge),self.accepted,
                  on_error=self.authorization_failed)

    def accepted(self,result):
        self.authorization_request_id = None
        if result.get('unchanged'):
            self.status.set('Wszystkie wybrane moduły są aktualne.')
            return
        self.terminal_message=None
        self.operation_id=result['operation_id']
        self._show_progress(result)
        self._synchronize_controls()
        self.root.after(1000,self.poll)

    def poll(self):
        if self.operation_id: self._run(lambda:self.model.client.module_operation(self.operation_id),self.progress)

    def progress(self,result):
        if result is None:
            self.status.set('Oczekiwanie na kontroler…'); self.root.after(2000,self.poll); return
        self._show_progress(result)
        if result['state'] in {'committed','rolled_back','failed','recovery_required'}:
            self.terminal_message=self.status.get()
            if result['state']=='committed':
                self.model.selected.clear(); self.model.selected_versions.clear()
            self.operation_id=None; self.refresh()
        else: self.root.after(1500,self.poll)

    def _show_progress(self,result):
        self.last_operation = result
        row = self._place_progress(result.get('action'),(result.get('progress') or {}).get('module_id'))
        self.status.set(operation_message(result))
        self.progressbar.stop()
        progress=result.get('progress') or {}
        total=progress.get('total_bytes',0)
        if result.get('state') == 'downloading' and total > 0:
            self.progressbar.configure(mode='determinate',maximum=total,value=progress.get('downloaded_bytes',0))
        elif result.get('state') in {'committed','rolled_back','failed','recovery_required'}:
            self.progressbar.configure(mode='determinate',maximum=1,value=1 if result['state']=='committed' else 0)
        else:
            self.progressbar.configure(mode='indeterminate',value=0)
            self.progressbar.start()
        if row:
            details = result.get('error_details') or {}
            if result.get('error') and result.get('state') in {'failed','rolled_back'} and (result.get('action') == 'install_ocr' or details.get('retryable')):
                self.retry_action = result['action']
                row['retry'].pack(side='left',padx=4)
            if details: row['details'].pack(side='left',padx=4)

    def open_panel(self):
        if self.busy or self.operation_id: return
        def start():
            self.model.client.start_backend()
            from .controller_host import _backend_ready
            if not _backend_ready(self.model.client):
                raise RuntimeError('Backend nie potwierdził gotowości. Sprawdź logi instalacji i ponów uruchomienie.')
            return self.model.client.snapshot()
        def opened(result):
            self.render_backend(result)
            webbrowser.open('http://127.0.0.1:8010')
        self._run(start, opened)

    def render_backend(self, state):
        self.backend_status.set('Backend: uruchomiony' if state['backend_running'] else 'Backend: zatrzymany')
        self.autostart.set(state.get('autostart', False))
        if self.tray:
            self.tray.title = 'PicSyncra — ' + ('WEB uruchomiony' if state['backend_running'] else 'WEB zatrzymany')

    def refresh_backend(self):
        if self.closed: return
        if not self.busy and not self.operation_id:
            self._run(self.model.client.snapshot, self.render_backend)
        self.root.after(5000, self.refresh_backend)

    def stop_backend(self, *, quit_after=False):
        if self.busy or self.operation_id: return
        def stop():
            if not self.model.client.stop_backend(force=False):
                raise RuntimeError('Nie udało się zatrzymać backendu. Poczekaj na koniec operacji i ponów próbę.')
            return self.model.client.snapshot()
        def stopped(result):
            self.render_backend(result)
            if quit_after: self.quit_launcher()
        self._run(stop, stopped)

    def restart_backend(self):
        if self.busy or self.operation_id: return
        self._run(lambda: restart_and_wait(self.model.client), self.render_backend)

    def change_autostart(self):
        if self.busy or self.operation_id: return
        enabled = self.autostart.get()
        def change():
            self.model.client.set_autostart(enabled)
            return self.model.client.snapshot()
        self._run(change, self.render_backend)

    def open_app(self,app):
        if self.busy or self.operation_id: return
        def launch():
            from .module_sessions import standalone_session
            from .module_state import read_module_set, module_set_root, verify_module_set_files
            from .module_filesystem import safe_path
            with standalone_session(self.context):
                selected=read_module_set(self.context)
                verify_module_set_files(self.context,selected)
                name='PicSyncra-Migrator.exe' if app=='migrator' else 'PicSyncra.exe'
                executable=safe_path(module_set_root(self.context,selected),f'apps/{app}/{name}')
                if not executable.is_file(): raise RuntimeError('Ten moduł nie jest zainstalowany.')
            # The child reacquires the lifetime lease before loading any app code.
            subprocess.Popen([str(executable)],cwd=executable.parent)
        self._run(launch,lambda result:self.status.set('Aplikacja została uruchomiona.'))


def parse_authorization_url(value):
    matched = re.fullmatch(r'picsyncra-update://authorize/([A-Za-z0-9][A-Za-z0-9._-]{0,63})/([a-f0-9]{32})', value)
    if not matched: raise ValueError('Nieprawidłowe żądanie jednorazowego logowania.')
    return matched.groups()


def main(argv=None):
    parser=argparse.ArgumentParser(prog='PicSyncra-Launcher')
    parser.add_argument('--installation-id',default='primary-installation')
    parser.add_argument('--app',choices=('web','migrator','local'))
    parser.add_argument('--authorize-url')
    args=parser.parse_args(argv)
    authorization_request_id = None
    if args.authorize_url:
        args.installation_id, authorization_request_id = parse_authorization_url(args.authorize_url)
    if _elevate(args.installation_id,args.app,args.authorize_url): return 0
    from ..install_paths import load_registered_install_context
    context=load_registered_install_context(args.installation_id)
    if context is None: raise RuntimeError('Brak poprawnej rejestracji instalacji PicSyncra.')
    import tkinter as tk
    root=tk.Tk()
    ModuleLauncherWindow(root,context,ModuleLauncherModel(InstallationControlClient(args.installation_id)),app=args.app,
                         authorization_request_id=authorization_request_id)
    root.mainloop()
    return 0
