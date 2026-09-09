"""Point d'entrée en ligne de commande.

ramtracker migrate
ramtracker health
ramtracker run-once  --source ebay
ramtracker backfill  --days 30
ramtracker replay    --since 2026-08-01
ramtracker report    --weekly
ramtracker status
ramtracker loop
ramtracker account-deletion-drain
ramtracker serve-account-deletion  --host 0.0.0.0 --port 8782
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from decimal import Decimal

from ramtracker.core.clock import utc_now
from ramtracker.core.db import apply_migrations, check_health, connection, session_scope
from ramtracker.core.logging import configure_logging, get_logger
from ramtracker.core.models import RawListing, SaleType
from ramtracker.decide import market
from ramtracker.extract import cascade
from ramtracker.notify.base import Notification
from ramtracker.runtime import pipeline
from ramtracker.runtime.llm_queue import Lane, drain, load_llm_policy
from ramtracker.runtime.watchdog import check as watchdog_check
from ramtracker.runtime.watchdog import load_watchdog_policy
from ramtracker.runtime.wiring import build_deps, build_scheduler

_log = get_logger("runtime.cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ramtracker")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate")
    sub.add_parser("health")
    p_once = sub.add_parser("run-once")
    p_once.add_argument("--source", default=None)
    p_bf = sub.add_parser("backfill")
    p_bf.add_argument("--days", type=int, default=30)
    p_rp = sub.add_parser("replay")
    p_rp.add_argument("--since", required=True)
    p_rep = sub.add_parser("report")
    p_rep.add_argument("--weekly", action="store_true")
    p_st = sub.add_parser("status")
    p_st.add_argument("--json", action="store_true")
    sub.add_parser("loop")
    sub.add_parser("account-deletion-drain")
    p_del = sub.add_parser("serve-account-deletion")
    p_del.add_argument("--host", default="0.0.0.0")  # point d'entrée public
    p_del.add_argument("--port", type=int, default=8782)

    args = parser.parse_args(argv)
    configure_logging()

    if args.cmd == "migrate":
        applied = apply_migrations()
        print(f"migrations appliquées : {applied}")
        return 0
    if args.cmd == "health":
        print(check_health().model_dump_json(indent=2))
        return 0
    if args.cmd == "run-once":
        return _run_once(args.source)
    if args.cmd == "backfill":
        return _backfill(args.days)
    if args.cmd == "replay":
        return _replay(args.since)
    if args.cmd == "report":
        return _report()
    if args.cmd == "status":
        return _status(args.json)
    if args.cmd == "loop":
        return _loop()
    if args.cmd == "account-deletion-drain":
        return _account_deletion_drain()
    if args.cmd == "serve-account-deletion":
        return _serve_account_deletion(args.host, args.port)
    return 1


def _run_once(source: str | None) -> int:
    apply_migrations()
    deps = build_deps()
    targets = [source] if source else list(deps.collectors)
    if not targets:
        _log.warning("run.no_sources")
        return 0
    for name in targets:
        report = pipeline.run_source(name, deps)
        if report.error and not report.skipped:
            pipeline.persist_failed_run(deps, report)
        print(report.model_dump_json())
    _post_cycle(deps)
    return 0


def _backfill(days: int) -> int:
    apply_migrations()
    deps = build_deps()
    _log.info("backfill.start", days=days)
    for name in deps.collectors:
        report = pipeline.run_source(name, deps)
        print(report.model_dump_json())
    _post_cycle(deps)
    return 0


def _post_cycle(deps: pipeline.Deps) -> None:
    """Chien de garde, recalcul d'indice, file LLM différée, file suppression eBay."""
    from ramtracker.runtime.ebay_deletion import drain as drain_account_deletion
    from ramtracker.runtime.ebay_deletion import push_seller_allowlist

    push_seller_allowlist()  # avant le tirage : le Worker filtre sur une liste fraîche
    drain_account_deletion()
    with session_scope() as conn:
        anomalies = watchdog_check(conn, load_watchdog_policy(), utc_now())
        for anomaly in anomalies:
            deps.notifier.send(_technical(anomaly.message))
        market.refresh_index(
            conn,
            deps.policy.market_index.window_days,
            shipping_estimate=deps.policy.shipping.default_estimate_eur,
            buckets=tuple(deps.policy.market_index.capacity_buckets),
        )
        if deps.llm_enabled:
            policy = load_llm_policy()
            drain(
                conn,
                Lane.DEFERRED,
                policy.batch_size,
                deps.server_busy,
                matrix=deps.matrix,
                parser_version=deps.parser_version,
                policy=policy,
            )


