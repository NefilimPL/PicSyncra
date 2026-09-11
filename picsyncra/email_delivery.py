"""Redacted Microsoft Graph and SMTP mail delivery transports."""

from __future__ import annotations

import base64
import json
import smtplib
import ssl
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol

try:
    import certifi
except ImportError:  # pragma: no cover - certifi is an optional CA enhancement
    certifi = None

try:
    import msal
except ImportError:  # pragma: no cover - exercised through the explicit test seam
    msal = None


_DELIVERY_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class MailAttachment:
    """A transport-neutral UTF-8 text mail attachment."""

    filename: str
    content_type: str
    content: str


@dataclass(frozen=True)
class MailMessage:
    """A transport-neutral outbound e-mail."""

    message_id: str
    subject: str
    text_body: str
    html_body: str
    sender_address: str
    sender_name: str
    recipients: Sequence[str]
    attachments: Sequence[MailAttachment] = ()


class MailTransport(Protocol):
    """Contract implemented by outbound mail transports."""

    def send(self, message: MailMessage) -> dict[str, object]:
        """Send one message and return non-sensitive diagnostics."""


def _text(value: object) -> str:
    return str(value or "").strip()


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


class GraphMailTransport:
    """Send mail through the Microsoft Graph application API."""

    def __init__(self, settings: Mapping[str, object]) -> None:
        self._tenant_id = _text(settings.get("tenant_id"))
        self._client_id = _text(settings.get("client_id"))
        self._client_secret = _text(settings.get("client_secret"))

    def send(self, message: MailMessage) -> dict[str, object]:
        started = time.perf_counter()
        if msal is None:
            raise RuntimeError("MSAL dependency is unavailable.")

        try:
            application = msal.ConfidentialClientApplication(
                self._client_id,
                authority=(
                    "https://login.microsoftonline.com/" + self._tenant_id
                ),
                client_credential=self._client_secret,
            )
            token_result = application.acquire_token_for_client(
                ["https://graph.microsoft.com/.default"]
            )
        except Exception:
            raise RuntimeError("Microsoft Graph authentication failed.") from None

        access_token = ""
        if isinstance(token_result, Mapping):
            access_token = _text(token_result.get("access_token"))
        if not access_token:
            raise RuntimeError("Microsoft Graph authentication failed.")

        endpoint = (
            "https://graph.microsoft.com/v1.0/users/"
            + urllib.parse.quote(message.sender_address, safe="")
            + "/sendMail"
        )
        payload = {
            "message": {
                "subject": message.subject,
                "body": {"contentType": "HTML", "content": message.html_body},
                "toRecipients": [
                    {"emailAddress": {"address": address}}
                    for address in message.recipients
                ],
                "internetMessageHeaders": [
                    {
                        "name": "x-picsyncra-message-id",
                        "value": message.message_id,
                    }
                ],
            },
            "saveToSentItems": True,
        }
        if message.attachments:
            payload["message"]["attachments"] = [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": attachment.filename,
                    "contentType": attachment.content_type,
                    "contentBytes": base64.b64encode(
                        attachment.content.encode("utf-8")
                    ).decode("ascii"),
                }
                for attachment in message.attachments
            ]
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        response = None
        try:
            response = urllib.request.urlopen(
                request,
                timeout=_DELIVERY_TIMEOUT_SECONDS,
            )
            status_code = getattr(response, "status", None)
            if status_code is None:
                status_code = response.getcode()
        except Exception:
            raise RuntimeError("Microsoft Graph delivery failed.") from None
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

        if status_code != 202:
            raise RuntimeError("Microsoft Graph delivery failed.")
        return {
            "channel": "entra",
            "status_code": status_code,
            "elapsed_ms": _elapsed_ms(started),
        }


def _verified_ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


