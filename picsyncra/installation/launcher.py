"""Safe client used by an installed user-session launcher to contact the controller."""

from __future__ import annotations

import json
import re
from typing import Protocol

from .control_pipe import NamedPipeControlClient
from .control_protocol import PROTOCOL_VERSION


_INSTALLATION_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?")
_PIPE_PREFIX = r"\\.\pipe\PicSyncra.Control."


class LauncherError(RuntimeError):
    """The installed controller could not confirm a launcher action."""


class PipeClient(Protocol):
    def request(self, message: bytes) -> dict[str, object]: ...


class InstallationControlClient:
    """Client for the fixed, local controller command set."""

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
        payload: dict[str, bool],
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
            raise LauncherError("The controller could not perform the requested action.")
        return response


__all__ = ["InstallationControlClient", "LauncherError", "PipeClient"]
