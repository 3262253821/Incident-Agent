"""Credential masking for incident input and tool observations.

Design rules:

1. This module is a pure function boundary: same input, same output, no I/O.
2. A credential-shaped *key* is a strong enough signal to mask its value, even
   when the value is short, because ``password=devpass`` is already a leak.
3. Bare patterns that would create false positives (11-digit phone numbers)
   are only masked when a known Chinese label precedes them. A bare 11-digit
   number in a log is far more likely to be an order id or a timestamp.
4. Redaction happens before the text reaches the model *and* before anything is
   persisted, so the graph state, MySQL rows and API responses all carry the
   same masked text.
"""

from __future__ import annotations

import re

MASK = "[已脱敏]"

DEFAULT_MAX_LENGTH = 20_000

# Keys whose value is masked regardless of how short the value is.
CREDENTIAL_KEY_NAMES = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api[_-]?key",
    "access[_-]?key",
    "auth[_-]?key",
    "client[_-]?secret",
    "jwt[_-]?secret[_-]?key",
)

_CREDENTIAL_KEY = rf"(?:{'|'.join(CREDENTIAL_KEY_NAMES)})"

# ``Authorization: Bearer <credential>`` — the whole credential is masked.
_BEARER = re.compile(
    r"(?P<label>\bBearer\s+)(?P<value>[A-Za-z0-9\-._~+/]{8,}=*)",
    re.IGNORECASE,
)

# Last-resort safety net: whatever non-space run follows ``Bearer `` is a
# credential, even when it does not match any known token shape.
_BEARER_VALUE = re.compile(
    r"(?P<label>\bBearer\s+)(?P<value>\S+)",
    re.IGNORECASE,
)

# A three-segment JWT is a credential wherever it appears. The leading ``eyJ``
# check is deliberately loose: a token whose first segment happens to be short
# must still be masked, and the Bearer rule below is the real guarantee.
_JWT = re.compile(
    r"\beyJ[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{2,}\b"
)

# ``mysql://user:password@host`` should mask the userinfo only, so the host and
# database stay available for troubleshooting. Requiring a ``:`` in the
# userinfo avoids masking ordinary URLs such as ``https://user@example.com``.
_CONNECTION_URI = re.compile(
    r"(?P<label>\b[a-zA-Z][a-zA-Z0-9+.\-]*://)(?P<userinfo>[^/\s@:]+:[^/\s@]+)@",
    re.IGNORECASE,
)

# ``password=...`` / ``api_key: ...`` / ``"token": "..."``
_KEY_VALUE = re.compile(
    rf"(?P<label>(?P<quote>[\"']?)\b{_CREDENTIAL_KEY}(?P=quote)"
    r"[\"']?\s*[:=]\s*[\"']?)(?P<value>[^\s\"']+)",
    re.IGNORECASE,
)

# Phone numbers: only with an explicit Chinese or English label, because a bare
# 11-digit run is usually an order id.
_LABELED_PHONE = re.compile(
    r"(?P<label>(?:手机号|手机号码|联系电话|联系方式|电话|phone(?:_number)?|mobile)"
    r"\s*[:=：]?\s*)(?P<value>1[3-9]\d{9})",
    re.IGNORECASE,
)

# Mainland China resident id: 17 digits with a digit/X checksum.
_LABELED_ID_CARD = re.compile(
    r"(?P<label>(?:身份证号|身份证|id[_ ]?card|id[_ ]?number)\s*[:=：]?\s*)"
    r"(?P<value>\d{17}[\dXx])",
    re.IGNORECASE,
)


def _mask_match(match: re.Match[str]) -> str:
    """Keep the label (and any structure) but replace the secret value."""

    return f"{match.group('label')}{MASK}"


def _mask_userinfo(match: re.Match[str]) -> str:
    """Mask ``user:password`` inside a connection URI, keeping host and db."""

    return f"{match.group('label')}{MASK}@"


def redact_text(text: str) -> str:
    """Mask credential-shaped fragments in one string.

    Idempotent: masking an already masked string changes nothing, because
    ``[已脱敏]`` contains no characters that the patterns match.
    """

    if not text:
        return text

    redacted = _BEARER.sub(_mask_match, text)
    redacted = _JWT.sub(MASK, redacted)
    # A labelled credential key means the value is a secret even if it does not
    # look like one (``token=abc``).
    redacted = _KEY_VALUE.sub(_mask_match, redacted)
    redacted = _CONNECTION_URI.sub(_mask_userinfo, redacted)
    redacted = _LABELED_PHONE.sub(_mask_match, redacted)
    redacted = _LABELED_ID_CARD.sub(_mask_match, redacted)
    # Finally: anything still attached to a ``Bearer`` prefix is a credential,
    # whatever its shape.
    redacted = _BEARER_VALUE.sub(_mask_match, redacted)
    return redacted


def redact_for_model(text: str, *, max_length: int = DEFAULT_MAX_LENGTH) -> str:
    """Mask credentials, then clamp the length before the text reaches a model.

    The clip marker is appended so the model can tell that input was truncated
    instead of silently reasoning about a partial log.
    """

    redacted = redact_text(text)
    if len(redacted) <= max_length:
        return redacted
    return f"{redacted[:max_length]}\n[已截断，原文共 {len(redacted)} 字符]"


def redact_payload(value):
    """Recursively mask every string inside dicts, lists and tuples.

    Used for tool results, observations and the validated report, so no nested
    free text escapes masking.
    """

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_payload(item) for item in value]
    return value
