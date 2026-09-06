"""Journalisation structurée — blueprint/07-ERRORS-AND-LOGGING.md §3.

`structlog`, sortie JSON, un événement par ligne. `run_id` est propagé par
contextvar et apparaît dans tous les événements d'un cycle.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from ulid import ULID

_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog une fois pour le processus."""
    global _configured  # noqa: PLW0603 - idempotence du processus
    if _configured:
        return
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=numeric)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.EventRenamer("event"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Logger nommé, à utiliser aux frontières de composant."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]


def new_run_id() -> str:
    """ULID de cycle, trié dans le temps."""
    return str(ULID())


@contextmanager
def run_context(run_id: str | None = None, **fields: str) -> Iterator[str]:
    """Lie `run_id` (+ champs) au contexte de journalisation pour la durée du bloc."""
    rid = run_id or new_run_id()
    bind_contextvars(run_id=rid, **fields)
    try:
        yield rid
    finally:
        clear_contextvars()
