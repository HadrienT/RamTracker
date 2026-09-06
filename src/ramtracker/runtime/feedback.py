"""Point d'entrée d'action des notifications (WP09 §2).

Trente lignes de FastAPI, en écoute sur **127.0.0.1 uniquement**. Chaque
« Ignorer » devient une étiquette négative exploitable par la boucle
d'amélioration.
"""

from __future__ import annotations

from datetime import timedelta

from ramtracker.core.clock import utc_now
from ramtracker.core.db import session_scope
from ramtracker.core.logging import configure_logging, get_logger

_log = get_logger("runtime.feedback")

_MUTE_HOURS = 24


def create_app() -> object:
    from fastapi import FastAPI, HTTPException

    configure_logging()
    app = FastAPI(title="RamTracker feedback", docs_url=None, redoc_url=None)

    @app.post("/mute/{fingerprint}")
    def mute(fingerprint: str) -> dict[str, str]:
        until = (utc_now() + timedelta(hours=_MUTE_HOURS)).isoformat()
        with session_scope() as conn:
            changed = conn.execute(
                "UPDATE alerts SET outcome = 'ignored', muted_until = ? WHERE fingerprint = ?",
                (until, fingerprint),
            ).rowcount
        if not changed:
            raise HTTPException(status_code=404, detail="empreinte inconnue")
        _log.info("feedback.mute", fingerprint=fingerprint, until=until)
        return {"status": "muted", "until": until}

    @app.post("/bought/{fingerprint}")
    def bought(fingerprint: str) -> dict[str, str]:
        with session_scope() as conn:
            changed = conn.execute(
                "UPDATE alerts SET outcome = 'bought' WHERE fingerprint = ?",
                (fingerprint,),
            ).rowcount
        if not changed:
            raise HTTPException(status_code=404, detail="empreinte inconnue")
        _log.info("feedback.bought", fingerprint=fingerprint)
        return {"status": "bought"}

    return app


def serve(host: str = "127.0.0.1", port: int = 8781) -> None:  # pragma: no cover
    import uvicorn

    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("le point d'entrée d'action n'écoute que sur la boucle locale")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")  # type: ignore[arg-type]
