"""The SCM adapter reports actual Windows service state to the controller."""

from __future__ import annotations

import threading
import pytest

from picsyncra.installation.windows_service import (
    ControllerPipeHost,
    WindowsServiceAdapter,
)


class FakeServiceApi:
    def __init__(self) -> None:
        self.running = False
        self.autostart = False
        self.started: list[str] = []
        self.stopped: list[tuple[str, bool]] = []

    def start(self, service_name: str) -> None:
        self.started.append(service_name)
        self.running = True

    def stop(self, service_name: str, *, force: bool) -> bool:
        self.stopped.append((service_name, force))
        self.running = False
        return True

    def set_autostart(self, service_name: str, enabled: bool) -> bool:
        assert service_name == "PicSyncraBackend-primary"
        self.autostart = enabled
        return self.autostart is enabled

    def snapshot(self, service_name: str) -> dict[str, bool]:
        assert service_name == "PicSyncraBackend-primary"
        return {"backend_running": self.running, "autostart": self.autostart}


def test_windows_service_adapter_uses_the_registered_service_and_confirmed_state() -> None:
    """Catches falling back to arbitrary processes instead of the named service."""

    api = FakeServiceApi()
    adapter = WindowsServiceAdapter(
        "PicSyncraBackend-primary",
        service_api=api,
        listener_owner=lambda _port: "primary-installation",
    )

    adapter.start_backend()
    assert adapter.set_autostart(True) is True
    assert adapter.stop_backend(force=True) is True

    assert api.started == ["PicSyncraBackend-primary"]
    assert api.stopped == [("PicSyncraBackend-primary", True)]
    assert adapter.snapshot() == {"backend_running": False, "autostart": True}


def test_controller_pipe_host_stops_after_the_current_request_when_signalled() -> None:
    """Catches a service host reopening pipe instances after its stop request."""

    stop_requested = threading.Event()
    events: list[str] = []

    class FakePipeServer:
        def __enter__(self):
            events.append("open")
            return self

        def serve_once(self) -> None:
            events.append("request")
            stop_requested.set()

        def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
            events.append("close")

    host = ControllerPipeHost(
        server_factory=FakePipeServer,
        stop_requested=stop_requested.is_set,
    )

    host.serve_forever()

    assert events == ["open", "request", "close"]


def test_controller_pipe_host_survives_a_client_closing_before_reading():
    from picsyncra.installation.control_pipe import ControlPipeError
    from picsyncra.installation import control_pipe
    disconnected = getattr(control_pipe, 'ControlPipePeerDisconnected', ControlPipeError)
    requests = []
    class Server:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def serve_once(self):
            requests.append(1)
            if len(requests) == 1: raise disconnected('client left')
    ControllerPipeHost(server_factory=Server, stop_requested=lambda: len(requests) >= 2).serve_forever()
    assert len(requests) == 2


def test_controller_pipe_host_does_not_hide_an_ownership_or_acl_failure():
    class Server:
        def __enter__(self): raise RuntimeError('duplicate owner')
        def __exit__(self, *args): pass
    with pytest.raises(RuntimeError, match='duplicate owner'):
        ControllerPipeHost(server_factory=Server, stop_requested=lambda: False).serve_forever()
