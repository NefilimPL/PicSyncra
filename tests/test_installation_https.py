"""Real TLS exchanges with a fresh system trust store and a bundled CA."""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import ssl
import threading
from urllib.request import Request, urlopen, build_opener
from urllib.error import URLError

import certifi
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@pytest.fixture
def tls_endpoint(tmp_path, monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Test bundled CA')])
    now=datetime.now(timezone.utc)
    ca=(x509.CertificateBuilder().subject_name(issuer).issuer_name(issuer).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256()))
    server_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    server_cert=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'test-server.invalid')]))
        .issuer_name(issuer).public_key(server_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
        .sign(key,hashes.SHA256()))
    ca_path=tmp_path/'ca.pem'; ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path=tmp_path/'server.pem'; cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    key_path=tmp_path/'key.pem'; key_path.write_bytes(server_key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption()))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b'[]')
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path),str(key_path))
    server.socket=context.wrap_socket(server.socket,server_side=True)
    worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
    # No machine/user certificates; bundling must supply trust explicitly.
    empty=lambda *args,**kwargs: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    monkeypatch.setattr(ssl,'create_default_context',empty)
    monkeypatch.setattr(ssl,'_create_default_https_context',empty)
    monkeypatch.setattr(certifi,'where',lambda:str(ca_path))
    yield f'https://127.0.0.1:{server.server_port}/'
    server.shutdown(); server.server_close(); worker.join(timeout=2)


@pytest.mark.parametrize('transport',['api','manifest','content','legacy_content'])
def test_installed_github_transport_uses_bundled_ca_with_empty_system_store(tls_endpoint,monkeypatch,transport):
    if transport=='api':
        from picsyncra.installation import repository as module
        monkeypatch.setattr(module,'urlopen',lambda request,**kwargs:urlopen(tls_endpoint,**kwargs))
        assert module.fetch_release_json('/repos/NefilimPL/PicSyncra/releases') == []
        return
    if transport=='manifest':
        from picsyncra.installation import module_source as module
        fetch=lambda:module.fetch_manifest_asset('https://github.com/NefilimPL/PicSyncra/releases/download/v1/test')
    elif transport=='content':
        from picsyncra.installation import module_content as module
        fetch=lambda:module._fetch_range('https://github.com/NefilimPL/PicSyncra/releases/download/v1/test',0,2,2)
    else:
        from picsyncra.installation import downloads as module
        fetch=lambda:module._open_github_asset('https://github.com/NefilimPL/PicSyncra/releases/download/v1/test')
    def routed_opener(*handlers):
        opener=build_opener(*handlers)
        class Route:
            def open(self,request,**kwargs): return opener.open(Request(tls_endpoint,headers=dict(request.header_items())),**kwargs)
        return Route()
    monkeypatch.setattr(module,'build_opener',routed_opener)
    result=fetch()
    if isinstance(result,bytes): assert result==b'[]'
    else:
        with result: assert result.read()==b'[]'


def test_https_context_preserves_system_trust_and_hostname_verification(tls_endpoint,monkeypatch):
    from picsyncra.installation.https import verified_https_context
    original=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    original.load_verify_locations(cafile=certifi.where())
    monkeypatch.setattr(ssl,'create_default_context',lambda:original)
    context=verified_https_context()
    assert context is original and context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
    # The CA is trusted, but the certificate deliberately has no DNS SAN.
    with pytest.raises(URLError):
        urlopen(tls_endpoint.replace('127.0.0.1','localhost'),context=context,timeout=2)
