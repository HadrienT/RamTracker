"""Les deux voies d'appel au LLM (WP07).

Voie **urgente** : `best_case < urgent_lane_margin × hard_ceiling`, tentative
immédiate, repli distant si le serveur local est occupé.
Voie **différée** : tout le reste, vidée toutes les 30 min, tour sauté si occupé,
**jamais** de repli distant.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from ramtracker.core.clock import utc_now
from ramtracker.core.errors import LLMUnavailable
from ramtracker.core.logging import get_logger
from ramtracker.core.models import Method, RawListing, SaleType
from ramtracker.extract import llm, qualify
from ramtracker.extract.compat import CompatMatrix

_log = get_logger("runtime.llm_queue")


class Lane(StrEnum):
    URGENT = "urgent"
    DEFERRED = "deferred"


class LlmPolicy(BaseModel):
    enabled: bool = False
    concurrency: int = 1
    batch_size: int = 4
    timeout_s: int = 45
    urgent_lane_margin: float = 0.50
    deferred_drain_interval_min: int = 30
    remote_fallback: bool = True


class _LlmSettings(BaseModel):
    llm: LlmPolicy


def load_llm_policy() -> LlmPolicy:
    from ramtracker.core.config import load_yaml

    return load_yaml("thresholds", _LlmSettings).llm


def lane_for(best_case: Decimal | None, hard_ceiling: Decimal, margin: float) -> Lane:
    """Voie urgente uniquement quand la borne optimiste est très sous la barrière."""
    if best_case is None:
        return Lane.DEFERRED
    if best_case < hard_ceiling * Decimal(str(margin)):
        return Lane.URGENT
    return Lane.DEFERRED


def enqueue(
    conn: sqlite3.Connection, spec_hash: str, lane: Lane, best_case: Decimal | None
) -> None:
    """Ajoute une entrée à la file (idempotent sur `spec_hash`)."""
    conn.execute(
        "INSERT OR IGNORE INTO llm_queue(spec_hash, lane, best_case, enqueued_at) "
        "VALUES (?, ?, ?, ?)",
        (
            spec_hash,
            lane.value,
            str(best_case) if best_case is not None else None,
            utc_now().isoformat(),
        ),
    )
    _log.info("llm.enqueued", spec_hash=spec_hash[:12], lane=lane.value)


def _listing_for(conn: sqlite3.Connection, spec_hash: str) -> RawListing | None:
    row = conn.execute(
        "SELECT * FROM listings WHERE spec_hash = ? ORDER BY last_seen DESC LIMIT 1",
        (spec_hash,),
    ).fetchone()
    if row is None:
        return None
    return RawListing.model_validate(
        {
            "source": row["source"],
            "external_id": row["external_id"],
            "spec_hash": row["spec_hash"],
            "url": row["url"],
            "title": row["title"],
            "description": row["description"],
            "price": Decimal(row["price"]),
            "currency": row["currency"],
            "shipping": Decimal(row["shipping"]) if row["shipping"] is not None else None,
            "sale_type": SaleType(row["sale_type"]),
            "current_bid": Decimal(row["current_bid"]) if row["current_bid"] else None,
            "ends_at": row["ends_at"],
            "seller_id": row["seller_id"],
            "country": row["country"],
            "posted_at": row["posted_at"],
            "raw_payload": row["raw_payload"],
        },
        context={"free_shipping": row["shipping"] == "0"},
    )


def drain(
    conn: sqlite3.Connection,
    lane: Lane,
    budget: int,
    server_busy: Callable[[], bool],
    *,
    matrix: CompatMatrix,
    parser_version: int,
    policy: LlmPolicy,
) -> int:
    """Traite jusqu'à `budget` entrées de la voie. Renvoie le nombre résolu."""
    if lane is Lane.DEFERRED and server_busy():
        _log.info("llm.drain.skipped", lane=lane.value, reason="server_busy")
        _bump_attempts(conn, lane, budget)
        return 0

    rows = conn.execute(
        "SELECT spec_hash, best_case FROM llm_queue WHERE lane = ? "
        "ORDER BY best_case IS NULL, best_case ASC LIMIT ?",
        (lane.value, budget),
    ).fetchall()
    if not rows:
        return 0

    listings: list[RawListing] = []
    hashes: list[str] = []
    for row in rows:
        listing = _listing_for(conn, row["spec_hash"])
        if listing is not None:
            listings.append(listing)
            hashes.append(row["spec_hash"])

    if not listings:
        return 0

    try:
        specs = llm.extract_batch(
            listings,
            timeout_s=policy.timeout_s,
            allow_remote_fallback=(lane is Lane.URGENT and policy.remote_fallback),
            server_busy=server_busy,
        )
    except LLMUnavailable:
        _bump_attempts(conn, lane, budget)
        _log.warning("llm.drain.unavailable", lane=lane.value)
        return 0

    resolved = 0
    for spec_hash, spec in zip(hashes, specs, strict=False):
        final = qualify.qualify(spec.model_copy(update={"method": Method.LLM}), matrix)
        conn.execute(
            """
            INSERT OR REPLACE INTO spec_cache
            (spec_hash, module_capacity_gb, module_count, total_gb, kind, speed_mts,
             ranks, part_number, price_basis, confidence, method, reject_reason,
             parser_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                spec_hash,
                final.module_capacity_gb,
                final.module_count,
                final.total_gb,
                final.kind.value,
                final.speed_mts,
                final.ranks,
                final.part_number,
                final.price_basis.value,
                final.confidence,
                final.method.value,
                final.reject_reason,
                parser_version,
                utc_now().isoformat(),
            ),
        )
        conn.execute("DELETE FROM llm_queue WHERE spec_hash = ?", (spec_hash,))
        resolved += 1

    _log.info("llm.drain.done", lane=lane.value, resolved=resolved)
    return resolved


def _bump_attempts(conn: sqlite3.Connection, lane: Lane, budget: int) -> None:
    conn.execute(
        "UPDATE llm_queue SET attempts = attempts + 1, last_try_at = ? "
        "WHERE spec_hash IN (SELECT spec_hash FROM llm_queue WHERE lane = ? LIMIT ?)",
        (utc_now().isoformat(), lane.value, budget),
    )
