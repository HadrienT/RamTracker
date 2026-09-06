"""Horloge injectable — jamais `datetime.now()` ailleurs (règle N5)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def _system_clock() -> datetime:
    return datetime.now(UTC)


_current: Clock = _system_clock


def utc_now() -> datetime:
    """Instant présent, toujours *aware* et en UTC."""
    now = _current()
    if now.tzinfo is None:
        raise RuntimeError("l'horloge a renvoyé un datetime naïf")
    return now.astimezone(UTC)


def set_clock(clock: Clock) -> None:
    """Substitue l'horloge globale (usage test uniquement)."""
    global _current  # noqa: PLW0603 - point d'injection assumé pour les tests
    _current = clock


def reset_clock() -> None:
    """Rétablit l'horloge système."""
    set_clock(_system_clock)


@contextmanager
def frozen(instant: datetime) -> Iterator[datetime]:
    """Fige l'horloge sur `instant` le temps du bloc `with`."""
    if instant.tzinfo is None:
        raise ValueError("frozen() exige un datetime aware")
    pinned = instant.astimezone(UTC)
    previous = _current
    set_clock(lambda: pinned)
    try:
        yield pinned
    finally:
        set_clock(previous)
