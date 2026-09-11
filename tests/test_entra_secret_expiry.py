import json
from datetime import datetime, timezone
from urllib.error import HTTPError

import pytest

import picsyncra.entra_secret_expiry as expiry


NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)
SAFE_FIELDS = {
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
}


class _Response:
    status = 200

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")
        self.closed = False

    def read(self):
        return self._payload

    def close(self):
        self.closed = True


class _MsalApplication:
    def __init__(self, client_id, authority, client_credential, http_client=None):
        self.client_id = client_id
        self.authority = authority
        self.client_credential = client_credential
        self.http_client = http_client

    def acquire_token_for_client(self, scopes):
        assert scopes == ["https://graph.microsoft.com/.default"]
        return {"access_token": "access-token-sentinel"}


class _Msal:
    ConfidentialClientApplication = _MsalApplication


def _settings(secret="abc-sensitive-secret"):
    return {
        "tenant_id": "tenant-id",
        "client_id": "client-id",
        "client_secret": secret,
    }


def _credential(*, hint="abc", end="2026-08-01T00:00:00Z", key="key-1", name="Current"):
    return {
        "hint": hint,
        "displayName": name,
        "keyId": key,
        "endDateTime": end,
    }


def _graph_opener(payload, requests=None):
    def opener(request, timeout):
        assert timeout == 20
        if requests is not None:
            requests.append(request)
        return _Response(payload)

    return opener


@pytest.fixture(autouse=True)
def _fake_msal(monkeypatch):
    monkeypatch.setattr(expiry, "msal", _Msal)


def test_fetch_selects_unique_hint_matching_active_secret_and_requests_minimum_fields():
    requests = []
    result = expiry.fetch_entra_secret_expiry(
        _settings(),
        now=NOW,
        opener=_graph_opener(
            {
                "appId": "client-id",
                "displayName": "Example application",
                "passwordCredentials": [
                    _credential(end="2026-08-01T00:00:00Z"),
                    _credential(hint="old", end="2026-12-01T00:00:00Z", key="key-old"),
                ],
            },
            requests,
        ),
    )

    assert set(result) == SAFE_FIELDS
    assert result == {
        "status": "ok",
        "code": "ok",
        "expires_at": "2026-08-01T00:00:00.000Z",
        "remaining_seconds": 1_036_800,
        "remaining_days": 12,
        "application_name": "Example application",
        "credential_name": "Current",
        "credential_key_id": "key-1",
        "source": "microsoft_graph",
        "error_message": "",
    }
    assert len(requests) == 1
    assert "/v1.0/applications(appId='client-id')" in requests[0].full_url
    assert "%24select=appId%2CdisplayName%2CpasswordCredentials" in requests[0].full_url


def test_fetch_supplies_a_timeout_bound_http_client_to_msal(monkeypatch):
    clients = []

    class MsalApplication:
        def __init__(self, *_args, http_client=None, **_kwargs):
            clients.append(http_client)

        def acquire_token_for_client(self, _scopes):
            return {"access_token": "safe-access-token"}

    class Msal:
        ConfidentialClientApplication = MsalApplication

    monkeypatch.setattr(expiry, "msal", Msal)
    result = expiry.fetch_entra_secret_expiry(
        _settings(),
        now=NOW,
        opener=_graph_opener({"appId": "client-id", "passwordCredentials": [_credential()]}),
    )

    assert result["status"] == "ok"
    assert len(clients) == 1
    assert clients[0].timeout_seconds == 20


def test_fetch_uses_the_only_active_credential_when_no_hint_matches():
    result = expiry.fetch_entra_secret_expiry(
        _settings("zzz-secret"),
        now=NOW,
        opener=_graph_opener(
            {
                "appId": "client-id",
                "displayName": "Example application",
                "passwordCredentials": [
                    _credential(hint="abc", end="2026-07-01T00:00:00Z", key="expired"),
                    _credential(hint="not", end="2026-08-01T00:00:00Z", key="key-2", name="Only active"),
                ],
            }
        ),
    )

    assert result["status"] == "ok"
    assert result["credential_name"] == "Only active"
    assert result["credential_key_id"] == "key-2"


