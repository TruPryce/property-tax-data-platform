"""High-confidence redaction for untrusted GitHub text entering model packets."""

from __future__ import annotations

import re

_AUTHORIZATION = re.compile(
    r"""(?P<prefix>
        authorization[\"']?\s*:\s*[\"']?(?:bearer|basic)\s+
    )
    (?P<value>
        \"(?:\\.|[^\"\\])*\"
        | '(?:\\.|[^'\\])*'
        | \[[^\]\r\n]*\]
        | [^\s,;&|\"'`()\[\]{}]+
    )""",
    re.IGNORECASE | re.VERBOSE,
)
_ASSIGNMENT = re.compile(
    r"""(?P<prefix>
        (?P<key_quote>[\"']?)
        (?P<key>[A-Za-z_][A-Za-z0-9_-]*)
        (?P=key_quote)
        \s*(?:=(?!=)|:(?![-+?=]))\s*
    )
    (?P<value>
        \"(?:\\.|[^\"\\])*\"
        | '(?:\\.|[^'\\])*'
        | \[[^\]\r\n]*\]
        | [^\s,;&|\"'`()\[\]{}]+
    )""",
    re.VERBOSE,
)
_NON_SECRET_KEYS = {"canary_token", "verification_token"}
_SENSITIVE_SUFFIXES = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "client_secret",
    "private_key",
    "signing_key",
    "secret_key",
    "access_key",
    "access_key_id",
    "secret_access_key",
)
_DYNAMIC_MARKERS = ("$", "{{", "{%", "<%", "process.env", "os.environ", "getenv(", "[REDACTED]")


def _is_dynamic(value: str) -> bool:
    inner = (
        value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'" else value
    )
    return any(marker in inner for marker in _DYNAMIC_MARKERS)


def _redacted_literal(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[0] + "[REDACTED]" + value[-1]
    if len(value) >= 2 and value[0] == "[" and value[-1] == "]":
        return "[REDACTED]"
    return "[REDACTED]"


def _redact_authorization(match: re.Match[str]) -> str:
    value = match.group("value")
    if _is_dynamic(value):
        return match.group(0)
    return match.group("prefix") + _redacted_literal(value)


def _redact_assignment(match: re.Match[str]) -> str:
    key = match.group("key").lower().replace("-", "_")
    if key in _NON_SECRET_KEYS or not any(
        key == suffix or key.endswith("_" + suffix) for suffix in _SENSITIVE_SUFFIXES
    ):
        return match.group(0)
    value = match.group("value")
    if _is_dynamic(value):
        return match.group(0)
    return match.group("prefix") + _redacted_literal(value)


def redact_untrusted_text(text: str) -> tuple[str, int]:
    """Redact credential-looking literals while preserving surrounding syntax."""

    count = 0

    def authorization(match: re.Match[str]) -> str:
        nonlocal count
        replacement = _redact_authorization(match)
        if replacement != match.group(0):
            count += 1
        return replacement

    def assignment(match: re.Match[str]) -> str:
        nonlocal count
        replacement = _redact_assignment(match)
        if replacement != match.group(0):
            count += 1
        return replacement

    redacted = _AUTHORIZATION.sub(authorization, text)
    redacted = _ASSIGNMENT.sub(assignment, redacted)
    return redacted, count


__all__ = ["redact_untrusted_text"]
