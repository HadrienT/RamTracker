"""WP06 — disjoncteur, chien de garde inversé, ordonnanceur."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from ramtracker.runtime.breaker import Breaker
from ramtracker.runtime.scheduler import Scheduler
from ramtracker.runtime.watchdog import WatchdogPolicy, check

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_breaker_opens_after_three_failures_per_source() -> None:
    b = Breaker(rng=random.Random(0))
    for _ in range(2):
        assert b.record_failure("leboncoin", NOW) is False
    assert b.record_failure("leboncoin", NOW) is True
    assert b.is_open("leboncoin", NOW)
    # eBay n'est pas affecté
    assert b.allow("ebay", NOW)


def test_breaker_success_closes_immediately() -> None:
    b = Breaker(rng=random.Random(0))
    b.record_failure("ebay", NOW)
    b.record_failure("ebay", NOW)
    b.record_success("ebay")
    assert b.allow("ebay", NOW)
    assert not b.is_open("ebay", NOW)


def test_breaker_backoff_grows() -> None:
    b = Breaker(rng=random.Random(1))
    b.record_failure("s", NOW)
    first = b._state["s"].open_until
    b.record_failure("s", NOW)
    second = b._state["s"].open_until
    assert first is not None and second is not None
    assert (second - NOW) > (first - NOW)


def test_scheduler_jitter_varies_offsets() -> None:
    s = Scheduler({"ebay": (10, 3)}, rng=random.Random(5))
    a = s.mark_ran("ebay", NOW)
    b = s.mark_ran("ebay", NOW)
    assert a != b


@pytest.mark.usefixtures("migrated_db")
def test_watchdog_alerts_on_silent_but_previously_active_source() -> None:
    from ramtracker.core.db import session_scope

    policy = WatchdogPolicy(empty_cycles_before_alert=3, min_prior_activity=5)
    with session_scope() as conn:
        _runs(conn, "leboncoin", [10, 8, 12, 0, 0, 0])
        anomalies = check(conn, policy, NOW)
    assert [a.source for a in anomalies] == ["leboncoin"]


@pytest.mark.usefixtures("migrated_db")
def test_watchdog_silent_on_never_active_source() -> None:
    from ramtracker.core.db import session_scope

    policy = WatchdogPolicy(empty_cycles_before_alert=3, min_prior_activity=5)
    with session_scope() as conn:
        _runs(conn, "reddit", [0, 0, 0])
        assert check(conn, policy, NOW) == []


@pytest.mark.usefixtures("migrated_db")
def test_watchdog_silent_when_raw_positive_but_zero_qualified() -> None:
    from ramtracker.core.db import session_scope

    policy = WatchdogPolicy(empty_cycles_before_alert=3, min_prior_activity=5)
    with session_scope() as conn:
        _runs(conn, "ebay", [20, 20, 20], qualified=0)
        assert check(conn, policy, NOW) == []


@pytest.mark.usefixtures("migrated_db")
def test_watchdog_disarms_when_source_returns() -> None:
    from ramtracker.core.db import session_scope

    policy = WatchdogPolicy(empty_cycles_before_alert=3, min_prior_activity=5)
    with session_scope() as conn:
        _runs(conn, "leboncoin", [10, 8, 0, 0, 0, 7])
        assert check(conn, policy, NOW) == []


def _runs(conn, source: str, raw_counts: list[int], *, qualified: int | None = None) -> None:
    for i, raw in enumerate(raw_counts):
        conn.execute(
            "INSERT INTO source_runs(run_id, source, started_at, duration_ms, raw_count,"
            " new_count, qualified, alerted) VALUES (?, ?, ?, 10, ?, 0, ?, 0)",
            (
                f"{source}-{i}",
                source,
                (NOW + timedelta(minutes=i)).isoformat(),
                raw,
                qualified if qualified is not None else raw,
            ),
        )


@pytest.mark.usefixtures("migrated_db")
def test_status_command_ok_and_degraded(capsys: pytest.CaptureFixture[str]) -> None:
    from ramtracker.core.clock import utc_now
    from ramtracker.core.db import session_scope
    from ramtracker.runtime.cli import main

    fresh = utc_now().isoformat()
    with session_scope() as conn:
        conn.execute(
            "INSERT INTO source_runs(run_id, source, started_at, duration_ms, raw_count,"
            " new_count, qualified, alerted, challenged, error) "
            "VALUES ('r1', 'ebay', ?, 10, 40, 40, 1, 0, 0, NULL)",
            (fresh,),
        )
    assert main(["status"]) == 0
    assert "OK" in capsys.readouterr().out

    with session_scope() as conn:
        conn.execute(
            "INSERT INTO source_runs(run_id, source, started_at, duration_ms, raw_count,"
            " new_count, qualified, alerted, challenged, error) "
            "VALUES ('r2', 'ebay', ?, 10, 0, 0, 0, 0, 0, 'source_unavailable')",
            (utc_now().isoformat(),),
        )
    assert main(["status"]) == 1
    assert "DÉGRADÉ" in capsys.readouterr().out
