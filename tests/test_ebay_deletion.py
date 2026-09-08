"""WP10 — point d'entrée de suppression de compte eBay (conformité RGPD/CCPA)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator

import pytest

_TOKEN = "ramtracker-ebay-account-deletion-verification-0001"
_ENDPOINT = "https://ram.example.org/ebay/marketplace-account-deletion"

pytestmark = pytest.mark.usefixtures("migrated_db")


@pytest.fixture
def _configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from ramtracker.core import config

    monkeypatch.setenv("EBAY_VERIFICATION_TOKEN", _TOKEN)
    monkeypatch.setenv("EBAY_DELETION_ENDPOINT_URL", _ENDPOINT)
    config.reset_settings_cache()
    yield
    config.reset_settings_cache()


def _seed_ebay_listing(external_id: str, seller: str) -> None:
    from datetime import UTC, datetime

    from ramtracker.core.db import session_scope
    from ramtracker.core.payloads import pack

    now = datetime(2026, 9, 1, tzinfo=UTC).isoformat()
    payload = pack(
        json.dumps(
            {"itemId": external_id, "title": "DDR4 ECC", "seller": {"username": seller}}
        ).encode()
    )
    with session_scope() as conn:
        conn.execute(
            "INSERT INTO listings(source, external_id, spec_hash, url, title, price, currency,"
            " sale_type, seller_id, country, posted_at, first_seen, last_seen, raw_payload) "
            "VALUES ('ebay', ?, 'h', 'u', 't', '200', 'EUR', 'buy_now', ?, 'FR', ?, ?, ?, ?)",
            (external_id, seller, now, now, now, payload),
        )


def _notification(notification_id: str, username: str) -> dict[str, object]:
    return {
        "metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION", "schemaVersion": "1.0"},
        "notification": {
            "notificationId": notification_id,
            "eventDate": "2026-09-08T00:00:00.000Z",
            "publishDate": "2026-09-08T00:00:00.000Z",
            "publishAttemptCount": 1,
            "data": {"username": username, "userId": "abc123", "eiasToken": "nY+sHZ2Pr"},
        },
    }


def test_challenge_response_hashes_code_token_endpoint_in_order() -> None:
    from ramtracker.runtime.ebay_deletion import challenge_response

    expected = hashlib.sha256(f"XYZ{_TOKEN}{_ENDPOINT}".encode()).hexdigest()
    assert challenge_response("XYZ", _TOKEN, _ENDPOINT) == expected


@pytest.mark.usefixtures("_configured")
def test_challenge_endpoint_returns_json_200() -> None:
    from fastapi.testclient import TestClient

    from ramtracker.runtime.ebay_deletion import challenge_response, create_app

    client = TestClient(create_app())
    resp = client.get("/ebay/marketplace-account-deletion", params={"challenge_code": "abc-123"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {"challengeResponse": challenge_response("abc-123", _TOKEN, _ENDPOINT)}


def test_create_app_refuses_to_start_without_config() -> None:
    from ramtracker.core.errors import ConfigError
    from ramtracker.runtime.ebay_deletion import create_app

    with pytest.raises(ConfigError, match="EBAY_VERIFICATION_TOKEN"):
        create_app()


def test_create_app_rejects_malformed_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from ramtracker.core import config
    from ramtracker.core.errors import ConfigError
    from ramtracker.runtime.ebay_deletion import create_app

    monkeypatch.setenv("EBAY_VERIFICATION_TOKEN", "trop-court")
    monkeypatch.setenv("EBAY_DELETION_ENDPOINT_URL", _ENDPOINT)
    config.reset_settings_cache()
    with pytest.raises(ConfigError, match="invalide"):
        create_app()
    config.reset_settings_cache()


@pytest.mark.usefixtures("_configured")
def test_notification_anonymises_seller_and_returns_204() -> None:
    from fastapi.testclient import TestClient

    from ramtracker.core.db import connection
    from ramtracker.core.payloads import unpack
    from ramtracker.runtime.ebay_deletion import create_app

    _seed_ebay_listing("item-1", "vendeur_ferme")
    _seed_ebay_listing("item-2", "vendeur_ferme")
    _seed_ebay_listing("item-3", "autre_vendeur")

    client = TestClient(create_app())
    resp = client.post(
        "/ebay/marketplace-account-deletion", json=_notification("n-1", "vendeur_ferme")
    )
    assert resp.status_code == 204

    with connection() as conn:
        rows = conn.execute(
            "SELECT external_id, seller_id, raw_payload FROM listings ORDER BY external_id"
        ).fetchall()
        event = conn.execute(
            "SELECT scrubbed_rows FROM account_deletion_events WHERE notification_id = 'n-1'"
        ).fetchone()

    by_id = {r["external_id"]: r for r in rows}
    assert by_id["item-1"]["seller_id"] is None
    assert by_id["item-2"]["seller_id"] is None
    assert by_id["item-3"]["seller_id"] == "autre_vendeur"
    assert "seller" not in json.loads(unpack(by_id["item-1"]["raw_payload"]))
    assert "seller" in json.loads(unpack(by_id["item-3"]["raw_payload"]))
    assert event["scrubbed_rows"] == 2


@pytest.mark.usefixtures("_configured")
def test_notification_is_idempotent_on_notification_id() -> None:
    from fastapi.testclient import TestClient

    from ramtracker.core.db import connection
    from ramtracker.runtime.ebay_deletion import create_app

    _seed_ebay_listing("item-1", "vendeur_ferme")
    client = TestClient(create_app())
    body = _notification("n-dup", "vendeur_ferme")
    assert client.post("/ebay/marketplace-account-deletion", json=body).status_code == 204
    assert client.post("/ebay/marketplace-account-deletion", json=body).status_code == 204

    with connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM account_deletion_events WHERE notification_id = 'n-dup'"
        ).fetchone()["n"]
    assert count == 1


@pytest.mark.usefixtures("_configured")
def test_unexpected_topic_is_acknowledged_without_scrub() -> None:
    from fastapi.testclient import TestClient

    from ramtracker.core.db import connection
    from ramtracker.runtime.ebay_deletion import create_app

    _seed_ebay_listing("item-1", "vendeur_ferme")
    client = TestClient(create_app())
    resp = client.post(
        "/ebay/marketplace-account-deletion",
        json={"metadata": {"topic": "SOMETHING_ELSE"}, "notification": {}},
    )
    assert resp.status_code == 204
    with connection() as conn:
        row = conn.execute("SELECT seller_id FROM listings WHERE external_id = 'item-1'").fetchone()
    assert row["seller_id"] == "vendeur_ferme"


# -- tirage de la file du Worker --------------------------------------------------


@pytest.fixture
def _queue(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from ramtracker.core import config

    monkeypatch.setenv("ACCOUNT_DELETION_QUEUE_URL", "https://worker.example.workers.dev")
    monkeypatch.setenv("ACCOUNT_DELETION_PULL_SECRET", "pull-secret-xyz")
    config.reset_settings_cache()
    yield
    config.reset_settings_cache()


def test_drain_noop_when_queue_unconfigured() -> None:
    from ramtracker.runtime.ebay_deletion import drain

    assert drain() == 0


def test_drain_raises_when_half_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from ramtracker.core import config
    from ramtracker.core.errors import ConfigError
    from ramtracker.runtime.ebay_deletion import drain

    monkeypatch.setenv("ACCOUNT_DELETION_QUEUE_URL", "https://worker.example.workers.dev")
    config.reset_settings_cache()
    with pytest.raises(ConfigError, match="ACCOUNT_DELETION_PULL_SECRET"):
        drain()
    config.reset_settings_cache()


@pytest.mark.usefixtures("_queue")
def test_drain_processes_pending_and_acks() -> None:
    import httpx

    from ramtracker.core.db import connection
    from ramtracker.runtime.ebay_deletion import drain

    _seed_ebay_listing("item-1", "vendeur_ferme")
    _seed_ebay_listing("item-2", "autre")
    acked: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer pull-secret-xyz"
        if request.url.path == "/pending":
            return httpx.Response(
                200,
                json=[
                    {"notificationId": "n-1", "username": "vendeur_ferme"},
                    {"notificationId": "n-2", "username": "inconnu"},
                ],
            )
        if request.url.path == "/ack":
            acked.update(json.loads(request.content))
            return httpx.Response(204)
        raise AssertionError(request.url.path)

    count = drain(client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert count == 2
    assert set(acked["notificationIds"]) == {"n-1", "n-2"}
    with connection() as conn:
        seller = conn.execute(
            "SELECT seller_id FROM listings WHERE external_id = 'item-1'"
        ).fetchone()["seller_id"]
        events = conn.execute("SELECT COUNT(*) AS n FROM account_deletion_events").fetchone()["n"]
    assert seller is None
    assert events == 2


@pytest.mark.usefixtures("_queue")
def test_drain_is_idempotent_across_runs() -> None:
    import httpx

    from ramtracker.core.db import connection
    from ramtracker.runtime.ebay_deletion import drain

    _seed_ebay_listing("item-1", "vendeur_ferme")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/pending":
            return httpx.Response(
                200, json=[{"notificationId": "n-1", "username": "vendeur_ferme"}]
            )
        return httpx.Response(204)

    for _ in range(2):
        drain(client=httpx.Client(transport=httpx.MockTransport(handler)))

    with connection() as conn:
        events = conn.execute("SELECT COUNT(*) AS n FROM account_deletion_events").fetchone()["n"]
    assert events == 1
