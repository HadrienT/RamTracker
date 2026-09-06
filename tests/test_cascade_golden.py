"""Non-régression sur le corpus doré (blueprint/08-TESTING.md §1 et §4).

Seuil de sortie de WP02 : exactitude >= 85 % sur les qualifiées, et **aucun**
piège `prix_unitaire` mal interprété (bloquant à 100 %).
"""

from __future__ import annotations

import pytest

from ramtracker.extract import cascade
from ramtracker.extract.compat import CompatMatrix
from tests._corpus import make_listing, matches

pytestmark = pytest.mark.golden

_MIN_CONFIDENCE = 0.80


def _run(entry: dict, matrix: CompatMatrix):
    listing = make_listing(entry["text"])
    return cascade.run(listing, matrix, None, min_confidence=_MIN_CONFIDENCE)


def test_golden_accuracy(golden_corpus: list[dict], compat_matrix: CompatMatrix) -> None:
    ok = 0
    failures: list[str] = []
    for entry in golden_corpus:
        spec = _run(entry, compat_matrix)
        good, why = matches(spec, entry["expect"])
        if good:
            ok += 1
        else:
            failures.append(f"{entry['text'][:60]!r}: {why}")
    accuracy = ok / len(golden_corpus)
    print(f"\nexactitude corpus : {accuracy:.1%} ({ok}/{len(golden_corpus)})")
    for line in failures:
        print("  ✗", line)
    assert accuracy >= 0.85, f"exactitude {accuracy:.1%} < 85 %"


def test_no_unit_price_trap_misread(golden_corpus: list[dict], compat_matrix: CompatMatrix) -> None:
    """Bloquant : un prix unitaire ne doit jamais être lu comme un prix de lot."""
    offenders: list[str] = []
    for entry in golden_corpus:
        if entry.get("trap") != "prix_unitaire":
            continue
        spec = _run(entry, compat_matrix)
        if spec.price_basis.value == "lot":
            offenders.append(entry["text"])
    assert not offenders, f"prix unitaire lu comme lot : {offenders}"


def test_stage_resolution_table(golden_corpus: list[dict], compat_matrix: CompatMatrix) -> None:
    """Affiche le tableau de résolution par étage (just test-golden -s)."""
    from ramtracker.extract import grammar, partnum

    counts = {"part_number": 0, "grammar_ok": 0, "low_confidence": 0, "rejected": 0}
    for entry in golden_corpus:
        text = entry["text"]
        if partnum.decode(text, compat_matrix) is not None:
            counts["part_number"] += 1
            continue
        spec = _run(entry, compat_matrix)
        if spec.reject_reason == "low_confidence":
            counts["low_confidence"] += 1
        elif spec.reject_reason is not None:
            counts["rejected"] += 1
        else:
            counts["grammar_ok"] += 1
        _ = grammar
    total = len(golden_corpus)
    print(f"\ncorpus : {total} annonces")
    for stage, n in counts.items():
        print(f"  {stage:16s} {n:4d}  ({n / total:.1%})")
