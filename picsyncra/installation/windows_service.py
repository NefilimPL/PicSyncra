"""Windows SCM adapter for the backend registered by an installed PicSyncra."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Protocol


class ServiceApi(Protocol):
    """Small SCM boundary that can be exercised without changing a service."""

    def start(self, service_name: str) -> None: ...

    def stop(self, service_name: str, *, force: bool) -> bool: ...

    def set_autostart(self, service_name: str, enabled: bool) -> bool: ...

    def snapshot(self, service_name: str) -> dict[str, bool]: ...


class Pywin32ServiceApi:
    """SCM implementation backed by pywin32, imported only in installed runtime."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        try:
            import win32service
            import win32serviceutil
        except ImportError as exc:  # pragma: no cover - requires installed build
            raise RuntimeError("pywin32 is required for installed Windows services.") from exc
        self._win32service = win32service
        self._win32serviceutil = win32serviceutil
        self._timeout_seconds = timeout_seconds

    def start(self, service_name: str) -> None:  # pragma: no cover - privileged SCM
        status = self._win32serviceutil.QueryServiceStatus(service_name)
        if status[1] != self._win32service.SERVICE_RUNNING:
            self._win32serviceutil.StartService(service_name)

    def stop(self, service_name: str, *, force: bool) -> bool:  # pragma: no cover - privileged SCM
        del force  # SCM stop applies only to this registered service, never taskkill.
        status = self._win32serviceutil.QueryServiceStatus(service_name)
        if status[1] == self._win32service.SERVICE_STOPPED:
            return True
        self._win32serviceutil.StopService(service_name)
        deadline = time.monotonic() + self._timeout_seconds
        while time.monotonic() < deadline:
            status = self._win32serviceutil.QueryServiceStatus(service_name)
            if status[1] == self._win32service.SERVICE_STOPPED:
                return True
            time.sleep(0.25)
        return False

    def set_autostart(self, service_name: str, enabled: bool) -> bool:  # pragma: no cover - privileged SCM
        service = self._open_service(
            service_name,
            self._win32service.SERVICE_CHANGE_CONFIG | self._win32service.SERVICE_QUERY_CONFIG,
        )
        try:
            self._win32service.ChangeServiceConfig(
                service,
                self._win32service.SERVICE_NO_CHANGE,
                self._win32service.SERVICE_AUTO_START
                if enabled
                else self._win32service.SERVICE_DEMAND_START,
                self._win32service.SERVICE_NO_CHANGE,
                None,
                None,
                0,
                None,
                None,
                None,
                None,
            )
        finally:
            self._win32service.CloseServiceHandle(service)
        return self.snapshot(service_name)["autostart"] is enabled

    def snapshot(self, service_name: str) -> dict[str, bool]:  # pragma: no cover - privileged SCM
        service = self._open_service(service_name, self._win32service.SERVICE_QUERY_CONFIG)
        try:
            config = self._win32service.QueryServiceConfig(service)
        finally:
            self._win32service.CloseServiceHandle(service)
        status = self._win32serviceutil.QueryServiceStatus(service_name)
        return {
            "backend_running": status[1] == self._win32service.SERVICE_RUNNING,
            "autostart": config[1] == self._win32service.SERVICE_AUTO_START,
        }

    def _open_service(self, service_name: str, access: int):  # pragma: no cover - privileged SCM
        manager = self._win32service.OpenSCManager(
            None, None, self._win32service.SC_MANAGER_CONNECT
        )
        try:
            return self._win32service.OpenService(manager, service_name, access)
        finally:
            self._win32service.CloseServiceHandle(manager)


class WindowsServiceAdapter:
    """Connect :class:`InstallationController` to one explicitly named service."""

    def __init__(
        self,
        service_name: str,
        *,
        service_api: ServiceApi | None = None,
        listener_owner: Callable[[int], str | None],
    ) -> None:
        if not isinstance(service_name, str) or not service_name.strip():
            raise ValueError("service_name must be a non-empty string.")
        self._service_name = service_name
        self._service_api = service_api if service_api is not None else Pywin32ServiceApi()
        self._listener_owner = listener_owner

    def listener_owner(self, port: int) -> str | None:
        return self._listener_owner(port)

    def start_backend(self) -> None:
        self._service_api.start(self._service_name)

    def stop_backend(self, *, force: bool) -> bool:
        return self._service_api.stop(self._service_name, force=force)

    def set_autostart(self, enabled: bool) -> bool:
        return self._service_api.set_autostart(self._service_name, enabled)

    def snapshot(self) -> dict[str, object]:
        return dict(self._service_api.snapshot(self._service_name))


__all__ = ["Pywin32ServiceApi", "ServiceApi", "WindowsServiceAdapter"]
