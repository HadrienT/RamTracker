"""Étage 4 — borne optimiste et préfiltre €/Go admissible (WP07).

Surtout pas un filtre sur le prix absolu : un lot à 1 800 € peut être 512 Go à
3,50 €/Go. La sortie est une **borne inférieure admissible du €/Go**, calculée
à partir de la capacité *maximale plausible*.

Invariant I1 : `optimistic_total_gb(texte) >= total_gb réel`. La fonction est
délibérément généreuse ; elle n'écarte que ce dont elle est certaine, et
retourne `None` quand elle ne peut rien borner.
"""

from __future__ import annotations

import re
from decimal import Decimal

from ramtracker.core.models import RawListing
from ramtracker.extract.grammar import (
    NXM_RE,
    PARENS_NXM_RE,
    TOTAL_RE,
    UNIT_MARKERS,
    max_plausible_count,
)

_CAP_RE = re.compile(r"(\d{1,4})\s*(?:go|gb|gib|g[oö])\b", re.IGNORECASE)

# Bornes physiques : DDR4 RDIMM/LRDIMM va jusqu'à 128 Go/module, 16 modules max
# sur la carte cible. Au-delà, la borne perd son sens et on ne préfiltre pas.
_MAX_PLAUSIBLE_MODULE_GB = 128
_MAX_PLAUSIBLE_MODULES = 16
_SAFETY_CEILING_GB = _MAX_PLAUSIBLE_MODULE_GB * _MAX_PLAUSIBLE_MODULES


def optimistic_total_gb(text: str) -> int | None:
    """Majorant de la capacité totale. `None` si rien n'est bornable."""
    candidates: list[int] = [int(v) for v in TOTAL_RE.findall(text)]

    for count_s, cap_s in NXM_RE.findall(text) + PARENS_NXM_RE.findall(text):
        candidates.append(int(count_s) * int(cap_s))

    caps = [int(v) for v in _CAP_RE.findall(text) if 1 <= int(v) <= 4096]
    if caps:
        max_cap = max(caps)
        # Nombre de modules maximal plausible : marqueurs explicites, ou — si un
        # prix « à l'unité » suggère un lot de taille inconnue — le plafond carte.
        count = max_plausible_count(text)
        if count == 1 and UNIT_MARKERS.search(text):
            count = _MAX_PLAUSIBLE_MODULES
        candidates.append(max_cap * count)
        candidates.append(max_cap)

    if not candidates:
        return None

    upper = max(candidates)
    if upper > _SAFETY_CEILING_GB:
        return None
    return upper


def best_case_eur_per_gb(listing: RawListing, text: str) -> Decimal | None:
    """€/Go minimal possible pour cette annonce. `None` si non bornable."""
    upper_gb = optimistic_total_gb(text)
    if upper_gb is None or upper_gb <= 0:
        return None
    # Le port est ignoré : l'inclure ne pourrait que *remonter* le meilleur cas,
    # donc préserve « zéro faux négatif par construction ».
    return (listing.price / Decimal(upper_gb)).quantize(Decimal("0.0001"))
