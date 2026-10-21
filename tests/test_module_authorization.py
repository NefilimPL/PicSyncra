from contextlib import contextmanager
import json
import pytest
import sys
from tests.test_module_state import context
from tests.test_module_executor import prepare, Controller
from tests.test_module_service import Source
from picsyncra.installation.module_service import ModuleService
from picsyncra.installation.module_preflight import ModuleAccessError


class Token:
    def __init__(self): self.active = False; self.closed = False; self.scopes = 0
    @contextmanager
    def scope(self):
        assert not self.closed and not self.active
        self.active = True; self.scopes += 1
        try: yield
        finally: self.active = False
    def close(self): self.closed = True


def setup(context, monkeypatch):
    _, store, _ = prepare(context)
    token = Token()
    def check(_):
        if not token.active: raise ModuleAccessError('maintenance_ready', PermissionError(13, 'denied'))
    monkeypatch.setattr('picsyncra.installation.module_preflight.check_update_access', check)
    jobs = []
    service = ModuleService(context, Controller(), source=Source(), content=store, schedule=jobs.append,
                            quiesce=lambda _: None, healthy=lambda: True)
    monkeypatch.setattr('picsyncra.installation.module_authorization.logon_credentials', lambda *args: token)
    request = service.authorization_request(action='update_all', selected={}, excluded=[], restore_backup_id=None)
    return service, token, jobs, request


def test_credentials_are_bound_to_one_plan_and_closed_after_worker(context, monkeypatch):
    service, token, jobs, request = setup(context, monkeypatch)
    plan = service.authorize(request['request_id'], 'encrypted-secret')
    assert not token.active and not token.closed
    assert service.authorization_status(request['request_id'])['state'] == 'prepared'
    payload = json.loads((context.state_root / 'module-plans' / (plan['plan_id'] + '.json')).read_text())
    assert payload['requires_authorization'] is True
    assert 'secret' not in json.dumps(payload)
    result = service.execute(plan['plan_id'])
    assert result['state'] == 'accepted' and not token.closed and not token.active
    jobs[0]()
    assert token.closed and not token.active
    assert service.operation(plan['plan_id'])['state'] == 'committed'
    with pytest.raises(RuntimeError, match='logowanie'):
        service.execute(plan['plan_id'])


def test_cancel_releases_token_and_blocks_execution(context, monkeypatch):
    service, token, _, request = setup(context, monkeypatch)
    plan = service.authorize(request['request_id'], 'encrypted-secret')
    service.cancel_authorization(request['request_id'])
    assert token.closed
    assert service.authorization_status(request['request_id'])['state'] == 'cancelled'
    with pytest.raises(RuntimeError): service.execute(plan['plan_id'])


def test_insufficient_credentials_release_token_without_downloading(context, monkeypatch):
    service, token, jobs, request = setup(context, monkeypatch)
    monkeypatch.setattr('picsyncra.installation.module_preflight.check_update_access',
                        lambda _: (_ for _ in ()).throw(ModuleAccessError('state', PermissionError(13, 'denied'))))
    with pytest.raises(ModuleAccessError): service.authorize(request['request_id'], 'encrypted-secret')
    assert token.closed and jobs == [] and not service.busy


