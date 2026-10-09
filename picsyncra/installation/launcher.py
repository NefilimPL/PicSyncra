"""Safe client used by an installed user-session launcher to contact the controller."""

from __future__ import annotations

import json
import re
from typing import Protocol

from .control_pipe import NamedPipeControlClient
from .control_protocol import PROTOCOL_VERSION, validate_module_payload


_INSTALLATION_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?")
_PIPE_PREFIX = r"\\.\pipe\PicSyncra.Control."


class LauncherError(RuntimeError):
    """The installed controller could not confirm a launcher action."""


class PipeClient(Protocol):
    def request(self, message: bytes) -> dict[str, object]: ...


class InstallationControlClient:
    """Client for the fixed, local controller command set."""

    # The controller acknowledges the pipe request before it stops this WEB
    # process. It later commits the durable handoff after a health check.
    restart_is_deferred = True

    def __init__(
        self, installation_id: str, *, pipe_client: PipeClient | None = None
    ) -> None:
        if not isinstance(installation_id, str) or _INSTALLATION_ID.fullmatch(installation_id) is None:
            raise ValueError("installation_id is not safe for the controller pipe.")
        self._installation_id = installation_id
        self._pipe_client = pipe_client or NamedPipeControlClient(
            _PIPE_PREFIX + installation_id
        )

    def snapshot(self) -> dict[str, bool]:
        response = self._request("snapshot", {})
        snapshot = response.get("snapshot")
        if not isinstance(snapshot, dict):
            raise LauncherError("The controller returned an invalid snapshot.")
        return {
            "backend_running": bool(snapshot.get("backend_running", False)),
            "autostart": bool(snapshot.get("autostart", False)),
        }

    def start_backend(self) -> None:
        self._request("start_backend", {})

    def stop_backend(self, *, force: bool = False) -> bool:
        if not isinstance(force, bool):
            raise ValueError("force must be a boolean.")
        response = self._request("stop_backend", {"force": force}, require_ok=False)
        return bool(response["ok"])

    def restart_backend(self) -> bool:
        """Request the controller to restart its own backend service."""
        response = self._request("restart_backend", {}, require_ok=False)
        return bool(response["ok"])

    def set_autostart(self, enabled: bool) -> bool:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean.")
        response = self._request("set_autostart", {"enabled": enabled})
        value = response.get("autostart")
        if not isinstance(value, bool):
            raise LauncherError("The controller did not confirm the autostart state.")
        return value

    def _request(
        self,
        command: str,
        payload: dict[str, object],
        *,
        require_ok: bool = True,
    ) -> dict[str, object]:
        response = self._pipe_client.request(
            json.dumps(
                {
                    "version": PROTOCOL_VERSION,
                    "installation_id": self._installation_id,
                    "command": command,
                    "payload": payload,
                },
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
            raise LauncherError("The controller returned an invalid response.")
        if require_ok and not response["ok"]:
            raise LauncherError(str(response.get('error') or "The controller could not perform the requested action."))
        return response

    def module_catalog(self):
        return self._module_request('module_catalog', {})

    def module_recover(self):
        return self._module_request('module_recover', {})

    def module_channel(self, channel):
        return self._module_request('module_channel', dict(channel=channel))

    def module_plan(self, *, action, selected, excluded, restore_backup_id=None):
        return self._module_request('module_plan', dict(action=action, selected=selected, excluded=excluded, restore_backup_id=restore_backup_id))

    def module_execute(self, plan_id, *, restore_backup_id=None, acknowledge_data_loss=False):
        return self._module_request('module_execute', dict(plan_id=plan_id, restore_backup_id=restore_backup_id, acknowledge_data_loss=acknowledge_data_loss))

    def module_operation(self, operation_id):
        return self._module_request('module_operation', dict(operation_id=operation_id))

    def _module_request(self, command, payload):
        validate_module_payload(command, payload)
        return self._request(command, payload)['result']


__all__ = ["InstallationControlClient", "LauncherError", "PipeClient"]
