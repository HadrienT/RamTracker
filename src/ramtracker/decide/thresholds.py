"""Double barrière, garde-fous, mode observation (WP04 §3).

`evaluate` retourne `None` quand il ne faut pas alerter. L'ordre des règles est
**normatif** (blueprint/03-INTERFACES.md §5) et ne doit pas être réarrangé.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from ramtracker.core.hashing import fingerprint
from ramtracker.core.logging import get_logger
from ramtracker.core.models import (
    Deal,
    MemorySpec,
    Method,
    PriceBasis,
    RawListing,
    SaleType,
    Urgency,
)
from ramtracker.core.money import eur_per_gb, to_eur, total_cost
from ramtracker.decide import auction, market
from ramtracker.decide.policy import ThresholdPolicy

_log = get_logger("decide.thresholds")


class EvalOutcome:
    """Résultat détaillé — `deal` peut être `None` tout en demandant un renvoi au LLM."""

    __slots__ = ("deal", "reason", "send_to_llm")

    def __init__(
        self, deal: Deal | None, send_to_llm: bool = False, reason: str | None = None
    ) -> None:
        self.deal = deal
        self.send_to_llm = send_to_llm
        self.reason = reason


def evaluate_detailed(
    listing: RawListing,
    spec: MemorySpec,
    index: Mapping[int, Decimal],
    policy: ThresholdPolicy,
    now: datetime,
    *,
    observation: bool,
) -> EvalOutcome:
    """Applique les règles dans l'ordre normatif et renvoie un `EvalOutcome`."""
    rates = policy.currency.rates_to_eur

    # 1 — spec rejetée.
    if not spec.qualified:
        return EvalOutcome(None, reason=spec.reject_reason)

    # 2 — base de prix inconnue sans passage LLM (interdit n°5).
    if spec.price_basis is PriceBasis.UNKNOWN and spec.method is not Method.LLM:
        return EvalOutcome(None, reason="price_basis_unknown")

    if spec.total_gb is None or spec.total_gb <= 0:
        return EvalOutcome(None, reason="total_gb_unknown")

    price_eur = to_eur(listing.price, listing.currency, rates)
    shipping_eur = (
        to_eur(listing.shipping, listing.currency, rates) if listing.shipping is not None else None
    )
    cost = total_cost(
        price_eur, shipping_eur, estimate_when_unknown=policy.shipping.default_estimate_eur
    )
    per_gb = eur_per_gb(cost.total, spec.total_gb)

    # 3 — prix implausible : bug de parsing, renvoi au LLM.
    if per_gb < policy.guards.plausibility_floor_eur_per_gb:
        return EvalOutcome(None, send_to_llm=True, reason="below_plausibility_floor")

    # 4 — volume minimal.
    if spec.total_gb < policy.guards.min_total_gb:
        return EvalOutcome(None, reason="below_min_total_gb")

    ref = market.reference_for(spec.module_capacity_gb or spec.total_gb, index)
    discount = 0.0 if ref is None or ref <= 0 else 1.0 - float(per_gb / ref)

    # 5 — barrière absolue.
    if per_gb >= policy.barriers.hard_ceiling_eur_per_gb:
        return EvalOutcome(None, reason="above_hard_ceiling")

    # 6 — barrière relative (ignorée en mode observation).
    if not observation and (ref is None or discount <= policy.barriers.min_discount):
        return EvalOutcome(None, reason="insufficient_discount")

    fp = fingerprint(listing.seller_id, spec.module_capacity_gb, spec.module_count, price_eur)
    est_shipping = cost.shipping_used

    # 7 — enchères.
    if listing.sale_type is SaleType.AUCTION:
        urgency = auction.gate(listing, now, policy.auction)
        if urgency is Urgency.WATCH or urgency is Urgency.NONE:
            return EvalOutcome(None, reason=f"auction_{urgency.value}")
        bid = auction.effective_bid(listing, policy.auction)
        bid_per_gb = eur_per_gb(
            total_cost(
                to_eur(bid, listing.currency, rates),
                shipping_eur,
                estimate_when_unknown=policy.shipping.default_estimate_eur,
            ).total,
            spec.total_gb,
        )
        if bid_per_gb >= policy.barriers.hard_ceiling_eur_per_gb:
            return EvalOutcome(None, reason="auction_bid_above_ceiling")
        deal = Deal(
            listing=listing,
            spec=spec,
            total_cost=cost.total,
            eur_per_gb=per_gb,
            market_ref=ref,
            discount=discount,
            urgency=Urgency.QUIET,
            max_bid=auction.max_bid(
                spec.total_gb, policy.barriers.hard_ceiling_eur_per_gb, est_shipping
            ),
            fingerprint=fp,
            shipping_estimated=cost.shipping_estimated,
        )
        return EvalOutcome(deal)

    deal = Deal(
        listing=listing,
        spec=spec,
        total_cost=cost.total,
        eur_per_gb=per_gb,
        market_ref=ref,
        discount=discount,
        urgency=Urgency.IMMEDIATE,
        max_bid=None,
        fingerprint=fp,
        shipping_estimated=cost.shipping_estimated,
    )
    _log.info(
        "decide.evaluated",
        listing_id=f"{listing.source}:{listing.external_id}",
        eur_per_gb=str(per_gb),
        discount=round(discount, 3),
        urgency=deal.urgency.value,
    )
    return EvalOutcome(deal)


def evaluate(
    listing: RawListing,
    spec: MemorySpec,
    index: Mapping[int, Decimal],
    policy: ThresholdPolicy,
    now: datetime,
    *,
    observation: bool = False,
) -> Deal | None:
    """Vue simple du contrat 03 §5 : renvoie un `Deal` ou `None`."""
    return evaluate_detailed(listing, spec, index, policy, now, observation=observation).deal


def in_observation_mode(policy: ThresholdPolicy, now: datetime, sample_size: int) -> bool:
    """Mode observation : date non atteinte, ou échantillon insuffisant."""
    if policy.observation_mode.enabled and now.date() < policy.observation_mode.until:
        return True
    return sample_size < policy.market_index.min_sample_size
