"""Orchestration de la cascade — du plus déterministe au plus coûteux.

S'arrête dès qu'elle est sûre, ne devine jamais. `cascade.run` accepte `llm=None`
(WP02 complet et testable avant WP07).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal

from ramtracker.core.models import MemorySpec, Method, RawListing
from ramtracker.extract import coherence, grammar, partnum, prefilter, qualify
from ramtracker.extract.compat import CompatMatrix

LlmFn = Callable[[Sequence[RawListing]], list[MemorySpec]]


def run(
    listing: RawListing,
    matrix: CompatMatrix,
    llm: LlmFn | None,
    *,
    min_confidence: float,
    hard_ceiling_eur_per_gb: Decimal | None = None,
) -> MemorySpec:
    """Exécute la cascade sur une annonce et renvoie sa `MemorySpec`."""
    text = _text(listing)

    keyword_reject = qualify.reject_by_keywords(text, matrix)
    if keyword_reject is not None:
        return grammar.parse(text).with_confidence(1.0).rejected(keyword_reject)

    parsed = grammar.parse(text)

    decoded = partnum.decode(text, matrix)
    if decoded is not None:
        if not decoded.qualified:
            return qualify.qualify(decoded, matrix)
        # La référence fixe capacité / type / fréquence avec certitude ; la
        # grammaire complète le nombre de modules et la base de prix.
        merged = decoded.model_copy(
            update={
                "module_count": parsed.module_count,
                "price_basis": parsed.price_basis,
                "speed_mts": decoded.speed_mts or parsed.speed_mts,
                "ranks": decoded.ranks or parsed.ranks,
                "total_gb": (decoded.module_capacity_gb or 0) * parsed.module_count
                or decoded.total_gb,
            }
        )
        return qualify.qualify(merged, matrix)

    checked = coherence.check(parsed, text)

    # Les rejets durs (SODIMM, DDR3/5, 4 Go, UDIMM ECC) sont certains quelle que
    # soit la confiance : les appliquer avant la porte de confiance évite un appel
    # LLM inutile.
    qualified = qualify.qualify(checked, matrix)
    if not qualified.qualified:
        return qualified

    if checked.confidence >= min_confidence and not qualify.price_basis_blocks_shortcut(checked):
        return qualified

    # Confiance insuffisante : préfiltre gratuit, puis LLM ou quarantaine.
    if hard_ceiling_eur_per_gb is not None:
        best_case = prefilter.best_case_eur_per_gb(listing, text)
        if best_case is not None and best_case > hard_ceiling_eur_per_gb:
            return checked.rejected("meilleur_cas_hors_seuil")

    if llm is not None:
        try:
            results = llm([listing])
        except Exception:
            return checked.rejected("low_confidence")
        if results:
            spec = results[0]
            return qualify.qualify(spec.model_copy(update={"method": Method.LLM}), matrix)
        return checked.rejected("low_confidence")

    return checked.rejected("low_confidence")


def _text(listing: RawListing) -> str:
    if listing.description:
        return f"{listing.title}\n{listing.description}"
    return listing.title
