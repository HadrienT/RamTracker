"""Collecteur Leboncoin — impersonation TLS, jamais navigateur par défaut (WP08).

Les données sont déjà dans le HTML (`<script id="__NEXT_DATA__">`). `curl_cffi`
en `impersonate="chrome"` corrige l'empreinte JA3 ; il n'y a rien à rendre.
Le défi anti-bot est un état de premier ordre : `SourceBlocked` + `challenged`,
jamais de reprise (c'est `runtime.breaker`).

`[À CONFIRMER]` au spike WP00 : les deux chemins JSON.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ramtracker.collect.base import CollectResult, LeboncoinSource
from ramtracker.core.clock import utc_now
from ramtracker.core.errors import SourceBlocked, SourceSchemaChanged, SourceUnavailable
from ramtracker.core.hashing import spec_hash
from ramtracker.core.logging import get_logger
from ramtracker.core.models import RawListing, SaleType
from ramtracker.core.payloads import pack

_log = get_logger("collect.leboncoin")

_SEARCH_URL = "https://www.leboncoin.fr/recherche"
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)
_DATADOME_MARKERS = ("datadome", "geo.captcha-delivery.com", "dd_cookie")
# [À CONFIRMER] au spike WP00
_AD_PATHS = (
    ("props", "pageProps", "searchData", "ads"),
    ("props", "pageProps", "initialProps", "searchData", "ads"),
)


class LeboncoinCollector:
    """Implémente `Collector`. Une requête à la fois, `max_pages: 1`, gigue amont."""

    name = "leboncoin"

    def __init__(self, config: LeboncoinSource, *, session: Any | None = None) -> None:
        self._config = config
        self._session = session or _default_session(config.impersonate)

    def fetch_recent(self, since: datetime) -> CollectResult:
        started = utc_now()
        query = " ".join(self._config.queries) if self._config.queries else "DDR4 ECC"
        params = {
            "text": query,
            "category": str(self._config.category),
            "sort": "time",
        }
        _log.info("source.fetch.start", source=self.name)
        try:
            resp = self._session.get(_SEARCH_URL, params=params, timeout=25)
        except Exception as exc:  # curl_cffi lève ses propres types
            raise SourceUnavailable("Leboncoin injoignable", source=self.name) from exc

        body = resp.text
        if resp.status_code == 403 or _looks_challenged(body):
            _log.warning("source.challenged", source=self.name, status=resp.status_code)
            raise SourceBlocked("défi DataDome", source=self.name, challenged=True)
        if resp.status_code != 200:
            raise SourceUnavailable(
                "Leboncoin réponse inattendue", source=self.name, status=resp.status_code
            )

        ads = _extract_ads(body)
        listings = [listing for ad in ads if (listing := _to_listing(ad)) is not None]
        duration_ms = int((utc_now() - started).total_seconds() * 1000)
        _log.info(
            "source.fetch.done",
            source=self.name,
            raw_count=len(ads),
            new_count=len(listings),
            duration_ms=duration_ms,
            challenged=False,
        )
        return CollectResult(
            source=self.name,
            listings=listings,
            raw_count=len(ads),
            duration_ms=duration_ms,
        )


def _default_session(impersonate: str) -> Any:
    from curl_cffi import requests  # import tardif : dépendance lourde

    return requests.Session(impersonate=impersonate)


def _looks_challenged(body: str) -> bool:
    low = body.lower()
    return any(marker in low for marker in _DATADOME_MARKERS)


def _extract_ads(html: str) -> list[dict[str, Any]]:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise SourceSchemaChanged("__NEXT_DATA__ absent de la page", source="leboncoin")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SourceSchemaChanged("__NEXT_DATA__ non-JSON", source="leboncoin") from exc
    for path in _AD_PATHS:
        node: Any = data
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, list):
            return node
    raise SourceSchemaChanged(
        "aucun chemin JSON connu ne contient les annonces", source="leboncoin"
    )


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


def _to_listing(ad: dict[str, Any]) -> RawListing | None:
    try:
        external_id = str(ad["list_id"])
        title = str(ad["subject"])
        url = str(ad.get("url") or f"https://www.leboncoin.fr/ad/{external_id}")
    except KeyError as exc:
        raise SourceSchemaChanged(
            "champ obligatoire absent d'une annonce Leboncoin",
            source="leboncoin",
            missing=str(exc),
        ) from exc

    price_list = ad.get("price") or []
    price = _decimal(price_list[0]) if price_list else None
    if price is None:
        return None
    description = ad.get("body")
    location = ad.get("location") or {}
    posted = _parse_dt(ad.get("index_date")) or utc_now()
    owner = ad.get("owner") or {}

    # Remise en main propre : le port est INCONNU, jamais 0 (N4).
    return RawListing.model_validate(
        {
            "source": "leboncoin",
            "external_id": external_id,
            "spec_hash": spec_hash(title, description),
            "url": url,
            "title": title,
            "description": description,
            "price": price,
            "currency": "EUR",
            "shipping": None,
            "sale_type": SaleType.BUY_NOW,
            "seller_id": str(owner.get("user_id") or "") or None,
            "country": str(location.get("country_id") or "FR"),
            "posted_at": posted,
            "raw_payload": pack(json.dumps(ad, ensure_ascii=False).encode("utf-8")),
        }
    )


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
