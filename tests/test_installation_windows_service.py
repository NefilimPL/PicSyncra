"""The SCM adapter reports actual Windows service state to the controller."""

from __future__ import annotations

from picsyncra.installation.windows_service import WindowsServiceAdapter


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
