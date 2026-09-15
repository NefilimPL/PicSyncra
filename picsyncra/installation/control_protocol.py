"""Closed request schema for the private installed-controller pipe.

The named-pipe transport authenticates its peer before it calls this parser.
This module deliberately accepts neither commands, URLs nor paths supplied by
the caller: a request can only select one of the controller's fixed actions.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping, Protocol


PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 8 * 1024


class ControlProtocolError(ValueError):
    """The controller received an unauthorised or malformed pipe request."""


@dataclass(frozen=True)
class ControlRequest:
    """A request whose command and payload have been validated."""

    command: str
    payload: Mapping[str, bool]


class ControllerCommands(Protocol):
    """The fixed controller methods which may be invoked from the pipe."""

    def snapshot(self) -> dict[str, object]: ...

    def start_backend(self) -> None: ...

    def stop_backend(self, force: bool) -> bool: ...

    def set_autostart(self, enabled: bool) -> bool: ...


_COMMAND_PAYLOADS: dict[str, frozenset[str]] = {
    "snapshot": frozenset(),
    "start_backend": frozenset(),
    "stop_backend": frozenset({"force"}),
    "set_autostart": frozenset({"enabled"}),
}


def _reject(message: str) -> None:
    raise ControlProtocolError(message)


def parse_control_request(
    message: bytes,
    *,
    installation_id: str,
    peer_identity: str,
    authorized_identities: frozenset[str] | set[str],
) -> ControlRequest:
    """Validate a complete pipe message for one registered installation."""

    if not isinstance(message, bytes) or len(message) > MAX_MESSAGE_BYTES:
        _reject("Invalid controller message size.")
    if not isinstance(peer_identity, str) or peer_identity not in authorized_identities:
        _reject("The pipe caller is not authorised.")
    try:
        payload = json.loads(message.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _reject("The controller message is not valid JSON.")
    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "installation_id",
        "command",
        "payload",
    }:
        _reject("The controller message has an invalid schema.")
    if payload["version"] != PROTOCOL_VERSION:
        _reject("Unsupported controller protocol version.")
    if payload["installation_id"] != installation_id:
        _reject("The request targets another installation.")
    command = payload["command"]
    request_payload = payload["payload"]
    if not isinstance(command, str) or command not in _COMMAND_PAYLOADS:
        _reject("Unsupported controller command.")
    if not isinstance(request_payload, dict):
        _reject("The controller command payload must be an object.")
    required_keys = _COMMAND_PAYLOADS[command]
    if set(request_payload) != required_keys or any(
        not isinstance(value, bool) for value in request_payload.values()
    ):
        _reject("The controller command payload is invalid.")
    return ControlRequest(command=command, payload=dict(request_payload))


class ControlDispatcher:
    """Dispatch already-authenticated pipe messages to the closed controller API."""

    def __init__(
        self,
        controller: ControllerCommands,
        *,
        installation_id: str,
        authorized_identities: frozenset[str] | set[str],
    ) -> None:
        self._controller = controller
        self._installation_id = installation_id
        self._authorized_identities = frozenset(authorized_identities)

    def dispatch(self, message: bytes, *, peer_identity: str) -> dict[str, object]:
        """Return a small response for one valid command, never exception details."""

        request = parse_control_request(
            message,
            installation_id=self._installation_id,
            peer_identity=peer_identity,
            authorized_identities=self._authorized_identities,
        )
        if request.command == "snapshot":
            snapshot = self._controller.snapshot()
            return {
                "ok": True,
                "snapshot": {
                    "backend_running": bool(snapshot.get("backend_running", False)),
                    "autostart": bool(snapshot.get("autostart", False)),
                },
            }
        if request.command == "start_backend":
            self._controller.start_backend()
            return {"ok": True}
        if request.command == "stop_backend":
            return {"ok": self._controller.stop_backend(request.payload["force"])}
        if request.command == "set_autostart":
            return {
                "ok": True,
                "autostart": self._controller.set_autostart(
                    request.payload["enabled"]
                ),
            }
        raise AssertionError("Validated controller command was not dispatched.")


__all__ = [
    "ControlProtocolError",
    "ControlRequest",
    "ControlDispatcher",
    "ControllerCommands",
    "MAX_MESSAGE_BYTES",
    "PROTOCOL_VERSION",
    "parse_control_request",
]
