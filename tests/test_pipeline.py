"""WP06 — câblage du pipeline : isolation des erreurs, persistance, bout-en-bout."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ramtracker.collect.base import CollectResult
from ramtracker.core.config import load_yaml
from ramtracker.core.db import connection
from ramtracker.core.errors import SourceUnavailable
from ramtracker.core.models import RawListing, SaleType
from ramtracker.decide.policy import load_threshold_policy
from ramtracker.extract.compat import CompatMatrix
from ramtracker.notify.base import Notification, load_spam_policy
from ramtracker.runtime.breaker import Breaker
from ramtracker.runtime.pipeline import Deps, run_source

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("migrated_db")


class FakeCollector:
    def __init__(self, name: str, result: CollectResult | Exception) -> None:
        self.name = name
        self._result = result

    def fetch_recent(self, since: datetime) -> CollectResult:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, n: Notification) -> None:
        self.sent.append(n)


def _listing(title: str, price: str, ext: str = "1") -> RawListing:
    from ramtracker.core.hashing import spec_hash

    return RawListing(
        source="ebay",
        external_id=ext,
        spec_hash=spec_hash(title, None),
        url="https://ebay/x",
        title=title,
        description=None,
        price=Decimal(price),
        currency="EUR",
        shipping=Decimal("6"),
        sale_type=SaleType.BUY_NOW,
        country="FR",
        posted_at=NOW,
        raw_payload=b"{}",
    )


def _deps(collectors: dict, notifier: RecordingNotifier) -> Deps:
    return Deps(
        collectors=collectors,
        matrix=load_yaml("compat", CompatMatrix),
        policy=load_threshold_policy(),
        spam=load_spam_policy(),
        notifier=notifier,
        breaker=Breaker(),
        conn_factory=connection,
    )


def test_failing_source_writes_run_row_and_spares_others() -> None:
    notifier = RecordingNotifier()
    good = CollectResult(source="reddit", listings=[], raw_count=4, duration_ms=1)
    deps = _deps(
        {
            "ebay": FakeCollector("ebay", SourceUnavailable("5xx", source="ebay")),
            "reddit": FakeCollector("reddit", good),
        },
        notifier,
    )
    ebay_report = run_source("ebay", deps, NOW)
    reddit_report = run_source("reddit", deps, NOW)
    assert ebay_report.error == "source_unavailable"
    assert reddit_report.error is None

    from ramtracker.runtime.pipeline import persist_failed_run

    persist_failed_run(deps, ebay_report)
    with connection() as conn:
        rows = {
            r["source"]: r["error"] for r in conn.execute("SELECT source, error FROM source_runs")
        }
    assert rows["ebay"] == "source_unavailable"
    assert rows["reddit"] is None


def test_end_to_end_alert_in_observation_mode() -> None:
    notifier = RecordingNotifier()
    # 4x32 Go RDIMM 2133 à 180 € -> ~1.45 €/Go, sous le plafond dur
    result = CollectResult(
        source="ebay",
        listings=[_listing("Lot 4x32GB DDR4 ECC REG 2133 PC4-17000", "180")],
        raw_count=1,
        duration_ms=5,
    )
    deps = _deps({"ebay": FakeCollector("ebay", result)}, notifier)
    report = run_source("ebay", deps, NOW)
    assert report.qualified == 1
    assert report.alerted == 1
    assert notifier.sent and notifier.sent[0].priority == 5
    with connection() as conn:
        alerts = conn.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()["n"]
    assert alerts == 1


def test_reposts_do_not_realert() -> None:
    notifier = RecordingNotifier()
    listing = _listing("Lot 4x32GB DDR4 ECC REG 2133 PC4-17000", "180")
    result = CollectResult(source="ebay", listings=[listing], raw_count=1, duration_ms=1)
    deps = _deps({"ebay": FakeCollector("ebay", result)}, notifier)
    run_source("ebay", deps, NOW)
    # même annonce, nouvel identifiant, texte identique -> zéro nouvelle alerte
    repost = CollectResult(
        source="ebay",
        listings=[_listing("Lot 4x32GB DDR4 ECC REG 2133 PC4-17000", "180", ext="2")],
        raw_count=1,
        duration_ms=1,
    )
    deps.collectors["ebay"] = FakeCollector("ebay", repost)
    run_source("ebay", deps, NOW)
    assert len(notifier.sent) == 1
