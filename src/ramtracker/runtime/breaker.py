"""Disjoncteur par source — repli exponentiel (WP06 §3.2).

Deux règles absolues : **par source** (Leboncoin bloqué n'arrête pas eBay) et
**aucune reprise immédiate** après un blocage. État en mémoire : le processus
est long, un redémarrage repart d'un état fermé, ce qui est acceptable.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from ramtracker.core.logging import get_logger

_log = get_logger("runtime.breaker")

_BACKOFF_MINUTES = (15, 60, 240, 720)
_FAILURES_BEFORE_OPEN = 3
_JITTER_FRAC = 0.15


class _SourceState:
    __slots__ = ("failures", "open_until")

    def __init__(self) -> None:
        self.failures = 0
        self.open_until: datetime | None = None


class Breaker:
    def __init__(self, *, rng: random.Random | None = None) -> None:
        self._state: dict[str, _SourceState] = {}
        self._rng = rng or random.Random()

    def _get(self, source: str) -> _SourceState:
        return self._state.setdefault(source, _SourceState())

    def allow(self, source: str, now: datetime) -> bool:
        """Vrai si une tentative est autorisée maintenant."""
        st = self._get(source)
        if st.open_until is None:
            return True
        if now >= st.open_until:
            return True
        return False

    def record_success(self, source: str) -> None:
        """Fermeture immédiate, compteur remis à zéro."""
        st = self._get(source)
        if st.failures or st.open_until:
            _log.info("breaker.closed", source=source)
        st.failures = 0
        st.open_until = None

    def record_failure(self, source: str, now: datetime) -> bool:
        """Programme la prochaine tentative. Renvoie `True` si le disjoncteur vient d'ouvrir."""
        st = self._get(source)
        st.failures += 1
        step = min(st.failures - 1, len(_BACKOFF_MINUTES) - 1)
        base = _BACKOFF_MINUTES[step]
        jitter = self._rng.uniform(-_JITTER_FRAC, _JITTER_FRAC) * base
        st.open_until = now + timedelta(minutes=base + jitter)
        just_opened = st.failures == _FAILURES_BEFORE_OPEN
        _log.warning(
            "breaker.failure",
            source=source,
            failures=st.failures,
            next_attempt=st.open_until.isoformat(),
            opened=just_opened,
        )
        return just_opened

    def is_open(self, source: str, now: datetime) -> bool:
        st = self._get(source)
        return (
            st.open_until is not None
            and now < st.open_until
            and st.failures >= _FAILURES_BEFORE_OPEN
        )
