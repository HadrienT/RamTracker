"""Qualification — application de `compat.yaml`, remplissage de `reject_reason`.

Les motifs de rejet sont des identifiants stables (`sodimm`, `ddr3`,
`udimm_non_ecc`, `capacity_4gb`…), persistés et comparés en test. Les renommer
casse l'historique de rejeu (blueprint/09-CONVENTIONS.md §2).
"""

from __future__ import annotations

import re

from ramtracker.core.models import Kind, MemorySpec, PriceBasis
from ramtracker.extract.compat import CompatMatrix

# Motifs de rejet — stables, jamais traduits.
REJECT_REASONS = frozenset(
    {
        "ddr3",
        "ddr5",
        "sodimm",
        "udimm_non_ecc",
        "capacity_4gb",
        "capacity_reject",
        "capacity_unknown",
        "speed_rejected",
        "keyword_reject",
        "low_confidence",
        "meilleur_cas_hors_seuil",
        "llm_schema_invalid",
    }
)

_DDR3_RE = re.compile(r"\b(ddr3|pc3|pc3l|pc3-\d)\b", re.IGNORECASE)
_DDR5_RE = re.compile(r"\b(ddr5|pc5|pc5-\d)\b", re.IGNORECASE)
_SODIMM_RE = re.compile(r"\b(sodimm|so-dimm|so\s?dimm|260[\s-]?pin)\b", re.IGNORECASE)
_NON_ECC_RE = re.compile(r"\bnon[\s-]?ecc\b", re.IGNORECASE)


def reject_by_keywords(text: str, matrix: CompatMatrix) -> str | None:
    """Rejet précoce sur le texte brut (étage « rejet par mots-clés » de l'entonnoir)."""
    low = text.lower()
    if _DDR3_RE.search(low):
        return "ddr3"
    if _DDR5_RE.search(low):
        return "ddr5"
    if _SODIMM_RE.search(low):
        return "sodimm"
    if _NON_ECC_RE.search(low):
        return "keyword_reject"
    for keyword in matrix.reject_keywords:
        if keyword.lower() in low:
            if keyword.lower() in {"ddr3", "pc3"}:
                return "ddr3"
            if keyword.lower() in {"ddr5", "pc5"}:
                return "ddr5"
            if "dimm" in keyword.lower():
                return "sodimm"
            return "keyword_reject"
    return None


def qualify(spec: MemorySpec, matrix: CompatMatrix) -> MemorySpec:
    """Applique la matrice à une spec. Renvoie une spec avec `reject_reason` renseigné ou non."""
    if not spec.qualified:
        return spec

    if spec.module_capacity_gb is not None:
        if spec.module_capacity_gb in matrix.capacity_gb.reject:
            return spec.rejected(
                "capacity_4gb" if spec.module_capacity_gb == 4 else "capacity_reject"
            )
        if matrix.capacity_gb.accept and spec.module_capacity_gb not in matrix.capacity_gb.accept:
            return spec.rejected("capacity_reject")

    if spec.kind is Kind.UDIMM_ECC:
        # La carte cible exige du registered : l'UDIMM ECC est incompatible.
        return spec.rejected("udimm_non_ecc")

    if spec.speed_mts is not None and not matrix.accepts_speed(spec.speed_mts):
        return spec.rejected("speed_rejected")

    return spec


def is_native_speed(spec: MemorySpec, matrix: CompatMatrix) -> bool:
    """Vrai si la fréquence est native (2133/2400) — sert à déprioriser, pas à rejeter."""
    return spec.speed_mts is not None and matrix.native_speed(spec.speed_mts)


def price_basis_blocks_shortcut(spec: MemorySpec) -> bool:
    """Une base de prix inconnue ne doit jamais court-circuiter vers l'alerte."""
    return spec.price_basis is PriceBasis.UNKNOWN
