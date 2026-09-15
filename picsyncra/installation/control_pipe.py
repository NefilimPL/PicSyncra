"""Authenticated local named-pipe transport for the installed controller."""

from __future__ import annotations

import json
import re
from typing import Any
import winerror

from .control_protocol import ControlDispatcher, ControlProtocolError, MAX_MESSAGE_BYTES


_INSTALLATION_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?")
_SID = re.compile(r"S-1-(?:\d+-)*\d+", re.IGNORECASE)
_PIPE_PREFIX = r"\\.\pipe\PicSyncra.Control."
_RESPONSE_BYTES = 1024


class ControlPipeError(RuntimeError):
    """The local controller pipe could not exchange a complete request."""


def _windows_modules() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import win32api
        import win32con
        import win32file
        import win32pipe
        import win32security
    except ImportError as exc:  # pragma: no cover - requires installed Windows build
        raise ControlPipeError("pywin32 is required for the controller pipe.") from exc
    return win32api, win32con, win32file, win32pipe, win32security


def _validate_installation_id(installation_id: str) -> str:
    if not isinstance(installation_id, str) or _INSTALLATION_ID.fullmatch(installation_id) is None:
        raise ValueError("installation_id is not safe for a pipe name.")
    return installation_id


def _validate_sids(allowed_sids: frozenset[str] | set[str]) -> tuple[str, ...]:
    values = tuple(sorted(set(allowed_sids)))
    if not values or any(not isinstance(sid, str) or _SID.fullmatch(sid) is None for sid in values):
        raise ValueError("allowed_sids must contain Windows SID strings.")
    return values


class NamedPipeControlServer:
    """One-message server with ACL and caller-SID verification for a controller."""

    def __init__(
        self,
        dispatcher: ControlDispatcher,
        *,
        installation_id: str,
        allowed_sids: frozenset[str] | set[str],
    ) -> None:
        self._dispatcher = dispatcher
        self._installation_id = _validate_installation_id(installation_id)
        self._allowed_sids = _validate_sids(allowed_sids)
        self._handle: Any | None = None

    @property
    def pipe_name(self) -> str:
        return _PIPE_PREFIX + self._installation_id

    def __enter__(self) -> "NamedPipeControlServer":
        if self._handle is not None:
            raise ControlPipeError("The controller pipe is already open.")
        _win32api, _win32con, _win32file, win32pipe, win32security = _windows_modules()
        descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            self._security_descriptor(), win32security.SDDL_REVISION_1
        )
        attributes = win32security.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = descriptor
        self._handle = win32pipe.CreateNamedPipe(
            self.pipe_name,
            win32pipe.PIPE_ACCESS_DUPLEX | win32pipe.FILE_FLAG_FIRST_PIPE_INSTANCE,
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
            1,
            _RESPONSE_BYTES,
            MAX_MESSAGE_BYTES + 1,
            5_000,
            attributes,
        )
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        if self._handle is None:
            return
        _win32api, _win32con, win32file, win32pipe, _win32security = _windows_modules()
        try:
            win32pipe.DisconnectNamedPipe(self._handle)
        except Exception:
            pass
        finally:
            win32file.CloseHandle(self._handle)
            self._handle = None

    def serve_once(self) -> None:
        """Serve one fully framed client request and then return."""

        if self._handle is None:
            raise ControlPipeError("Open the controller pipe before serving requests.")
        _win32api, _win32con, win32file, win32pipe, _win32security = _windows_modules()
        try:
            win32pipe.ConnectNamedPipe(self._handle, None)
        except Exception as exc:
            if getattr(exc, "winerror", None) != winerror.ERROR_PIPE_CONNECTED:
                raise ControlPipeError("The controller pipe could not accept a client.") from exc
        response: dict[str, object]
        try:
            error_code, message = win32file.ReadFile(self._handle, MAX_MESSAGE_BYTES + 1)
            if error_code == winerror.ERROR_MORE_DATA or len(message) > MAX_MESSAGE_BYTES:
                raise ControlProtocolError("The controller request is too large.")
            if error_code:
                raise ControlProtocolError("The controller request could not be read.")
            response = self._dispatcher.dispatch(
                message, peer_identity=self._client_sid(win32pipe)
            )
        except (ControlProtocolError, ControlPipeError, ValueError):
            response = {"ok": False, "error": "invalid_request"}
        except Exception:
            response = {"ok": False, "error": "controller_unavailable"}
        encoded = json.dumps(response, separators=(",", ":")).encode("utf-8")
        win32file.WriteFile(self._handle, encoded)

    def _client_sid(self, win32pipe: Any) -> str:
        win32api, win32con, _win32file, _win32pipe, win32security = _windows_modules()
        process_id = win32pipe.GetNamedPipeClientProcessId(self._handle)
        process = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, process_id
        )
        try:
            token = win32security.OpenProcessToken(process, win32con.TOKEN_QUERY)
            try:
                sid, _attributes = win32security.GetTokenInformation(
                    token, win32security.TokenUser
                )
                return win32security.ConvertSidToStringSid(sid)
            finally:
                token.Close()
        finally:
            process.Close()

    def _security_descriptor(self) -> str:
        # SYSTEM owns the controller; each approved client SID receives only
        # read/write access.  No default Everyone or Anonymous ACE is retained.
        entries = ["(A;;GA;;;SY)"]
        entries.extend(f"(A;;GRGW;;;{sid})" for sid in self._allowed_sids if sid.upper() != "S-1-5-18")
        return "D:P" + "".join(entries)


class NamedPipeControlClient:
    """Request one bounded response from a private installed-controller pipe."""

    def __init__(self, pipe_name: str) -> None:
        if not isinstance(pipe_name, str) or not pipe_name.startswith(_PIPE_PREFIX):
            raise ValueError("pipe_name is not a PicSyncra controller pipe.")
        self._pipe_name = pipe_name

    def request(self, message: bytes) -> dict[str, object]:
        if not isinstance(message, bytes) or len(message) > MAX_MESSAGE_BYTES:
            raise ControlPipeError("The controller request is too large.")
        _win32api, win32con, win32file, win32pipe, _win32security = _windows_modules()
        try:
            handle = win32file.CreateFile(
                self._pipe_name,
                win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                0,
                None,
                win32con.OPEN_EXISTING,
                0,
                None,
            )
        except Exception as exc:
            raise ControlPipeError("The controller pipe is unavailable.") from exc
        try:
            win32pipe.SetNamedPipeHandleState(
                handle, win32pipe.PIPE_READMODE_MESSAGE, None, None
            )
            win32file.WriteFile(handle, message)
            error_code, response = win32file.ReadFile(handle, _RESPONSE_BYTES)
            if error_code or len(response) > _RESPONSE_BYTES:
                raise ControlPipeError("The controller response is invalid.")
            decoded = json.loads(response.decode("utf-8"))
            if not isinstance(decoded, dict) or not isinstance(decoded.get("ok"), bool):
                raise ControlPipeError("The controller response has an invalid schema.")
            return decoded
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ControlPipeError("The controller response is not valid JSON.") from exc
        finally:
            win32file.CloseHandle(handle)


__all__ = [
    "ControlPipeError",
    "NamedPipeControlClient",
    "NamedPipeControlServer",
]
