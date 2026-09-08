"""WP04 — decide : invariants I3, I4, I7, double barrière, mode observation, enchères."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from ramtracker.core.models import (
    Kind,
    MemorySpec,
    Method,
    PriceBasis,
    RawListing,
    SaleType,
    Urgency,
)
from ramtracker.decide import auction, market
from ramtracker.decide.policy import load_threshold_policy
from ramtracker.decide.thresholds import evaluate, evaluate_detailed

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _listing(**kw: object) -> RawListing:
    base = dict(
        source="ebay",
        external_id="1",
        spec_hash="h",
        url="u",
        title="t",
        description=None,
        price=Decimal("200"),
        currency="EUR",
        shipping=Decimal("10"),
        sale_type=SaleType.BUY_NOW,
        country="FR",
        posted_at=NOW,
        raw_payload=b"{}",
    )
    base.update(kw)
    return RawListing(**base)  # type: ignore[arg-type]


def _spec(**kw: object) -> MemorySpec:
    base = dict(
        module_capacity_gb=32,
        module_count=4,
        total_gb=128,
        kind=Kind.RDIMM,
        speed_mts=2133,
        price_basis=PriceBasis.LOT,
        confidence=0.95,
        method=Method.RULES,
    )
    base.update(kw)
    return MemorySpec(**base)  # type: ignore[arg-type]


@pytest.fixture
def policy():
    return load_threshold_policy()


def test_i3_unknown_basis_without_llm_never_deal(policy) -> None:
    spec = _spec(price_basis=PriceBasis.UNKNOWN, method=Method.RULES)
    assert evaluate(_listing(price=Decimal("50")), spec, {}, policy, NOW) is None


def test_unknown_basis_allowed_when_llm(policy) -> None:
    spec = _spec(price_basis=PriceBasis.UNKNOWN, method=Method.LLM)
    deal = evaluate(_listing(price=Decimal("200")), spec, {32: Decimal("6")}, policy, NOW)
    assert deal is not None


def test_i4_below_plausibility_floor_never_immediate(policy) -> None:
    spec = _spec()
    out = evaluate_detailed(_listing(price=Decimal("10")), spec, {}, policy, NOW, observation=True)
    assert out.deal is None
    assert out.send_to_llm is True


def test_absolute_barrier_blocks_expensive_market(policy) -> None:
    # 40 % de décote sur un marché à 12 €/Go -> €/Go ~ 7 -> au-dessus du plafond dur
    spec = _spec()
    deal = evaluate(_listing(price=Decimal("900")), spec, {32: Decimal("12")}, policy, NOW)
    assert deal is None


def test_relative_barrier_blocks_when_market_even_cheaper() -> None:
    spec = _spec()
    # €/Go ~ 1.64 sous le plafond, mais marché à 1.70 -> décote < min_discount.
    # Politique explicite : ce test porte sur la logique de barrière, pas sur la
    # valeur de min_discount dans thresholds.yaml.
    pol = _fixed_policy(barriers=_barriers(hard="5.00", min_discount=0.25))
    deal = evaluate(_listing(price=Decimal("200")), spec, {32: Decimal("1.70")}, pol, NOW)
    assert deal is None


def _barriers(hard: str = "5.00", min_discount: float = 0.0):
    from ramtracker.decide.policy import Barriers

    return Barriers(hard_ceiling_eur_per_gb=Decimal(hard), min_discount=min_discount)


def _fixed_policy(**over: object):
    """Politique explicite : découple ces tests des réglages de thresholds.yaml."""
    from ramtracker.decide.policy import Guards, ObservationMode, ThresholdPolicy

    base: dict[str, object] = dict(
        barriers=_barriers(),
        guards=Guards(plausibility_floor_eur_per_gb=Decimal("0.50"), min_total_gb=8),
        observation_mode=ObservationMode(enabled=False, until=date(2020, 1, 1)),
    )
    base.update(over)
    return ThresholdPolicy(**base)  # type: ignore[arg-type]


def test_unit_price_basis_scales_to_full_set() -> None:
    # 4x32 Go, prix affiché 99,50 € l'unité -> 398 € / 128 Go = 3,1094 €/Go.
    spec = _spec(price_basis=PriceBasis.UNIT)
    out = evaluate_detailed(
        _listing(price=Decimal("99.50"), shipping=Decimal("0")),
        spec,
        {32: Decimal("6")},
        _fixed_policy(),
        NOW,
        observation=False,
    )
    assert out.deal is not None
    assert out.deal.eur_per_gb == Decimal("3.1094")


def test_unit_price_basis_can_flip_a_deal_to_no_deal() -> None:
    listing = _listing(price=Decimal("99.50"), shipping=Decimal("0"))
    pol = _fixed_policy(barriers=_barriers(hard="2.00", min_discount=0.0))
    # En « lot » l'annonce passerait (0,78 €/Go) ; en « unité » (3,11 €/Go) elle est écartée.
    as_lot = evaluate_detailed(
        listing, _spec(price_basis=PriceBasis.LOT), {32: Decimal("6")}, pol, NOW, observation=False
    )
    as_unit = evaluate_detailed(
        listing, _spec(price_basis=PriceBasis.UNIT), {32: Decimal("6")}, pol, NOW, observation=False
    )
    assert as_lot.deal is not None
    assert as_unit.deal is None
    assert as_unit.reason == "above_hard_ceiling"


def test_observation_mode_ignores_relative_barrier(policy) -> None:
    spec = _spec()
    deal = evaluate_detailed(
        _listing(price=Decimal("200")),
        spec,
        {32: Decimal("1.70")},
        policy,
        NOW,
        observation=True,
    ).deal
    assert deal is not None
    assert deal.urgency is Urgency.IMMEDIATE


def test_i7_auction_far_from_end_is_watch(policy) -> None:
    listing = _listing(
        sale_type=SaleType.AUCTION,
        current_bid=Decimal("5"),
        ends_at=NOW + timedelta(days=6),
    )
    assert evaluate(listing, _spec(), {32: Decimal("6")}, policy, NOW) is None
    assert auction.gate(listing, NOW, policy.auction) is Urgency.WATCH


def test_auction_in_window_quiet(policy) -> None:
    listing = _listing(
        sale_type=SaleType.AUCTION,
        current_bid=Decimal("120"),
        ends_at=NOW + timedelta(minutes=30),
        price=Decimal("120"),
    )
    deal = evaluate(listing, _spec(), {32: Decimal("6")}, policy, NOW)
    assert deal is not None
    assert deal.urgency is Urgency.QUIET
    assert deal.max_bid is not None


def test_max_bid_formula() -> None:
    assert auction.max_bid(64, Decimal("2.50"), Decimal("9")) == Decimal("151.00")


def test_market_index_monotone_and_empty_safe() -> None:
    assert market.reference_for(32, {}) is None
    idx = {8: Decimal("5"), 16: Decimal("4"), 32: Decimal("3.5"), 64: Decimal("3")}
    assert market.reference_for(32, idx) == Decimal("3.5")
    assert market.reference_for(48, idx) in idx.values()


def test_percentile_monotone() -> None:
    vals = [Decimal(x) for x in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)]
    assert market._percentile(vals, 0.25) <= market._percentile(vals, 0.5)
    assert market._percentile(vals, 0.5) <= market._percentile(vals, 0.75)
