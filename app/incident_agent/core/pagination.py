"""Opaque cursor for history pagination (P1-3-3).

Why a cursor instead of ``offset``: history is an append-heavy list ordered by
``(started_at DESC, id DESC)``. With offset paging, a run inserted while the user
is reading page 1 shifts every later page, so rows get repeated or skipped. The
cursor carries the exact last row of the previous page, and the next query asks
for rows *strictly older* than it, which is stable under concurrent inserts.

The format is deliberately opaque to clients (base64url of ``timestamp|id``) so it
can change without breaking the UI, and it is validated on the way in: a malformed
or tampered cursor must produce a 400, never an unhandled exception.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime

CURSOR_SEPARATOR = "|"


def encode_cursor(started_at: datetime, row_id: int) -> str:
    """Encode one row's ordering key as a URL-safe token."""

    raw = f"{started_at.isoformat()}{CURSOR_SEPARATOR}{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    """Decode a token produced by :func:`encode_cursor`.

    Raises ``ValueError`` for anything that is not a well-formed cursor, so the
    caller can answer 400 instead of leaking a traceback.
    """

    text = (cursor or "").strip()
    if not text:
        raise ValueError("游标为空")

    padded = text + "=" * (-len(text) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("游标不是合法的 base64 文本") from exc

    timestamp_text, separator, id_text = raw.rpartition(CURSOR_SEPARATOR)
    if not separator or not timestamp_text or not id_text:
        raise ValueError("游标缺少时间戳或主键")

    try:
        started_at = datetime.fromisoformat(timestamp_text)
    except ValueError as exc:
        raise ValueError("游标里的时间戳无法解析") from exc

    try:
        row_id = int(id_text)
    except ValueError as exc:
        raise ValueError("游标里的主键不是整数") from exc

    return started_at, row_id
