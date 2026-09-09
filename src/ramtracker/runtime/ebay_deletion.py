"""Suppression de compte eBay — conformité RGPD/CCPA (WP10).

eBay impose à toute application avec des clés de production un point d'entrée
HTTPS public qui accuse réception d'une notification par utilisateur eBay qui
ferme son compte, puis efface ses données personnelles. Sans lui, eBay suspend
l'accès à l'API de production.

Le serveur maison ne tournant que la journée, la responsabilité est coupée en
deux :

- un **Cloudflare Worker** (`deploy/worker/`, hébergement gratuit, toujours actif)
  répond au *challenge* et met les notifications en file (Cloudflare KV) ;
- **RamTracker tire cette file** (`drain`) à chaque cycle et anonymise en base les
  annonces du vendeur concerné.

Ce module fournit aussi une petite application FastAPI équivalente au Worker, utile
en test et pour un déploiement auto-hébergé 24/7 (VM gratuite). Elle n'est jamais
servie par `loop`.
"""

import hashlib
import json
import sqlite3

import httpx

from ramtracker.core.clock import utc_now
from ramtracker.core.config import Settings, get_settings
from ramtracker.core.db import session_scope
from ramtracker.core.errors import ConfigError
from ramtracker.core.logging import configure_logging, get_logger
from ramtracker.core.payloads import pack, unpack

_log = get_logger("runtime.ebay_deletion")

_PATH = "/ebay/marketplace-account-deletion"
_TOPIC = "MARKETPLACE_ACCOUNT_DELETION"
# Contrainte eBay : 32 à 80 caractères, alphanumérique + tiret + souligné.
_TOKEN_MIN, _TOKEN_MAX = 32, 80
_DRAIN_TIMEOUT_S = 15.0


def challenge_response(challenge_code: str, verification_token: str, endpoint: str) -> str:
    """SHA-256 hexadécimal de `challenge_code + verification_token + endpoint`.

    L'ordre de concaténation est imposé par eBay ; `endpoint` doit être identique
    au caractère près à l'URL déclarée dans le portail développeur.
    """
    digest = hashlib.sha256()
    digest.update(challenge_code.encode("utf-8"))
    digest.update(verification_token.encode("utf-8"))
    digest.update(endpoint.encode("utf-8"))
    return digest.hexdigest()


def _valid_token(token: str) -> bool:
    return _TOKEN_MIN <= len(token) <= _TOKEN_MAX and all(c.isalnum() or c in "_-" for c in token)


# -- effacement en base ------------------------------------------------------------


def process_deletion(notification_id: str, username: str) -> int | None:
    """Anonymise les annonces eBay de `username`. Idempotent sur `notification_id`.

    Renvoie le nombre de lignes anonymisées, ou `None` si la notification avait
    déjà été traitée.
    """
    with session_scope() as conn:
        seen = conn.execute(
            "SELECT 1 FROM account_deletion_events WHERE notification_id = ?",
            (notification_id,),
        ).fetchone()
        if seen is not None:
            _log.info("ebay.deletion.duplicate", notification_id=notification_id)
            return None
        scrubbed = _scrub_seller(conn, username)
        conn.execute(
            "INSERT INTO account_deletion_events(notification_id, received_at, scrubbed_rows) "
            "VALUES (?, ?, ?)",
            (notification_id, utc_now().isoformat(), scrubbed),
        )
    _log.info("ebay.deletion.processed", notification_id=notification_id, scrubbed_rows=scrubbed)
    return scrubbed


def _scrub_seller(conn: sqlite3.Connection, username: str) -> int:
    """Anonymise les annonces eBay du vendeur `username`. Renvoie le nombre de lignes."""
    rows = conn.execute(
        "SELECT external_id, raw_payload FROM listings WHERE source = 'ebay' AND seller_id = ?",
        (username,),
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE listings SET seller_id = NULL, raw_payload = ? "
            "WHERE source = 'ebay' AND external_id = ?",
            (_scrub_payload(row["raw_payload"]), row["external_id"]),
        )
    return len(rows)


