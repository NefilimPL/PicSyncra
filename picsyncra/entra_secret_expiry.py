"""Read a Microsoft Entra application secret expiry without exposing credentials."""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone
from urllib.error import HTTPError

import requests

from picsyncra.redaction import sanitize_free_text

try:
    import msal
except ImportError:  # pragma: no cover - exercised through the dependency seam
    msal = None


_GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_REQUEST_TIMEOUT_SECONDS = 20
_SAFE_FIELDS = (
    "status",
    "code",
    "expires_at",
    "remaining_seconds",
    "remaining_days",
    "application_name",
    "credential_name",
    "credential_key_id",
    "source",
    "error_message",
)
_ERROR_MESSAGES = {
    "malformed_settings": "Ustaw poprawne dane Microsoft Entra.",
    "authentication_failed": "Nie można uwierzytelnić aplikacji w Microsoft Entra.",
    "permission_required": (
        "Dodaj Microsoft Graph Application.Read.All i zatwierdź admin consent."
    ),
    "application_not_found": "Nie znaleziono aplikacji Entra dla podanego Client ID.",
    "credential_not_found": "Nie znaleziono aktywnego Client Secret w aplikacji Entra.",
    "credential_ambiguous": "Nie można jednoznacznie dopasować aktywnego Client Secret.",
    "transport_unavailable": "Nie można teraz połączyć się z Microsoft Graph.",
    "invalid_response": "Microsoft Graph zwrócił nieprawidłowe dane aplikacji.",
}


class _InvalidResponse(Exception):
    pass


class _TransportUnavailable(Exception):
    pass


class _TimeoutHttpClient:
    """MSAL transport adapter that forces a bounded timeout on token requests."""

    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        self._session = requests.Session()

    def get(self, *args, **kwargs):
        kwargs["timeout"] = self.timeout_seconds
        return self._session.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        kwargs["timeout"] = self.timeout_seconds
        return self._session.post(*args, **kwargs)


def fetch_entra_secret_expiry(
    settings: Mapping[str, object],
    *,
    now: datetime | None = None,
    opener=urllib.request.urlopen,
) -> dict[str, object]:
    """Return a safe, selected Entra client-secret expiry status."""

    normalized = _normalized_settings(settings)
    if normalized is None:
        return _result("malformed_settings")
    tenant_id, client_id, client_secret = normalized
    checked_at = _utc_now(now)

    access_token = _access_token(tenant_id, client_id, client_secret)
    if not access_token:
        return _result("authentication_failed")

    try:
        application = _read_application(client_id, access_token, opener)
    except HTTPError as error:
        return _result(_http_error_code(error.code))
    except _TransportUnavailable:
        return _result("transport_unavailable")
    except _ApplicationNotFound:
        return _result("application_not_found")
    except _InvalidResponse:
        return _result("invalid_response")

    try:
        selected = _select_credential(
            application, client_secret, access_token, checked_at
        )
    except _InvalidResponse:
        return _result("invalid_response")

    if selected is None:
        return _result("credential_not_found")
    if selected == "ambiguous":
        return _result("credential_ambiguous")

    expires_at, credential_name, credential_key_id = selected
    remaining = (expires_at - checked_at).total_seconds()
    return {
        "status": "ok",
        "code": "ok",
        "expires_at": _canonical_timestamp(expires_at),
        "remaining_seconds": math.floor(remaining),
        "remaining_days": math.ceil(remaining / 86_400),
        "application_name": _safe_graph_text(
            application.get("displayName"), client_secret, access_token
        ),
        "credential_name": credential_name,
        "credential_key_id": credential_key_id,
        "source": "microsoft_graph",
        "error_message": "",
    }


def _normalized_settings(
    settings: Mapping[str, object],
) -> tuple[str, str, str] | None:
    if not isinstance(settings, Mapping):
        return None
    values = tuple(
        value.strip() if isinstance(value, str) else ""
        for value in (
            settings.get("tenant_id"),
            settings.get("client_id"),
            settings.get("client_secret"),
        )
    )
    if not all(values):
        return None
    return values


