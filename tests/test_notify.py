"""WP05 — notify : gabarits, invariant I5, anti-spam."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ramtracker.core.models import (
    Deal,
    Kind,
    MemorySpec,
    Method,
    PriceBasis,
    RawListing,
    SaleType,
    Urgency,
)
from ramtracker.notify import ratelimit, templates
from ramtracker.notify.base import load_spam_policy

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


_LISTING_SQL = (
    "INSERT OR IGNORE INTO listings"
    "(source, external_id, spec_hash, url, title, price, currency, sale_type, country,"
    " posted_at, first_seen, last_seen, raw_payload) "
    "VALUES ('ebay', '1', 'h', 'u', 't', '200', 'EUR', 'buy_now', 'FR', ?, ?, ?, ?)"
)
_ALERT_SQL = (
    "INSERT INTO alerts(fingerprint, source, external_id, eur_per_gb, discount, "
    "urgency, price, sent_at) "
    "VALUES (?, 'ebay', '1', '1.60', 0.33, 'immediate', ?, ?)"
)


def _seed_listing(conn: object) -> None:
    conn.execute(_LISTING_SQL, (NOW.isoformat(), NOW.isoformat(), NOW.isoformat(), b"{}"))  # type: ignore[attr-defined]


def _deal(urgency: Urgency = Urgency.IMMEDIATE, price: str = "200", fp: str = "fp1") -> Deal:
    listing = RawListing(
        source="ebay",
        external_id="1",
        spec_hash="h",
        url="https://x/y",
        title="t",
        description=None,
        price=Decimal(price),
        currency="EUR",
        shipping=Decimal("9"),
        sale_type=SaleType.AUCTION if urgency is Urgency.QUIET else SaleType.BUY_NOW,
        current_bid=Decimal(price) if urgency is Urgency.QUIET else None,
        ends_at=datetime(2026, 10, 1, 13, tzinfo=UTC) if urgency is Urgency.QUIET else None,
        country="FR",
        posted_at=NOW,
        raw_payload=b"{}",
    )
    spec = MemorySpec(
        module_capacity_gb=32,
        module_count=4,
        total_gb=128,
        kind=Kind.RDIMM,
        speed_mts=2400,
        price_basis=PriceBasis.LOT,
        confidence=0.95,
        method=Method.RULES,
    )
    return Deal(
        listing=listing,
        spec=spec,
        total_cost=Decimal(price),
        eur_per_gb=Decimal("1.60"),
        market_ref=Decimal("2.40"),
        discount=0.33,
        urgency=urgency,
        max_bid=Decimal("400") if urgency is Urgency.QUIET else None,
        fingerprint=fp,
    )


def test_immediate_priority_and_open_button() -> None:
    n = templates.render(_deal(Urgency.IMMEDIATE))
    assert n.priority == 5
    assert any(a.label.startswith("Ouvrir") for a in n.actions)


def test_quiet_carries_max_bid() -> None:
    n = templates.render(_deal(Urgency.QUIET))
    assert n.priority == 2
    assert "plafond" in n.title or "400" in n.body


@pytest.mark.usefixtures("migrated_db")
def test_i5_one_alert_per_fingerprint() -> None:
    from ramtracker.core.db import session_scope

    policy = load_spam_policy()
    deal = _deal(price="200")
    with session_scope() as conn:
        _seed_listing(conn)
        assert ratelimit.decide(deal, conn, policy, NOW).allowed is True
        conn.execute(_ALERT_SQL, (deal.fingerprint, "200", NOW.isoformat()))
        assert ratelimit.decide(deal, conn, policy, NOW).allowed is False


@pytest.mark.usefixtures("migrated_db")
def test_re_alert_only_on_price_drop() -> None:
    from ramtracker.core.db import session_scope

    policy = load_spam_policy()
    with session_scope() as conn:
        _seed_listing(conn)
        conn.execute(_ALERT_SQL, ("fp1", "200", NOW.isoformat()))
        assert ratelimit.decide(_deal(price="195"), conn, policy, NOW).allowed is False
        assert ratelimit.decide(_deal(price="150"), conn, policy, NOW).allowed is True


@pytest.mark.usefixtures("migrated_db")
def test_quiet_hours_downgrade() -> None:
    from ramtracker.core.db import session_scope

    policy = load_spam_policy()
    night = datetime(2026, 10, 1, 23, 30, tzinfo=UTC)
    with session_scope() as conn:
        decision = ratelimit.decide(_deal(fp="night"), conn, policy, night)
    assert decision.allowed is True
    assert decision.priority == 3
