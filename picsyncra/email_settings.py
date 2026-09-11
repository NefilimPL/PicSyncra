"""Normalization and public projection for e-mail notification settings."""

from __future__ import annotations

import copy
import re
from email.utils import parseaddr


EMAIL_SETTINGS_KEY = "email_notifications"
EMAIL_CLIENT_SECRET = "client_secret"
EMAIL_SMTP_PASSWORD = "password"
EMAIL_SEVERITIES = ("info", "warning", "error", "critical")
_EMAIL_LOCAL_ALLOWED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    "!#$%&'*+/=?^_`{|}~.-"
)
_EMAIL_DOMAIN_LABEL_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z"
)


def _is_valid_email_local_part(value: str) -> bool:
    if not value:
        return False
    return all(character in _EMAIL_LOCAL_ALLOWED for character in value)


def normalize_email_address(value: object) -> str:
    """Return one normalized mailbox address or an empty optional value."""

    raw_text = str(value or "")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_text):
        raise ValueError("Niepoprawny adres e-mail.")
    text = raw_text.strip()
    if not text:
        return ""
    display, address = parseaddr(text)
    if (
        display
        or address != text
        or len(address) > 254
        or address.count("@") != 1
    ):
        raise ValueError("Niepoprawny adres e-mail.")
    local, domain = address.rsplit("@", 1)
    if (
        not local
        or len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or not _is_valid_email_local_part(local)
        or any(ch.isspace() for ch in address)
    ):
        raise ValueError("Niepoprawny adres e-mail.")
    labels = domain.split(".")
    if (
        len(domain) > 253
        or len(labels) < 2
        or any(
            len(label) > 63 or not _EMAIL_DOMAIN_LABEL_RE.fullmatch(label)
            for label in labels
        )
    ):
        raise ValueError("Niepoprawny adres e-mail.")
    return f"{local}@{domain.lower()}"


def default_email_settings() -> dict[str, object]:
    return {
        "primary_channel": "entra",
        "fallback_enabled": False,
        "daily_summary_time": "16:00",
        "entra": {
            "tenant_id": "",
            "client_id": "",
            EMAIL_CLIENT_SECRET: "",
            "from_address": "",
        },
        "smtp": {
            "host": "",
            "port": 587,
            "security": "starttls",
            "username": "",
            EMAIL_SMTP_PASSWORD: "",
            "from_address": "",
            "from_name": "",
        },
        "rules": {
            severity: {
                "enabled": False,
                "recipients": [],
                "include_actor": False,
            }
            for severity in EMAIL_SEVERITIES
        },
    }


def _text(value: object) -> str:
    return str(value or "").strip()


def _recipients(value: object) -> list[str]:
    values = value.split(",") if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)):
        return []
    recipients: list[str] = []
    seen: set[str] = set()
    for item in values:
        try:
            address = normalize_email_address(item)
        except ValueError:
            continue
        identity = address.casefold()
        if not address or identity in seen:
            continue
        seen.add(identity)
        recipients.append(address)
    return recipients


def validate_email_rule_recipients(raw: object) -> None:
    """Reject crafted non-empty recipient values before settings are mutated."""

    source = raw if isinstance(raw, dict) else {}
    rules = source.get("rules") if isinstance(source.get("rules"), dict) else {}
    for severity in EMAIL_SEVERITIES:
        rule = rules.get(severity)
        if not isinstance(rule, dict) or "recipients" not in rule:
            continue
        raw_recipients = rule.get("recipients")
        values = raw_recipients.split(",") if isinstance(raw_recipients, str) else raw_recipients
        if not isinstance(values, (list, tuple)):
            if _text(values):
                raise ValueError(
                    f"Niepoprawna lista adresow e-mail dla reguly {severity}."
                )
            continue
        for value in values:
            if not _text(value):
                continue
            try:
                normalize_email_address(value)
            except ValueError as exc:
                raise ValueError(
                    f"Niepoprawny adres e-mail odbiorcy dla reguly {severity}."
                ) from exc


def _bool_value(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"", "0", "false", "no", "off"}:
            return False
    return default


def _daily_summary_time(value: object) -> str:
    """Return a strict, portable 24-hour schedule value."""

    text = _text(value)
    if len(text) != 5 or text[2] != ":":
        return "16:00"
    hour, minute = text[:2], text[3:]
    if not hour.isascii() or not minute.isascii() or not hour.isdigit() or not minute.isdigit():
        return "16:00"
    if int(hour) > 23 or int(minute) > 59:
        return "16:00"
    # Europe/Warsaw skips this hour in spring and repeats it in autumn.
    if int(hour) == 2:
        return "16:00"
    return text


def normalize_email_settings(raw: object) -> dict[str, object]:
    defaults = default_email_settings()
    source = raw if isinstance(raw, dict) else {}

    primary_channel = _text(source.get("primary_channel")).lower()
    if primary_channel not in {"entra", "smtp"}:
        primary_channel = "entra"

    raw_entra = source.get("entra")
    if not isinstance(raw_entra, dict):
        raw_entra = {}
    entra = {
        key: _text(raw_entra.get(key, default))
        for key, default in defaults["entra"].items()
    }

    raw_smtp = source.get("smtp")
    if not isinstance(raw_smtp, dict):
        raw_smtp = {}
    try:
        port = int(raw_smtp.get("port", defaults["smtp"]["port"]))
    except (TypeError, ValueError):
        port = int(defaults["smtp"]["port"])
    port = max(1, min(65_535, port))
    security = _text(raw_smtp.get("security", "starttls")).lower()
    if security not in {"starttls", "tls", "none"}:
        security = "starttls"
    smtp = {
        key: _text(raw_smtp.get(key, default))
        for key, default in defaults["smtp"].items()
        if key not in {"port", "security"}
    }
    smtp["port"] = port
    smtp["security"] = security

    raw_rules = source.get("rules")
    if not isinstance(raw_rules, dict):
        raw_rules = {}
    rules: dict[str, dict[str, object]] = {}
    for severity in EMAIL_SEVERITIES:
        raw_rule = raw_rules.get(severity)
        if not isinstance(raw_rule, dict):
            raw_rule = {}
        rules[severity] = {
            "enabled": _bool_value(raw_rule.get("enabled"), False),
            "recipients": _recipients(raw_rule.get("recipients", [])),
            "include_actor": _bool_value(raw_rule.get("include_actor"), False),
        }

    return {
        "primary_channel": primary_channel,
        "fallback_enabled": _bool_value(source.get("fallback_enabled"), False),
        "daily_summary_time": _daily_summary_time(source.get("daily_summary_time")),
        "entra": entra,
        "smtp": smtp,
        "rules": rules,
    }


def public_email_settings(raw: object) -> dict[str, object]:
    settings = copy.deepcopy(normalize_email_settings(raw))
    client_secret = settings["entra"].pop(EMAIL_CLIENT_SECRET, "")
    smtp_password = settings["smtp"].pop(EMAIL_SMTP_PASSWORD, "")
    settings["entra"]["client_secret_set"] = bool(_text(client_secret))
    settings["smtp"]["password_set"] = bool(_text(smtp_password))
    return settings
