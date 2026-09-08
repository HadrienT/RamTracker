"""WP03 — collecteur eBay contre charges utiles figées, sans réseau."""

from __future__ import annotations

import json

import httpx
import pytest

from ramtracker.collect.base import EbaySource
from ramtracker.collect.ebay import EbayCollector
from ramtracker.core.clock import utc_now
from ramtracker.core.config import get_settings
from ramtracker.core.errors import SourceAuthError, SourceBlocked, SourceSchemaChanged
from ramtracker.core.payloads import unpack
from tests.conftest import FIXTURES

pytestmark = pytest.mark.contract

_SEARCH = json.loads((FIXTURES / "payloads" / "ebay_search_fr.json").read_text())


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _token_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})


def _make(handler) -> EbayCollector:
    return EbayCollector(
        EbaySource(marketplaces=["EBAY_FR"], queries=["DDR4 ECC RDIMM"]),
        get_settings(),
        client=_client(handler),
    )


def test_parses_real_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return _token_ok(request)
        return httpx.Response(200, json=_SEARCH)

    result = _make(handler).fetch_recent(utc_now())
    assert result.raw_count == len(_SEARCH["itemSummaries"]) * 2  # achat + enchère
    listings = {listing.external_id: listing for listing in result.listings}
    assert listings["v1|1100000000002|0"].shipping is None  # port non annoncé
    assert listings["v1|1100000000003|0"].shipping == 0  # port gratuit annoncé
    for listing in result.listings:
        assert unpack(listing.raw_payload)  # décompressable


def test_empty_response_is_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return _token_ok(request)
        return httpx.Response(200, json={"total": 0, "itemSummaries": []})

    result = _make(handler).fetch_recent(utc_now())
    assert result.raw_count == 0
    assert result.listings == []


def test_429_is_source_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return _token_ok(request)
        return httpx.Response(429, json={})

    with pytest.raises(SourceBlocked):
        _make(handler).fetch_recent(utc_now())


def test_401_retries_once_then_auth_error() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return _token_ok(request)
        calls["n"] += 1
        return httpx.Response(401, json={})

    with pytest.raises(SourceAuthError):
        _make(handler).fetch_recent(utc_now())
    assert calls["n"] == 2


def test_missing_field_is_schema_changed_not_keyerror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return _token_ok(request)
        return httpx.Response(200, json={"nonsense": True})

    with pytest.raises(SourceSchemaChanged):
        _make(handler).fetch_recent(utc_now())


def test_multiple_queries_become_an_or_group() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return _token_ok(request)
        captured["q"] = dict(request.url.params)["q"]
        return httpx.Response(200, json={"total": 0, "itemSummaries": []})

    EbayCollector(
        EbaySource(marketplaces=["EBAY_FR"], queries=["DDR4 ECC RDIMM", "PC4-2400T"]),
        get_settings(),
        client=_client(handler),
    ).fetch_recent(utc_now())

    assert captured["q"] == "(DDR4 ECC RDIMM,PC4-2400T)"


def test_auction_without_price_uses_current_bid() -> None:
    payload = {
        "total": 1,
        "itemSummaries": [
            {
                "itemId": "v1|auction1|0",
                "title": "SK hynix 16Go DDR4 ECC RDIMM PC4-2400T",
                "itemWebUrl": "https://www.ebay.fr/itm/auction1",
                "buyingOptions": ["AUCTION"],
                "currentBidPrice": {"value": "16.15", "currency": "EUR"},
                "bidCount": 3,
                "itemEndDate": "2026-09-09T12:00:00.000Z",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return _token_ok(request)
        return httpx.Response(200, json=payload)

    result = _make(handler).fetch_recent(utc_now())
    listing = next(x for x in result.listings if x.external_id == "v1|auction1|0")
    assert str(listing.price) == "16.15"
    assert str(listing.current_bid) == "16.15"


def test_item_without_any_price_is_skipped_not_a_schema_error() -> None:
    payload = {
        "total": 1,
        "itemSummaries": [
            {
                "itemId": "v1|noprice|0",
                "title": "annonce sans prix",
                "itemWebUrl": "https://www.ebay.fr/itm/noprice",
                "buyingOptions": ["AUCTION"],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return _token_ok(request)
        return httpx.Response(200, json=payload)

    result = _make(handler).fetch_recent(utc_now())
    assert result.listings == []
