"""Vue `decide` de `configs/thresholds.yaml`.

Chaque package valide ce fichier contre sa propre vue partielle (les clés non
pertinentes sont ignorées). Aucune valeur par défaut ici n'est un *seuil métier* :
ce sont des filets pour que le modèle charge, les vraies valeurs vivent dans le YAML.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class Barriers(BaseModel):
    hard_ceiling_eur_per_gb: Decimal
    min_discount: float


class Guards(BaseModel):
    plausibility_floor_eur_per_gb: Decimal
    min_total_gb: int
    min_confidence: float = 0.80


class Shipping(BaseModel):
    default_estimate_eur: Decimal = Decimal("12.00")


class Currency(BaseModel):
    rates_to_eur: dict[str, Decimal] = Field(default_factory=dict)


class MarketIndex(BaseModel):
    window_days: int = 30
    min_sample_size: int = 20
    refresh_interval_min: int = 60
    capacity_buckets: list[int] = Field(default_factory=lambda: [8, 16, 32, 64])


class ObservationMode(BaseModel):
    enabled: bool = True
    until: date


class AuctionPolicy(BaseModel):
    gate_minutes: int = 90
    bid_increment_eur: Decimal = Decimal("5.00")
    notify_once: bool = True


class ThresholdPolicy(BaseModel):
    """Agrégat passé à `decide.thresholds.evaluate`."""

    barriers: Barriers
    guards: Guards
    shipping: Shipping = Field(default_factory=Shipping)
    currency: Currency = Field(default_factory=Currency)
    market_index: MarketIndex = Field(default_factory=MarketIndex)
    observation_mode: ObservationMode
    auction: AuctionPolicy = Field(default_factory=AuctionPolicy)


def load_threshold_policy() -> ThresholdPolicy:
    from ramtracker.core.config import load_yaml

    return load_yaml("thresholds", ThresholdPolicy)
