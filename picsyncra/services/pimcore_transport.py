"""HTTP transports used by the Pimcore API client."""

from __future__ import annotations

from dataclasses import dataclass
import json
import ssl
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

import certifi
import requests


@dataclass(frozen=True)
class PimcoreHttpResponse:
    status_code: int
    text: str
    headers: dict[str, str]


class PimcoreTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        query: dict[str, object] | None,
        body: dict[str, object] | None,
        timeout: int,
    ) -> PimcoreHttpResponse: ...

    def close(self) -> None: ...


class RequestsPimcoreTransport:
    """A private ``requests.Session`` transport for one Pimcore operation."""

    def __init__(self, session, *, verify_tls: bool) -> None:
        self._session = session
        self._verify = certifi.where() if verify_tls else False

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        query: dict[str, object] | None,
        body: dict[str, object] | None,
        timeout: int,
    ) -> PimcoreHttpResponse:
        try:
            response = self._session.request(
                method=method,
                url=url,
                headers=headers,
                params=query or None,
                json=body,
                timeout=(timeout, timeout),
                verify=self._verify,
            )
        except requests.RequestException as exc:
            raise PimcoreTransportNetworkError(str(exc)) from exc
        return PimcoreHttpResponse(
            status_code=int(response.status_code),
            text=str(response.text or ""),
            headers=dict(response.headers or {}),
        )

    def close(self) -> None:
        self._session.close()


class LegacyPimcoreTransport:
    """Adapter for the pre-existing injectable urllib opener."""

    def __init__(
        self,
        opener: Callable[[Request, int, ssl.SSLContext | None], object],
        *,
        ssl_context: ssl.SSLContext | None,
    ) -> None:
        self._opener = opener
        self._ssl_context = ssl_context

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        query: dict[str, object] | None,
        body: dict[str, object] | None,
        timeout: int,
    ) -> PimcoreHttpResponse:
        endpoint = f"{url}?{urlencode(query)}" if query else url
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(endpoint, data=data, method=method, headers=headers)
        try:
            with self._opener(request, timeout, self._ssl_context) as response:
                return PimcoreHttpResponse(
                    status_code=int(getattr(response, "status", 200) or 200),
                    text=response.read().decode("utf-8", errors="replace"),
                    headers=dict(getattr(response, "headers", {}) or {}),
                )
        except HTTPError as exc:
            return PimcoreHttpResponse(
                status_code=int(exc.code),
                text=exc.read().decode("utf-8", errors="replace"),
                headers=dict(exc.headers or {}),
            )
        except URLError as exc:
            raise PimcoreTransportNetworkError(str(exc)) from exc

    def close(self) -> None:
        return None


class PimcoreTransportNetworkError(Exception):
    """A transport-level connection error without request secrets."""

