"""Les trois DTO et leurs énumérations — blueprint/03-INTERFACES.md §1.

Tous immuables (`frozen=True`). Un étage du pipeline retourne un nouvel objet,
il ne mute jamais son entrée. Aucune règle de décision ici.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SaleType(StrEnum):
    BUY_NOW = "buy_now"
    AUCTION = "auction"
    BEST_OFFER = "best_offer"


class Kind(StrEnum):
    RDIMM = "rdimm"
    LRDIMM = "lrdimm"
    UDIMM_ECC = "udimm_ecc"
    UNKNOWN = "unknown"


class PriceBasis(StrEnum):
    LOT = "lot"
    UNIT = "unit"
    UNKNOWN = "unknown"


class Method(StrEnum):
    PART_NUMBER = "part_number"
    RULES = "rules"
    LLM = "llm"


class Urgency(StrEnum):
    IMMEDIATE = "immediate"
    QUIET = "quiet"
    WATCH = "watch"
    NONE = "none"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class RawListing(_Frozen):
    """Une offre telle que collectée, normalisée mais non interprétée."""

    source: str
    external_id: str
    spec_hash: str
    url: str
    title: str
    description: str | None
    price: Decimal
    currency: str
    shipping: Decimal | None
    sale_type: SaleType
    current_bid: Decimal | None = None
    ends_at: datetime | None = None
    seller_id: str | None = None
    country: str
    posted_at: datetime
    raw_payload: bytes
    # Additif hors contrat 03 §1 : un collecteur peut marquer une annonce comme
    # non éligible à l'alerte tout en la laissant nourrir l'indice de marché
    # (Reddit hors zone d'expédition, WP08 §2). Défaut : éligible.
    alert_eligible: bool = True

    @model_validator(mode="after")
    def _guard_shipping(self) -> Self:
        """`shipping=None` (inconnu) et `shipping=0` (gratuit) restent distincts (N4).

        Un port négatif est toujours invalide. La discipline « passer `None` quand
        le port est inconnu, jamais `0` » est de la responsabilité des collecteurs
        et vérifiée par leurs tests de contrat.
        """
        if self.shipping is not None and self.shipping < 0:
            raise ValueError("shipping ne peut pas être négatif")
        return self

    @model_validator(mode="after")
    def _guard_aware_datetimes(self) -> Self:
        for name in ("ends_at", "posted_at"):
            value: datetime | None = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} doit être aware UTC")
        if self.sale_type is SaleType.AUCTION and self.ends_at is None:
            raise ValueError("une enchère doit porter ends_at")
        return self


class MemorySpec(_Frozen):
    """Le résultat de l'extraction."""

    module_capacity_gb: int | None = None
    module_count: int = 1
    total_gb: int | None = None
    kind: Kind = Kind.UNKNOWN
    speed_mts: int | None = None
    ranks: str | None = None
    part_number: str | None = None
    price_basis: PriceBasis = PriceBasis.UNKNOWN
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    method: Method = Method.RULES
    reject_reason: str | None = None

    @property
    def qualified(self) -> bool:
        return self.reject_reason is None

    def with_confidence(self, value: float) -> MemorySpec:
        return self.model_copy(update={"confidence": max(0.0, min(1.0, value))})

    def rejected(self, reason: str) -> MemorySpec:
        return self.model_copy(update={"reject_reason": reason})


class Deal(_Frozen):
    """Une spec qualifiée à laquelle un €/Go et une décote ont été attribués."""

    listing: RawListing
    spec: MemorySpec
    total_cost: Decimal
    eur_per_gb: Decimal
    market_ref: Decimal | None
    discount: float
    urgency: Urgency
    max_bid: Decimal | None = None
    fingerprint: str
    shipping_estimated: bool = False
