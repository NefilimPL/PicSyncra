"""The controller pipe uses both its ACL and protocol identity check."""

from __future__ import annotations

import json
import os
import threading
import time
from uuid import uuid4
import pytest

import win32api
import win32con
import win32security

from picsyncra.installation.control_pipe import (
    NamedPipeControlClient,
    NamedPipeControlServer,
)
from picsyncra.installation.control_protocol import ControlDispatcher


def test_controller_response_timeout_does_not_replay_request_and_next_call_works():
    from picsyncra.installation.control_pipe import ControlPipeError
    from picsyncra.installation.windows_service import ControllerPipeHost
    ready = threading.Event()
    calls, failures = [], []
    installation_id = 'timeout-' + uuid4().hex
    class Dispatcher:
        def dispatch(self, message, *, peer_identity):
            calls.append(message)
            if message == b'slow': time.sleep(0.35)
            return {'ok': True}
    class Server(NamedPipeControlServer):
        def __enter__(self): super().__enter__(); ready.set(); return self
    def serve():
        try:
            ControllerPipeHost(server_factory=lambda: Server(Dispatcher(), installation_id=installation_id,
                allowed_sids={_current_user_sid()}), stop_requested=lambda: b'next' in calls).serve_forever()
        except Exception as exc: failures.append(exc)
    worker = threading.Thread(target=serve, daemon=True); worker.start()
    assert ready.wait(5)
    pipe_name = r'\\.\pipe\PicSyncra.Control.' + installation_id
    with pytest.raises(ControlPipeError, match='czas'):
        NamedPipeControlClient(pipe_name, response_timeout_seconds=0.1).request(b'slow')
    assert NamedPipeControlClient(pipe_name).request(b'next') == {'ok': True}
    worker.join(5)
    assert not worker.is_alive() and not failures
    assert calls == [b'slow', b'next']


def test_server_shutdown_preserves_reply_until_delayed_client_reads(monkeypatch):
    from picsyncra.installation import control_pipe
    modules = control_pipe._windows_modules()
    real_file = modules[2]
    caller = threading.current_thread()

    class SlowClientFile:
        def __getattr__(self, name):
            return getattr(real_file, name)

        def ReadFile(self, *args):
            if threading.current_thread() is caller:
                time.sleep(0.15)
            return real_file.ReadFile(*args)

    monkeypatch.setattr(control_pipe, '_windows_modules', lambda: (*modules[:2], SlowClientFile(), *modules[3:]))
    ready = threading.Event()
    failures = []
    installation_id = 'delayed-' + uuid4().hex
    class Dispatcher:
        def dispatch(self, message, *, peer_identity):
            return {'ok': True, 'received': message.decode()}
    server = NamedPipeControlServer(Dispatcher(), installation_id=installation_id, allowed_sids={_current_user_sid()})
    def serve():
        try:
            with server:
                ready.set()
                server.serve_once()
        except Exception as exc:
            failures.append(exc)
    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    assert ready.wait(5)
    try:
        response = NamedPipeControlClient(server.pipe_name).request(b'hello')
    finally:
        worker.join(5)
    assert not failures
    assert not worker.is_alive()
    assert response == {'ok': True, 'received': 'hello'}


def test_native_read_failure_is_a_control_pipe_error_not_an_unhandled_win32_error(monkeypatch):
    from picsyncra.installation import control_pipe
    import pywintypes
    class File:
        writes = 0
        def CreateFile(self, *args): return object()
        def WriteFile(self, *args): self.writes += 1
        def ReadFile(self, *args): raise pywintypes.error(233, 'ReadFile', 'disconnected')
        def CloseHandle(self, handle): pass
    class Pipe:
        PIPE_READMODE_MESSAGE = 2
        def SetNamedPipeHandleState(self, *args): pass
        def PeekNamedPipe(self, *args): return b'', 1, 0
    modules = control_pipe._windows_modules()
    file = File()
    monkeypatch.setattr(control_pipe, '_windows_modules', lambda: (*modules[:2], file, Pipe(), modules[4]))
    with pytest.raises(control_pipe.ControlPipeError, match='kontroler'):
        NamedPipeControlClient(r'\\.\pipe\PicSyncra.Control.test').request(b'hello')
    assert file.writes == 1


