"""Anti-spam — décide du DROIT d'envoyer, pas de la pertinence (WP05 §3.3).

Quatre règles : une alerte par empreinte, re-alerte à la baisse seulement,
plafond quotidien, silence nocturne. Toute suppression émet `notify.suppressed`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

from ramtracker.core.logging import get_logger
from ramtracker.core.models import Deal, Urgency
from ramtracker.notify.base import SpamPolicy

_log = get_logger("notify.ratelimit")


class Decision:
    __slots__ = ("allowed", "priority", "reason")

    def __init__(self, allowed: bool, priority: int, reason: str | None = None) -> None:
        self.allowed = allowed
        self.priority = priority
        self.reason = reason


def _last_alert(conn: sqlite3.Connection, fingerprint: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT price, sent_at, muted_until FROM alerts "
        "WHERE fingerprint = ? ORDER BY sent_at DESC LIMIT 1",
        (fingerprint,),
    ).fetchone()
    return row


def _urgent_today(conn: sqlite3.Connection, now: datetime) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM alerts WHERE urgency = 'immediate' AND date(sent_at) = date(?)",
        (now.isoformat(),),
    ).fetchone()
    return int(row["n"])


def _in_quiet_hours(policy: SpamPolicy, now: datetime) -> bool:
    start = policy.quiet_hours.from_
    end = policy.quiet_hours.to
    t = now.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def decide(deal: Deal, conn: sqlite3.Connection, policy: SpamPolicy, now: datetime) -> Decision:
    """Renvoie une `Decision` : droit d'envoi + priorité effective."""
    base_priority = 5 if deal.urgency is Urgency.IMMEDIATE else 2
    listing_id = f"{deal.listing.source}:{deal.listing.external_id}"

    previous = _last_alert(conn, deal.fingerprint)
    if previous is not None:
        if previous["muted_until"] and now.isoformat() < str(previous["muted_until"]):
            return _suppressed(listing_id, "muted", base_priority)
        prev_price = Decimal(previous["price"])
        if prev_price > 0:
            drop_pct = float((prev_price - deal.listing.price) / prev_price) * 100.0
            if drop_pct < policy.re_alert_min_drop_pct:
                return _suppressed(listing_id, "already_alerted", base_priority)

    if deal.urgency is Urgency.IMMEDIATE and _urgent_today(conn, now) >= policy.daily_cap_urgent:
        return _suppressed(listing_id, "daily_cap", base_priority)

    priority = base_priority
    if base_priority == 5 and _in_quiet_hours(policy, now):
        priority = policy.quiet_hours.downgrade_to
        _log.info("notify.downgraded", listing_id=listing_id, priority=priority)

    return Decision(True, priority)


def allow(deal: Deal, conn: sqlite3.Connection, policy: SpamPolicy, now: datetime) -> bool:
    """Vue booléenne du contrat 03 §6."""
    return decide(deal, conn, policy, now).allowed


def _suppressed(listing_id: str, reason: str, priority: int) -> Decision:
    _log.info("notify.suppressed", listing_id=listing_id, reason=reason)
    return Decision(False, priority, reason)
