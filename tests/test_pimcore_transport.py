from __future__ import annotations

import json
import ssl
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import certifi
import pytest
import requests

from picsyncra.services.pimcore_service import (
    PimcoreApiError,
    PimcoreClient,
    pimcore_client_scope,
)


SETTINGS = {
    "base_url": "https://pimcore.example.test",
    "api_key": "test-secret",
    "verify_tls": True,
    "timeout_seconds": 5,
}


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.text = json.dumps(payload)
        self.headers = {}


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = iter(responses)
        self.request_count = 0
        self.close_count = 0
        self.requests: list[dict] = []

    def request(self, **request):
        self.request_count += 1
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response

    def close(self) -> None:
        self.close_count += 1


def test_client_reuses_private_session_and_closes_it() -> None:
    session = FakeSession(
        [
            FakeResponse(200, {"data": []}),
            FakeResponse(200, {"success": True}),
            FakeResponse(200, {"data": {"id": 7}}),
        ]
    )

    with PimcoreClient(SETTINGS, session_factory=lambda: session) as client:
        client.object_list(object_class="Product")
        client.create_object({"key": "p-1"})
        client.object_by_id(7)

    assert session.request_count == 3
    assert session.close_count == 1


def test_requests_and_legacy_transports_keep_request_contract_equivalent() -> None:
    session = FakeSession([FakeResponse(200, {"data": []})])
    legacy_request: dict[str, object] = {}

    class LegacyResponse:
        status = 200
        headers = {}

        def read(self) -> bytes:
            return b'{"data": []}'

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> bool:
            return False

    def opener(request, timeout, context) -> LegacyResponse:
        legacy_request.update(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "headers": {
                    "accept": request.get_header("Accept"),
                    "content_type": request.get_header("Content-type"),
                    "api_key": request.get_header("X-api-key"),
                },
                "body": request.data,
                "timeout": timeout,
                "context": context,
            }
        )
        return LegacyResponse()

    query_filter = {"EAN": "5901234567890"}
    requests_client = PimcoreClient(SETTINGS, session_factory=lambda: session)
    legacy_client = PimcoreClient(SETTINGS, opener=opener)

    requests_client.object_list(query_filter, object_class="Product", limit=7, offset=3)
    legacy_client.object_list(query_filter, object_class="Product", limit=7, offset=3)

    request = session.requests[0]
    legacy_url = urlsplit(str(legacy_request["url"]))
    assert request["method"] == legacy_request["method"] == "GET"
    assert urlsplit(str(request["url"])).path == legacy_url.path
    assert {key: str(value) for key, value in request["params"].items()} == {
        key: values[0] for key, values in parse_qs(legacy_url.query).items()
    }
    assert request["json"] is None
    assert legacy_request["body"] is None
    assert request["headers"] == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-api-key": "test-secret",
    }
    assert legacy_request["headers"] == {
        "accept": "application/json",
        "content_type": "application/json",
        "api_key": "test-secret",
    }
    assert request["timeout"] == (5, 5)
    assert legacy_request["timeout"] == 5
    assert request["verify"] == certifi.where()
    assert isinstance(legacy_request["context"], ssl.SSLContext)
    assert "test-secret" not in str(request["url"])
    assert "test-secret" not in str(legacy_request["url"])


def test_client_scope_closes_owned_but_not_supplied_client() -> None:
    owned = Mock()
    with pimcore_client_scope(SETTINGS, factory=lambda _config: owned):
        pass
    owned.close.assert_called_once()

    supplied = Mock()
    with pimcore_client_scope(SETTINGS, supplied=supplied) as client:
        assert client is supplied
    supplied.close.assert_not_called()


def test_client_retries_get_once_with_new_session_after_connection_error() -> None:
    failed_session = FakeSession([requests.Timeout("connection lost")])
    replacement_session = FakeSession([FakeResponse(200, {"data": {"version": "6"}})])
    sessions = iter((failed_session, replacement_session))

    with PimcoreClient(SETTINGS, session_factory=lambda: next(sessions)) as client:
        assert client.server_info() == {"data": {"version": "6"}}

    assert failed_session.request_count == 1
    assert failed_session.close_count == 1
    assert replacement_session.request_count == 1
    assert replacement_session.close_count == 1


def test_client_does_not_retry_mutating_request_after_connection_error() -> None:
    failed_session = FakeSession([requests.Timeout("connection lost")])
    session_factory = Mock(return_value=failed_session)

    with PimcoreClient(SETTINGS, session_factory=session_factory) as client:
        with pytest.raises(PimcoreApiError, match="Nie mozna polaczyc"):
            client.create_object({"key": "p-1"})

    assert failed_session.request_count == 1
    assert session_factory.call_count == 1