def test_native_prompt_encrypted_blob_uses_request_binding_and_zeroes_buffers():
    # Native UI has no password persistence option. Actual credentials are never
    # supplied by tests; the secure Windows API integration is checked separately.
    from picsyncra.installation.module_authorization import _binding
    assert _binding('first', 'a' * 32) != _binding('second', 'a' * 32)
    assert _binding('first', 'a' * 32) != _binding('first', 'b' * 32)


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows DPAPI')
def test_dpapi_roundtrip_is_bound_to_exact_request():
    import ctypes
    from picsyncra.installation.module_authorization import _Blob, _dpapi, AuthorizationError
    data = ctypes.create_string_buffer(b'synthetic-no-credentials')
    packed = _Blob(len(data.raw), ctypes.cast(data, ctypes.c_void_p))
    with _dpapi(packed, b'first-request', encrypt=True) as protected:
        with _dpapi(protected, b'first-request', encrypt=False) as plain:
            assert ctypes.string_at(plain.data, plain.size) == data.raw
        with pytest.raises(AuthorizationError):
            with _dpapi(protected, b'another-request', encrypt=False): pytest.fail('wrong binding accepted')


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows credential packing and logon')
def test_native_credentials_reject_unknown_account_without_exposing_secret():
    import base64
    import ctypes
    from ctypes import wintypes
    from uuid import uuid4
    from picsyncra.installation.module_authorization import _Blob, _dpapi, _binding, _zero, logon_credentials, AuthorizationError
    api = ctypes.WinDLL('credui', use_last_error=True)
    api.CredPackAuthenticationBufferW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.LPWSTR,
                                                ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    api.CredPackAuthenticationBufferW.restype = wintypes.BOOL
    name = ctypes.create_unicode_buffer('.\\PicSyncraNonexistent' + uuid4().hex)
    password = ctypes.create_unicode_buffer('synthetic-not-a-real-password')
    size = wintypes.DWORD()
    assert not api.CredPackAuthenticationBufferW(0, name, password, None, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    try:
        assert api.CredPackAuthenticationBufferW(0, name, password, buffer, ctypes.byref(size))
        with _dpapi(_Blob(size.value, ctypes.cast(buffer, ctypes.c_void_p)), _binding('test', 'a' * 32), encrypt=True) as protected:
            blob = base64.b64encode(ctypes.string_at(protected.data, protected.size)).decode('ascii')
        with pytest.raises(AuthorizationError) as failure:
            logon_credentials('test', 'a' * 32, blob)
        assert failure.value.details['code'] == 'logon_failed'
        assert failure.value.details['system_code'] in {1326, 1332}
        assert 'synthetic' not in str(failure.value) and 'PicSyncraNonexistent' not in str(failure.value.details)
    finally:
        for value in (name, password, buffer): _zero(value, ctypes.sizeof(value))


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows token impersonation')
def test_windows_authorization_reverts_thread_and_closes_handle():
    win32security = pytest.importorskip('win32security')
    import win32api
    import win32con
    from picsyncra.installation.module_authorization import WindowsAuthorization
    source = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY | win32con.TOKEN_DUPLICATE)
    try: duplicated = win32security.DuplicateToken(source, win32security.SecurityImpersonation)
    finally: source.Close()
    authorization = WindowsAuthorization(duplicated.Detach())
    try:
        with authorization.scope():
            token = win32security.OpenThreadToken(win32api.GetCurrentThread(), win32con.TOKEN_QUERY, True)
            token.Close()
            raise_expected = True
        with pytest.raises(win32api.error) as reverted:
            win32security.OpenThreadToken(win32api.GetCurrentThread(), win32con.TOKEN_QUERY, True)
        assert reverted.value.winerror == 1008
        assert raise_expected
    finally: authorization.close()
    assert authorization.handle is None


def test_expiration_releases_prepared_token_and_prevents_reuse(context, monkeypatch):
    service, token, jobs, request = setup(context, monkeypatch)
    plan = service.authorize(request['request_id'], 'encrypted-secret')
    service._expire_authorization(request['request_id'])
    assert token.closed
    with pytest.raises(RuntimeError, match='wygasło'): service.authorization_status(request['request_id'])
    with pytest.raises(RuntimeError): service.execute(plan['plan_id'])
    assert jobs == []


def test_failed_scheduler_does_not_leave_busy_or_keep_credentials(context, monkeypatch):
    service, token, jobs, request = setup(context, monkeypatch)
    plan = service.authorize(request['request_id'], 'encrypted-secret')
    service.schedule = lambda job: (_ for _ in ()).throw(RuntimeError('cannot schedule'))
    with pytest.raises(RuntimeError, match='schedule'): service.execute(plan['plan_id'])
    assert token.closed and not service.busy and jobs == []


@pytest.mark.parametrize('phase', ['before_credentials', 'during_prepare', 'before_execute'])
def test_deadline_is_enforced_without_waiting_for_expiry_thread(context, monkeypatch, phase):
    service, token, jobs, request = setup(context, monkeypatch)
    clock = [10.0]
    monkeypatch.setattr('picsyncra.installation.module_service.time.monotonic', lambda: clock[0])
    service._authorization_requests[request['request_id']]['expires_at'] = 20.0
    if phase == 'before_credentials':
        clock[0] = 21.0
        with pytest.raises(RuntimeError, match='wygasło'): service.authorize(request['request_id'], 'encrypted-secret')
        assert token.scopes == 0
    elif phase == 'during_prepare':
        original = service.prepare
        def slow(**payload):
            result = original(**payload); clock[0] = 21.0; return result
        service.prepare = slow
        with pytest.raises(RuntimeError, match='wygasło'): service.authorize(request['request_id'], 'encrypted-secret')
        assert token.closed
    else:
        plan = service.authorize(request['request_id'], 'encrypted-secret')
        clock[0] = 21.0
        with pytest.raises(RuntimeError, match='wygasło'): service.execute(plan['plan_id'])
        assert token.closed
    assert jobs == [] and not service.busy