def test_native_host_survives_a_client_disconnect_and_serves_the_next_client():
    import win32file
    from picsyncra.installation.windows_service import ControllerPipeHost
    installation_id = 'closed-' + uuid4().hex
    ready, dispatched = threading.Event(), threading.Event()
    calls, failures = [], []
    class Dispatcher:
        def dispatch(self, message, *, peer_identity):
            calls.append(message)
            dispatched.set()
            return {'ok':True}
    class ReadyServer(NamedPipeControlServer):
        def __enter__(self):
            super().__enter__()
            ready.set()
            return self
    def factory():
        return ReadyServer(Dispatcher(), installation_id=installation_id, allowed_sids={_current_user_sid()})
    def serve():
        try:
            ControllerPipeHost(server_factory=factory, stop_requested=lambda: len(calls) >= 2).serve_forever()
        except Exception as exc: failures.append(exc)
    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    assert ready.wait(5)
    pipe_name = r'\\.\pipe\PicSyncra.Control.' + installation_id
    handle = win32file.CreateFile(pipe_name, win32con.GENERIC_READ | win32con.GENERIC_WRITE, 0, None, win32con.OPEN_EXISTING, 0, None)
    try:
        win32file.WriteFile(handle, b'first')
        assert dispatched.wait(5)
    finally: win32file.CloseHandle(handle)
    response = NamedPipeControlClient(pipe_name).request(b'second')
    worker.join(5)
    assert not worker.is_alive() and not failures
    assert calls == [b'first',b'second'] and response == {'ok':True}


def test_concurrent_native_clients_wait_for_the_current_pipe_request():
    from picsyncra.installation.windows_service import ControllerPipeHost
    installation_id = 'busy-' + uuid4().hex
    ready = threading.Event()
    requests, responses, failures = [], [], []
    class Dispatcher:
        def dispatch(self, message, *, peer_identity):
            time.sleep(0.15)
            requests.append(message)
            return {'ok':True, 'received':message.decode()}
    class Server(NamedPipeControlServer):
        def __enter__(self):
            super().__enter__()
            ready.set()
            return self
    def serve():
        try:
            ControllerPipeHost(server_factory=lambda: Server(Dispatcher(), installation_id=installation_id,
                allowed_sids={_current_user_sid()}), stop_requested=lambda: len(requests) >= 2).serve_forever()
        except Exception as exc: failures.append(exc)
    worker = threading.Thread(target=serve, daemon=True); worker.start()
    assert ready.wait(5)
    def request(message):
        try: responses.append(NamedPipeControlClient(r'\\.\pipe\PicSyncra.Control.' + installation_id).request(message))
        except Exception as exc: failures.append(exc)
    clients = [threading.Thread(target=request, args=(message,), daemon=True) for message in (b'one',b'two')]
    for client in clients: client.start()
    for client in clients: client.join(6)
    worker.join(5)
    assert not worker.is_alive() and not failures
    assert {response['received'] for response in responses} == {'one','two'}


@pytest.mark.parametrize('mode', ['unread_reply', 'no_request', 'invalid_receipt'])
def test_a_live_client_that_never_reads_cannot_block_the_next_request(mode):
    import win32file
    from picsyncra.installation.windows_service import ControllerPipeHost
    installation_id = 'stalled-' + uuid4().hex
    ready, dispatched = threading.Event(), threading.Event()
    calls, failures = [], []
    class Dispatcher:
        def dispatch(self, message, *, peer_identity):
            calls.append(message); dispatched.set()
            return {'ok':True}
    class Server(NamedPipeControlServer):
        def __enter__(self): super().__enter__(); ready.set(); return self
    def serve():
        try:
            ControllerPipeHost(server_factory=lambda: Server(Dispatcher(), installation_id=installation_id,
                allowed_sids={_current_user_sid()}), stop_requested=lambda: b'next' in calls).serve_forever()
        except Exception as exc: failures.append(exc)
    worker = threading.Thread(target=serve, daemon=True); worker.start()
    assert ready.wait(5)
    pipe_name = r'\\.\pipe\PicSyncra.Control.' + installation_id
    handle = win32file.CreateFile(pipe_name, win32con.GENERIC_READ | win32con.GENERIC_WRITE, 0, None, win32con.OPEN_EXISTING, 0, None)
    try:
        if mode != 'no_request':
            win32file.WriteFile(handle,b'stalled')
            assert dispatched.wait(5)
        if mode == 'invalid_receipt':
            import win32pipe
            win32pipe.SetNamedPipeHandleState(handle,win32pipe.PIPE_READMODE_MESSAGE,None,None)
            assert win32file.ReadFile(handle,1024)[1]
            win32file.WriteFile(handle,b'invalid receipt')
        response = NamedPipeControlClient(pipe_name).request(b'next')
        assert response == {'ok':True}
    finally: win32file.CloseHandle(handle)
    worker.join(5)
    assert not worker.is_alive() and not failures


