"""WP01 — socle : monnaie, hachage, horloge, configuration, base."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ramtracker.core import clock, hashing
from ramtracker.core.config import get_settings, load_yaml, reset_settings_cache
from ramtracker.core.errors import ConfigError
from ramtracker.core.money import MoneyError, eur_per_gb, total_cost


def test_eur_per_gb_exact() -> None:
    assert eur_per_gb(Decimal("100"), 64) == Decimal("1.5625")


def test_eur_per_gb_rejects_zero() -> None:
    with pytest.raises(MoneyError):
        eur_per_gb(Decimal("100"), 0)


def test_no_float_touches_money() -> None:
    with pytest.raises(MoneyError):
        total_cost(Decimal("10"), 3.5, estimate_when_unknown=Decimal("12"))  # type: ignore[arg-type]


def test_shipping_none_is_estimated_and_flagged() -> None:
    result = total_cost(Decimal("100"), None, estimate_when_unknown=Decimal("12"))
    assert result.shipping_estimated is True
    assert result.total == Decimal("112.00")


def test_shipping_zero_is_not_estimated() -> None:
    result = total_cost(Decimal("100"), Decimal("0"), estimate_when_unknown=Decimal("12"))
    assert result.shipping_estimated is False
    assert result.total == Decimal("100.00")


def test_shipping_none_and_zero_differ() -> None:
    a = total_cost(Decimal("100"), None, estimate_when_unknown=Decimal("12")).total
    b = total_cost(Decimal("100"), Decimal("0"), estimate_when_unknown=Decimal("12")).total
    assert a != b


def test_spec_hash_stable_to_whitespace_and_case() -> None:
    assert hashing.spec_hash("DDR4  ECC   16Go", None) == hashing.spec_hash("ddr4 ecc 16go", None)


def test_fingerprint_price_bucketed() -> None:
    a = hashing.fingerprint("seller", 16, 4, Decimal("201"))
    b = hashing.fingerprint("seller", 16, 4, Decimal("209"))
    assert a == b


def test_utc_now_is_aware_and_substitutable() -> None:
    pinned = datetime(2026, 1, 1, tzinfo=UTC)
    with clock.frozen(pinned):
        assert clock.utc_now() == pinned
    assert clock.utc_now().tzinfo is not None


def test_missing_required_var_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    reset_settings_cache()
    with pytest.raises(ConfigError) as exc:
        get_settings()
    assert "EBAY_CLIENT_ID" in str(exc.value.context)


def test_secret_not_serialised() -> None:
    settings = get_settings()
    assert "test-secret" not in settings.model_dump_json()


def test_env_beats_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAMTRACKER_LOG_LEVEL", "DEBUG")
    reset_settings_cache()
    assert get_settings().log_level == "DEBUG"


@pytest.mark.usefixtures("migrated_db")
def test_migrations_idempotent() -> None:
    from ramtracker.core.db import apply_migrations, check_health

    assert apply_migrations() == 0  # déjà à jour
    health = check_health()
    assert health.ok
    assert health.journal_mode.lower() == "wal"
    assert health.schema_version >= 6


def test_load_yaml_validates() -> None:
    from ramtracker.extract.compat import CompatMatrix

    matrix = load_yaml("compat", CompatMatrix)
    assert 32 in matrix.capacity_gb.accept
    assert 4 in matrix.capacity_gb.reject
