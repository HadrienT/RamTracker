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
