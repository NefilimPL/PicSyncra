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
import webbrowser
from .launcher import InstallationControlClient


class ModuleLauncherModel:
    def __init__(self, client):
        self.client = client
        self.selected = {}
        self.selected_versions = {}
        self.snapshot = {}

    def refresh(self):
        self.snapshot = self.client.module_catalog()
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
            selected=dict(self.selected) if action == 'rollback_modules' else {},
            excluded=list(self.selected) if action == 'update' else [], restore_backup_id=restore_backup_id)

    def execute(self, plan_id, *, restore_backup_id=None, acknowledge_data_loss=False):
        return self.client.module_execute(plan_id, restore_backup_id=restore_backup_id, acknowledge_data_loss=acknowledge_data_loss)


def _elevate(installation_id, app):
    if sys.platform != 'win32' or ctypes.windll.shell32.IsUserAnAdmin(): return False
    arguments = ['--installation-id', installation_id, '--app', app]
    if not getattr(sys, 'frozen', False): arguments.insert(0, str(Path(sys.argv[0]).absolute()))
    result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', sys.executable, subprocess.list2cmdline(arguments), None, 1)
    if result <= 32: raise RuntimeError('Launcher wymaga uprawnień administratora do sterowania instalacją.')
    return True


class ModuleLauncherWindow:
    def __init__(self, root, context, model, *, app='web'):
        import tkinter as tk
        from tkinter import ttk, messagebox
        self.root, self.context, self.model = root, context, model
        self.ttk, self.messagebox = ttk, messagebox
        self.callbacks = queue.Queue()
        self.busy = False
        self.operation_id = None
        self.terminal_message = None
        self.app = app
        root.title('PicSyncra — launcher i odzyskiwanie modułów')
        root.geometry('1060x740')
        ttk.Label(root, text='Wybór wersji przygotowuje cofnięcie. Zatwierdza je jeden wspólny przycisk.', wraplength=1000).pack(padx=12, pady=12)
        toolbar = ttk.Frame(root); toolbar.pack(fill='x', padx=12)
        self.buttons=[]
        actions = [('Uruchom panel', self.open_panel), ('Uruchom Migrator', lambda: self.open_app('migrator')),
                              ('Uruchom LOCAL', lambda: self.open_app('local')), ('Sprawdź wersje', self.refresh),
                              ('Aktualizuj moduły', lambda: self.prepare('update')),
                              ('Aktualizuj wszystko', lambda: self.prepare('update_all')),
                              ('Cofnij wersję modułu', lambda: self.prepare('rollback_modules')), ('Pobierz OCR', lambda: self.prepare('install_ocr')),
                              ('Ponów odzyskiwanie', lambda: self._run(self.model.client.module_recover, self.accepted))]
        for index, (label, action) in enumerate(actions):
            button=ttk.Button(toolbar,text=label,command=action)
            button.grid(row=index//3,column=index%3,padx=3,pady=3,sticky='ew'); self.buttons.append(button)
            if label == 'Cofnij wersję modułu': self.rollback_button = button
        for column in range(3): toolbar.columnconfigure(column,weight=1)
        channel_frame=ttk.Frame(root); channel_frame.pack(fill='x',padx=12,pady=6)
        ttk.Label(channel_frame,text='Kanał aktualizacji:').pack(side='left')
        self.channel=ttk.Combobox(channel_frame,state='readonly',values=['Stable','Dev'],width=12)
        self.channel.set('Stable'); self.channel.pack(side='left',padx=8)
        self.channel.bind('<<ComboboxSelected>>',lambda event: self.change_channel())
        self.status=tk.StringVar(value='Odczyt kontrolera…')
        ttk.Label(root,textvariable=self.status,wraplength=1000).pack(fill='x',padx=12,pady=10)
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
        self.refresh()

    def _callbacks(self):
        while True:
            try: callback=self.callbacks.get_nowait()
            except queue.Empty: break
            callback()
        self.root.after(100,self._callbacks)

    def _run(self, work, finished):
        self.busy=True
        for button in self.buttons: button.configure(state='disabled')
        for widget in self.rows.winfo_children():
            if isinstance(widget,self.ttk.Combobox): widget.configure(state='disabled')
        self.backup.configure(state='disabled')
        self.channel.configure(state='disabled')
        def worker():
            try:
                result=work()
                self.callbacks.put(lambda: self._finish(finished,result))
            except Exception as exc:
                message=str(exc)
                def failed(value):
                    self.status.set(value)
                    self.channel.set('Dev' if self.model.snapshot.get('channel') == 'dev' else 'Stable')
                    if self.operation_id: self.root.after(2000,self.poll)
                self.callbacks.put(lambda: self._finish(failed,message))
        threading.Thread(target=worker,daemon=True,name='PicSyncraLauncherIO').start()

    def _finish(self, callback, result):
        self.busy=False
        for button in self.buttons: button.configure(state='normal')
        for widget in self.rows.winfo_children():
            if isinstance(widget,self.ttk.Combobox): widget.configure(state='readonly')
        self.backup.configure(state='readonly')
        self.channel.configure(state='disabled' if self.operation_id else 'readonly')
        callback(result)
        self.channel.configure(state='disabled' if self.busy or self.operation_id else 'readonly')
        self.rollback_button.configure(state='disabled' if self.busy or self.operation_id or not self.model.selected else 'normal')

    def refresh(self): self._run(self.model.refresh,self.render)

    def change_channel(self):
        if self.busy or self.operation_id: return
        channel='dev' if self.channel.get() == 'Dev' else 'stable'
        def work():
            self.model.change_channel(channel)
            return self.model.refresh()
        self._run(work,self.render)

    def render(self,snapshot):
        self.channel.set('Dev' if snapshot.get('channel') == 'dev' else 'Stable')
        for widget in self.rows.winfo_children(): widget.destroy()
        for index,module in enumerate(snapshot.get('modules',[])):
            self.ttk.Label(self.rows,text=module['label']).grid(row=index,column=0,padx=5,pady=10,sticky='w')
            text=f"Obecna: {module['current']}  Dostępna: {module['latest'] or 'brak podpisanego wydania'}"
            if module['pinned']: text+='  [wyłączony z aktualizacji]'
            if module['module_id'] in self.model.selected: text+='  [wybrany do cofnięcia; pomijany w aktualizacji]'
            chosen=self.model.selected.get(module['module_id'])
            if chosen and not any(v['version_id']==chosen and v['available'] for v in module['versions']):
                text+='  [wybrana wersja niedostępna w tym kanale]'
            self.ttk.Label(self.rows,text=text,wraplength=350).grid(row=index,column=1,sticky='w',padx=5)
            values={'Bez zmiany':None}
            links={}
            for version in module['versions']:
                if not version['available']: continue
                label=f"{version['display_version']} ({version['version_id'][:8]})"
                values[label]=version['version_id']; links[label]=version['release_url']
            combo=self.ttk.Combobox(self.rows,state='readonly',values=list(values),width=25)
            chosen=self.model.selected.get(module['module_id'])
            if chosen and chosen not in values.values():
                version=self.model.selected_versions.get(module['module_id'],{})
                label=f"{version.get('display_version',chosen[:8])} — niedostępna w tym kanale"
                values[label]=chosen; links[label]=version.get('release_url','')
                combo.configure(values=list(values))
            combo.set(next((key for key,value in values.items() if value==chosen),'Bez zmiany'))
            combo.grid(row=index,column=2,padx=5)
            combo.bind('<<ComboboxSelected>>',lambda event,mid=module['module_id'],box=combo,options=values: self.select_version(mid,options[box.get()]))
            current_link=next((v['release_url'] for v in module['versions'] if v['version_id']==module['current_id']),'')
            self.ttk.Button(self.rows,text='Wydanie na GitHub',command=lambda box=combo,urls=links,current=current_link: self.open_release(urls.get(box.get(),current))).grid(row=index,column=3,padx=5)
        self.backup_ids={'Zachowaj obecną bazę':None}
        for backup in snapshot.get('backups',[]):
            self.backup_ids[f"{backup['backup_id']} · schemat {backup['schema_version']}"]=backup['backup_id']
        self.backup.configure(values=list(self.backup_ids))
        if self.backup.get() not in self.backup_ids: self.backup.current(0)
        if not self.operation_id:
            self.status.set(self.terminal_message or ('Katalog lokalny — brak Internetu. Brakujące pliki wymagają połączenia.' if snapshot.get('offline') else 'Wybierz moduły i zatwierdź operację.'))
        self.rollback_button.configure(state='disabled' if self.busy or self.operation_id or not self.model.selected else 'normal')

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
        restore=self.backup_ids.get(self.backup.get())
        self._run(lambda: self.model.prepare(action,restore_backup_id=restore),lambda plan:self.confirm_plan(plan,restore))

    def confirm_plan(self,plan,restore):
        for widget in self.conflicts.winfo_children(): widget.destroy()
        if plan['conflicts']:
            text='\n'.join(f"{c['module_id']} {c['selected_version']} ↔ {c['dependency_id'] or 'baza/runtime'} {c['dependency_version'] or ''}: {c['requirement']}" for c in plan['conflicts'])
            self.ttk.Label(self.conflicts,text=text,wraplength=1000).pack(anchor='w')
            self.ttk.Button(self.conflicts,text='Aktualizuj wszystko',command=lambda:self.prepare('update_all')).pack(side='left')
            self.ttk.Button(self.conflicts,text='Nie aktualizuj',command=lambda:[widget.destroy() for widget in self.conflicts.winfo_children()]).pack(side='left')
            return
        changes='\n'.join(f"{c['module_id']}: {c['current'] or 'brak'} → {c['target']}" for c in plan['changes'])
        if plan['action'] == 'update_all':
            overridden = set(self.model.selected) | {m['module_id'] for m in (self.model.snapshot or {}).get('modules',[]) if m['pinned']}
            if overridden: changes += '\nAktualizacje zostaną włączone, a wybory cofnięcia pominięte dla: ' + ', '.join(sorted(overridden)) + '.'
        if not self.messagebox.askyesno('Zatwierdź plan',f"{changes or 'Zgodny zestaw modułów.'}\nDo pobrania: {plan['download_bytes']:,} bajtów.\nZatwierdzić operację?",parent=self.root): return
        acknowledge=False
        if restore:
            acknowledge=self.messagebox.askyesno('Utrata nowszych danych','Odtworzenie starszej bazy usunie dane zapisane po wykonaniu kopii. Potwierdzasz utratę tych nowszych danych?',parent=self.root)
            if not acknowledge: return
        self._run(lambda:self.model.execute(plan['plan_id'],restore_backup_id=restore,acknowledge_data_loss=acknowledge),self.accepted)

    def accepted(self,result):
        self.terminal_message=None
        self.operation_id=result['operation_id']
        self.status.set('Operacja została przyjęta przez kontroler.')
        self.root.after(1000,self.poll)

    def poll(self):
        if self.operation_id: self._run(lambda:self.model.client.module_operation(self.operation_id),self.progress)

    def progress(self,result):
        if result is None:
            self.status.set('Oczekiwanie na kontroler…'); self.root.after(2000,self.poll); return
        self.status.set(f"Operacja: {result['state']} — {result.get('error') or ''}")
        if result['state'] in {'committed','rolled_back','failed','recovery_required'}:
            self.terminal_message=self.status.get()
            if result['state']=='committed':
                self.model.selected.clear(); self.model.selected_versions.clear()
            self.operation_id=None; self.refresh()
        else: self.root.after(1500,self.poll)

    def open_panel(self):
        self._run(lambda:self.model.client.start_backend(),lambda result:webbrowser.open('http://127.0.0.1:8010'))

    def open_app(self,app):
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


def main(argv=None):
    parser=argparse.ArgumentParser(prog='PicSyncra-Launcher')
    parser.add_argument('--installation-id',default='primary-installation')
    parser.add_argument('--app',choices=('web','migrator','local'),default='web')
    args=parser.parse_args(argv)
    if _elevate(args.installation_id,args.app): return 0
    from ..install_paths import load_registered_install_context
    context=load_registered_install_context(args.installation_id)
    if context is None: raise RuntimeError('Brak poprawnej rejestracji instalacji PicSyncra.')
    import tkinter as tk
    root=tk.Tk()
    ModuleLauncherWindow(root,context,ModuleLauncherModel(InstallationControlClient(args.installation_id)),app=args.app)
    root.mainloop()
    return 0
