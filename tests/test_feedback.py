"""WP09 — point d'entrée d'action (127.0.0.1 uniquement) et rejeu."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("migrated_db")


def _seed_alert(fingerprint: str) -> None:
    from datetime import UTC, datetime

    from ramtracker.core.db import session_scope

    now = datetime(2026, 10, 1, tzinfo=UTC).isoformat()
    with session_scope() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO listings(source, external_id, spec_hash, url, title, price,"
            " currency, sale_type, country, posted_at, first_seen, last_seen, raw_payload) "
            "VALUES ('ebay','1','h','u','t','200','EUR','buy_now','FR',?,?,?,?)",
            (now, now, now, b"{}"),
        )
        conn.execute(
            "INSERT INTO alerts(fingerprint, source, external_id, eur_per_gb, discount, urgency,"
            " price, sent_at) VALUES (?, 'ebay', '1', '1.6', 0.3, 'immediate', '200', ?)",
            (fingerprint, now),
        )


def test_mute_marks_ignored_and_sets_cooldown() -> None:
    from fastapi.testclient import TestClient

    from ramtracker.core.db import connection
    from ramtracker.runtime.feedback import create_app

    _seed_alert("fp-mute")
    client = TestClient(create_app())
    resp = client.post("/mute/fp-mute")
    assert resp.status_code == 200
    with connection() as conn:
        row = conn.execute(
            "SELECT outcome, muted_until FROM alerts WHERE fingerprint = 'fp-mute'"
        ).fetchone()
    assert row["outcome"] == "ignored"
    assert row["muted_until"] is not None


def test_unknown_fingerprint_is_404_no_write() -> None:
    from fastapi.testclient import TestClient

    from ramtracker.runtime.feedback import create_app

    client = TestClient(create_app())
    assert client.post("/mute/nope").status_code == 404


def test_serve_refuses_non_loopback() -> None:
    from ramtracker.runtime.feedback import serve

    with pytest.raises(ValueError, match="boucle locale"):
        serve(host="0.0.0.0")


def test_replay_is_read_only_on_alerts() -> None:
    from datetime import UTC, datetime

    from ramtracker.core.config import load_yaml
    from ramtracker.core.db import connection
    from ramtracker.core.payloads import pack
    from ramtracker.decide.policy import load_threshold_policy
    from ramtracker.extract import cascade
    from ramtracker.extract.compat import CompatMatrix

    now = datetime(2026, 9, 1, tzinfo=UTC).isoformat()
    with connection() as conn:
        conn.execute(
            "INSERT INTO spec_cache(spec_hash, kind, price_basis, confidence, method,"
            " parser_version, created_at) VALUES ('h', 'unknown', 'unknown', 0.4, 'rules', 1, ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO listings(source, external_id, spec_hash, url, title, price, currency,"
            " sale_type, country, posted_at, first_seen, last_seen, raw_payload) "
            "VALUES ('ebay','9','h','u','Lot 4x16GB DDR4 ECC REG 2133 PC4-17000','180','EUR',"
            "'buy_now','FR',?,?,?,?)",
            (now, now, now, pack(b"{}")),
        )
    # Un rejeu recalcule les specs mais ne doit jamais toucher `alerts`.
    matrix = load_yaml("compat", CompatMatrix)
    policy = load_threshold_policy()
    with connection() as conn:
        row = conn.execute("SELECT * FROM listings WHERE external_id = '9'").fetchone()
        from decimal import Decimal

        from ramtracker.core.models import RawListing, SaleType

        listing = RawListing(
            source=row["source"],
            external_id=row["external_id"],
            spec_hash=row["spec_hash"],
            url=row["url"],
            title=row["title"],
            description=None,
            price=Decimal(row["price"]),
            currency="EUR",
            shipping=None,
            sale_type=SaleType.BUY_NOW,
            country="FR",
            posted_at=datetime.fromisoformat(row["posted_at"]),
            raw_payload=row["raw_payload"],
        )
        spec = cascade.run(listing, matrix, None, min_confidence=policy.guards.min_confidence)
        assert spec.qualified  # la cascade courante la qualifie désormais
        alerts = conn.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()["n"]
    assert alerts == 0
