"""WP07 — préfiltre : invariant I1 (borne optimiste) + comportement."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ramtracker.extract.prefilter import best_case_eur_per_gb, optimistic_total_gb
from tests._corpus import make_listing

pytestmark = pytest.mark.property


def _real_total(entry: dict) -> int | None:
    exp = entry["expect"]
    if "total_gb" in exp:
        return int(exp["total_gb"])
    if "module_capacity_gb" in exp and "module_count" in exp:
        return int(exp["module_capacity_gb"]) * int(exp["module_count"])
    return None


@pytest.mark.golden
def test_i1_exhaustive_on_corpus(golden_corpus: list[dict]) -> None:
    """Pour toute annonce : optimistic_total_gb >= total_gb réel."""
    for entry in golden_corpus:
        real = _real_total(entry)
        if real is None:
            continue
        bound = optimistic_total_gb(entry["text"])
        if bound is None:
            continue  # ne borne rien -> ne préfiltre pas, acceptable
        assert bound >= real, f"{entry['text']!r}: borne {bound} < réel {real}"


@given(
    count=st.integers(min_value=1, max_value=16),
    cap=st.sampled_from([8, 16, 32, 64]),
    speed=st.sampled_from([2133, 2400, 2666]),
)
def test_i1_property_generated_titles(count: int, cap: int, speed: int) -> None:
    text = f"Lot de {count} barrettes {cap}Go DDR4 ECC REG {speed}"
    real = count * cap
    bound = optimistic_total_gb(text)
    assert bound is not None
    assert bound >= real


def test_rejects_when_best_case_above_ceiling() -> None:
    listing = make_listing("DDR4 ECC 16GB — module unique", price="180")
    best = best_case_eur_per_gb(listing, listing.title)
    assert best is not None
    assert best > Decimal("3.50")


def test_generous_bound_lets_big_lot_through() -> None:
    text = "512GB TOTAL (16x32GB) DDR4 ECC REG"
    listing = make_listing(text, price="1800")
    best = best_case_eur_per_gb(listing, text)
    # borne généreuse -> meilleur cas bas -> ne rejette pas
    assert best is None or best <= Decimal("3.50")


def test_none_when_no_capacity() -> None:
    assert optimistic_total_gb("RAM serveur ECC pas chère") is None
