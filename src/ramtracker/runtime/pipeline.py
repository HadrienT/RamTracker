"""Câblage des huit étages (WP06).

Aucune règle métier ici : l'ordre des appels, la persistance, le traitement des
erreurs par étage. Une source en échec n'interrompt jamais le cycle des autres.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel

from ramtracker.collect.base import Collector, CollectResult
from ramtracker.core.clock import utc_now
from ramtracker.core.errors import (
    SourceAuthError,
    SourceBlocked,
    SourceError,
    SourceSchemaChanged,
    SourceUnavailable,
)
from ramtracker.core.logging import get_logger, new_run_id, run_context
from ramtracker.core.models import Deal, MemorySpec, RawListing
from ramtracker.decide import dedupe, market
from ramtracker.decide.policy import ThresholdPolicy
from ramtracker.decide.thresholds import evaluate_detailed, in_observation_mode
from ramtracker.extract import cascade
from ramtracker.extract.compat import CompatMatrix
from ramtracker.extract.prefilter import best_case_eur_per_gb
from ramtracker.notify import ratelimit
from ramtracker.notify.base import Notification, Notifier, SpamPolicy
from ramtracker.notify.templates import render
from ramtracker.runtime import llm_queue
from ramtracker.runtime.breaker import Breaker

_log = get_logger("runtime.pipeline")

PARSER_VERSION = 1


class RunReport(BaseModel):
    source: str
    run_id: str
    started_at: datetime
    duration_ms: int
    raw_count: int
    new_count: int
    qualified: int
    alerted: int
    challenged: bool = False
    skipped: bool = False
    error: str | None = None


ConnFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]


@dataclass
class Deps:
    collectors: dict[str, Collector]
    matrix: CompatMatrix
    policy: ThresholdPolicy
    spam: SpamPolicy
    notifier: Notifier
    breaker: Breaker
    conn_factory: ConnFactory
    llm_enabled: bool = False
    mute_endpoint: str | None = None
    parser_version: int = PARSER_VERSION
    server_busy: Callable[[], bool] = field(default=lambda: False)


def _since(conn: sqlite3.Connection, source: str, now: datetime) -> datetime:
    row = conn.execute(
        "SELECT MAX(started_at) AS last FROM source_runs WHERE source = ? AND error IS NULL",
        (source,),
    ).fetchone()
    if row and row["last"]:
        return datetime.fromisoformat(row["last"]) - timedelta(minutes=5)
    return now - timedelta(hours=1)


def run_source(name: str, deps: Deps, now: datetime | None = None) -> RunReport:
    """Exécute un cycle complet pour une source. Écrit toujours dans `source_runs`."""
    now = now or utc_now()
    run_id = new_run_id()
    with run_context(run_id, source=name):
        started = now
        collector = deps.collectors.get(name)
        if collector is None:
            return RunReport(
                source=name,
                run_id=run_id,
                started_at=started,
                duration_ms=0,
                raw_count=0,
                new_count=0,
                qualified=0,
                alerted=0,
                skipped=True,
                error="collector_absent",
            )
        if not deps.breaker.allow(name, now):
            _log.info("source.skipped", source=name, reason="breaker_open")
            return RunReport(
                source=name,
                run_id=run_id,
                started_at=started,
                duration_ms=0,
                raw_count=0,
                new_count=0,
                qualified=0,
                alerted=0,
                skipped=True,
                error="breaker_open",
            )

        with deps.conn_factory() as conn:
            since = _since(conn, name, now)

        try:
            result = collector.fetch_recent(since)
        except SourceBlocked as exc:
            just_opened = deps.breaker.record_failure(name, now)
            if just_opened:
                _emit_technical(deps, f"{name} bloqué — disjoncteur ouvert")
            return _failed_report(name, run_id, started, now, exc, challenged=True)
        except SourceSchemaChanged as exc:
            _emit_technical(deps, f"{name} — schéma de données changé : {exc.message}")
            return _failed_report(name, run_id, started, now, exc)
        except SourceAuthError as exc:
            deps.breaker.record_failure(name, now)
            _emit_technical(deps, f"{name} — authentification en échec")
            return _failed_report(name, run_id, started, now, exc)
        except (SourceUnavailable, SourceError) as exc:
            deps.breaker.record_failure(name, now)
            return _failed_report(name, run_id, started, now, exc)

        deps.breaker.record_success(name)
        report = _process(name, run_id, started, now, result, deps)
        return report


def _process(
    name: str,
    run_id: str,
    started: datetime,
    now: datetime,
    result: CollectResult,
    deps: Deps,
) -> RunReport:
    new_count = qualified = alerted = 0
    with deps.conn_factory() as conn:
        sample = market.latest_sample_size(conn, 32)
        observation = in_observation_mode(deps.policy, now, sample)
        index = market.latest_index(conn)

        for listing in result.listings:
            outcome = _handle_listing(listing, deps, conn, index, now, observation)
            if outcome.is_new:
                new_count += 1
            if outcome.qualified:
                qualified += 1
            if outcome.alerted:
                alerted += 1

        duration_ms = int((now - started).total_seconds() * 1000)
        conn.execute(
            "INSERT OR REPLACE INTO source_runs"
            "(run_id, source, started_at, duration_ms, raw_count, new_count, qualified,"
            " alerted, challenged, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                name,
                started.isoformat(),
                duration_ms,
                result.raw_count,
                new_count,
                qualified,
                alerted,
                int(result.challenged),
                None,
            ),
        )

    _log.info(
        "run.done",
        run_id=run_id,
        source=name,
        raw_count=result.raw_count,
        new_count=new_count,
        qualified=qualified,
        alerts_sent=alerted,
    )
    return RunReport(
        source=name,
        run_id=run_id,
        started_at=started,
        duration_ms=int((now - started).total_seconds() * 1000),
        raw_count=result.raw_count,
        new_count=new_count,
        qualified=qualified,
        alerted=alerted,
        challenged=result.challenged,
    )


@dataclass
class _ListingOutcome:
    is_new: bool = False
    qualified: bool = False
    alerted: bool = False


def _handle_listing(
    listing: RawListing,
    deps: Deps,
    conn: sqlite3.Connection,
    index: dict[int, Decimal],
    now: datetime,
    observation: bool,
) -> _ListingOutcome:
    out = _ListingOutcome()
    fresh = dedupe.is_new(listing, conn)
    dropped = not fresh and dedupe.price_dropped(listing, conn, deps.spam.re_alert_min_drop_pct)
    if not fresh and not dropped:
        conn.execute(
            "UPDATE listings SET last_seen = ? WHERE source = ? AND external_id = ?",
            (now.isoformat(), listing.source, listing.external_id),
        )
        return out

    out.is_new = fresh
    spec = _cached_spec(conn, listing.spec_hash, deps.parser_version)
    if spec is None:
        spec = cascade.run(
            listing,
            deps.matrix,
            None,
            min_confidence=deps.policy.guards.min_confidence,
            hard_ceiling_eur_per_gb=(
                deps.policy.barriers.hard_ceiling_eur_per_gb if deps.llm_enabled else None
            ),
        )
        _store_spec(conn, listing.spec_hash, spec, deps.parser_version)

    _upsert_listing(conn, listing, now, fresh)
    if spec.qualified:
        out.qualified = True

    if not listing.alert_eligible:
        return out

    result = evaluate_detailed(listing, spec, index, deps.policy, now, observation=observation)
    if result.send_to_llm and deps.llm_enabled:
        best = best_case_eur_per_gb(listing, _listing_text(listing))
        lane = llm_queue.lane_for(
            best,
            deps.policy.barriers.hard_ceiling_eur_per_gb,
            llm_queue.load_llm_policy().urgent_lane_margin,
        )
        llm_queue.enqueue(conn, listing.spec_hash, lane, best)
        return out

    if result.deal is not None and _send(deps, conn, result.deal, now):
        out.alerted = True
    return out


def _send(deps: Deps, conn: sqlite3.Connection, deal: Deal, now: datetime) -> bool:
    decision = ratelimit.decide(deal, conn, deps.spam, now)
    if not decision.allowed:
        return False
    notification = render(deal, mute_endpoint=deps.mute_endpoint)
    notification = notification.model_copy(update={"priority": decision.priority})
    try:
        deps.notifier.send(notification)
    except Exception:
        try:
            deps.notifier.send(notification)
        except Exception as exc:
            _log.error("notify.failed", listing_id=deal.listing.url, error=str(exc))
            return False
    conn.execute(
        "INSERT INTO alerts(fingerprint, source, external_id, eur_per_gb, discount,"
        " urgency, price, sent_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            deal.fingerprint,
            deal.listing.source,
            deal.listing.external_id,
            str(deal.eur_per_gb),
            deal.discount,
            deal.urgency.value,
            str(deal.listing.price),
            now.isoformat(),
        ),
    )
    return True


def _listing_text(listing: RawListing) -> str:
    return f"{listing.title}\n{listing.description}" if listing.description else listing.title


def _cached_spec(
    conn: sqlite3.Connection, spec_hash: str, parser_version: int
) -> MemorySpec | None:
    row = conn.execute(
        "SELECT * FROM spec_cache WHERE spec_hash = ? AND parser_version >= ?",
        (spec_hash, parser_version),
    ).fetchone()
    if row is None:
        return None
    from ramtracker.core.models import Kind, Method, PriceBasis

    return MemorySpec(
        module_capacity_gb=row["module_capacity_gb"],
        module_count=row["module_count"],
        total_gb=row["total_gb"],
        kind=Kind(row["kind"]),
        speed_mts=row["speed_mts"],
        ranks=row["ranks"],
        part_number=row["part_number"],
        price_basis=PriceBasis(row["price_basis"]),
        confidence=row["confidence"],
        method=Method(row["method"]),
        reject_reason=row["reject_reason"],
    )


def _store_spec(
    conn: sqlite3.Connection, spec_hash: str, spec: MemorySpec, parser_version: int
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO spec_cache
        (spec_hash, module_capacity_gb, module_count, total_gb, kind, speed_mts, ranks,
         part_number, price_basis, confidence, method, reject_reason, parser_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            spec_hash,
            spec.module_capacity_gb,
            spec.module_count,
            spec.total_gb,
            spec.kind.value,
            spec.speed_mts,
            spec.ranks,
            spec.part_number,
            spec.price_basis.value,
            spec.confidence,
            spec.method.value,
            spec.reject_reason,
            parser_version,
            utc_now().isoformat(),
        ),
    )


def _upsert_listing(
    conn: sqlite3.Connection, listing: RawListing, now: datetime, fresh: bool
) -> None:
    ts = now.isoformat()
    conn.execute(
        """
        INSERT INTO listings
        (source, external_id, spec_hash, url, title, description, price, currency,
         shipping, sale_type, current_bid, ends_at, seller_id, country, posted_at,
         first_seen, last_seen, raw_payload)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
          price = excluded.price, shipping = excluded.shipping,
          current_bid = excluded.current_bid, last_seen = excluded.last_seen,
          spec_hash = excluded.spec_hash
        """,
        (
            listing.source,
            listing.external_id,
            listing.spec_hash,
            listing.url,
            listing.title,
            listing.description,
            str(listing.price),
            listing.currency,
            None if listing.shipping is None else str(listing.shipping),
            listing.sale_type.value,
            None if listing.current_bid is None else str(listing.current_bid),
            listing.ends_at.isoformat() if listing.ends_at else None,
            listing.seller_id,
            listing.country,
            listing.posted_at.isoformat(),
            ts,
            ts,
            listing.raw_payload,
        ),
    )
    _ = fresh


def _emit_technical(deps: Deps, message: str) -> None:
    try:
        deps.notifier.send(
            Notification(
                title="RamTracker — alerte technique",
                body=message,
                priority=3,
                tags=["warning"],
                click="",
            )
        )
    except Exception as exc:
        _log.error("notify.technical.failed", error=str(exc))


def _failed_report(
    name: str,
    run_id: str,
    started: datetime,
    now: datetime,
    exc: SourceError,
    *,
    challenged: bool = False,
) -> RunReport:
    _log.warning("source.failed", source=name, code=exc.code, error=exc.message)
    return RunReport(
        source=name,
        run_id=run_id,
        started_at=started,
        duration_ms=int((now - started).total_seconds() * 1000),
        raw_count=0,
        new_count=0,
        qualified=0,
        alerted=0,
        challenged=challenged,
        error=exc.code,
    )


def persist_failed_run(deps: Deps, report: RunReport) -> None:
    """Écrit une ligne `source_runs` pour un run en échec (P3 : jamais silencieux)."""
    with deps.conn_factory() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO source_runs"
            "(run_id, source, started_at, duration_ms, raw_count, new_count, qualified,"
            " alerted, challenged, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report.run_id,
                report.source,
                report.started_at.isoformat(),
                report.duration_ms,
                0,
                0,
                0,
                0,
                int(report.challenged),
                report.error,
            ),
        )
