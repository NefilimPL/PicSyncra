"""Contract tests for Microsoft Graph and generic SMTP delivery."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
import smtplib
import ssl
from types import SimpleNamespace

import pytest

from picsyncra import email_delivery
from picsyncra.email_delivery import (
    GraphMailTransport,
    MailAttachment,
    MailMessage,
    SmtpMailTransport,
    build_transport,
)


def sample_message() -> MailMessage:
    return MailMessage(
        message_id="incident-1",
        subject="Incident test",
        text_body="Plain incident body",
        html_body="<p>HTML incident body</p>",
        sender_address="sender+alerts@example.com",
        sender_name="PicSyncraFTP SQL",
        recipients=("first@example.com", "second@example.com"),
    )


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeSmtp:
    def __init__(
        self,
        *,
        send_error: Exception | None = None,
        send_result: object = None,
    ) -> None:
        self.calls: list[str] = []
        self.login_args: tuple[str, str] | None = None
        self.message = ""
        self.starttls_context: ssl.SSLContext | None = None
        self.send_error = send_error
        self.send_result = send_result

    def ehlo(self) -> None:
        self.calls.append("ehlo")

    def starttls(self, *, context: ssl.SSLContext) -> None:
        self.calls.append("starttls")
        self.starttls_context = context

    def login(self, username: str, password: str) -> None:
        self.calls.append("login")
        self.login_args = (username, password)

    def send_message(self, message: object) -> object:
        self.calls.append("send_message")
        self.message = message.as_string()
        if self.send_error is not None:
            raise self.send_error
        return self.send_result

    def quit(self) -> None:
        self.calls.append("quit")

    def close(self) -> None:
        self.calls.append("close")


def test_graph_transport_requests_token_and_posts_expected_payload(monkeypatch) -> None:
    applications: list[object] = []
    requests: list[tuple[object, int]] = []
    response = FakeResponse(202)

    class FakeMsalApplication:
        def __init__(self, client_id: str, *, authority: str, client_credential: str) -> None:
            self.client_id = client_id
            self.authority = authority
            self.client_credential = client_credential
            self.scopes: list[str] | None = None
            applications.append(self)

        def acquire_token_for_client(self, scopes: list[str]) -> dict[str, str]:
            self.scopes = scopes
            return {"access_token": "access-token-sensitive"}

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        requests.append((request, timeout))
        return response

    monkeypatch.setattr(
        email_delivery,
        "msal",
        SimpleNamespace(ConfidentialClientApplication=FakeMsalApplication),
    )
    monkeypatch.setattr(email_delivery.urllib.request, "urlopen", fake_urlopen)

    transport = GraphMailTransport(
        {
            "tenant_id": "tenant-id",
            "client_id": "client-id",
            "client_secret": "client-secret-sensitive",
        }
    )
    result = transport.send(sample_message())

    application = applications[0]
    assert application.client_id == "client-id"
    assert application.authority == "https://login.microsoftonline.com/tenant-id"
    assert application.client_credential == "client-secret-sensitive"
    assert application.scopes == ["https://graph.microsoft.com/.default"]

    request, timeout = requests[0]
    assert timeout == 20
    assert request.get_method() == "POST"
    assert request.full_url == (
        "https://graph.microsoft.com/v1.0/users/"
        "sender%2Balerts%40example.com/sendMail"
    )
    assert request.headers["Authorization"] == "Bearer access-token-sensitive"
    assert json.loads(request.data.decode("utf-8")) == {
        "message": {
            "subject": "Incident test",
            "body": {"contentType": "HTML", "content": "<p>HTML incident body</p>"},
            "toRecipients": [
                {"emailAddress": {"address": "first@example.com"}},
                {"emailAddress": {"address": "second@example.com"}},
            ],
            "internetMessageHeaders": [
                {"name": "x-picsyncra-message-id", "value": "incident-1"}
            ],
        },
        "saveToSentItems": True,
    }
    assert response.closed is True
    assert result["channel"] == "entra"
    assert result["status_code"] == 202
    assert isinstance(result["elapsed_ms"], int)
    assert "access-token-sensitive" not in repr(result)
    assert "client-secret-sensitive" not in repr(result)


def test_graph_transport_encodes_text_attachment(monkeypatch) -> None:
    requests: list[object] = []

    class FakeMsalApplication:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def acquire_token_for_client(self, _scopes: list[str]) -> dict[str, str]:
            return {"access_token": "access-token-sensitive"}

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        requests.append(request)
        return FakeResponse(202)

    monkeypatch.setattr(
        email_delivery,
        "msal",
        SimpleNamespace(ConfidentialClientApplication=FakeMsalApplication),
    )
    monkeypatch.setattr(email_delivery.urllib.request, "urlopen", fake_urlopen)

    message = replace(
        sample_message(),
        attachments=(
            MailAttachment(
                filename="picsyncra-exception.txt",
                content_type="text/plain",
                content="RuntimeError: safe diagnostic",
            ),
        ),
    )
    GraphMailTransport(
        {"tenant_id": "tenant", "client_id": "client", "client_secret": "secret"}
    ).send(message)

    payload = json.loads(requests[0].data.decode("utf-8"))
    attachment = payload["message"]["attachments"][0]
    assert attachment["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert attachment["name"] == "picsyncra-exception.txt"
    assert attachment["contentType"] == "text/plain"
    assert (
        base64.b64decode(attachment["contentBytes"]).decode("utf-8")
        == "RuntimeError: safe diagnostic"
    )


@pytest.mark.parametrize("status", [200, 201, 204, 400, 500])
def test_graph_transport_accepts_only_http_202(monkeypatch, status: int) -> None:
    class FakeMsalApplication:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def acquire_token_for_client(self, _scopes: list[str]) -> dict[str, str]:
            return {"access_token": "token-sensitive"}

    monkeypatch.setattr(
        email_delivery,
        "msal",
        SimpleNamespace(ConfidentialClientApplication=FakeMsalApplication),
    )
    monkeypatch.setattr(
        email_delivery.urllib.request,
        "urlopen",
        lambda _request, *, timeout: FakeResponse(status),
    )

    with pytest.raises(RuntimeError) as exc_info:
        GraphMailTransport(
            {
                "tenant_id": "tenant",
                "client_id": "client",
                "client_secret": "secret-sensitive",
            }
        ).send(sample_message())

    assert "token-sensitive" not in str(exc_info.value)
    assert "secret-sensitive" not in str(exc_info.value)


def test_graph_transport_redacts_auth_and_http_failures(monkeypatch) -> None:
    password = "password-sensitive"
    secret = "client-secret-sensitive"
    token = "access-token-sensitive"

    class FailingMsalApplication:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def acquire_token_for_client(self, _scopes: list[str]) -> dict[str, str]:
            return {
                "error": "invalid_client",
                "error_description": f"{secret} {password} {token}",
            }

    monkeypatch.setattr(
        email_delivery,
        "msal",
        SimpleNamespace(ConfidentialClientApplication=FailingMsalApplication),
    )
    settings = {
        "tenant_id": "tenant",
        "client_id": "client",
        "client_secret": secret,
    }
    with pytest.raises(RuntimeError) as auth_error:
        GraphMailTransport(settings).send(sample_message())
    for sensitive in (password, secret, token):
        assert sensitive not in str(auth_error.value)

    class SuccessfulMsalApplication(FailingMsalApplication):
        def acquire_token_for_client(self, _scopes: list[str]) -> dict[str, str]:
            return {"access_token": token}

    monkeypatch.setattr(
        email_delivery,
        "msal",
        SimpleNamespace(ConfidentialClientApplication=SuccessfulMsalApplication),
    )

    def failing_urlopen(_request: object, *, timeout: int) -> FakeResponse:
        raise OSError(f"server echoed {password} {secret} {token}")

    monkeypatch.setattr(email_delivery.urllib.request, "urlopen", failing_urlopen)
    with pytest.raises(RuntimeError) as http_error:
        GraphMailTransport(settings).send(sample_message())
    for sensitive in (password, secret, token):
        assert sensitive not in str(http_error.value)


def test_graph_transport_fails_safely_when_msal_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(email_delivery, "msal", None)

    with pytest.raises(RuntimeError) as exc_info:
        GraphMailTransport(
            {
                "tenant_id": "tenant",
                "client_id": "client",
                "client_secret": "secret-sensitive",
            }
        ).send(sample_message())

    assert "secret-sensitive" not in str(exc_info.value)
    assert "MSAL" in str(exc_info.value)


def test_smtp_transport_uses_starttls_login_and_message_id(monkeypatch) -> None:
    smtp = FakeSmtp()
    monkeypatch.setattr(
        email_delivery.smtplib,
        "SMTP",
        lambda host, port, timeout: smtp,
    )
    transport = SmtpMailTransport(
        {
            "host": "smtp.example",
            "port": 587,
            "security": "starttls",
            "username": "sender",
            "password": "secret",
        }
    )
    result = transport.send(sample_message())

    assert smtp.calls[:2] == ["ehlo", "starttls"]
    assert smtp.login_args == ("sender", "secret")
    assert smtp.starttls_context is not None
    assert smtp.starttls_context.verify_mode == ssl.CERT_REQUIRED
    assert smtp.starttls_context.check_hostname is True
    assert "Message-ID: <incident-1@picsyncra>" in smtp.message
    assert "Subject: Incident test" in smtp.message
    assert "first@example.com, second@example.com" in smtp.message
    assert "Plain incident body" in smtp.message
    assert "HTML incident body" in smtp.message
    assert smtp.calls[-1] == "quit"
    assert result["channel"] == "smtp"
    assert result["status"] == "sent"
    assert isinstance(result["elapsed_ms"], int)
    assert "secret" not in repr(result)


def test_smtp_transport_serializes_text_attachment(monkeypatch) -> None:
    smtp = FakeSmtp()
    monkeypatch.setattr(
        email_delivery.smtplib,
        "SMTP",
        lambda host, port, timeout: smtp,
    )
    message = replace(
        sample_message(),
        attachments=(
            MailAttachment(
                filename="picsyncra-exception.txt",
                content_type="text/plain",
                content="RuntimeError: safe diagnostic",
            ),
        ),
    )

    SmtpMailTransport(
        {"host": "smtp.example", "port": 25, "security": "none"}
    ).send(message)

    assert "Content-Disposition: attachment;" in smtp.message
    assert 'filename="picsyncra-exception.txt"' in smtp.message
    assert "RuntimeError: safe diagnostic" in smtp.message


def test_smtp_transport_serializes_json_attachment_with_its_mime_type(monkeypatch) -> None:
    smtp = FakeSmtp()
    monkeypatch.setattr(
        email_delivery.smtplib,
        "SMTP",
        lambda host, port, timeout: smtp,
    )
    message = replace(
        sample_message(),
        attachments=(
            MailAttachment(
                filename="picsyncra-incident-details.json",
                content_type="application/json",
                content='{"trigger": {"metric": "cpu_percent"}}',
            ),
        ),
    )

    SmtpMailTransport(
        {"host": "smtp.example", "port": 25, "security": "none"}
    ).send(message)

    assert 'filename="picsyncra-incident-details.json"' in smtp.message
    assert "Content-Type: application/json" in smtp.message


def test_smtp_transport_uses_implicit_tls_without_empty_username_login(monkeypatch) -> None:
    smtp = FakeSmtp(send_result={})
    calls: list[tuple[str, int, int, ssl.SSLContext]] = []

    def fake_smtp_ssl(
        host: str,
        port: int,
        timeout: int,
        *,
        context: ssl.SSLContext,
    ) -> FakeSmtp:
        calls.append((host, port, timeout, context))
        return smtp

    monkeypatch.setattr(email_delivery.smtplib, "SMTP_SSL", fake_smtp_ssl)

    result = SmtpMailTransport(
        {
            "host": "smtp.example",
            "port": 465,
            "security": "tls",
            "username": "  ",
            "password": "password-sensitive",
        }
    ).send(sample_message())

    assert calls[0][:3] == ("smtp.example", 465, 20)
    assert calls[0][3].verify_mode == ssl.CERT_REQUIRED
    assert calls[0][3].check_hostname is True
    assert smtp.login_args is None
    assert "starttls" not in smtp.calls
    assert result["channel"] == "smtp"
    assert "password-sensitive" not in repr(result)


def test_smtp_transport_supports_plain_mode_without_tls(monkeypatch) -> None:
    smtp = FakeSmtp()
    calls: list[tuple[str, int, int]] = []

    def fake_smtp(host: str, port: int, timeout: int) -> FakeSmtp:
        calls.append((host, port, timeout))
        return smtp

    monkeypatch.setattr(email_delivery.smtplib, "SMTP", fake_smtp)

    SmtpMailTransport(
        {
            "host": "smtp.example",
            "port": 25,
            "security": "none",
            "username": "",
            "password": "password-sensitive",
        }
    ).send(sample_message())

    assert calls == [("smtp.example", 25, 20)]
    assert "starttls" not in smtp.calls
    assert smtp.login_args is None
    assert smtp.calls[-1] == "quit"


def test_smtp_transport_redacts_errors_and_always_cleans_up(monkeypatch) -> None:
    password = "password-sensitive"
    smtp = FakeSmtp(send_error=OSError(f"server echoed {password}"))
    monkeypatch.setattr(
        email_delivery.smtplib,
        "SMTP",
        lambda host, port, timeout: smtp,
    )

    with pytest.raises(RuntimeError) as exc_info:
        SmtpMailTransport(
            {
                "host": "smtp.example",
                "port": 25,
                "security": "none",
                "username": "sender",
                "password": password,
            }
        ).send(sample_message())

    assert password not in str(exc_info.value)
    assert smtp.calls[-1] == "quit"


def test_smtp_transport_redacts_recipient_refusals_and_cleans_up(
    monkeypatch,
) -> None:
    sensitive_response = (
        "550 password-sensitive recipient@example.com Plain incident body"
    )
    smtp = FakeSmtp(
        send_result={
            "second@example.com": (550, sensitive_response.encode("utf-8"))
        }
    )
    monkeypatch.setattr(
        email_delivery.smtplib,
        "SMTP",
        lambda host, port, timeout: smtp,
    )

    result = SmtpMailTransport(
        {
            "host": "smtp.example",
            "port": 25,
            "security": "none",
            "username": "sender",
            "password": "password-sensitive",
        }
    ).send(sample_message())

    assert result["status"] == "partial"
    for sensitive in (
        sensitive_response,
        "password-sensitive",
        "Plain incident body",
    ):
        assert sensitive not in str(result)
    assert smtp.calls[-1] == "quit"


def test_smtp_transport_returns_internal_partial_refusal_without_sensitive_response(
    monkeypatch,
) -> None:
    smtp = FakeSmtp(
        send_result={
            "second@example.com": (452, b"temporary mailbox failure with private data")
        }
    )
    monkeypatch.setattr(
        email_delivery.smtplib,
        "SMTP",
        lambda host, port, timeout: smtp,
    )

    result = SmtpMailTransport(
        {"host": "smtp.example", "port": 25, "security": "none"}
    ).send(sample_message())

    assert result == {
        "channel": "smtp",
        "status": "partial",
        "routing_known": True,
        "accepted_count": 1,
        "refused_count": 1,
        "refusal_codes": [452],
        "refused_recipients": ["second@example.com"],
        "elapsed_ms": result["elapsed_ms"],
    }
    assert "private data" not in repr(result)
    assert smtp.calls[-1] == "quit"


def test_smtp_transport_reports_all_refused_for_service_fallback(monkeypatch) -> None:
    smtp = FakeSmtp(
        send_result={
            "first@example.com": (550, b"no"),
            "second@example.com": (551, b"no"),
        }
    )
    monkeypatch.setattr(
        email_delivery.smtplib, "SMTP", lambda *_args, **_kwargs: smtp
    )

    result = SmtpMailTransport(
        {"host": "smtp.example", "port": 25, "security": "none"}
    ).send(sample_message())

    assert result["status"] == "refused"
    assert result["accepted_count"] == 0
    assert result["refused_count"] == 2
    assert result["refusal_codes"] == [550, 551]


def test_smtp_all_recipients_refused_exception_uses_safe_internal_routing(
    monkeypatch,
) -> None:
    refusal = smtplib.SMTPRecipientsRefused(
        {
            "first@example.com": (550, b"private first response"),
            "second@example.com": (551, b"private second response"),
        }
    )
    smtp = FakeSmtp(send_error=refusal)
    monkeypatch.setattr(
        email_delivery.smtplib,
        "SMTP",
        lambda host, port, timeout: smtp,
    )

    result = SmtpMailTransport(
        {"host": "smtp.example", "port": 25, "security": "none"}
    ).send(sample_message())

    assert result == {
        "channel": "smtp",
        "status": "refused",
        "routing_known": True,
        "accepted_count": 0,
        "refused_count": 2,
        "refusal_codes": [550, 551],
        "refused_recipients": ["first@example.com", "second@example.com"],
        "elapsed_ms": result["elapsed_ms"],
    }
    assert "private" not in repr(result)
    assert smtp.calls[-1] == "quit"


@pytest.mark.parametrize("recipients", [{}, None, ["malformed"]])
def test_smtp_recipients_refused_with_unknown_payload_never_becomes_success(
    monkeypatch,
    recipients: object,
) -> None:
    smtp = FakeSmtp(send_error=smtplib.SMTPRecipientsRefused(recipients))
    monkeypatch.setattr(
        email_delivery.smtplib,
        "SMTP",
        lambda host, port, timeout: smtp,
    )

    result = SmtpMailTransport(
        {"host": "smtp.example", "port": 25, "security": "none"}
    ).send(sample_message())

    assert result == {
        "channel": "smtp",
        "status": "routing_unknown",
        "routing_known": False,
        "refusal_codes": [],
        "refused_recipients": [],
        "elapsed_ms": result["elapsed_ms"],
    }
    assert "malformed" not in repr(result)
    assert smtp.calls[-1] == "quit"


def test_smtp_recipients_refused_incomplete_mapping_is_routing_unknown(
    monkeypatch,
) -> None:
    smtp = FakeSmtp(
        send_error=smtplib.SMTPRecipientsRefused(
            {"second@example.com": (550, b"private incomplete response")}
        )
    )
    monkeypatch.setattr(
        email_delivery.smtplib,
        "SMTP",
        lambda host, port, timeout: smtp,
    )

    result = SmtpMailTransport(
        {"host": "smtp.example", "port": 25, "security": "none"}
    ).send(sample_message())

    assert result["status"] == "routing_unknown"
    assert result["routing_known"] is False
    assert result["refusal_codes"] == [550]
    assert result["refused_recipients"] == []
    assert "second@example.com" not in repr(result)
    assert "private" not in repr(result)


def test_smtp_recipients_refused_complete_case_variant_mapping_is_verified(
    monkeypatch,
) -> None:
    smtp = FakeSmtp(
        send_error=smtplib.SMTPRecipientsRefused(
            {
                "FIRST@EXAMPLE.COM": (550, b"private first"),
                "Second@Example.Com": (551, b"private second"),
            }
        )
    )
    monkeypatch.setattr(
        email_delivery.smtplib,
        "SMTP",
        lambda host, port, timeout: smtp,
    )

    result = SmtpMailTransport(
        {"host": "smtp.example", "port": 25, "security": "none"}
    ).send(sample_message())

    assert result["status"] == "refused"
    assert result["routing_known"] is True
    assert result["accepted_count"] == 0
    assert result["refused_count"] == 2
    assert result["refusal_codes"] == [550, 551]
    assert result["refused_recipients"] == [
        "first@example.com",
        "second@example.com",
    ]


def test_build_transport_selects_supported_channel() -> None:
    assert isinstance(build_transport("entra", {}), GraphMailTransport)
    assert isinstance(build_transport("smtp", {}), SmtpMailTransport)
    with pytest.raises(ValueError):
        build_transport("unsupported", {"password": "password-sensitive"})