def _current_user_sid() -> str:
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    try:
        sid, _attributes = win32security.GetTokenInformation(
            token, win32security.TokenUser
        )
        return win32security.ConvertSidToStringSid(sid)
    finally:
        token.Close()


def test_named_pipe_dispatches_one_authorized_message_and_returns_json() -> None:
    """Catches falling back from the authenticated pipe to an open local channel."""

    class FakeController:
        def set_autostart(self, enabled: bool) -> bool:
            self.enabled = enabled
            return enabled

    controller = FakeController()
    dispatcher = ControlDispatcher(
        controller,
        installation_id="primary-installation",
        authorized_identities={_current_user_sid()},
    )
    with NamedPipeControlServer(
        dispatcher,
        installation_id="primary-installation",
        allowed_sids={_current_user_sid()},
    ) as server:
        worker = threading.Thread(target=server.serve_once, daemon=True)
        worker.start()
        response = NamedPipeControlClient(server.pipe_name).request(
            json.dumps(
                {
                    "version": 1,
                    "installation_id": "primary-installation",
                    "command": "set_autostart",
                    "payload": {"enabled": True},
                }
            ).encode("utf-8")
        )
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert response == {"ok": True, "autostart": True}
    assert controller.enabled is True


def test_pipe_maps_an_elevated_administrator_to_the_authorized_group(
    monkeypatch,
) -> None:
    """Catches granting a local administrator an ACL entry but rejecting it in the protocol."""

    from picsyncra.installation import control_pipe

    class Handle:
        def Close(self) -> None:
            pass

    class Api:
        @staticmethod
        def OpenProcess(_access, _inherit, _process_id):
            return Handle()

    class Con:
        PROCESS_QUERY_LIMITED_INFORMATION = 1
        TOKEN_QUERY = 2
        TOKEN_DUPLICATE = 4

    class Security:
        TokenUser = 1
        WinBuiltinAdministratorsSid = 2
        SecurityImpersonation = 2

        @staticmethod
        def OpenProcessToken(_process, _access):
            return Handle()

        @staticmethod
        def GetTokenInformation(_token, _kind):
            return ("person", 0)

        @staticmethod
        def ConvertSidToStringSid(_sid):
            return "S-1-5-21-1000"

        @staticmethod
        def CreateWellKnownSid(_kind, _domain):
            return "administrators"

        @staticmethod
        def DuplicateToken(_token, _level):
            return Handle()

        @staticmethod
        def CheckTokenMembership(_token, group):
            return group == "administrators"

    class Pipe:
        @staticmethod
        def GetNamedPipeClientProcessId(_handle):
            return 99

    monkeypatch.setattr(
        control_pipe,
        "_windows_modules",
        lambda: (Api, Con, object(), Pipe, Security),
    )
    server = control_pipe.NamedPipeControlServer(
        dispatcher=object(),
        installation_id="primary",
        allowed_sids={"S-1-5-18", "S-1-5-32-544"},
    )
    server._handle = object()

    assert server._client_sid(Pipe) == "S-1-5-32-544"


def test_pipe_checks_administrator_membership_using_a_real_windows_process_token() -> None:
    """Process primary tokens must be duplicated before CheckTokenMembership."""

    class CurrentProcessPipe:
        @staticmethod
        def GetNamedPipeClientProcessId(_handle):
            return os.getpid()

    server = NamedPipeControlServer(
        dispatcher=object(), installation_id="native-token-test",
        allowed_sids={"S-1-5-18", "S-1-5-32-544"},
    )
    administrators = win32security.CreateWellKnownSid(
        win32security.WinBuiltinAdministratorsSid, None
    )
    expected = (
        "S-1-5-32-544" if win32security.CheckTokenMembership(None, administrators)
        else _current_user_sid()
    )

    assert server._client_sid(CurrentProcessPipe) == expected
