"""Politique d'enchères — blueprint/03-INTERFACES.md §5, WP04 §3.6.

Le prix d'une enchère à J−6 ne veut rien dire. Hors de la fenêtre de fin :
`WATCH`, aucune notification. Dans la fenêtre : évaluer sur (cote + incrément).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ramtracker.core.models import RawListing, SaleType, Urgency
from ramtracker.decide.policy import AuctionPolicy


def time_left_minutes(listing: RawListing, now: datetime) -> float | None:
    if listing.ends_at is None:
        return None
    return (listing.ends_at - now).total_seconds() / 60.0


def gate(listing: RawListing, now: datetime, policy: AuctionPolicy) -> Urgency:
    """`WATCH` tant qu'il reste plus de `gate_minutes`, sinon `QUIET`."""
    if listing.sale_type is not SaleType.AUCTION:
        return Urgency.NONE
    left = time_left_minutes(listing, now)
    if left is None or left <= 0:
        return Urgency.NONE
    if left > policy.gate_minutes:
        return Urgency.WATCH
    return Urgency.QUIET


def effective_bid(listing: RawListing, policy: AuctionPolicy) -> Decimal:
    """Cote actuelle majorée de l'incrément — la valeur à comparer au seuil."""
    base = listing.current_bid if listing.current_bid is not None else listing.price
    return base + policy.bid_increment_eur


def max_bid(total_gb: int, hard_ceiling: Decimal, shipping: Decimal) -> Decimal:
    """Plafond à ne pas dépasser : (barrière absolue × capacité) − port estimé."""
    return (hard_ceiling * Decimal(total_gb) - shipping).quantize(Decimal("0.01"))
