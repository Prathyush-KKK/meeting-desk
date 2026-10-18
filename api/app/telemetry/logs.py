"""Structured JSON logs.

One JSON object per line with ``level``, ``service``, ``event``, ``request_id``, ``route``,
``duration_ms`` and, on every failure path, ``failure_reason``. stdlib ``logging`` rather than
structlog: the app has no other use for it, and a formatter plus a ``contextvar`` is the whole job.

Nothing here ever writes a secret, a token, a request body or user content. ``log_event`` takes
named fields only, and ``_SCRUBBED`` drops anything that looks like a credential even if a future
call site passes one by accident.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

SERVICE = "meeting_desk"
LOGGER_ROOT = "meeting_desk"

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_route: ContextVar[str] = ContextVar("route", default="")

# Field names that must never reach a log line, whatever a call site passes.
_SCRUBBED = frozenset(
    {
        "authorization",
        "access_token",
        "refresh_token",
        "token",
        "id_token",
        "secret",
        "client_secret",
        "password",
        "cookie",
        "session",
        "body",
        "payload",
        "text",
        "notes",
        "note",
        "content",
        "prompt",
        "email",
        "values",
    }
)
_RESERVED = frozenset(
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
        "thread",
        "threadName",
        "taskName",
    }
)


def new_request_id() -> str:
    return uuid.uuid4().hex


def set_request_id(request_id: str) -> Any:
    return _request_id.set(request_id)


def reset_request_id(token: Any) -> None:
    _request_id.reset(token)


def current_request_id() -> str:
    return _request_id.get()


def set_route(route: str) -> Any:
    return _route.set(route)


def reset_route(token: Any) -> None:
    _route.reset(token)


def current_route() -> str:
    return _route.get()


class JsonFormatter(logging.Formatter):
    """One JSON object per record. ``event`` is the record's message: a token, never prose."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "level": record.levelname.lower(),
            "service": SERVICE,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", "") or current_request_id(),
            "route": getattr(record, "route", "") or current_route(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key in line or key.startswith("_"):
                continue
            if key.lower() in _SCRUBBED:
                continue
            line[key] = value
        if record.exc_info:
            # The type and message only: a traceback can quote request content.
            exc_type, exc_value, _ = record.exc_info
            line["exception"] = getattr(exc_type, "__name__", "Exception")
            line.setdefault("failure_reason", "server_error")
            line["exception_message"] = str(exc_value)[:200]
        return json.dumps(line, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO", stream: Any = None) -> logging.Logger:
    """Install the JSON handler on the ``meeting_desk`` logger namespace.

    Deliberately not the root logger: uvicorn's own loggers and pytest's capture keep working, and
    running ``create_app`` twice in one process (which the tests do constantly) cannot stack
    handlers.
    """
    logger = logging.getLogger(LOGGER_ROOT)
    logger.setLevel(level.upper())
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_ROOT}.{name}" if name else LOGGER_ROOT)


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    failure_reason: str = "",
    duration_ms: float | None = None,
    exc_info: Any = None,
    **fields: Any,
) -> None:
    """Emit one line. ``event`` is a token from ``app/telemetry/events.py``."""
    extra: dict[str, Any] = {k: v for k, v in fields.items() if k.lower() not in _SCRUBBED}
    if failure_reason:
        extra["failure_reason"] = failure_reason
    if duration_ms is not None:
        extra["duration_ms"] = round(float(duration_ms), 3)
    extra.setdefault("request_id", current_request_id())
    extra.setdefault("route", current_route())
    logger.log(level, event, extra=extra, exc_info=exc_info)


__all__ = [
    "SERVICE",
    "JsonFormatter",
    "configure_logging",
    "current_request_id",
    "current_route",
    "get_logger",
    "log_event",
    "new_request_id",
    "reset_request_id",
    "reset_route",
    "set_request_id",
    "set_route",
]
