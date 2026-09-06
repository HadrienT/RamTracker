"""Étage 1 — décodeur de références constructeur (blueprint/10-HARDWARE-TARGET.md §4).

Le meilleur rapport effort/résultat du projet : une référence est
auto-descriptive. Capacité, type et fréquence sortent d'une table, sans
traitement de langage — confiance 1.0.
"""

from __future__ import annotations

import re

from ramtracker.core.models import Kind, MemorySpec, Method, PriceBasis
from ramtracker.extract.compat import CompatMatrix

# Motif générique — attrape la majorité des références de vendeurs sérieux.
_PN_RE = re.compile(r"\b([A-Z]{1,3}\d{2,3}[A-Z0-9]{4,12}(?:-[A-Z0-9]{2,4})?)\b")

_SAMSUNG_FAMILY = {"M393": Kind.RDIMM, "M386": Kind.LRDIMM, "M378": None, "M471": None}
_SAMSUNG_DENSITY = {"A1G43": 8, "A2G40": 16, "A4K40": 32, "A8K40": 64}
_SAMSUNG_SPEED = {"CPB": 2133, "CRC": 2400, "CTD": 2666, "CVF": 2933, "DVR": 3200}

_HYNIX_DENSITY = {"HMA42GR7": 16, "HMA82GR7": 16, "HMA84GR7": 32, "HMAA8GL7": 64}
_HYNIX_SPEED = {"TF": 2133, "UH": 2400, "R4": 2400, "V4": 2666, "T4": 2666}

_MICRON_DENSITY = {"MTA18ASF2G72": 16, "MTA36ASF4G72": 32, "MTA18ASF1G72": 8, "MTA36ASF8G72": 64}
_MICRON_SPEED = {"PDZ": 2133, "PZ": 2400, "PZ-2G9": 2933, "PZ-3G2": 3200}


def decode(text: str, matrix: CompatMatrix | None = None) -> MemorySpec | None:
    """Décode une référence constructeur dans `text`. `None` si aucune ne s'y trouve."""
    upper = text.upper()
    for token in _PN_RE.findall(upper):
        spec = (
            _decode_samsung(token)
            or _decode_hynix(token)
            or _decode_micron(token)
            or _decode_from_matrix(token, matrix)
        )
        if spec is not None:
            return spec
    return None


def _finish(token: str, kind: Kind, capacity_gb: int | None, speed_mts: int | None) -> MemorySpec:
    return MemorySpec(
        module_capacity_gb=capacity_gb,
        module_count=1,
        total_gb=capacity_gb,
        kind=kind,
        speed_mts=speed_mts,
        part_number=token,
        # Une référence décrit un module mais ne dit rien du nombre vendu ni de
        # la base de prix : rester UNKNOWN, quitte à passer par le LLM (interdit n°5).
        price_basis=PriceBasis.UNKNOWN,
        confidence=1.0,
        method=Method.PART_NUMBER,
    )


def _decode_samsung(token: str) -> MemorySpec | None:
    if not token.startswith("M3"):
        return None
    family = token[:4]
    if family not in _SAMSUNG_FAMILY:
        return None
    kind = _SAMSUNG_FAMILY[family]
    if kind is None:
        return _rejected_module(token, "udimm_non_ecc")
    capacity = next((v for k, v in _SAMSUNG_DENSITY.items() if k in token), None)
    speed = next((v for k, v in _SAMSUNG_SPEED.items() if token.endswith(f"-{k}")), None)
    if capacity is None:
        return None
    return _finish(token, kind, capacity, speed)


def _decode_hynix(token: str) -> MemorySpec | None:
    if not token.startswith("HMA"):
        return None
    kind = Kind.LRDIMM if "GL7" in token else Kind.RDIMM if "GR7" in token else Kind.UNKNOWN
    if kind is Kind.UNKNOWN:
        return None
    capacity = next((v for k, v in _HYNIX_DENSITY.items() if token.startswith(k)), None)
    speed = next((v for k, v in _HYNIX_SPEED.items() if token.endswith(f"-{k}")), None)
    if capacity is None:
        return None
    return _finish(token, kind, capacity, speed)


def _decode_micron(token: str) -> MemorySpec | None:
    if not token.startswith("MTA"):
        return None
    kind = Kind.LRDIMM if token.startswith("MTA72ASS") else Kind.RDIMM
    capacity = next((v for k, v in _MICRON_DENSITY.items() if token.startswith(k)), None)
    speed = next((v for k, v in _MICRON_SPEED.items() if token.endswith(k)), None)
    if capacity is None:
        return None
    return _finish(token, kind, capacity, speed)


def _decode_from_matrix(token: str, matrix: CompatMatrix | None) -> MemorySpec | None:
    """Repli sur les tables de `compat.yaml` (complétées au spike WP00)."""
    if matrix is None:
        return None
    for table in matrix.part_numbers.values():
        family = next((v for k, v in table.family.items() if token.startswith(k)), None)
        if family is None:
            continue
        if family == "reject":
            return _rejected_module(token, "udimm_non_ecc")
        kind = Kind.RDIMM if family == "rdimm" else Kind.LRDIMM
        capacity = next((v for k, v in table.density.items() if k in token), None)
        speed = next((v for k, v in table.speed.items() if token.endswith(f"-{k}")), None)
        if capacity is None:
            continue
        return _finish(token, kind, capacity, speed)
    return None


def _rejected_module(token: str, reason: str) -> MemorySpec:
    return MemorySpec(
        part_number=token,
        kind=Kind.UDIMM_ECC,
        confidence=1.0,
        method=Method.PART_NUMBER,
        reject_reason=reason,
    )
