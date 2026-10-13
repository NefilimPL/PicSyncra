from io import BytesIO
import json
from types import SimpleNamespace
from urllib.error import URLError

from picsyncra.installation import controller_host as host


class Response(BytesIO):
    def __init__(self, **payload):
        super().__init__(json.dumps(payload).encode())


def mock_probe(monkeypatch, probe):
    # Exercise the current checker and the explicit proxy-free opener equally.
    monkeypatch.setattr(host, 'urlopen', probe, raising=False)
    monkeypatch.setattr(host, 'build_opener', lambda *args: SimpleNamespace(open=probe), raising=False)


def test_first_update_waits_for_slow_but_healthy_ocr_start(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(host.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(host.time, 'sleep', lambda duration: now.__setitem__(0, now[0]+duration))
    def probe(url, **kwargs):
        if now[0] < 40: raise URLError('still verifying installed OCR files')
        return Response(ok=True, application='picsyncra', process_id=22)
    mock_probe(monkeypatch, probe)
    controller = SimpleNamespace(snapshot=lambda: dict(backend_running=True, backend_pid=22, backend_port=8010))
    assert host._backend_ready(controller)
    assert now[0] >= 40


def test_health_check_uses_configured_port_and_rejects_foreign_application(monkeypatch):
    now = [0.0]
    urls = []
    monkeypatch.setattr(host.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(host.time, 'sleep', lambda duration: now.__setitem__(0, now[0]+duration))
    def probe(url, **kwargs):
        urls.append(url)
        now[0] += 0.1
        return Response(ok=True, application='other-app', process_id=99)
    mock_probe(monkeypatch, probe)
    controller = SimpleNamespace(snapshot=lambda: dict(backend_running=True, backend_pid=22, backend_port=8765))
    assert not host._backend_ready(controller, timeout_seconds=1)
    assert urls and set(urls)=={'http://127.0.0.1:8765/api/health'}


def test_unhealthy_backend_polling_is_paced_and_reports_failed_components(monkeypatch):
    now, sleeps, details = [0.0], [], []
    monkeypatch.setattr(host.time, 'monotonic', lambda: now[0])
    def sleep(duration):
        sleeps.append(duration); now[0] += duration
    monkeypatch.setattr(host.time, 'sleep', sleep)
    def probe(url, **kwargs):
        now[0] += 0.01
        return Response(ok=False, application='picsyncra', process_id=22,
                        components=dict(sqlite=dict(status='critical'), backend=dict(status='online')),
                        private_secret='never include this')
    mock_probe(monkeypatch, probe)
    controller = SimpleNamespace(snapshot=lambda: dict(backend_running=True, backend_pid=22))
    assert not host._backend_ready(controller, timeout_seconds=1, on_status=details.append)
    assert sleeps and len(sleeps) <= 5
    assert details[-1]['code']=='backend_health_timeout'
    assert details[-1]['components']=={'sqlite':'critical', 'backend':'online'}
    assert 'private_secret' not in str(details) and 'never include' not in str(details)


def test_alive_but_different_process_cannot_pass_validation(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(host.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(host.time, 'sleep', lambda duration: now.__setitem__(0, now[0]+duration))
    def probe(url, **kwargs):
        now[0] += 0.1
        return Response(ok=True, application='picsyncra', process_id=99)
    mock_probe(monkeypatch, probe)
    controller = SimpleNamespace(snapshot=lambda: dict(backend_running=True, backend_pid=22))
    assert not host._backend_ready(controller, timeout_seconds=1)


def test_slow_response_cannot_keep_startup_check_reading_past_deadline(monkeypatch):
    now=[0.0]
    monkeypatch.setattr(host.time,'monotonic',lambda:now[0])
    monkeypatch.setattr(host.time,'sleep',lambda duration:now.__setitem__(0,now[0]+duration))
    class Drip(Response):
        def read(self, size=-1):
            data=bytearray()
            while len(data)<size:
                piece=self.read1(1)
                if not piece: break
                data.extend(piece)
            return bytes(data)
        def read1(self,size=-1):
            now[0]+=0.1
            return super().read(1)
    mock_probe(monkeypatch,lambda *a,**k:Drip(ok=True,application='picsyncra',process_id=22))
    controller=SimpleNamespace(snapshot=lambda:dict(backend_running=True,backend_pid=22))
    assert not host._backend_ready(controller,timeout_seconds=1)
    assert now[0]<1.2


def test_malformed_http_response_is_reported_without_raw_transport_data(monkeypatch):
    import http.client
    now, details=[0.0],[]
    monkeypatch.setattr(host.time,'monotonic',lambda:now[0])
    monkeypatch.setattr(host.time,'sleep',lambda duration:now.__setitem__(0,now[0]+duration))
    def probe(*args,**kwargs): raise http.client.BadStatusLine('private health response')
    mock_probe(monkeypatch,probe)
    controller=SimpleNamespace(snapshot=lambda:dict(backend_running=True,backend_pid=22))
    assert not host._backend_ready(controller,timeout_seconds=1,on_status=details.append)
    assert details[-1]['observation']=='no_valid_response'
    assert 'private' not in str(details)


def test_native_delayed_backend_is_checked_directly_despite_proxy(tmp_path, monkeypatch):
    import subprocess, sys
    import threading, time
    from queue import Queue
    script=tmp_path/'backend.py'
    script.write_text('''import os,json,time
from http.server import HTTPServer,BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  data=json.dumps(dict(ok=True,application='picsyncra',process_id=os.getpid())).encode()
  self.send_response(200); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
 def log_message(self,*args): pass
server=HTTPServer(('127.0.0.1',0),Handler)
print(server.server_port,flush=True)
time.sleep(1.2)
server.serve_forever()
''', encoding='utf-8')
    process=subprocess.Popen([sys.executable,str(script)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        lines=Queue()
        threading.Thread(target=lambda:lines.put(process.stdout.readline()),daemon=True).start()
        port=int(lines.get(timeout=10))
        monkeypatch.setenv('http_proxy','http://127.0.0.1:1')
        monkeypatch.setenv('HTTP_PROXY','http://127.0.0.1:1')
        monkeypatch.setenv('no_proxy','')
        monkeypatch.setenv('NO_PROXY','')
        controller=SimpleNamespace(snapshot=lambda: dict(backend_running=process.poll() is None,
            backend_pid=process.pid, backend_port=port))
        started=time.monotonic()
        assert host._backend_ready(controller,timeout_seconds=5)
        assert time.monotonic()-started>=1
    finally:
        import psutil
        try: children=psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess: children=[]
        for child in children:
            try: child.terminate()
            except psutil.NoSuchProcess: pass
        process.terminate(); process.wait(timeout=10)
        _, alive=psutil.wait_procs(children,timeout=5)
        for child in alive:
            child.kill(); child.wait(timeout=5)
        process.stdout.close(); process.stderr.close()
