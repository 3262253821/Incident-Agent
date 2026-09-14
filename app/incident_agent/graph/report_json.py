"""Tolerant parsing of the model's report JSON (P1-2-1).

The report node asks for raw JSON, but a chat model routinely wraps it anyway:
as a ```` ```json ```` fenced block, with a sentence before or after it, or with
trailing commas. Rejecting all of those turns one formatting slip into a fully
degraded run, so the text is unwrapped before validation:

1. strip Markdown code fences (```` ```json ... ``` ````);
2. keep the outermost ``{ ... }`` object if there is surrounding prose;
3. retry the decode after removing trailing commas.

Anything still unparseable is a real failure and is handled by the caller, which
may spend one bounded repair request (see ``graph/nodes.py``).
"""

from __future__ import annotations

import json
import re

_FENCE_PATTERN = r"```(?:json|JSON)?\s*(.*?)\s*```"
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def strip_code_fence(text: str) -> str:
    """Return the content of the first fenced block, or the text unchanged."""

    match = re.search(_FENCE_PATTERN, text, re.DOTALL)
    if match is None:
        return text
    return match.group(1).strip()


def extract_json_object(text: str) -> str:
    """Keep the outermost ``{ ... }`` object, dropping surrounding prose.

    Uses brace counting that ignores braces inside string literals, so a JSON
    value containing ``}`` does not truncate the object.
    """

    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]


def remove_trailing_commas(text: str) -> str:
    """Drop ``,`` immediately before ``}`` or ``]``."""

    return _TRAILING_COMMA.sub(r"\1", text)


def unwrap_json(text: str) -> str:
    """Apply every non-destructive cleanup before a parse attempt."""

    if not isinstance(text, str):
        return text
    candidate = text.strip()
    candidate = strip_code_fence(candidate)
    candidate = extract_json_object(candidate)
    return candidate.strip()


def parse_json_tolerantly(text: str) -> object:
    """Decode ``text`` as JSON, tolerating the common model formatting slips.

    Raises ``json.JSONDecodeError`` when nothing works, so the caller can decide
    whether to spend a repair request.
    """

    candidate = unwrap_json(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # One more attempt with a lossless cleanup: trailing commas.
        return json.loads(remove_trailing_commas(candidate))
