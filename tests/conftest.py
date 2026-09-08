"""Fixtures partagées — aucune ne touche au réseau."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    # Isole les tests du `.env` du développeur : pydantic-settings lit un
    # `.env` dans le CWD, ce qui masquerait les variables supprimées en test.
    from ramtracker.core.config import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EBAY_CLIENT_ID", "test-id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("EBAY_ZIP", "69001")
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/ramtracker-test-topic")
    monkeypatch.setenv("RAMTRACKER_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("RAMTRACKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("RAMTRACKER_CONFIG_DIR", str(Path(__file__).parent.parent / "configs"))
    monkeypatch.setenv(
        "RAMTRACKER_MIGRATIONS_DIR", str(Path(__file__).parent.parent / "migrations")
    )
    from ramtracker.core import clock, config, logging

    config.reset_settings_cache()
    clock.reset_clock()
    logging._configured = False
    yield
    config.reset_settings_cache()
    clock.reset_clock()


@pytest.fixture
def migrated_db() -> Iterator[None]:
    from ramtracker.core.db import apply_migrations

    apply_migrations()
    yield


@pytest.fixture
def frozen_clock() -> Iterator[datetime]:
    from ramtracker.core import clock

    instant = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    with clock.frozen(instant) as pinned:
        yield pinned


@pytest.fixture
def golden_corpus() -> list[dict]:
    path = FIXTURES / "titles.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture
def compat_matrix():
    from ramtracker.core.config import load_yaml
    from ramtracker.extract.compat import CompatMatrix

    return load_yaml("compat", CompatMatrix)


@pytest.fixture
def threshold_policy():
    from ramtracker.decide.policy import load_threshold_policy

    return load_threshold_policy()
