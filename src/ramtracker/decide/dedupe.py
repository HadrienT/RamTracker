"""Les trois identités — blueprint/04-DATA-MODEL.md §1.

`is_new` répond « l'ai-je déjà vue ? » sur `(source, external_id)`.
`price_dropped` autorise une ré-évaluation à la baisse.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from ramtracker.core.models import RawListing


def is_new(listing: RawListing, conn: sqlite3.Connection) -> bool:
    """Vrai si `(source, external_id)` n'est pas encore en base."""
    row = conn.execute(
        "SELECT 1 FROM listings WHERE source = ? AND external_id = ?",
        (listing.source, listing.external_id),
    ).fetchone()
    return row is None


def stored_price(listing: RawListing, conn: sqlite3.Connection) -> Decimal | None:
    row = conn.execute(
        "SELECT price FROM listings WHERE source = ? AND external_id = ?",
        (listing.source, listing.external_id),
    ).fetchone()
    return Decimal(row["price"]) if row else None


def price_dropped(listing: RawListing, conn: sqlite3.Connection, min_pct: float) -> bool:
    """Vrai si le prix a baissé d'au moins `min_pct` % depuis la dernière vue."""
    previous = stored_price(listing, conn)
    if previous is None or previous <= 0:
        return False
    drop = (previous - listing.price) / previous
    return float(drop) * 100.0 >= min_pct