class SmtpMailTransport:
    """Send mail through a generic SMTP server."""

    def __init__(self, settings: Mapping[str, object]) -> None:
        self._host = _text(settings.get("host"))
        try:
            self._port = int(settings.get("port", 587))
        except (TypeError, ValueError):
            self._port = 587
        self._security = _text(settings.get("security")).lower() or "starttls"
        self._username = _text(settings.get("username"))
        self._password = _text(settings.get("password"))

    def send(self, message: MailMessage) -> dict[str, object]:
        started = time.perf_counter()
        outbound = EmailMessage()
        outbound["From"] = formataddr(
            (message.sender_name, message.sender_address)
        )
        outbound["To"] = ", ".join(message.recipients)
        outbound["Subject"] = message.subject
        outbound["Message-ID"] = f"<{message.message_id}@picsyncra>"
        outbound.set_content(message.text_body)
        outbound.add_alternative(message.html_body, subtype="html")
        for attachment in message.attachments:
            if attachment.content_type == "application/json":
                outbound.add_attachment(
                    attachment.content.encode("utf-8"),
                    maintype="application",
                    subtype="json",
                    filename=attachment.filename,
                )
            else:
                outbound.add_attachment(
                    attachment.content,
                    subtype="plain",
                    filename=attachment.filename,
                )

        client = None
        refused_recipients: object = None
        refusal_exception = False
        try:
            if self._security == "tls":
                client = smtplib.SMTP_SSL(
                    self._host,
                    self._port,
                    timeout=_DELIVERY_TIMEOUT_SECONDS,
                    context=_verified_ssl_context(),
                )
            elif self._security in {"starttls", "none"}:
                client = smtplib.SMTP(
                    self._host,
                    self._port,
                    timeout=_DELIVERY_TIMEOUT_SECONDS,
                )
                if self._security == "starttls":
                    client.ehlo()
                    client.starttls(context=_verified_ssl_context())
                    client.ehlo()
            else:
                raise ValueError("Unsupported SMTP security mode.")

            if self._username:
                client.login(self._username, self._password)
            refused_recipients = client.send_message(outbound)
        except smtplib.SMTPRecipientsRefused as exc:
            refusal_exception = True
            refused_recipients = getattr(exc, "recipients", None)
        except Exception:
            raise RuntimeError("SMTP delivery failed.") from None
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:
                    try:
                        client.close()
                    except Exception:
                        pass

        return _smtp_result(
            message,
            refused_recipients,
            started,
            refusal_exception=refusal_exception,
        )


def _smtp_result(
    message: MailMessage,
    refused_recipients: object,
    started: float,
    *,
    refusal_exception: bool = False,
) -> dict[str, object]:
    if refusal_exception and (
        not isinstance(refused_recipients, Mapping)
        or not refused_recipients
    ):
        return _smtp_unknown_routing(started)
    if not refused_recipients:
        return {
            "channel": "smtp",
            "status": "sent",
            "elapsed_ms": _elapsed_ms(started),
        }

    refused = (
        refused_recipients
        if isinstance(refused_recipients, Mapping)
        else {}
    )
    original = [_text(address) for address in message.recipients]
    requested = {
        address.casefold(): address for address in original if address
    }
    routing_known = (
        isinstance(refused_recipients, Mapping)
        and len(requested) == len(original)
    )
    if refusal_exception:
        refused_identities = [
            _text(address).casefold() for address in refused.keys()
        ]
        complete_exception_mapping = (
            len(refused_identities) == len(original)
            and len(set(refused_identities)) == len(original)
            and set(refused_identities) == set(requested)
        )
        if not complete_exception_mapping:
            safe_codes = []
            for diagnostic in refused.values():
                values = (
                    diagnostic
                    if isinstance(diagnostic, (tuple, list))
                    else ()
                )
                if (
                    values
                    and isinstance(values[0], int)
                    and not isinstance(values[0], bool)
                ):
                    safe_codes.append(max(0, values[0]))
            return _smtp_unknown_routing(started, safe_codes)
    refused_addresses: list[str] = []
    seen: set[str] = set()
    refusal_codes: list[int] = []
    for raw_address, raw_diagnostic in refused.items():
        identity = _text(raw_address).casefold()
        address = requested.get(identity)
        if not identity or identity in seen or not address:
            routing_known = False
            continue
        seen.add(identity)
        refused_addresses.append(address)
        diagnostic = (
            raw_diagnostic
            if isinstance(raw_diagnostic, (tuple, list))
            else ()
        )
        if (
            diagnostic
            and isinstance(diagnostic[0], int)
            and not isinstance(diagnostic[0], bool)
        ):
            refusal_codes.append(max(0, diagnostic[0]))
    if len(seen) != len(refused):
        routing_known = False
    if not routing_known:
        return _smtp_unknown_routing(started, refusal_codes)
    refused_count = len(refused_addresses)
    accepted_count = max(0, len(original) - refused_count)
    status = "refused" if refused_count == len(original) else "partial"
    return {
        "channel": "smtp",
        "status": status,
        "routing_known": bool(routing_known and refused_count),
        "accepted_count": accepted_count,
        "refused_count": refused_count,
        "refusal_codes": sorted(set(refusal_codes)),
        # Internal-only routing data; NotificationService strips it before
        # persistence and public projection.
        "refused_recipients": refused_addresses,
        "elapsed_ms": _elapsed_ms(started),
    }


def _smtp_unknown_routing(
    started: float,
    refusal_codes: Sequence[int] = (),
) -> dict[str, object]:
    return {
        "channel": "smtp",
        "status": "routing_unknown",
        "routing_known": False,
        "refusal_codes": sorted(set(refusal_codes)),
        "refused_recipients": [],
        "elapsed_ms": _elapsed_ms(started),
    }


def build_transport(
    channel: str,
    settings: Mapping[str, object],
) -> MailTransport:
    """Build a supported transport without exposing its settings in errors."""

    normalized = _text(channel).lower()
    if normalized == "entra":
        return GraphMailTransport(settings)
    if normalized == "smtp":
        return SmtpMailTransport(settings)
    raise ValueError("Unsupported mail transport channel.")
