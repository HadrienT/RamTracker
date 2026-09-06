"""Étage 3 — contrôles croisés. Chaque contrôle *ajuste la confiance*, aucun ne rejette.

Le dernier contrôle est structurant : une annonce dont la base de prix est
ambiguë ne peut jamais court-circuiter la cascade (contrepartie de l'interdit
n°5 du primer).
"""

from __future__ import annotations

from ramtracker.core.models import MemorySpec, PriceBasis
from ramtracker.extract.grammar import PC4_RE, PC4_TO_MTS  # tables partagées

_PLAUSIBLE_CAPACITIES = (4, 8, 16, 32, 64, 128)
_INCOHERENT = 0.30
_PC4_MISMATCH = 0.40
_UNKNOWN_BASIS_CAP = 0.70


def check(spec: MemorySpec, text: str) -> MemorySpec:
    """Renvoie une nouvelle spec avec la confiance ajustée."""
    confidence = spec.confidence

    if (
        spec.module_capacity_gb is not None
        and spec.total_gb is not None
        and spec.module_count >= 1
        and spec.module_capacity_gb * spec.module_count != spec.total_gb
    ):
        confidence = min(confidence, _INCOHERENT)

    if spec.module_capacity_gb is not None and spec.module_capacity_gb not in _PLAUSIBLE_CAPACITIES:
        confidence = min(confidence, _INCOHERENT)

    pc4 = PC4_RE.search(text)
    if pc4 and pc4.group(1) in PC4_TO_MTS and spec.speed_mts is not None:
        if PC4_TO_MTS[pc4.group(1)] != spec.speed_mts:
            confidence = min(confidence, _PC4_MISMATCH)

    if spec.price_basis is PriceBasis.UNKNOWN:
        confidence = min(confidence, _UNKNOWN_BASIS_CAP)

    return spec.with_confidence(confidence)
