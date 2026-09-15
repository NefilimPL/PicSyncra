"""The controller pipe uses both its ACL and protocol identity check."""

from __future__ import annotations

import json
import threading

import win32api
import win32con
import win32security

from picsyncra.installation.control_pipe import (
    NamedPipeControlClient,
    NamedPipeControlServer,
)
from picsyncra.installation.control_protocol import ControlDispatcher


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
