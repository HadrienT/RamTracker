"""Collecteur Reddit — r/homelabsales (WP08).

Traité en priorité comme **capteur de prix** pour l'indice de marché. Seules les
annonces expédiables depuis l'Europe (`shippable_from`) remontent à l'alerte ;
les autres sont marquées `region_out` et servent uniquement l'indice.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from ramtracker.collect.base import CollectResult, RedditSource
from ramtracker.core.clock import utc_now
from ramtracker.core.config import Settings
from ramtracker.core.errors import (
    SourceAuthError,
    SourceBlocked,
    SourceSchemaChanged,
    SourceUnavailable,
)
from ramtracker.core.hashing import spec_hash
from ramtracker.core.logging import get_logger
from ramtracker.core.models import RawListing, SaleType
from ramtracker.core.payloads import pack

_log = get_logger("collect.reddit")

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_BASE = "https://oauth.reddit.com"
_TITLE_RE = re.compile(r"\[([A-Z]{2}(?:-[A-Z]{2})?|USA|US|EU|UK|CA|W|H)\]", re.IGNORECASE)
_HW_RE = re.compile(r"\[H\](.*?)\[W\]", re.IGNORECASE | re.DOTALL)
_PRICE_RE = re.compile(r"(?:€|EUR|\$|USD|£|GBP)\s?([0-9][0-9.,]*)", re.IGNORECASE)


class RedditCollector:
    name = "reddit"

    def __init__(
        self, config: RedditSource, settings: Settings, *, client: httpx.Client | None = None
    ) -> None:
        self._config = config
        self._settings = settings
        self._client = client or httpx.Client(timeout=20.0)
        self._bearer: str | None = None

    def _token(self) -> str:
        if self._bearer:
            return self._bearer
        cid = self._settings.reddit_client_id
        secret = self._settings.reddit_client_secret
        ua = self._settings.reddit_user_agent
        if not (cid and secret and ua):
            raise SourceAuthError("identifiants Reddit absents", source=self.name)
        try:
            resp = self._client.post(
                _TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(cid, secret.get_secret_value()),
                headers={"User-Agent": ua},
            )
        except httpx.HTTPError as exc:
            raise SourceUnavailable("Reddit OAuth injoignable", source=self.name) from exc
        if resp.status_code in (401, 403):
            raise SourceAuthError("OAuth Reddit refusé", source=self.name)
        if resp.status_code != 200:
            raise SourceUnavailable(
                "Reddit OAuth erreur", source=self.name, status=resp.status_code
            )
        self._bearer = str(resp.json()["access_token"])
        return self._bearer

    def fetch_recent(self, since: datetime) -> CollectResult:
        started = utc_now()
        ua = self._settings.reddit_user_agent or "ramtracker/0.1"
        listings: list[RawListing] = []
        raw_count = 0
        for subreddit in self._config.subreddits:
            _log.info("source.fetch.start", source=self.name, subreddit=subreddit)
            try:
                resp = self._client.get(
                    f"{_BASE}/r/{subreddit}/new",
                    params={"limit": "100"},
                    headers={"Authorization": f"Bearer {self._token()}", "User-Agent": ua},
                )
            except httpx.HTTPError as exc:
                raise SourceUnavailable("Reddit injoignable", source=self.name) from exc
            if resp.status_code == 429:
                raise SourceBlocked("quota Reddit atteint", source=self.name)
            if resp.status_code != 200:
                raise SourceUnavailable(
                    "Reddit réponse inattendue", source=self.name, status=resp.status_code
                )
            children = _children(resp.json())
            raw_count += len(children)
            for child in children:
                parsed = _to_listing(child.get("data", {}), self._config.shippable_from)
                if parsed is not None:
                    listings.append(parsed)
        duration_ms = int((utc_now() - started).total_seconds() * 1000)
        _log.info(
            "source.fetch.done",
            source=self.name,
            raw_count=raw_count,
            new_count=len(listings),
            duration_ms=duration_ms,
            challenged=False,
        )
        return CollectResult(
            source=self.name, listings=listings, raw_count=raw_count, duration_ms=duration_ms
        )


def _children(payload: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return list(payload["data"]["children"])
    except (KeyError, TypeError) as exc:
        raise SourceSchemaChanged("structure listing Reddit inattendue", source="reddit") from exc


def _decimal(raw: str) -> Decimal | None:
    cleaned = raw.replace(",", "").rstrip(".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _shippable(title: str, allow: list[str]) -> bool:
    if not allow:
        return True
    tags = {t.upper() for t in _TITLE_RE.findall(title)}
    allow_up = {a.upper() for a in allow}
    if tags & allow_up:
        return True
    # Pas de tag de pays reconnu et une mention USA/US → hors zone.
    return not ({"USA", "US", "CA"} & tags)


def _to_listing(data: dict[str, Any], shippable_from: list[str]) -> RawListing | None:
    title = str(data.get("title") or "")
    if "[W]" not in title.upper() and "[H]" not in title.upper():
        return None
    external_id = str(data.get("id") or "")
    if not external_id:
        return None
    hw = _HW_RE.search(title)
    for_sale = hw.group(1).strip() if hw else title
    price_match = _PRICE_RE.search(f"{title} {data.get('selftext', '')}")
    price = _decimal(price_match.group(1)) if price_match else None
    if price is None:
        return None
    description = data.get("selftext") or None
    posted = datetime.fromtimestamp(float(data.get("created_utc", 0)), tz=UTC)

    return RawListing.model_validate(
        {
            "source": "reddit",
            "external_id": external_id,
            "spec_hash": spec_hash(for_sale, description),
            "url": f"https://reddit.com{data.get('permalink', '')}",
            "title": for_sale,
            "description": description,
            "price": price,
            "currency": "USD" if "$" in title or "USD" in title.upper() else "EUR",
            "shipping": None,
            "sale_type": SaleType.BUY_NOW,
            "seller_id": str(data.get("author") or "") or None,
            "country": "US",
            "posted_at": posted,
            "raw_payload": pack(json.dumps(data, ensure_ascii=False).encode("utf-8")),
            # Hors zone d'expédition : nourrit l'indice, jamais d'alerte.
            "alert_eligible": _shippable(title, shippable_from),
        }
    )