def test_fetch_refuses_ambiguous_active_credentials_without_selecting_latest_expiry():
    result = expiry.fetch_entra_secret_expiry(
        _settings("zzz-secret"),
        now=NOW,
        opener=_graph_opener(
            {
                "appId": "client-id",
                "displayName": "Example application",
                "passwordCredentials": [
                    _credential(hint="one", end="2026-08-01T00:00:00Z", key="key-1"),
                    _credential(hint="two", end="2027-01-01T00:00:00Z", key="key-2"),
                ],
            }
        ),
    )

    assert result["status"] == "unavailable"
    assert result["code"] == "credential_ambiguous"
    assert result["expires_at"] == ""
    assert result["credential_key_id"] == ""


def test_fetch_returns_uniquely_matched_expired_credential_with_negative_remaining_time():
    result = expiry.fetch_entra_secret_expiry(
        _settings(),
        now=NOW,
        opener=_graph_opener(
            {
                "appId": "client-id",
                "passwordCredentials": [
                    _credential(end="2026-07-19T00:00:00Z", key="expired-key"),
                    _credential(hint="old", end="2026-08-01T00:00:00Z", key="other-active-key"),
                ],
            }
        ),
    )

    assert result["status"] == "ok"
    assert result["credential_key_id"] == "expired-key"
    assert result["expires_at"] == "2026-07-19T00:00:00.000Z"
    assert result["remaining_seconds"] < 0
    assert result["remaining_days"] < 0


def test_fetch_refuses_ambiguous_expired_credentials_without_selecting_one():
    result = expiry.fetch_entra_secret_expiry(
        _settings("zzz-secret"),
        now=NOW,
        opener=_graph_opener(
            {
                "appId": "client-id",
                "passwordCredentials": [
                    _credential(hint="one", end="2026-07-19T00:00:00Z", key="expired-one"),
                    _credential(hint="two", end="2026-07-18T00:00:00Z", key="expired-two"),
                ],
            }
        ),
    )

    assert result["status"] == "unavailable"
    assert result["code"] == "credential_ambiguous"


def test_fetch_maps_graph_forbidden_to_permission_required_without_raw_response():
    error = HTTPError(
        "https://graph.microsoft.com/v1.0/applications",
        403,
        "authorization=access-token-sentinel",
        {},
        None,
    )

    def opener(_request, timeout):
        assert timeout == 20
        raise error

    result = expiry.fetch_entra_secret_expiry(_settings(), now=NOW, opener=opener)

    assert result["status"] == "unavailable"
    assert result["code"] == "permission_required"
    assert "Application.Read.All" in result["error_message"]
    assert "admin consent" in result["error_message"]
    assert "access-token-sentinel" not in json.dumps(result)


def test_fetch_uses_filtered_fallback_after_primary_app_not_found():
    requests = []
    responses = [
        HTTPError("https://graph.microsoft.com/v1.0/applications", 404, "not found", {}, None),
        _Response(
            {
                "value": [
                    {
                        "appId": "client-id",
                        "displayName": "Fallback application",
                        "passwordCredentials": [_credential()],
                    }
                ]
            }
        ),
    ]

    def opener(request, timeout):
        assert timeout == 20
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    result = expiry.fetch_entra_secret_expiry(_settings(), now=NOW, opener=opener)

    assert result["status"] == "ok"
    assert result["application_name"] == "Fallback application"
    assert len(requests) == 2
    assert "/v1.0/applications?" in requests[1].full_url
    assert "%24filter=appId+eq+%27client-id%27" in requests[1].full_url


def test_fetch_returns_application_not_found_when_filtered_fallback_is_empty():
    responses = [
        HTTPError("https://graph.microsoft.com/v1.0/applications", 404, "not found", {}, None),
        _Response({"value": []}),
    ]

    def opener(_request, timeout):
        assert timeout == 20
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    result = expiry.fetch_entra_secret_expiry(_settings(), now=NOW, opener=opener)

    assert result["status"] == "unavailable"
    assert result["code"] == "application_not_found"


