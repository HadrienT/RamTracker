"""Cadence par source, gigue (WP06 §3.1).

La cadence est **par source**, pas globale. La gigue n'est pas de la
superstition : un scan à la minute ronde, quatorze fois par jour, est un motif
que tout système de détection remarque.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from ramtracker.core.logging import get_logger

_log = get_logger("runtime.scheduler")


class Scheduler:
    """Décide quand une source est due, avec gigue. État en mémoire."""

    def __init__(
        self, intervals: dict[str, tuple[int, int]], *, rng: random.Random | None = None
    ) -> None:
        self._intervals = intervals
        self._next: dict[str, datetime] = {}
        self._rng = rng or random.Random()

    def due(self, source: str, now: datetime) -> bool:
        return now >= self._next.get(source, now - timedelta(seconds=1))

    def mark_ran(self, source: str, now: datetime) -> datetime:
        """Programme le prochain passage : intervalle ± gigue."""
        interval_min, jitter_min = self._intervals.get(source, (10, 2))
        offset = interval_min + self._rng.uniform(-jitter_min, jitter_min)
        nxt = now + timedelta(minutes=max(1.0, offset))
        self._next[source] = nxt
        _log.debug("scheduler.next", source=source, at=nxt.isoformat())
        return nxt

    def next_run(self, source: str) -> datetime | None:
        return self._next.get(source)

    def soonest(self) -> datetime | None:
        return min(self._next.values()) if self._next else None
