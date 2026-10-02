"""Structured logging.

All application logs go through structlog and are rendered as one JSON object per line (or a
readable console format for local development). Context such as ``run_id``, ``source`` and
``operation`` is bound with :func:`bind_context` and attached to every subsequent event.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

_configured = False


def _stderr_logger(*_: Any) -> structlog.PrintLogger:
    return structlog.PrintLogger(file=sys.stderr)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configure stdlib logging + structlog once per process."""
    global _configured  # noqa: PLW0603 - process-wide logging setup is intentionally global
    if _configured:
        return

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        # Resolve sys.stderr at emit time (not import time) so redirected/replaced streams
        # - test runners, embedding applications - never receive writes after being closed.
        logger_factory=_stderr_logger,
        cache_logger_on_first_use=False,
    )
    # Route noisy third-party stdlib loggers through the same level.
    logging.basicConfig(
        level=level.upper(), stream=sys.stderr, format="%(levelname)s %(name)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name)
    return logger


@contextmanager
def bind_context(**values: Any) -> Iterator[None]:
    """Temporarily bind key/value pairs to every log event emitted in this context."""
    with structlog.contextvars.bound_contextvars(**values):
        yield


@contextmanager
def timed_operation(operation: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Log start/finish (or failure) of an operation with its duration.

    The yielded dict can be filled with extra fields (e.g. row counts) that are included in the
    completion event.
    """
    log = get_logger("rdp.operation")
    extra: dict[str, Any] = {}
    started = time.perf_counter()
    with bind_context(operation=operation):
        log.info("operation.started", **fields)
        try:
            yield extra
        except Exception as exc:
            log.error(
                "operation.failed",
                duration_seconds=round(time.perf_counter() - started, 3),
                exception_type=type(exc).__name__,
                error=str(exc)[:500],
                **fields,
                **extra,
            )
            raise
        log.info(
            "operation.finished",
            duration_seconds=round(time.perf_counter() - started, 3),
            **fields,
            **extra,
        )
