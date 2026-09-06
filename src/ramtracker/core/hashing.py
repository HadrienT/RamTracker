"""Identités du système — blueprint/04-DATA-MODEL.md §1.

`spec_hash` répond « ai-je déjà compris ce texte ? », `fingerprint` répond
« ai-je déjà alerté là-dessus ? ». Ce ne sont pas les mêmes questions.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal

_WS = re.compile(r"\s+")

# Tranches de prix pour le fingerprint : deux annonces de la même barrette à
# quelques euros près doivent produire la même empreinte.
_PRICE_BUCKET_EUR = Decimal("10")


def normalize_text(value: str) -> str:
    """Minuscule, accents repliés, espaces normalisés. Base de `spec_hash`."""
    folded = unicodedata.normalize("NFKD", value)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return _WS.sub(" ", folded).strip().lower()


def spec_hash(title: str, description: str | None) -> str:
    """sha256 du titre + description normalisés. Stable aux espaces et à la casse."""
    payload = normalize_text(title)
    if description:
        payload = f"{payload}\n{normalize_text(description)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint(
    seller_id: str | None,
    capacity_gb: int | None,
    count: int,
    price: Decimal,
) -> str:
    """Empreinte d'alerte : vendeur, capacité, quantité, tranche de prix."""
    bucket = int((price / _PRICE_BUCKET_EUR).to_integral_value(rounding="ROUND_FLOOR"))
    seller = (seller_id or "?").strip().lower()
    key = f"{seller}|{capacity_gb or 0}|{count}|{bucket}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
