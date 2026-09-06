"""Étage 2 — grammaire d'expressions régulières.

Extrait capacité, multiplicateur, type, fréquence, rangs et **base de prix**.
Ne devine jamais : un champ incertain reste `None` et fait baisser la confiance.
Confiance de sortie : 0.60 à 0.95, ajustée ensuite par `coherence`.
"""

from __future__ import annotations

import re

from ramtracker.core.models import Kind, MemorySpec, Method, PriceBasis

_VALID_CAPACITIES = (4, 8, 16, 32, 64, 128)
_KNOWN_SPEEDS = (1333, 1600, 1866, 2133, 2400, 2666, 2933, 3200)
PC4_TO_MTS = {
    "12800": 1600,
    "14900": 1866,
    "17000": 2133,
    "19200": 2400,
    "21300": 2666,
    "23400": 2933,
    "25600": 3200,
}

UNIT_MARKERS = re.compile(
    r"(?:"
    r"\bpi[eè]ces?\b|\bl['’]unit[eé]\b|\bchacune?\b|\bchaque\b|\bunitaire\b|"
    r"\bper\s?stick\b|\bper\s?module\b|\bje\s+st[uü]ck\b|\bst[uü]ck\b|"
    r"\b/\s?ea\b|\beach\b|"
    r"\b(?:prix\s+)?(?:par|a\s+l['’]|à\s+l['’])\s*(?:unit[eé]|barrette|module|pi[eè]ce|stick)\b|"
    r"\beuros?\s+l['’]unit[eé]\b|\bvendu\s+(?:a\s+l['’]unit|par\s+(?:barrette|module|pi[eè]ce))|"
    r"\bje\s+\d+\s*(?:eur|€|euro)"
    r")",
    re.IGNORECASE,
)
_MULTIPLIER_PATTERNS = (
    re.compile(r"\blot\s+de\s+(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bkit\s+(?:de\s+)?(\d{1,2})\s*(?:x|barrettes?|modules?|pcs?)", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\s*(?:x|\*)\s*\d{1,3}\s*(?:go|gb|g[oö]|gib)\b", re.IGNORECASE),
    re.compile(r"\bj['’]en\s+(?:ai|vends?)\s+(\d{1,2})\b", re.IGNORECASE),
    re.compile(
        r"\b(\d{1,2})\s*(?:barrettes?|modules?|st[uü]cke?|sticks?|pi[eè]ces?|riegel|"
        r"disponibles?|dispo\b|verf[uü]gbar)",
        re.IGNORECASE,
    ),
    re.compile(r"\bset\s+of\s+(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bq(?:ty|té|te)?\s*[:.]?\s*(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bstock\s+(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\(\s*x\s*(\d{1,2})\s*\)", re.IGNORECASE),
)
NXM_RE = re.compile(r"\b(\d{1,2})\s*(?:x|\*)\s*(\d{1,3})\s*(?:go|gb|g[oö]|gib)\b", re.IGNORECASE)
PARENS_NXM_RE = re.compile(
    r"\(\s*(\d{1,2})\s*(?:x|\*)\s*(\d{1,3})\s*(?:go|gb)?\s*\)", re.IGNORECASE
)
_CAPACITY_RE = re.compile(r"\b(\d{1,3})\s*(go|gb|g[oö]|gib)\b", re.IGNORECASE)
TOTAL_RE = re.compile(
    r"\b(\d{2,4})\s*(?:go|gb)\s*(?:total|au\s+total|gesamt|in\s+total)\b", re.IGNORECASE
)

_WORD_COUNTS = {
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "huit": 8,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "sechs": 6,
    "acht": 8,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six ": 6,
    "eight": 8,
    "paire": 2,
    "pair": 2,
    "paar": 2,
}
_PLURAL_CONTAINERS = re.compile(
    r"\b(barrettes|modules|sticks|st[uü]cke|riegel|lot|kit|paire|pair|paar|set)\b",
    re.IGNORECASE,
)
_GENEROUS_COUNT_CEILING = 16
_SPEED_MHZ_RE = re.compile(r"\b(\d{4})\s*(?:mhz|mt/?s|mts)\b", re.IGNORECASE)
_DDR4_SPEED_RE = re.compile(r"\bddr4[\s-]+(\d{4})\b", re.IGNORECASE)
# PC4-<code><grade> : le code est soit une bande passante (17000, 19200…),
# soit la fréquence elle-même (2133P, 2400T…).
PC4_RE = re.compile(r"\bpc4[\s-]*(\d{4,5})([a-z]?)\b", re.IGNORECASE)
# Fréquence collée à un suffixe de grade : 2133P, 2400T, 2666V.
_SPEED_GRADE_RE = re.compile(r"\b(\d{4})\s?[ptvw]\b", re.IGNORECASE)
_RANKS_RE = re.compile(r"\b([1248])\s?r\s?x\s?(\d{1,2})\b", re.IGNORECASE)

_RDIMM_RE = re.compile(r"\b(rdimm|r-dimm|reg(?:istered|\.)?|reg\b|ecc\s?reg|preg)\b", re.IGNORECASE)
_LRDIMM_RE = re.compile(r"\b(lrdimm|lr-dimm|load[\s-]?reduced)\b", re.IGNORECASE)
_SODIMM_RE = re.compile(r"\b(sodimm|so-dimm|so\s?dimm|260[\s-]?pin)\b", re.IGNORECASE)
_UDIMM_RE = re.compile(r"\b(udimm|u-dimm|unbuffered|unregistered)\b", re.IGNORECASE)
_ECC_RE = re.compile(r"\becc\b", re.IGNORECASE)
_UDIMM_ECC_RE = re.compile(
    r"\b(udimm|u-dimm|unbuffered)\b.*\becc\b|\becc\b.*\budimm\b", re.IGNORECASE
)


def parse(text: str) -> MemorySpec:
    """Analyse `text` en `MemorySpec`. Toujours renvoyée, jamais `None`."""
    kind = _kind(text)
    speed = _speed(text)
    ranks = _ranks(text)
    total_declared = _declared_total(text)
    count, capacity, count_explicit = _count_and_capacity(text, speed)

    total = _resolve_total(capacity, count, total_declared)
    basis = _price_basis(text, count_explicit)

    confidence = 0.60
    if capacity is not None:
        confidence += 0.15
    if count_explicit:
        confidence += 0.10
    if kind in (Kind.RDIMM, Kind.LRDIMM):
        confidence += 0.10
    if speed is not None:
        confidence += 0.05
    confidence = min(confidence, 0.95)

    return MemorySpec(
        module_capacity_gb=capacity,
        module_count=count,
        total_gb=total,
        kind=kind,
        speed_mts=speed,
        ranks=ranks,
        price_basis=basis,
        confidence=confidence,
        method=Method.RULES,
    )


def _kind(text: str) -> Kind:
    if _SODIMM_RE.search(text):
        # Format tranché plus tard par `qualify` ; le type mémoire reste inconnu ici.
        return Kind.UNKNOWN
    if _LRDIMM_RE.search(text):
        return Kind.LRDIMM
    # "unbuffered"/"udimm" prime sur "reg" seulement s'il n'y a pas de "reg/rdimm".
    if _UDIMM_RE.search(text) and not _RDIMM_RE.search(text):
        return Kind.UDIMM_ECC if _ECC_RE.search(text) else Kind.UNKNOWN
    if _RDIMM_RE.search(text):
        return Kind.RDIMM
    if _UDIMM_ECC_RE.search(text):
        return Kind.UDIMM_ECC
    return Kind.UNKNOWN


def _speed(text: str) -> int | None:
    m = PC4_RE.search(text)
    if m:
        code = m.group(1)
        if code in PC4_TO_MTS:
            return PC4_TO_MTS[code]
        if int(code) in _KNOWN_SPEEDS:
            return int(code)
    m = _SPEED_MHZ_RE.search(text)
    if m and int(m.group(1)) in _KNOWN_SPEEDS:
        return int(m.group(1))
    m = _DDR4_SPEED_RE.search(text)
    if m and int(m.group(1)) in _KNOWN_SPEEDS:
        return int(m.group(1))
    m = _SPEED_GRADE_RE.search(text)
    if m and int(m.group(1)) in _KNOWN_SPEEDS:
        return int(m.group(1))
    # Fréquence isolée, uniquement si non collée à "Go/GB".
    for token in re.findall(r"\b(\d{4})\b", text):
        if int(token) in _KNOWN_SPEEDS:
            idx = text.find(token)
            trailing = text[idx + len(token) : idx + len(token) + 4].lower()
            if not trailing.strip().startswith(("go", "gb", "g ", "gi")):
                return int(token)
    return None


def _ranks(text: str) -> str | None:
    m = _RANKS_RE.search(text)
    return f"{m.group(1)}Rx{m.group(2)}" if m else None


def _declared_total(text: str) -> int | None:
    m = TOTAL_RE.search(text)
    if m:
        return int(m.group(1))
    return None


def _count_and_capacity(text: str, speed: int | None) -> tuple[int, int | None, bool]:
    nxm = NXM_RE.search(text) or PARENS_NXM_RE.search(text)
    if nxm:
        count = int(nxm.group(1))
        cap = int(nxm.group(2))
        if cap in _VALID_CAPACITIES:
            return count, cap, True

    count = 1
    count_explicit = False
    for pattern in _MULTIPLIER_PATTERNS:
        m = pattern.search(text)
        if m:
            value = int(m.group(1))
            if 1 <= value <= 32:
                count = value
                count_explicit = True
                break

    capacity = _capacity(text, speed)
    return count, capacity, count_explicit


def _capacity(text: str, speed: int | None) -> int | None:
    candidates: list[int] = []
    for value, _unit in _CAPACITY_RE.findall(text):
        n = int(value)
        if n in _VALID_CAPACITIES:
            candidates.append(n)
    # On retire une éventuelle capacité "totale" annoncée (plus grande valeur).
    if len(candidates) >= 2 and max(candidates) > min(candidates):
        module_candidates = [c for c in candidates if c != max(candidates)]
        if module_candidates:
            return max(module_candidates)
    if candidates:
        return min(candidates)
    return None


def _resolve_total(capacity: int | None, count: int, declared: int | None) -> int | None:
    if declared is not None:
        return declared
    if capacity is not None:
        return capacity * count
    return None


def _price_basis(text: str, count_explicit: bool) -> PriceBasis:
    if UNIT_MARKERS.search(text):
        return PriceBasis.UNIT
    if count_explicit:
        return PriceBasis.LOT
    return PriceBasis.UNKNOWN


def max_plausible_count(text: str) -> int:
    """Majorant *généreux* du nombre de modules — pour le préfiltre (I1), pas le parsing.

    En cas d'ambiguïté (pluriel « barrettes/modules » sans compte lisible), renvoie
    le plafond carte : sous-estimer le compte violerait l'invariant I1.
    """
    found: list[int] = []
    for count_s, _cap_s in NXM_RE.findall(text) + PARENS_NXM_RE.findall(text):
        found.append(int(count_s))
    for pattern in _MULTIPLIER_PATTERNS:
        found.extend(int(m) for m in pattern.findall(text))
    low = text.lower()
    for word, value in _WORD_COUNTS.items():
        if word.strip() and re.search(rf"\b{re.escape(word.strip())}\b", low):
            found.append(value)
    found = [v for v in found if 1 <= v <= _GENEROUS_COUNT_CEILING]
    if found:
        return max(found)
    if _PLURAL_CONTAINERS.search(text):
        return _GENEROUS_COUNT_CEILING
    return 1
