"""WP02 — tests unitaires par étage : partnum, grammar, coherence, qualify."""

from __future__ import annotations

from ramtracker.core.models import Kind, Method, PriceBasis
from ramtracker.extract import coherence, grammar, partnum, qualify
from ramtracker.extract.compat import CompatMatrix


def test_partnum_samsung_full_decode() -> None:
    spec = partnum.decode("M393A4K40BB1-CRC")
    assert spec is not None
    assert spec.module_capacity_gb == 32
    assert spec.speed_mts == 2400
    assert spec.kind is Kind.RDIMM
    assert spec.confidence == 1.0
    assert spec.method is Method.PART_NUMBER


def test_partnum_rejects_udimm_family() -> None:
    spec = partnum.decode("M378A1G43EB1-CPB desktop")
    assert spec is not None
    assert spec.reject_reason == "udimm_non_ecc"


def test_partnum_none_when_absent() -> None:
    assert partnum.decode("DDR4 16 Go ECC REG 2133") is None


def test_grammar_lot_total_decomposed() -> None:
    spec = grammar.parse("64 Go (4x16) DDR4 ECC RDIMM 2400")
    assert spec.total_gb == 64
    assert spec.module_count == 4
    assert spec.module_capacity_gb == 16


def test_grammar_unit_price_marker() -> None:
    spec = grammar.parse("16 Go DDR4 ECC REG - 25 EUR piece, j'en ai 8")
    assert spec.price_basis is PriceBasis.UNIT
    assert spec.module_count == 8


def test_grammar_kit_or_module_ambiguous() -> None:
    spec = grammar.parse("DDR4 32GB ECC Samsung")
    assert spec.module_count == 1
    assert spec.price_basis is PriceBasis.UNKNOWN


def test_grammar_pc4_frequency_resolution() -> None:
    assert grammar.parse("RAM DDR4 PC4-19200 16GB ECC").speed_mts == 2400
    assert grammar.parse("PC4-17000 8GB ECC REG").speed_mts == 2133


def test_grammar_reverse_order_not_capacity() -> None:
    spec = grammar.parse("DDR4 2133 MHz - 8 Go ECC RDIMM")
    assert spec.module_capacity_gb == 8
    assert spec.speed_mts == 2133


def test_coherence_caps_unknown_basis() -> None:
    spec = grammar.parse("DDR4 32GB ECC Samsung")
    checked = coherence.check(spec, "DDR4 32GB ECC Samsung")
    assert checked.confidence <= 0.70


def test_coherence_drops_incoherent_totals() -> None:
    spec = grammar.parse("DDR4 ECC RDIMM 2133")
    spec = spec.model_copy(update={"module_capacity_gb": 16, "module_count": 4, "total_gb": 999})
    assert coherence.check(spec, "").confidence <= 0.30


def test_qualify_sodimm() -> None:
    matrix = CompatMatrix()
    assert qualify.reject_by_keywords("DDR4 ECC 16 Go SO-DIMM NAS", matrix) == "sodimm"


def test_qualify_keeps_reject_reasons_stable() -> None:
    assert "sodimm" in qualify.REJECT_REASONS
    assert "meilleur_cas_hors_seuil" in qualify.REJECT_REASONS