def _technical(message: str) -> Notification:
    return Notification(
        title="RamTracker — alerte technique",
        body=message,
        priority=3,
        tags=["warning"],
        click="",
    )


def _replay(since_str: str) -> int:
    """Rejoue la cascade courante sur l'archive brute et affiche le différentiel.

    Strictement en lecture seule vis-à-vis de `alerts` : aucune notification.
    """
    since = datetime.fromisoformat(since_str)
    apply_migrations()
    deps = build_deps()
    counters = {
        "rejouees": 0,
        "nouvellement_qualifiees": 0,
        "nouvellement_rejetees": 0,
        "changement_de_spec": 0,
        "inchangees": 0,
    }
    with connection() as conn:
        rows = conn.execute(
            "SELECT l.*, s.reject_reason AS old_reject, s.total_gb AS old_total "
            "FROM listings l JOIN spec_cache s ON s.spec_hash = l.spec_hash "
            "WHERE julianday(l.posted_at) >= julianday(?)",
            (since.isoformat(),),
        ).fetchall()
        for row in rows:
            counters["rejouees"] += 1
            listing = _row_to_listing(row)
            spec = cascade.run(
                listing,
                deps.matrix,
                None,
                min_confidence=deps.policy.guards.min_confidence,
            )
            old_rejected = row["old_reject"] is not None
            if spec.qualified and old_rejected:
                counters["nouvellement_qualifiees"] += 1
            elif not spec.qualified and not old_rejected:
                counters["nouvellement_rejetees"] += 1
            elif spec.total_gb != row["old_total"]:
                counters["changement_de_spec"] += 1
            else:
                counters["inchangees"] += 1
    for key, value in counters.items():
        print(f"{key:28s} {value:6d}")
    if counters["nouvellement_rejetees"] > 0:
        print("\n⚠  des annonces auparavant qualifiées sont maintenant rejetées")
    return 0


def _report() -> int:
    apply_migrations()
    deps = build_deps()
    now = utc_now()
    week_ago = (now - timedelta(days=7)).isoformat()
    lines: list[str] = [f"RamTracker — rapport hebdomadaire {date.today().isoformat()}", ""]
    with connection() as conn:
        idx = market.latest_index(conn)
        lines.append("Indice de marché (€/Go médian) :")
        for bucket, p50 in sorted(idx.items()):
            lines.append(f"  {bucket:>3} Go : {p50}")
        alerts = conn.execute(
            "SELECT urgency, outcome, COUNT(*) AS n FROM alerts "
            "WHERE sent_at >= ? GROUP BY urgency, outcome",
            (week_ago,),
        ).fetchall()
        lines.append("\nAlertes (7 j) :")
        for r in alerts:
            lines.append(f"  {r['urgency']:>10} / {r['outcome'] or 'sans retour':>12} : {r['n']}")
        runs = conn.execute(
            "SELECT source, SUM(raw_count) AS raw, SUM(qualified) AS q, "
            "SUM(CASE WHEN raw_count = 0 THEN 1 ELSE 0 END) AS empty, "
            "SUM(challenged) AS blocked FROM source_runs WHERE started_at >= ? GROUP BY source",
            (week_ago,),
        ).fetchall()
        lines.append("\nSources (7 j) :")
        for r in runs:
            lines.append(
                f"  {r['source']:>10} : brut {r['raw']}, qualifiées {r['q']}, "
                f"cycles vides {r['empty']}, blocages {r['blocked']}"
            )
        stages = conn.execute(
            "SELECT method, COUNT(*) AS n FROM spec_cache GROUP BY method"
        ).fetchall()
        quarantine = conn.execute(
            "SELECT COUNT(*) AS n FROM spec_cache WHERE reject_reason = 'low_confidence'"
        ).fetchone()["n"]
        lines.append("\nExtraction :")
        for r in stages:
            lines.append(f"  {r['method']:>12} : {r['n']}")
        lines.append(f"  quarantaine  : {quarantine}")
    body = "\n".join(lines)
    print(body)
    try:
        from ramtracker.notify.base import Notification

        deps.notifier.send(
            Notification(
                title="RamTracker — rapport hebdo",
                body=body,
                priority=2,
                tags=["bar_chart"],
                click="",
            )
        )
    except Exception as exc:
        _log.warning("report.notify_failed", error=str(exc))
    return 0


