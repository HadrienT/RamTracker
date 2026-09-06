"""Utilitaires partagés par les tests du corpus doré."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ramtracker.core.models import RawListing, SaleType


def make_listing(text: str, *, price: str = "200", source: str = "test") -> RawListing:
    """Construit un `RawListing` minimal à partir d'un titre du corpus."""
    return RawListing(
        source=source,
        external_id=str(abs(hash(text)) % 10_000_000),
        spec_hash="0" * 64,
        url="https://example.test/item",
        title=text,
        description=None,
        price=Decimal(price),
        currency="EUR",
        shipping=None,
        sale_type=SaleType.BUY_NOW,
        country="FR",
        posted_at=datetime(2026, 9, 1, tzinfo=UTC),
        raw_payload=b"{}",
    )


def matches(spec: Any, expect: dict[str, Any]) -> tuple[bool, str]:
    """Compare une spec produite au dictionnaire `expect` du corpus."""
    if "reject_reason" in expect:
        if spec.reject_reason == expect["reject_reason"]:
            return True, ""
        return False, f"reject_reason={spec.reject_reason!r} attendu {expect['reject_reason']!r}"

    for key, wanted in expect.items():
        if key in ("kind", "price_basis"):
            got = spec.__getattribute__(key).value
        else:
            got = getattr(spec, key)
        if got != wanted:
            return False, f"{key}={got!r} attendu {wanted!r}"
    return True, ""
