"""
Structured JSON logging for the NBFC Compliance AI system.

All log output goes to stdout as single-line JSON, ready for ingestion by
CloudWatch Logs on ECS.  Request/correlation IDs are injected automatically
from ``contextvars`` — no need to pass them at every call site.

PII fields are scrubbed by a ``logging.Filter`` before serialisation so
sensitive data never leaves the process boundary.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Context variables — set once per request in middleware, read by every log
# ---------------------------------------------------------------------------

REQUEST_ID_VAR: ContextVar[str] = ContextVar("request_id", default="")
CORRELATION_ID_VAR: ContextVar[str] = ContextVar("correlation_id", default="")


def set_request_context(
    request_id: str, correlation_id: str | None = None
) -> None:
    """Bind request-scoped identifiers into the current task context.

    Call this at the top of ``RequestIDMiddleware.dispatch`` so every
    subsequent log line automatically includes both IDs.
    """
    REQUEST_ID_VAR.set(request_id)
    CORRELATION_ID_VAR.set(correlation_id or "")


# ---------------------------------------------------------------------------
# PII scrubbing
# ---------------------------------------------------------------------------

PII_FIELDS: frozenset[str] = frozenset(
    [
        "pan_number",
        "aadhaar_number",
        "account_number",
        "mobile_number",
        "email",
        "password",
        "dob",
    ]
)

_REDACTED = "***REDACTED***"


class ScrubFilter(logging.Filter):
    """Remove or mask any log-record extra fields whose key is in ``PII_FIELDS``.

    Operates on the ``LogRecord.__dict__`` *before* the formatter runs,
    so redacted values never reach stdout.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for field in PII_FIELDS:
            if field in record.__dict__:
                record.__dict__[field] = _REDACTED
        return True


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

_BUILTIN_ATTRS: frozenset[str] = frozenset(
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
        "message",
        "module",
        "msecs",
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


class _JSONFormatter(logging.Formatter):
    """Single-line JSON formatter for CloudWatch ingestion.

    Output schema per line::

        {
          "timestamp": "2026-04-01T12:00:00.123456+00:00",
          "level": "INFO",
          "logger": "ai.agents.sanctions_agent",
          "message": "Sanctions check passed",
          "request_id": "abc-123",
          "correlation_id": "xyz-456",
          "extra": { ... }
        }
    """

    def format(self, record: logging.LogRecord) -> str:
        # Let the base class interpolate %-style messages & capture exc_info
        record.message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)

        extra: dict[str, Any] = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _BUILTIN_ATTRS
        }

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
            "request_id": REQUEST_ID_VAR.get(),
            "correlation_id": CORRELATION_ID_VAR.get() or None,
        }

        if record.exc_text:
            extra["traceback"] = record.exc_text

        if extra:
            payload["extra"] = extra

        return json.dumps(payload, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

_CONFIGURED: set[str] = set()


def get_logger(name: str) -> logging.Logger:
    """Return a logger that emits structured JSON to stdout.

    Safe to call repeatedly with the same *name* — the handler and filter
    are attached only once.

    Args:
        name: Dotted logger name, e.g. ``"ai.agents.rag_agent"``.
    """
    logger = logging.getLogger(name)

    if name not in _CONFIGURED:
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JSONFormatter())
        handler.addFilter(ScrubFilter())
        logger.addHandler(handler)

        _CONFIGURED.add(name)

    return logger