def _fmt_ago(value: object, now: datetime) -> str:
    if not isinstance(value, str) or not value:
        return "jamais"
    delta = now - datetime.fromisoformat(value)
    secs = int(delta.total_seconds())
    if secs < 0:
        return "à l'instant"
    if secs < 90:
        return f"il y a {secs} s"
    if secs < 5400:
        return f"il y a {secs // 60} min"
    if secs < 172800:
        return f"il y a {secs // 3600} h"
    return f"il y a {secs // 86400} j"


def _status(as_json: bool = False) -> int:
    """État de santé synthétique. Code de sortie 1 si une source est muette ou en erreur."""
    from ramtracker.collect.registry import load_sources_config

    apply_migrations()
    now = utc_now()
    health = check_health()
    sources_cfg = load_sources_config()
    report: dict[str, object] = {"generated_at": now.isoformat(), "ok": health.ok}
    src_rows: list[dict[str, object]] = []
    degraded = not health.ok

    with connection() as conn:
        for name in ("ebay", "reddit", "leboncoin"):
            section = getattr(sources_cfg, name)
            if not section.enabled:
                continue
            last = conn.execute(
                "SELECT started_at, raw_count, qualified, alerted, error FROM source_runs "
                "WHERE source = ? ORDER BY started_at DESC LIMIT 1",
                (name,),
            ).fetchone()
            last_ok = conn.execute(
                "SELECT MAX(started_at) AS t FROM source_runs WHERE source = ? AND error IS NULL",
                (name,),
            ).fetchone()["t"]
            # Muet : aucun cycle réussi depuis deux intervalles + la gigue + 5 min.
            stale_after = (section.interval_min * 2 + section.jitter_min + 5) * 60
            muted = last_ok is None or (now - datetime.fromisoformat(last_ok)).total_seconds() > (
                stale_after
            )
            errored = last is not None and last["error"] is not None
            if muted or errored:
                degraded = True
            src_rows.append(
                {
                    "source": name,
                    "last_run": last["started_at"] if last else None,
                    "last_success": last_ok,
                    "raw_count": last["raw_count"] if last else None,
                    "qualified": last["qualified"] if last else None,
                    "alerted": last["alerted"] if last else None,
                    "error": last["error"] if last else None,
                    "interval_min": section.interval_min,
                    "muted": muted,
                }
            )

        alerts_7d = conn.execute(
            "SELECT COUNT(*) AS n FROM alerts WHERE sent_at >= ?",
            ((now - timedelta(days=7)).isoformat(),),
        ).fetchone()["n"]
        last_alert = conn.execute(
            "SELECT sent_at, eur_per_gb, price FROM alerts ORDER BY sent_at DESC LIMIT 1"
        ).fetchone()
        index = market.latest_index(conn)
        index_at = conn.execute("SELECT MAX(computed_at) AS t FROM market_stats").fetchone()["t"]
        samples = {
            int(r["capacity_bucket"]): int(r["sample_size"])
            for r in conn.execute(
                "SELECT capacity_bucket, sample_size FROM market_stats "
                "WHERE computed_at = (SELECT MAX(computed_at) FROM market_stats)"
            ).fetchall()
        }
        llm_depth = conn.execute("SELECT COUNT(*) AS n FROM llm_queue").fetchone()["n"]
        deletion = conn.execute(
            "SELECT COUNT(*) AS n, MAX(received_at) AS last, COALESCE(SUM(scrubbed_rows), 0) AS s "
            "FROM account_deletion_events WHERE received_at >= ?",
            ((now - timedelta(hours=24)).isoformat(),),
        ).fetchone()

    report["sources"] = src_rows
    report["alerts_7d"] = alerts_7d
    report["llm_queue_depth"] = llm_depth
    report["deletion_notifications_24h"] = deletion["n"]

    if as_json:
        import json as _json

        print(_json.dumps(report, indent=2, default=str))
        return 1 if degraded else 0

    print(f"RamTracker — état · {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(
        f"Base            schéma v{health.schema_version} · {health.journal_mode} · "
        f"intégrité {health.integrity}"
    )
    print("Sources")
    for row in src_rows:
        flag = "ERREUR" if row["error"] else ("MUET" if row["muted"] else "OK")
        detail = (
            f"{row['raw_count']} vues · {row['qualified']} qual. · {row['alerted']} alerte"
            if row["last_run"] and not row["error"]
            else (str(row["error"]) if row["error"] else "aucun cycle")
        )
        print(
            f"  {row['source']:<11} {_fmt_ago(row['last_success'], now):<14} {detail:<34} {flag}"
            f"   (~{row['interval_min']} min)"
        )
    if index:
        buckets = "  ".join(f"{b}:{samples.get(b, 0)}" for b in sorted(index))
        print(f"Marché          indice {_fmt_ago(index_at, now)} · échantillons  {buckets}")
    else:
        print("Marché          aucun indice calculé (mode observation)")
    if last_alert:
        print(
            f"Alertes (7 j)   {alerts_7d} · dernière {last_alert['sent_at'][:16]}  "
            f"{last_alert['eur_per_gb']} €/Go  {last_alert['price']} €"
        )
    else:
        print(f"Alertes (7 j)   {alerts_7d}")
    print(f"File LLM        {llm_depth} en attente")
    print(
        f"Suppression eBay {deletion['n']} notifs / 24 h · {deletion['s']} anonymisation(s) · "
        f"dernier reçu {_fmt_ago(deletion['last'], now)}"
    )
    print()
    print("OK" if not degraded else "DÉGRADÉ — voir ci-dessus")
    return 1 if degraded else 0


