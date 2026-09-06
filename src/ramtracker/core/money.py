"""Monnaie — le seul endroit où un montant est manipulé (règle N3).

Aucun `float` ne touche un montant, de la lecture d'API à l'écriture en base.
`shipping=None` (inconnu) et `shipping=0` (gratuit) ne sont jamais coalescés (N4).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

from ramtracker.core.errors import AppError

_CENTS = Decimal("0.01")
_PER_GB = Decimal("0.0001")


class MoneyError(AppError):
    """Conversion de devise impossible ou grandeur invalide."""

    code = "money_error"


class CostBreakdown(BaseModel):
    """Résultat de `total_cost` — l'estimation de port est *signalée*, pas absorbée."""

    model_config = ConfigDict(frozen=True)

    total: Decimal
    shipping_used: Decimal
    shipping_estimated: bool


def money(value: str | int | float | Decimal) -> Decimal:
    """Construit un `Decimal` monétaire. Interdit explicitement `float`."""
    if isinstance(value, float):
        raise MoneyError("un float ne doit jamais toucher un montant", value=value)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def round_cents(amount: Decimal) -> Decimal:
    """Arrondit à 2 décimales, `ROUND_HALF_UP`."""
    return amount.quantize(_CENTS, rounding=ROUND_HALF_UP)


def to_eur(amount: Decimal, currency: str, rates: Mapping[str, Decimal]) -> Decimal:
    """Convertit `amount` en EUR via `rates` (unités d'EUR pour 1 unité de devise)."""
    code = currency.upper()
    if code == "EUR":
        return round_cents(amount)
    try:
        rate = rates[code]
    except KeyError as exc:
        raise MoneyError("taux de change absent", currency=code) from exc
    return round_cents(amount * money(rate))


def total_cost(
    price: Decimal,
    shipping: Decimal | None,
    *,
    estimate_when_unknown: Decimal,
) -> CostBreakdown:
    """Prix + port. Si le port est inconnu, l'estimation est appliquée et signalée."""
    price = money(price)
    if shipping is None:
        used = money(estimate_when_unknown)
        return CostBreakdown(
            total=round_cents(price + used), shipping_used=used, shipping_estimated=True
        )
    shipping = money(shipping)
    return CostBreakdown(
        total=round_cents(price + shipping), shipping_used=shipping, shipping_estimated=False
    )


def eur_per_gb(cost: Decimal, total_gb: int) -> Decimal:
    """Prix rapporté au gigaoctet, quantisé à 4 décimales."""
    if total_gb <= 0:
        raise MoneyError("total_gb doit être strictement positif", total_gb=total_gb)
    return (cost / Decimal(total_gb)).quantize(_PER_GB, rounding=ROUND_HALF_UP)
