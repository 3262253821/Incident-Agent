"""Structured logging for the Incident Agent.

One logger (``incident_agent``) with a JSON formatter, so a single ``run_id``
can be grepped across the whole request. Rules:

- never log the Authorization header, the JWT, the model API key, the MySQL
  password, or the full raw incident log;
- free text (a user-supplied title, a tool argument) is truncated before it is
  emitted, because it can be arbitrarily long and may contain credentials;
- anything whose *field name* looks like a secret is replaced by ``[已脱敏]``
  rather than trusted to be safe.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime

LOGGER_NAME = "incident_agent"

REDACTED = "[已脱敏]"

# Truncation bounds for anything that may echo user or tool content.
MAX_TEXT_LENGTH = 120
MAX_SUMMARY_ITEMS = 20

# Field names that must never be emitted, matched after lowercasing.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "jwt",
        "credential",
        "credentials",
        "database_url",
        "incident_database_url",
        "deepseek_api_key",
    }
)


def truncate(value: object, limit: int = MAX_TEXT_LENGTH) -> str:
    """Render a value for a log field, capped so one field cannot flood a line."""

    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…(共 {len(text)} 字符)"


def sanitize(value: object, *, _depth: int = 0) -> object:
    """Recursively mask secret-looking fields and truncate long strings.

    Applied to every ``extra`` payload so a new log call cannot accidentally
    leak a credential just because nobody remembered to field-filter it.
    """

    if _depth > 4:
        return truncate(value)
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                cleaned[str(key)] = REDACTED
            else:
                cleaned[str(key)] = sanitize(item, _depth=_depth + 1)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [sanitize(item, _depth=_depth + 1) for item in value[:MAX_SUMMARY_ITEMS]]
    if isinstance(value, str):
        return truncate(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return truncate(value)


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line, with sanitized structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key.startswith("_") or key in _STANDARD_LOG_ATTRS:
                continue
            # Check the field name here, not only inside ``sanitize``: that
            # function masks secret-looking *dict keys*, but the formatter pulls
            # fields out one at a time and would otherwise pass the raw value
            # through (``extra={"password": ...}``).
            if key.lower() in SENSITIVE_KEYS:
                payload[key] = REDACTED
            else:
                payload[key] = sanitize(value)

        if record.exc_info and record.exc_info[0] is not None:
            # Class name only: a traceback can contain file paths and arguments.
            payload["exception"] = record.exc_info[0].__name__

        return json.dumps(payload, ensure_ascii=False)


_STANDARD_LOG_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def configure_logging(
    *,
    level: str | None = None,
    fmt: str | None = None,
) -> logging.Logger:
    """Install a single stdout JSON handler on the ``incident_agent`` logger.

    Idempotent: repeated calls (module import, tests, reload) do not stack
    handlers. Environment overrides: ``INCIDENT_LOG_LEVEL`` and
    ``INCIDENT_LOG_FORMAT`` (``json`` or ``text``).
    """

    logger = logging.getLogger(LOGGER_NAME)

    resolved_level = level or os.getenv("INCIDENT_LOG_LEVEL", "INFO")
    resolved_format = fmt or os.getenv("INCIDENT_LOG_FORMAT", "json")

    logger.setLevel(resolved_level.upper())
    # Own handler only: do not also emit through uvicorn's root config.
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if resolved_format.lower() == "text":
        handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s %(message)s")
        )
    else:
        handler.setFormatter(JsonLogFormatter())

    logger.addHandler(handler)
    return logger


def get_logger(suffix: str | None = None) -> logging.Logger:
    """Return the shared logger, or a child logger for one module."""

    if suffix:
        return logging.getLogger(f"{LOGGER_NAME}.{suffix}")
    return logging.getLogger(LOGGER_NAME)
