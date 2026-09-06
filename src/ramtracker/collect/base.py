"""Le contrat `Collector` — trois lignes — et le schéma de `sources.yaml`."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ramtracker.core.models import RawListing


class CollectResult(BaseModel):
    """Sortie d'un collecteur. `raw_count` est rempli même si `listings` est vide."""

    source: str
    listings: list[RawListing]
    raw_count: int
    duration_ms: int
    challenged: bool = False


@runtime_checkable
class Collector(Protocol):
    name: str

    def fetch_recent(self, since: datetime) -> CollectResult: ...


# --- schéma de configs/sources.yaml -------------------------------------------------


class EbaySource(BaseModel):
    enabled: bool = True
    interval_min: int = 10
    jitter_min: int = 2
    marketplaces: list[str] = Field(default_factory=lambda: ["EBAY_FR"])
    category_ids: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    price_range_eur: tuple[int, int] = (15, 3000)
    limit: int = 200


class RedditSource(BaseModel):
    enabled: bool = False
    interval_min: int = 15
    jitter_min: int = 3
    subreddits: list[str] = Field(default_factory=lambda: ["homelabsales"])
    shippable_from: list[str] = Field(default_factory=list)


class LeboncoinSource(BaseModel):
    enabled: bool = False
    interval_min: int = 75
    jitter_min: int = 20
    category: int = 17
    queries: list[str] = Field(default_factory=list)
    impersonate: str = "chrome"
    max_pages: int = 1


class SourcesConfig(BaseModel):
    ebay: EbaySource = Field(default_factory=EbaySource)
    reddit: RedditSource = Field(default_factory=RedditSource)
    leboncoin: LeboncoinSource = Field(default_factory=LeboncoinSource)

    def interval_for(self, name: str) -> tuple[int, int]:
        section = getattr(self, name)
        return section.interval_min, section.jitter_min

    def enabled_sources(self) -> list[str]:
        return [n for n in ("ebay", "reddit", "leboncoin") if getattr(self, n).enabled]
