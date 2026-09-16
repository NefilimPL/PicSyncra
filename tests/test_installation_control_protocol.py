"""The installed controller accepts only its authenticated, closed protocol."""

from __future__ import annotations

import json

import pytest

from picsyncra.installation.control_protocol import (
    MAX_MESSAGE_BYTES,
    ControlDispatcher,
    ControlProtocolError,
    parse_control_request,
)


def _message(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "version": 1,
        "installation_id": "primary-installation",
        "command": "snapshot",
        "payload": {},
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def test_protocol_accepts_an_authenticated_snapshot_for_its_installation() -> None:
    """Catches accepting a request without both pipe identity and install identity."""

    request = parse_control_request(
        _message(),
        installation_id="primary-installation",
        peer_identity="S-1-5-21-1000",
        authorized_identities={"S-1-5-21-1000"},
    )

    assert request.command == "snapshot"
    assert request.payload == {}


@pytest.mark.parametrize(
    ("message", "peer_identity"),
    [
        (_message(installation_id="other-installation"), "S-1-5-21-1000"),
        (_message(command="powershell", payload={"command": "whoami"}), "S-1-5-21-1000"),
        (_message(payload={"url": "https://example.invalid/package.zip"}), "S-1-5-21-1000"),
        (_message(payload={"path": r"C:\\Windows\\System32\\cmd.exe"}), "S-1-5-21-1000"),
        (_message(version=2), "S-1-5-21-1000"),
        (_message(extra="not part of the protocol"), "S-1-5-21-1000"),
        (_message(), "S-1-5-21-9999"),
    ],
)
def test_protocol_rejects_unauthorized_or_open_ended_requests(
    message: bytes, peer_identity: str
) -> None:
    """Catches turning the private controller pipe into a generic command channel."""

    with pytest.raises(ControlProtocolError):
        parse_control_request(
            message,
            installation_id="primary-installation",
            peer_identity=peer_identity,
            authorized_identities={"S-1-5-21-1000"},
        )


def test_protocol_rejects_messages_larger_than_its_framing_limit() -> None:
    """Catches an unbounded pipe message exhausting the controller process."""

    with pytest.raises(ControlProtocolError):
        parse_control_request(
            b"{" + (b" " * MAX_MESSAGE_BYTES) + b"}",
            installation_id="primary-installation",
            peer_identity="S-1-5-21-1000",
            authorized_identities={"S-1-5-21-1000"},
        )


def test_dispatcher_exposes_only_a_confirmed_controller_result() -> None:
    """Catches a pipe handler leaking controller internals or accepting dynamic calls."""

    calls: list[tuple[str, object]] = []

    class FakeController:
        def snapshot(self) -> dict[str, object]:
            calls.append(("snapshot", None))
            return {"backend_running": True, "program_root": r"C:\\private"}

        def start_backend(self) -> None:
            calls.append(("start_backend", None))

        def stop_backend(self, force: bool) -> bool:
            calls.append(("stop_backend", force))
            return True

        def set_autostart(self, enabled: bool) -> bool:
            calls.append(("set_autostart", enabled))
            return True

    dispatcher = ControlDispatcher(
        FakeController(),
        installation_id="primary-installation",
        authorized_identities={"S-1-5-21-1000"},
    )

    response = dispatcher.dispatch(
        _message(command="set_autostart", payload={"enabled": True}),
        peer_identity="S-1-5-21-1000",
    )

    assert response == {"ok": True, "autostart": True}
    assert calls == [("set_autostart", True)]


def test_dispatcher_drops_private_fields_from_a_snapshot() -> None:
    """Catches exposing program paths through the otherwise local control response."""

    class FakeController:
        def snapshot(self) -> dict[str, object]:
            return {
                "installation_id": "primary-installation",
                "backend_port": 8010,
                "backend_running": True,
                "autostart": False,
                "program_root": r"C:\\Program Files\\PicSyncra",
            }

    dispatcher = ControlDispatcher(
        FakeController(),
        installation_id="primary-installation",
        authorized_identities={"S-1-5-21-1000"},
    )

    response = dispatcher.dispatch(_message(), peer_identity="S-1-5-21-1000")

    assert response == {
        "ok": True,
        "snapshot": {"backend_running": True, "autostart": False},
    }


def test_dispatcher_allows_only_the_closed_restart_backend_action() -> None:
    class FakeController:
        def restart_backend(self) -> bool:
            return True

    dispatcher = ControlDispatcher(
        FakeController(),
        installation_id="primary-installation",
        authorized_identities={"S-1-5-21-1000"},
    )

    response = dispatcher.dispatch(
        _message(command="restart_backend", payload={}),
        peer_identity="S-1-5-21-1000",
    )

    assert response == {"ok": True}
