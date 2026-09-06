"""Indice de marché — médiane glissante du €/Go par compartiment de capacité (WP04).

Seules les annonces **qualifiées** entrent dans l'indice : inclure les rejets le
tirerait vers des valeurs sans rapport. `sample_size` pilote le mode observation.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from decimal import Decimal

from ramtracker.core.clock import utc_now
from ramtracker.core.logging import get_logger
from ramtracker.core.money import eur_per_gb, total_cost

_log = get_logger("decide.market")

_DEFAULT_BUCKETS = (8, 16, 32, 64)


class BucketStats:
    __slots__ = ("p25", "p50", "p75", "sample_size")

    def __init__(self, p25: Decimal, p50: Decimal, p75: Decimal, sample_size: int) -> None:
        self.p25 = p25
        self.p50 = p50
        self.p75 = p75
        self.sample_size = sample_size


def _percentile(values: list[Decimal], q: float) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    idx = q * (len(ordered) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = Decimal(str(idx - lo))
    return (ordered[lo] + (ordered[hi] - ordered[lo]) * frac).quantize(Decimal("0.0001"))


def compute_stats(
    conn: sqlite3.Connection,
    window_days: int,
    *,
    shipping_estimate: Decimal,
    buckets: tuple[int, ...] = _DEFAULT_BUCKETS,
) -> dict[int, BucketStats]:
    """Calcule p25/p50/p75 du €/Go par compartiment sur la fenêtre glissante."""
    cutoff = utc_now().timestamp() - window_days * 86400
    rows = conn.execute(
        """
        SELECT l.price AS price, l.shipping AS shipping,
               s.module_capacity_gb AS cap, s.total_gb AS total_gb
        FROM listings l
        JOIN spec_cache s ON s.spec_hash = l.spec_hash
        WHERE s.reject_reason IS NULL
          AND s.total_gb IS NOT NULL AND s.total_gb > 0
          AND s.module_capacity_gb IN ({})
          AND julianday(l.posted_at) >= julianday('now') - ?
        """.format(",".join("?" * len(buckets))),
        (*buckets, window_days),
    ).fetchall()
    _ = cutoff  # borne lisible ; le filtre réel est en SQL

    grouped: dict[int, list[Decimal]] = {b: [] for b in buckets}
    for row in rows:
        shipping = Decimal(row["shipping"]) if row["shipping"] is not None else None
        cost = total_cost(
            Decimal(row["price"]), shipping, estimate_when_unknown=shipping_estimate
        ).total
        grouped[int(row["cap"])].append(eur_per_gb(cost, int(row["total_gb"])))

    return {
        bucket: BucketStats(
            _percentile(vals, 0.25),
            _percentile(vals, 0.50),
            _percentile(vals, 0.75),
            len(vals),
        )
        for bucket, vals in grouped.items()
        if vals
    }


def refresh_index(
    conn: sqlite3.Connection,
    window_days: int,
    *,
    shipping_estimate: Decimal = Decimal("12.00"),
    buckets: tuple[int, ...] = _DEFAULT_BUCKETS,
) -> dict[int, Decimal]:
    """Recalcule l'indice, le persiste dans `market_stats`, renvoie {compartiment: p50}."""
    stats = compute_stats(conn, window_days, shipping_estimate=shipping_estimate, buckets=buckets)
    now = utc_now().isoformat()
    for bucket, s in stats.items():
        conn.execute(
            "INSERT OR REPLACE INTO market_stats"
            "(computed_at, capacity_bucket, p25, p50, p75, sample_size, window_days) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, bucket, str(s.p25), str(s.p50), str(s.p75), s.sample_size, window_days),
        )
    _log.info(
        "market.index.refreshed",
        buckets={b: str(s.p50) for b, s in stats.items()},
        samples={b: s.sample_size for b, s in stats.items()},
    )
    return {b: s.p50 for b, s in stats.items()}


def latest_index(conn: sqlite3.Connection) -> dict[int, Decimal]:
    """Dernier indice persisté, par compartiment."""
    rows = conn.execute(
        """
        SELECT capacity_bucket, p50 FROM market_stats
        WHERE computed_at = (SELECT MAX(computed_at) FROM market_stats)
        """
    ).fetchall()
    return {int(r["capacity_bucket"]): Decimal(r["p50"]) for r in rows}


def latest_sample_size(conn: sqlite3.Connection, capacity_gb: int) -> int:
    row = conn.execute(
        """
        SELECT sample_size FROM market_stats
        WHERE capacity_bucket = ?
        ORDER BY computed_at DESC LIMIT 1
        """,
        (capacity_gb,),
    ).fetchone()
    return int(row["sample_size"]) if row else 0


def reference_for(capacity_gb: int, index: Mapping[int, Decimal]) -> Decimal | None:
    """Référence €/Go pour ce compartiment, ou le compartiment le plus proche."""
    if capacity_gb in index:
        return index[capacity_gb]
    if not index:
        return None
    nearest = min(index, key=lambda b: abs(b - capacity_gb))
    return index[nearest]