def _utc_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise TypeError("now must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _access_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    if msal is None:
        return ""
    try:
        application = msal.ConfidentialClientApplication(
            client_id,
            authority="https://login.microsoftonline.com/" + tenant_id,
            client_credential=client_secret,
            http_client=_TimeoutHttpClient(_REQUEST_TIMEOUT_SECONDS),
        )
        token_result = application.acquire_token_for_client([_GRAPH_SCOPE])
    except Exception:
        return ""
    if not isinstance(token_result, Mapping):
        return ""
    token = token_result.get("access_token")
    return token.strip() if isinstance(token, str) else ""


def _read_application(
    client_id: str,
    access_token: str,
    opener,
) -> Mapping[str, object]:
    try:
        return _request_application(
            _primary_url(client_id), client_id, access_token, opener
        )
    except HTTPError as error:
        if error.code not in {400, 404}:
            raise
    try:
        payload = _request_json(_filtered_url(client_id), access_token, opener)
    except HTTPError as error:
        if error.code == 404:
            raise _ApplicationNotFound from None
        raise
    return _filtered_application(payload, client_id)


def _request_application(
    url: str, client_id: str, access_token: str, opener
) -> Mapping[str, object]:
    payload = _request_json(url, access_token, opener)
    return _application_payload(payload, client_id)


def _request_json(url: str, access_token: str, opener) -> object:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    response = None
    try:
        response = opener(request, timeout=_REQUEST_TIMEOUT_SECONDS)
        raw_payload = response.read()
    except HTTPError:
        raise
    except Exception:
        raise _TransportUnavailable from None
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
    if not isinstance(raw_payload, bytes):
        raise _InvalidResponse
    try:
        return json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _InvalidResponse from None


def _primary_url(client_id: str) -> str:
    identifier = urllib.parse.quote(client_id.replace("'", "''"), safe="-._~")
    query = urllib.parse.urlencode(
        {"$select": "appId,displayName,passwordCredentials"}
    )
    return f"{_GRAPH_ROOT}/applications(appId='{identifier}')?{query}"


def _filtered_url(client_id: str) -> str:
    escaped = client_id.replace("'", "''")
    query = urllib.parse.urlencode(
        {
            "$filter": f"appId eq '{escaped}'",
            "$select": "appId,displayName,passwordCredentials",
        }
    )
    return f"{_GRAPH_ROOT}/applications?{query}"


def _filtered_application(payload: object, client_id: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise _InvalidResponse
    values = payload.get("value")
    if not isinstance(values, list):
        raise _InvalidResponse
    matching = [
        item
        for item in values
        if isinstance(item, Mapping) and item.get("appId") == client_id
    ]
    if not matching:
        raise _ApplicationNotFound
    if len(matching) != 1:
        raise _InvalidResponse
    return _application_payload(matching[0], client_id)


class _ApplicationNotFound(_InvalidResponse):
    pass


def _application_payload(
    payload: object, expected_client_id: str | None
) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise _InvalidResponse
    app_id = payload.get("appId")
    if not isinstance(app_id, str) or not app_id:
        raise _InvalidResponse
    if expected_client_id is not None and app_id != expected_client_id:
        raise _InvalidResponse
    if not isinstance(payload.get("passwordCredentials"), list):
        raise _InvalidResponse
    return payload


def _select_credential(
    application: Mapping[str, object],
    client_secret: str,
    access_token: str,
    now: datetime,
) -> tuple[datetime, str, str] | str | None:
    credentials = application["passwordCredentials"]
    if not isinstance(credentials, list):
        raise _InvalidResponse
    active: list[tuple[datetime, str, str, str]] = []
    expired: list[tuple[datetime, str, str, str]] = []
    for credential in credentials:
        if not isinstance(credential, Mapping):
            raise _InvalidResponse
        end_date = credential.get("endDateTime")
        key_id = credential.get("keyId")
        if not isinstance(end_date, str) or not isinstance(key_id, str) or not key_id:
            raise _InvalidResponse
        expires_at = _parse_timestamp(end_date)
        hint = credential.get("hint")
        name = credential.get("displayName")
        item = (
            expires_at,
            hint if isinstance(hint, str) else "",
            _safe_graph_text(name, client_secret, access_token),
            _safe_graph_text(key_id, client_secret, access_token),
        )
        if expires_at > now:
            active.append(item)
        else:
            expired.append(item)
    all_credentials = active + expired
    if not all_credentials:
        return None
    hint_matches = [
        item for item in all_credentials if item[1] == client_secret[:3]
    ]
    if hint_matches:
        candidates = hint_matches
    elif active:
        candidates = active
    else:
        candidates = expired
    if len(candidates) != 1:
        return "ambiguous"
    expires_at, _hint, name, key_id = candidates[0]
    return expires_at, name, key_id
def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _InvalidResponse from None
    if parsed.tzinfo is None:
        raise _InvalidResponse
    return parsed.astimezone(timezone.utc)


def _canonical_timestamp(value: datetime) -> str:
    milliseconds = value.microsecond // 1_000
    return value.strftime("%Y-%m-%dT%H:%M:%S") + f".{milliseconds:03d}Z"


def _safe_graph_text(value: object, *sensitive_values: str) -> str:
    if not isinstance(value, str):
        return ""
    text = value
    for sensitive_value in sensitive_values:
        if sensitive_value:
            text = text.replace(sensitive_value, "[REDACTED]")
    return sanitize_free_text(text, limit=512).strip()


def _http_error_code(status_code: object) -> str:
    if status_code in {401, 403}:
        return "permission_required"
    if status_code == 404:
        return "application_not_found"
    if status_code == 400:
        return "invalid_response"
    return "transport_unavailable"


def _result(code: str) -> dict[str, object]:
    return {
        "status": "unavailable",
        "code": code,
        "expires_at": "",
        "remaining_seconds": 0,
        "remaining_days": 0,
        "application_name": "",
        "credential_name": "",
        "credential_key_id": "",
        "source": "microsoft_graph",
        "error_message": _ERROR_MESSAGES[code],
    }
