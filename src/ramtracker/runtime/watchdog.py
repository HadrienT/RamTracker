"""Chien de garde inversé (WP06 §3.3, blueprint/07-ERRORS-AND-LOGGING.md §4).

Alerté par l'**absence** de résultats, pas par une erreur. Surveille `raw_count`,
jamais `qualified` : une source peut légitimement ne rien qualifier des jours ;
qu'elle ne remonte plus rien du tout est anormal. Se désarme seul.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from pydantic import BaseModel

from ramtracker.core.logging import get_logger

_log = get_logger("runtime.watchdog")


class WatchdogPolicy(BaseModel):
    empty_cycles_before_alert: int = 3
    min_prior_activity: int = 5


class WatchdogSettings(BaseModel):
    watchdog: WatchdogPolicy


class Anomaly(BaseModel):
    source: str
    message: str
    empty_cycles: int


def load_watchdog_policy() -> WatchdogPolicy:
    from ramtracker.core.config import load_yaml

    return load_yaml("thresholds", WatchdogSettings).watchdog


def check(conn: sqlite3.Connection, policy: WatchdogPolicy, now: datetime) -> list[Anomaly]:
    """Renvoie une anomalie par source qui produisait avant et ne produit plus."""
    _ = now
    anomalies: list[Anomaly] = []
    sources = [r["source"] for r in conn.execute("SELECT DISTINCT source FROM source_runs")]
    for source in sources:
        prior = conn.execute(
            "SELECT COALESCE(SUM(raw_count), 0) AS total FROM source_runs WHERE source = ?",
            (source,),
        ).fetchone()["total"]
        if prior < policy.min_prior_activity:
            continue
        recent = [
            row["raw_count"]
            for row in conn.execute(
                "SELECT raw_count FROM source_runs WHERE source = ? "
                "ORDER BY started_at DESC LIMIT ?",
                (source, policy.empty_cycles_before_alert),
            )
        ]
        if len(recent) >= policy.empty_cycles_before_alert and all(c == 0 for c in recent):
            anomalies.append(
                Anomaly(
                    source=source,
                    message=f"{source} — 0 annonce depuis {len(recent)} cycles",
                    empty_cycles=len(recent),
                )
            )
            _log.warning("watchdog.anomaly", source=source, empty_cycles=len(recent))
    return anomalies