def _loop() -> int:
    apply_migrations()
    deps = build_deps(breaker=None)
    scheduler = build_scheduler()
    _log.info("loop.start", sources=list(deps.collectors))
    last_post_cycle = utc_now() - timedelta(hours=1)
    try:
        while True:
            now = utc_now()
            for name in deps.collectors:
                if scheduler.due(name, now):
                    report = pipeline.run_source(name, deps, now)
                    if report.error and not report.skipped:
                        pipeline.persist_failed_run(deps, report)
                    scheduler.mark_ran(name, now)
            if (now - last_post_cycle) >= timedelta(
                minutes=deps.policy.market_index.refresh_interval_min
            ):
                _post_cycle(deps)
                last_post_cycle = now
            time.sleep(30)
    except KeyboardInterrupt:  # pragma: no cover
        _log.info("loop.stop")
        return 0


def _serve_account_deletion(host: str, port: int) -> int:
    """Point d'entrée de conformité RGPD/CCPA eBay (WP10). Bloquant."""
    apply_migrations()
    from ramtracker.runtime.ebay_deletion import serve

    _log.info("account_deletion.serve", host=host, port=port)
    serve(host=host, port=port)
    return 0


def _account_deletion_drain() -> int:
    """Publie l'allow-list vendeurs, tire la file du Worker eBay et efface en base (WP10)."""
    apply_migrations()
    from ramtracker.runtime.ebay_deletion import drain, push_seller_allowlist

    pushed = push_seller_allowlist()
    if pushed:
        print(f"allow-list vendeurs publiée : {pushed}")
    count = drain()
    print(f"notifications de suppression traitées : {count}")
    return 0


def _row_to_listing(r: sqlite3.Row) -> RawListing:
    return RawListing.model_validate(
        {
            "source": r["source"],
            "external_id": r["external_id"],
            "spec_hash": r["spec_hash"],
            "url": r["url"],
            "title": r["title"],
            "description": r["description"],
            "price": Decimal(r["price"]),
            "currency": r["currency"],
            "shipping": Decimal(r["shipping"]) if r["shipping"] is not None else None,
            "sale_type": SaleType(r["sale_type"]),
            "current_bid": Decimal(r["current_bid"]) if r["current_bid"] else None,
            "ends_at": r["ends_at"],
            "seller_id": r["seller_id"],
            "country": r["country"],
            "posted_at": r["posted_at"],
            "raw_payload": r["raw_payload"],
        },
        context={"free_shipping": r["shipping"] == "0"},
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