def test_fetch_returns_invalid_response_for_malformed_graph_payload():
    result = expiry.fetch_entra_secret_expiry(
        _settings(),
        now=NOW,
        opener=_graph_opener({"appId": "client-id", "passwordCredentials": "wrong"}),
    )

    assert result["status"] == "unavailable"
    assert result["code"] == "invalid_response"


def test_fetch_returns_invalid_response_when_primary_application_id_does_not_match():
    result = expiry.fetch_entra_secret_expiry(
        _settings(),
        now=NOW,
        opener=_graph_opener(
            {
                "appId": "other-client-id",
                "passwordCredentials": [_credential()],
            }
        ),
    )

    assert result["status"] == "unavailable"
    assert result["code"] == "invalid_response"


def test_fetch_canonicalizes_utc_milliseconds_and_calculates_remaining_time():
    result = expiry.fetch_entra_secret_expiry(
        _settings(),
        now=NOW,
        opener=_graph_opener(
            {
                "appId": "client-id",
                "displayName": "Example application",
                "passwordCredentials": [
                    _credential(end="2026-07-21T01:30:00.123+01:30")
                ],
            }
        ),
    )

    assert result["expires_at"] == "2026-07-21T00:00:00.123Z"
    assert result["remaining_seconds"] == 86_400
    assert result["remaining_days"] == 2


def test_fetch_never_leaks_client_secret_access_token_or_raw_error_text():
    client_secret = "abc-client-secret-sentinel"
    raw_error = "authorization=access-token-sentinel client_secret=abc-client-secret-sentinel"

    def opener(_request, timeout):
        assert timeout == 20
        raise OSError(raw_error)

    result = expiry.fetch_entra_secret_expiry(
        _settings(client_secret), now=NOW, opener=opener
    )
    serialized = json.dumps(result)

    assert result["code"] == "transport_unavailable"
    assert client_secret not in serialized
    assert "access-token-sentinel" not in serialized
    assert raw_error not in serialized


def test_fetch_redacts_secrets_and_access_tokens_echoed_by_graph_metadata():
    client_secret = "abc-client-secret-sentinel"
    result = expiry.fetch_entra_secret_expiry(
        _settings(client_secret),
        now=NOW,
        opener=_graph_opener(
            {
                "appId": "client-id",
                "displayName": "access-token-sentinel",
                "passwordCredentials": [
                    _credential(
                        name=client_secret,
                        key="access-token-sentinel",
                    )
                ],
            }
        ),
    )

    serialized = json.dumps(result)
    assert result["status"] == "ok"
    assert client_secret not in serialized
    assert "access-token-sentinel" not in serialized


def test_fetch_redacts_partial_overlength_secret_and_token_metadata(monkeypatch):
    client_secret = "c" * 513 + "-client-secret-sentinel"
    access_token = "t" * 513 + "-access-token-sentinel"

    class LongTokenApplication:
        def __init__(self, *_args, **_kwargs):
            pass

        def acquire_token_for_client(self, _scopes):
            return {"access_token": access_token}

    class LongTokenMsal:
        ConfidentialClientApplication = LongTokenApplication

    monkeypatch.setattr(expiry, "msal", LongTokenMsal)
    result = expiry.fetch_entra_secret_expiry(
        _settings(client_secret),
        now=NOW,
        opener=_graph_opener(
            {
                "appId": "client-id",
                "displayName": "untrusted-" + client_secret,
                "passwordCredentials": [
                    _credential(
                        hint="ccc",
                        name="untrusted-" + client_secret,
                        key="untrusted-" + access_token,
                    )
                ],
            }
        ),
    )

    for field, value in result.items():
        rendered = str(value)
        assert client_secret not in rendered, field
        assert access_token not in rendered, field
        assert client_secret[:64] not in rendered, field
        assert access_token[:64] not in rendered, field