def _scrub_payload(blob: bytes) -> bytes:
    """Retire le bloc `seller` de la charge utile archivée, en préservant le reste."""
    try:
        item = json.loads(unpack(blob))
    except (ValueError, json.JSONDecodeError):
        # Charge utile illisible : on la remplace par un marqueur plutôt que de
        # laisser une donnée personnelle non maîtrisée.
        return pack(b'{"_scrubbed": true}')
    if isinstance(item, dict):
        item.pop("seller", None)
    return pack(json.dumps(item, ensure_ascii=False).encode("utf-8"))


def _extract(payload: dict[str, object]) -> tuple[str, str] | None:
    """`(notification_id, username)` d'une charge utile eBay, ou `None` si malformée."""
    notification = payload.get("notification")
    if not isinstance(notification, dict):
        return None
    notification_id = str(notification.get("notificationId") or "")
    data = notification.get("data")
    username = str(data.get("username") or "") if isinstance(data, dict) else ""
    if not notification_id or not username:
        return None
    return notification_id, username


# -- tirage de la file distante (Cloudflare Worker) --------------------------------


def drain(settings: Settings | None = None, *, client: httpx.Client | None = None) -> int:
    """Tire les notifications en attente sur le Worker et les traite. Renvoie le nb traité.

    Sans file configurée, ne fait rien (la fonctionnalité est optionnelle tant que
    l'endpoint n'est pas branché). Configurée à moitié ⇒ `ConfigError`.
    """
    settings = settings or get_settings()
    url, secret = settings.account_deletion_queue_url, settings.account_deletion_pull_secret
    if not url and not secret:
        return 0
    if not url or not secret:
        raise ConfigError(
            "file de suppression de compte configurée à moitié",
            missing=[
                name
                for name, value in (
                    ("ACCOUNT_DELETION_QUEUE_URL", url),
                    ("ACCOUNT_DELETION_PULL_SECRET", secret),
                )
                if not value
            ],
        )

    owns_client = client is None
    client = client or httpx.Client(timeout=_DRAIN_TIMEOUT_S)
    headers = {"Authorization": f"Bearer {secret.get_secret_value()}"}
    try:
        resp = client.get(f"{url.rstrip('/')}/pending", headers=headers)
        resp.raise_for_status()
        pending = resp.json()
        done: list[str] = []
        for item in pending:
            notification_id = str(item.get("notificationId") or "")
            username = str(item.get("username") or "")
            if not notification_id or not username:
                _log.warning("ebay.deletion.malformed", reason="entrée de file incomplète")
                continue
            process_deletion(notification_id, username)
            done.append(notification_id)
        if done:
            ack = client.post(
                f"{url.rstrip('/')}/ack", headers=headers, json={"notificationIds": done}
            )
            ack.raise_for_status()
        _log.info("ebay.deletion.drained", count=len(done))
        return len(done)
    except httpx.HTTPError as exc:
        _log.warning("ebay.deletion.drain_failed", error=str(exc))
        return 0
    finally:
        if owns_client:
            client.close()


