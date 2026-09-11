"""Bounded secret redaction for free text and nested persistence payloads."""

from __future__ import annotations

import re
from numbers import Number


DEFAULT_TEXT_LIMIT = 8 * 1024
REDACTED = "[REDACTED]"

SECRET_KEY_RE = re.compile(
    r"password|passwd|pass|pwd|secret|token|authorization|api[_ -]?key|cookie",
    re.IGNORECASE,
)

_SECRET_NAME = (
    r"password|passwd|pass|pwd|secret|client[_ -]?secret|secret[_ -]?key|"
    r"token|access[_ -]?token|refresh[_ -]?token|api[_ -]?key|"
    r"authorization|cookie"
)
_VALUE_GAP = r"[ \t]*(?:\r?\n[ \t]+)?"
_SCHEME_GAP = r"[ \t]*(?:\r?\n[ \t]+|[ \t])"
_HEADER_RE = re.compile(
    r"(?im)(?P<prefix>\b(?:authorization|proxy-authorization|cookie|set-cookie)"
    r"[ \t]*:[ \t]*)[^\r\n]*(?:\r?\n[ \t]+[^\r\n]*)*"
)
_URI_USERINFO_RE = re.compile(
    r"(?i)(?P<prefix>\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)[^@/\s]+@"
)
_DOUBLE_QUOTED_VALUE_RE = re.compile(
    rf"(?i)(?P<prefix>(?<![\w-])[\"']?(?:{_SECRET_NAME})[\"']?"
    rf"[ \t]*[:=]{_VALUE_GAP})\"(?:\\[^\r\n]|[^\"\\\r\n])*\""
)
_SINGLE_QUOTED_VALUE_RE = re.compile(
    rf"(?i)(?P<prefix>(?<![\w-])[\"']?(?:{_SECRET_NAME})[\"']?"
    rf"[ \t]*[:=]{_VALUE_GAP})'(?:\\[^\r\n]|[^'\\\r\n])*'"
)
_BRACED_VALUE_RE = re.compile(
    rf"(?i)(?P<prefix>(?<![\w-])[\"']?(?:{_SECRET_NAME})[\"']?"
    rf"[ \t]*[:=]{_VALUE_GAP})\{{(?:\}}\}}|[^}}\r\n])*\}}"
)
_CONNECTION_PREFIX_RE = re.compile(
    rf"(?i)(?P<prefix>(?:^|;)[ \t]*(?:{_SECRET_NAME})[ \t]*=[ \t]*)"
    r"(?=[^\r\n]*;)"
)
_PLAIN_PREFIX_RE = re.compile(
    rf"(?i)(?P<prefix>(?<![\w-])[\"']?(?:{_SECRET_NAME})[\"']?"
    rf"[ \t]*[:=]{_VALUE_GAP})"
)
_AUTH_SCHEME_RE = re.compile(
    rf"(?i)(?P<prefix>\b(?:Bearer|Basic){_SCHEME_GAP})"
    r"(?!\[REDACTED\])\S+"
)
_ASCII_FIELD_START = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_"
)
_ASCII_FIELD_CONTINUATION = _ASCII_FIELD_START | frozenset("0123456789.-")
_SAFE_REDACTED_VALUES = (
    REDACTED,
    f'"{REDACTED}"',
    f"'{REDACTED}'",
    f"{{{REDACTED}}}",
)


def _truncate_utf8(value: str, limit: int) -> str:
    bounded = max(0, int(limit))
    encoded = value.encode("utf-8")
    if len(encoded) <= bounded:
        return value
    return encoded[:bounded].decode("utf-8", errors="ignore")


def _replace_value(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{REDACTED}"


def _replace_double_quoted_value(match: re.Match[str]) -> str:
    return f'{match.group("prefix")}\"{REDACTED}\"'


def _replace_single_quoted_value(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}'{REDACTED}'"


def _replace_braced_value(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{{{REDACTED}}}"


def _replace_uri_password(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{REDACTED}@"


def _next_structured_field(text: str, delimiter_at: int) -> bool:
    index = delimiter_at + 1
    while index < len(text) and text[index] in " \t":
        index += 1
    if index >= len(text) or text[index] not in _ASCII_FIELD_START:
        return False
    index += 1
    while index < len(text) and text[index] in _ASCII_FIELD_CONTINUATION:
        index += 1
    while index < len(text) and text[index] in " \t":
        index += 1
    return index < len(text) and text[index] in ":="


def _safe_redacted_value_end(text: str, start: int) -> int | None:
    for value in _SAFE_REDACTED_VALUES:
        if text.startswith(value, start):
            return start + len(value)
    return None


def _redact_prefixed_values(
    text: str,
    prefix_re: re.Pattern[str],
    *,
    stop_at_whitespace: bool,
) -> str:
    """Redact prefix-matched values with a single forward scan per match."""

    output: list[str] = []
    emitted_to = 0
    search_from = 0
    while match := prefix_re.search(text, search_from):
        value_start = match.end()
        safe_end = _safe_redacted_value_end(text, value_start)
        if safe_end is not None:
            search_from = safe_end
            continue

        value_end = value_start
        while value_end < len(text):
            character = text[value_end]
            if character in "\r\n;":
                break
            if stop_at_whitespace and character.isspace():
                break
            if character in ",)" and _next_structured_field(text, value_end):
                break
            value_end += 1

        if value_end == value_start:
            search_from = value_start + 1
            continue
        output.append(text[emitted_to:value_start])
        output.append(REDACTED)
        emitted_to = value_end
        search_from = value_end

    if not output:
        return text
    output.append(text[emitted_to:])
    return "".join(output)


def sanitize_free_text(value: object, *, limit: int = DEFAULT_TEXT_LIMIT) -> str:
    """Redact credential-shaped fragments, then cap the result by UTF-8 bytes."""

    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        try:
            text = str(value)
        except Exception:
            text = f"<{type(value).__name__}>"
    text = _URI_USERINFO_RE.sub(_replace_uri_password, text)
    text = _HEADER_RE.sub(_replace_value, text)
    text = _DOUBLE_QUOTED_VALUE_RE.sub(_replace_double_quoted_value, text)
    text = _SINGLE_QUOTED_VALUE_RE.sub(_replace_single_quoted_value, text)
    text = _BRACED_VALUE_RE.sub(_replace_braced_value, text)
    text = _redact_prefixed_values(
        text,
        _CONNECTION_PREFIX_RE,
        stop_at_whitespace=False,
    )
    text = _redact_prefixed_values(
        text,
        _PLAIN_PREFIX_RE,
        stop_at_whitespace=True,
    )
    text = _AUTH_SCHEME_RE.sub(_replace_value, text)
    return _truncate_utf8(text, limit)


def redact_sensitive_value(
    value: object,
    key: str = "",
    *,
    text_limit: int = DEFAULT_TEXT_LIMIT,
) -> object:
    """Recursively redact secret keys and credential fragments in string values."""

    if key and SECRET_KEY_RE.search(key):
        return REDACTED
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for item_key, item in value.items():
            raw_key = str(item_key)
            safe_key = sanitize_free_text(raw_key, limit=text_limit)
            redacted[safe_key] = redact_sensitive_value(
                item,
                raw_key,
                text_limit=text_limit,
            )
        return redacted
    if isinstance(value, (list, tuple)):
        return [
            redact_sensitive_value(item, text_limit=text_limit)
            for item in value
        ]
    if isinstance(value, str):
        return sanitize_free_text(value, limit=text_limit)
    if value is None or isinstance(value, (bool, Number)):
        return value
    return sanitize_free_text(value, limit=text_limit)
