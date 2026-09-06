"""Invariants I1 → I7 (blueprint/08-TESTING.md §2). Jamais désactivés."""

from __future__ import annotations

import builtins
import socket
import sqlite3
from datetime import UTC, datetime, timedelta
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
from ramtracker.core.money import total_cost

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_i2_extract_does_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """`extract` (hors extract.llm) ne fait aucune I/O."""

    def boom(*_a: object, **_k: object) -> object:
        raise AssertionError("I/O interdite dans extract")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(sqlite3, "connect", boom)
    real_open = builtins.open
    monkeypatch.setattr(
        builtins,
        "open",
        lambda *a, **k: boom() if "ramtracker/extract" in str(a[0]) else real_open(*a, **k),
    )

    from ramtracker.extract import cascade, coherence, grammar, partnum, prefilter, qualify
    from ramtracker.extract.compat import CompatMatrix

    text = "Lot de 4 x 16 Go DDR4 ECC REG 2133 M393A2G40EB1-CPB"
    grammar.parse(text)
    partnum.decode(text)
    coherence.check(grammar.parse(text), text)
    qualify.reject_by_keywords(text, CompatMatrix())
    prefilter.optimistic_total_gb(text)
    listing = RawListing(
        source="t",
        external_id="1",
        spec_hash="h",
        url="u",
        title=text,
        description=None,
        price=Decimal("200"),
        currency="EUR",
        shipping=None,
        sale_type=SaleType.BUY_NOW,
        country="FR",
        posted_at=NOW,
        raw_payload=b"{}",
    )
    cascade.run(listing, CompatMatrix(), None, min_confidence=0.8)


def test_i6_shipping_none_vs_zero_differ() -> None:
    none_cost = total_cost(Decimal("100"), None, estimate_when_unknown=Decimal("12")).total
    zero_cost = total_cost(Decimal("100"), Decimal("0"), estimate_when_unknown=Decimal("12")).total
    assert none_cost != zero_cost


def test_i3_i4_i7_via_decide() -> None:
    from ramtracker.decide.policy import load_threshold_policy
    from ramtracker.decide.thresholds import evaluate, evaluate_detailed

    policy = load_threshold_policy()

    def listing(**kw: object) -> RawListing:
        base = dict(
            source="ebay",
            external_id="1",
            spec_hash="h",
            url="u",
            title="t",
            description=None,
            price=Decimal("200"),
            currency="EUR",
            shipping=Decimal("9"),
            sale_type=SaleType.BUY_NOW,
            country="FR",
            posted_at=NOW,
            raw_payload=b"{}",
        )
        base.update(kw)
        return RawListing(**base)  # type: ignore[arg-type]

    spec = MemorySpec(
        module_capacity_gb=32,
        module_count=4,
        total_gb=128,
        kind=Kind.RDIMM,
        speed_mts=2133,
        price_basis=PriceBasis.UNKNOWN,
        confidence=0.9,
        method=Method.RULES,
    )
    # I3
    assert evaluate(listing(), spec, {}, policy, NOW) is None
    # I4
    out = evaluate_detailed(
        listing(price=Decimal("5")),
        spec.model_copy(update={"price_basis": PriceBasis.LOT}),
        {},
        policy,
        NOW,
        observation=True,
    )
    assert out.deal is None or out.deal.urgency is not Urgency.IMMEDIATE
    # I7
    auction = listing(
        sale_type=SaleType.AUCTION,
        current_bid=Decimal("5"),
        ends_at=NOW + timedelta(days=6),
    )
    assert (
        evaluate(
            auction,
            spec.model_copy(update={"price_basis": PriceBasis.LOT}),
            {32: Decimal("6")},
            policy,
            NOW,
        )
        is None
    )
