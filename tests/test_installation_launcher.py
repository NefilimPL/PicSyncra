"""The installed launcher can only send controller protocol commands."""

from __future__ import annotations

import json

from picsyncra.installation.launcher import InstallationControlClient


class FakePipeClient:
    def __init__(self) -> None:
        self.messages: list[bytes] = []

    def request(self, message: bytes) -> dict[str, object]:
        self.messages.append(message)
        return {"ok": True, "autostart": True}


def test_launcher_serializes_autostart_as_a_closed_controller_request() -> None:
    """Catches a launcher adding arbitrary process parameters to pipe messages."""

    pipe = FakePipeClient()
    client = InstallationControlClient("primary-installation", pipe_client=pipe)

    assert client.set_autostart(True) is True

    assert [json.loads(message) for message in pipe.messages] == [
        {
            "version": 1,
            "installation_id": "primary-installation",
            "command": "set_autostart",
            "payload": {"enabled": True},
        }
    ]


def test_launcher_serializes_remote_restart_without_any_process_arguments() -> None:
    pipe = FakePipeClient()
    client = InstallationControlClient("primary-installation", pipe_client=pipe)

    assert client.restart_backend() is True

    assert json.loads(pipe.messages[0]) == {
        "version": 1,
        "installation_id": "primary-installation",
        "command": "restart_backend",
        "payload": {},
    }
