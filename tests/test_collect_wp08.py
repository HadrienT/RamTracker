"""WP08 — collecteurs Leboncoin (DataDome) & Reddit, sans réseau."""

from __future__ import annotations

import httpx
import pytest

from ramtracker.collect.base import LeboncoinSource, RedditSource
from ramtracker.collect.leboncoin import LeboncoinCollector
from ramtracker.collect.reddit import RedditCollector
from ramtracker.core.clock import utc_now
from ramtracker.core.config import get_settings
from ramtracker.core.errors import SourceBlocked, SourceSchemaChanged
from tests.conftest import FIXTURES

pytestmark = pytest.mark.contract

_LBC_HTML = (FIXTURES / "payloads" / "leboncoin_recherche.html").read_text()
_REDDIT_JSON = (FIXTURES / "payloads" / "reddit_new.json").read_text()


class _FakeResp:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text


class _FakeSession:
    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp
        self.calls = 0

    def get(self, url: str, **kw: object) -> _FakeResp:
        self.calls += 1
        return self._resp


def test_leboncoin_parses_next_data() -> None:
    collector = LeboncoinCollector(
        LeboncoinSource(queries=["DDR4 ECC"]), session=_FakeSession(_FakeResp(200, _LBC_HTML))
    )
    result = collector.fetch_recent(utc_now())
    assert result.raw_count == 2
    assert {listing.external_id for listing in result.listings} == {"2600000001", "2600000002"}
    for listing in result.listings:
        assert listing.shipping is None  # remise en main propre : jamais 0


def test_leboncoin_datadome_marker_is_blocked() -> None:
    body = "<html>request blocked by geo.captcha-delivery.com datadome</html>"
    collector = LeboncoinCollector(LeboncoinSource(), session=_FakeSession(_FakeResp(200, body)))
    with pytest.raises(SourceBlocked):
        collector.fetch_recent(utc_now())


def test_leboncoin_403_is_blocked_single_request() -> None:
    session = _FakeSession(_FakeResp(403, "forbidden"))
    collector = LeboncoinCollector(LeboncoinSource(), session=session)
    with pytest.raises(SourceBlocked):
        collector.fetch_recent(utc_now())
    assert session.calls == 1  # aucune reprise immédiate


def test_leboncoin_schema_change() -> None:
    collector = LeboncoinCollector(
        LeboncoinSource(),
        session=_FakeSession(_FakeResp(200, "<html>no next data here</html>")),
    )
    with pytest.raises(SourceSchemaChanged):
        collector.fetch_recent(utc_now())


def test_reddit_region_filter_keeps_out_of_zone_for_index_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "access_token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, content=_REDDIT_JSON)

    import os

    os.environ["REDDIT_CLIENT_ID"] = "cid"
    os.environ["REDDIT_CLIENT_SECRET"] = "csecret"
    os.environ["REDDIT_USER_AGENT"] = "ramtracker-test/0.1"
    get_settings.cache_clear()

    collector = RedditCollector(
        RedditSource(subreddits=["homelabsales"], shippable_from=["DE", "EU", "FR"]),
        get_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = collector.fetch_recent(utc_now())
    by_id = {listing.external_id: listing for listing in result.listings}
    assert by_id["abc123"].alert_eligible is True  # DE -> alerte possible
    assert by_id["def456"].alert_eligible is False  # USA -> indice seulement
