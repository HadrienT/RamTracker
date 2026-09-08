"""Collecteur eBay — API Browse officielle (WP03).

Source n°1 : officielle, 5 000 appels/jour, documentée. Le port n'est renvoyé
correctement que si `X-EBAY-C-ENDUSERCTX` porte le pays et le code postal —
sans lui le €/Go calculé est faux (blueprint/03-INTERFACES.md §3.4).

`[À CONFIRMER]` au spike WP00 : identifiant de catégorie, forme exacte de la
réponse JSON `item_summary/search`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from ramtracker.collect.base import CollectResult, EbaySource, QuantityHint
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

_log = get_logger("collect.ebay")

_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_ITEM_URL = "https://api.ebay.com/buy/browse/v1/item/"
_SCOPE = "https://api.ebay.com/oauth/api_scope"
_TOKEN_REFRESH_SKEW_S = 300


class _Token:
    __slots__ = ("expires_at", "value")

    def __init__(self, value: str, expires_at: datetime) -> None:
        self.value = value
        self.expires_at = expires_at

    def fresh(self, now: datetime) -> bool:
        return (self.expires_at - now).total_seconds() > _TOKEN_REFRESH_SKEW_S


class EbayCollector:
    """Implémente `Collector`. Une requête à la fois, jamais de parallélisme."""

    name = "ebay"

    def __init__(
        self,
        config: EbaySource,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._settings = settings
        self._client = client or httpx.Client(timeout=20.0)
        self._token_path: Path = settings.state_dir / "ebay_token.json"
        self._token: _Token | None = self._load_token()

    # -- jeton --------------------------------------------------------------------

    def _load_token(self) -> _Token | None:
        if not self._token_path.is_file():
            return None
        try:
            data = json.loads(self._token_path.read_text(encoding="utf-8"))
            return _Token(data["value"], datetime.fromisoformat(data["expires_at"]))
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def _store_token(self, token: _Token) -> None:
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(
            json.dumps({"value": token.value, "expires_at": token.expires_at.isoformat()}),
            encoding="utf-8",
        )

    def _mint_token(self) -> _Token:
        try:
            resp = self._client.post(
                _OAUTH_URL,
                data={"grant_type": "client_credentials", "scope": _SCOPE},
                auth=(
                    self._settings.ebay_client_id,
                    self._settings.ebay_client_secret.get_secret_value(),
                ),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise SourceUnavailable("eBay OAuth injoignable", source=self.name) from exc
        if resp.status_code in (401, 403):
            raise SourceAuthError("identifiants eBay refusés", source=self.name)
        if resp.status_code != 200:
            raise SourceUnavailable(
                "eBay OAuth en erreur", source=self.name, status=resp.status_code
            )
        body = resp.json()
        expires_in = int(body.get("expires_in", 7200))
        token = _Token(body["access_token"], utc_now() + timedelta(seconds=expires_in))
        self._store_token(token)
        _log.info("ebay.token.minted", expires_in=expires_in)
        return token

    def _bearer(self, force: bool = False) -> str:
        now = utc_now()
        if force or self._token is None or not self._token.fresh(now):
            self._token = self._mint_token()
        return self._token.value

    # -- requêtes ---------------------------------------------------------------

    def fetch_recent(self, since: datetime) -> CollectResult:
        started = utc_now()
        listings: list[RawListing] = []
        raw_count = 0
        for marketplace in self._config.marketplaces:
            for sale_filter, sort in (
                ("buyingOptions:{FIXED_PRICE|BEST_OFFER}", "newlyListed"),
                ("buyingOptions:{AUCTION}", "endingSoonest"),
            ):
                payload = self._search(marketplace, sale_filter, sort)
                items = _extract_items(payload)
                raw_count += len(items)
                for item in items:
                    parsed = _to_listing(item, marketplace, since)
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
            source=self.name,
            listings=listings,
            raw_count=raw_count,
            duration_ms=duration_ms,
        )

    def _search(self, marketplace: str, sale_filter: str, sort: str) -> dict[str, Any]:
        params = {
            "q": _or_query(self._config.queries),
            "filter": (
                f"{sale_filter},"
                f"price:[{self._config.price_range_eur[0]}.."
                f"{self._config.price_range_eur[1]}],priceCurrency:EUR"
            ),
            "sort": sort,
            "limit": str(self._config.limit),
        }
        if self._config.category_ids:
            params["category_ids"] = ",".join(self._config.category_ids)
        return self._get(_SEARCH_URL, params, marketplace)

    def _get(
        self, url: str, params: dict[str, str], marketplace: str, *, retried: bool = False
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._bearer()}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace,
        }
        if self._settings.ebay_zip:
            country = (
                "FR" if marketplace.endswith("FR") else marketplace.rsplit("_", maxsplit=1)[-1]
            )
            headers["X-EBAY-C-ENDUSERCTX"] = (
                f"contextualLocation=country={country},zip={self._settings.ebay_zip}"
            )
        _log.info("source.fetch.start", source=self.name, marketplace=marketplace)
        try:
            resp = self._client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise SourceUnavailable("eBay Browse injoignable", source=self.name) from exc

        if resp.status_code == 401 and not retried:
            self._bearer(force=True)
            return self._get(url, params, marketplace, retried=True)
        if resp.status_code == 401:
            raise SourceAuthError("jeton eBay refusé après rafraîchissement", source=self.name)
        if resp.status_code == 429:
            raise SourceBlocked("quota eBay atteint", source=self.name)
        if resp.status_code >= 500:
            raise SourceUnavailable("eBay 5xx", source=self.name, status=resp.status_code)
        if resp.status_code != 200:
            raise SourceUnavailable(
                "eBay réponse inattendue", source=self.name, status=resp.status_code
            )
        try:
            return dict(resp.json())
        except json.JSONDecodeError as exc:
            raise SourceSchemaChanged("réponse eBay non-JSON", source=self.name) from exc

    # -- résolution de quantité (lot vs unité) ---------------------------------

    def quantity_hint(self, external_id: str, country: str) -> QuantityHint | None:
        """`lotSize` + quantité disponible d'une annonce, via `getItem`.

        `item_summary/search` ne les renvoie pas ; il faut un appel dédié. Best
        effort : toute erreur renvoie `None` (on garde alors la base de prix des
        règles). Le seul champ qui compte est le rapport lot / multi-quantité.
        """
        marketplace = (
            f"EBAY_{country.upper()}" if len(country) == 2 else self._config.marketplaces[0]
        )
        headers = {
            "Authorization": f"Bearer {self._bearer()}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace,
        }
        try:
            resp = self._client.get(_ITEM_URL + external_id, headers=headers)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            _log.info("ebay.getitem.skipped", status=resp.status_code, external_id=external_id)
            return None
        try:
            body = dict(resp.json())
        except json.JSONDecodeError:
            return None
        qty = 0
        for avail in body.get("estimatedAvailabilities") or []:
            for key in ("estimatedAvailableQuantity", "estimatedRemainingQuantity"):
                value = avail.get(key)
                if isinstance(value, int):
                    qty = max(qty, value)
        lot = body.get("lotSize")
        return QuantityHint(lot_size=lot if isinstance(lot, int) else 0, available_qty=qty)


def _or_query(queries: list[str]) -> str:
    """Combine plusieurs recherches en un `q` unique.

    Concaténées par une espace, les entrées formeraient un ET implicite qui ne
    remonte quasiment rien (« DDR4 ECC RDIMM PC4-2133P PC4-2400T » ne matche
    aucune annonce). eBay Browse admet un OU explicite : `q=(phrase1,phrase2)`.
    """
    cleaned = [q.strip() for q in queries if q.strip()]
    if not cleaned:
        return "DDR4 ECC"
    if len(cleaned) == 1:
        return cleaned[0]
    return "(" + ",".join(cleaned) + ")"


def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "itemSummaries" not in payload and "total" not in payload:
        raise SourceSchemaChanged(
            "clé 'itemSummaries'/'total' absente de la réponse eBay", source="ebay"
        )
    return list(payload.get("itemSummaries", []))


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


def _to_listing(item: dict[str, Any], marketplace: str, since: datetime) -> RawListing | None:
    try:
        external_id = str(item["itemId"])
        title = str(item["title"])
        url = str(item["itemWebUrl"])
    except KeyError as exc:
        raise SourceSchemaChanged(
            "champ obligatoire absent d'une annonce eBay", source="ebay", missing=str(exc)
        ) from exc

    # Les enchères n'exposent pas `price` ; leur prix courant est `currentBidPrice`.
    # Une annonce sans aucune information de prix est ignorée (pas une rupture de
    # schéma : la plupart des annonces en ont une).
    price_block = item.get("price") or item.get("currentBidPrice")
    if not isinstance(price_block, dict) or "value" not in price_block:
        return None
    price = _decimal(price_block["value"])
    currency = str(price_block.get("currency", "EUR"))
    if price is None:
        return None

    options = item.get("buyingOptions", ["FIXED_PRICE"])
    if "AUCTION" in options:
        sale_type = SaleType.AUCTION
    elif "BEST_OFFER" in options:
        sale_type = SaleType.BEST_OFFER
    else:
        sale_type = SaleType.BUY_NOW

    shipping, free_announced = _shipping(item)
    ends_at = _parse_dt(item.get("itemEndDate"))
    posted_at = _parse_dt(item.get("itemCreationDate")) or utc_now()
    description = item.get("shortDescription")

    ctx = {"free_shipping": free_announced}
    return RawListing.model_validate(
        {
            "source": "ebay",
            "external_id": external_id,
            "spec_hash": spec_hash(title, description),
            "url": url,
            "title": title,
            "description": description,
            "price": price,
            "currency": currency,
            "shipping": shipping,
            "sale_type": sale_type,
            "current_bid": _decimal(
                (item.get("currentBidPrice") or {}).get("value")
                if isinstance(item.get("currentBidPrice"), dict)
                else None
            ),
            "ends_at": ends_at,
            "seller_id": str((item.get("seller") or {}).get("username") or "") or None,
            "country": str(item.get("itemLocation", {}).get("country", "FR")),
            "posted_at": posted_at,
            "raw_payload": pack(json.dumps(item, ensure_ascii=False).encode("utf-8")),
        },
        context=ctx,
    )


def _shipping(item: dict[str, Any]) -> tuple[Decimal | None, bool]:
    """Renvoie (montant, gratuité_annoncée). `None` si la source ne dit rien (N4)."""
    options = item.get("shippingOptions")
    if not options:
        return None, False
    cost = (options[0] or {}).get("shippingCost")
    if not isinstance(cost, dict) or cost.get("value") is None:
        return None, False
    amount = _decimal(cost["value"])
    if amount is not None and amount == 0:
        return Decimal("0"), True
    return amount, False


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