def push_seller_allowlist(
    settings: Settings | None = None, *, client: httpx.Client | None = None
) -> int:
    """Publie sur le Worker la liste des vendeurs eBay effectivement suivis.

    eBay notifie la fermeture de *tout* compte de l'UE (~600/jour) ; sans filtre,
    chaque notification coûte une écriture KV et fait sauter le palier gratuit.
    Le Worker ne met alors en file que les notifications visant un de ces vendeurs.

    Idempotent : n'émet une requête que si l'ensemble a changé depuis le dernier
    envoi (empreinte gardée dans `state_dir`). Sans file configurée, ne fait rien.
    Renvoie le nombre de vendeurs publiés, ou `0` si rien n'a été envoyé.
    """
    settings = settings or get_settings()
    url, secret = settings.account_deletion_queue_url, settings.account_deletion_pull_secret
    if not url or not secret:
        return 0

    with session_scope() as conn:
        names = sorted(
            str(row["seller_id"])
            for row in conn.execute(
                "SELECT DISTINCT seller_id FROM listings "
                "WHERE source = 'ebay' AND seller_id IS NOT NULL AND seller_id <> ''"
            ).fetchall()
        )

    digest = hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()
    marker = settings.state_dir / "ebay_allowlist.sha256"
    try:
        if marker.read_text(encoding="utf-8").strip() == digest:
            return 0
    except OSError:
        pass

    owns_client = client is None
    client = client or httpx.Client(timeout=_DRAIN_TIMEOUT_S)
    try:
        resp = client.post(
            f"{url.rstrip('/')}/allowlist",
            headers={"Authorization": f"Bearer {secret.get_secret_value()}"},
            json=names,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        _log.warning("ebay.allowlist.push_failed", error=str(exc))
        return 0
    finally:
        if owns_client:
            client.close()

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(digest, encoding="utf-8")
    _log.info("ebay.allowlist.pushed", count=len(names))
    return len(names)


# -- application FastAPI équivalente (test / auto-hébergement 24/7) -----------------


def _endpoint_config(settings: Settings) -> tuple[str, str]:
    """`(verification_token, endpoint_url)` ou `ConfigError` nommant le trou."""
    missing = [
        name
        for name, value in (
            ("EBAY_VERIFICATION_TOKEN", settings.ebay_verification_token),
            ("EBAY_DELETION_ENDPOINT_URL", settings.ebay_deletion_endpoint_url),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "point d'entrée de suppression de compte eBay non configuré", missing=missing
        )
    token = settings.ebay_verification_token.get_secret_value()  # type: ignore[union-attr]
    if not _valid_token(token):
        raise ConfigError(
            "EBAY_VERIFICATION_TOKEN invalide : 32-80 caractères [A-Za-z0-9_-] attendus"
        )
    return token, settings.ebay_deletion_endpoint_url  # type: ignore[return-value]


def create_app() -> object:
    """Application FastAPI. Lève `ConfigError` si la conformité n'est pas configurée."""
    from fastapi import FastAPI, Request, Response

    configure_logging()
    token, endpoint = _endpoint_config(get_settings())
    app = FastAPI(title="RamTracker eBay account deletion", docs_url=None, redoc_url=None)

    @app.get(_PATH)
    def challenge(challenge_code: str) -> Response:
        body = json.dumps(
            {"challengeResponse": challenge_response(challenge_code, token, endpoint)}
        )
        _log.info("ebay.deletion.challenge")
        return Response(content=body, media_type="application/json", status_code=200)

    @app.post(_PATH)
    async def notify(request: Request) -> Response:
        raw = await request.body()
        # `[À CONFIRMER]` — vérification de la signature `x-ebay-signature` :
        # eBay la recommande mais le test de validation du portail ne l'exige pas.
        # Suivi ouvert dans WP10 §6.
        if "x-ebay-signature" not in request.headers:
            _log.info("ebay.deletion.unsigned")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            _log.warning("ebay.deletion.malformed", reason="corps non-JSON")
            return Response(status_code=204)
        topic = (payload.get("metadata") or {}).get("topic") if isinstance(payload, dict) else None
        if topic != _TOPIC:
            _log.warning("ebay.deletion.unexpected_topic", topic=str(topic))
            return Response(status_code=204)
        extracted = _extract(payload)
        if extracted is None:
            _log.warning("ebay.deletion.malformed", reason="notificationId ou username absent")
            return Response(status_code=204)
        process_deletion(*extracted)
        return Response(status_code=204)

    return app


def serve(host: str = "0.0.0.0", port: int = 8782) -> None:  # pragma: no cover
    """Sert le point d'entrée. Écoute publiquement : à placer derrière un proxy TLS."""
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, log_level="warning")  # type: ignore[arg-type]
