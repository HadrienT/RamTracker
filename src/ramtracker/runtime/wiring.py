"""Construction des dépendances du pipeline depuis la configuration."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from ramtracker.collect.registry import build_collectors, load_sources_config
from ramtracker.core.config import get_settings, load_yaml
from ramtracker.core.db import connection
from ramtracker.core.logging import configure_logging, get_logger
from ramtracker.decide.policy import load_threshold_policy
from ramtracker.extract.compat import CompatMatrix
from ramtracker.notify.base import load_spam_policy
from ramtracker.notify.ntfy import NtfyNotifier
from ramtracker.runtime.breaker import Breaker
from ramtracker.runtime.llm_queue import load_llm_policy
from ramtracker.runtime.pipeline import PARSER_VERSION, Deps
from ramtracker.runtime.scheduler import Scheduler

_log = get_logger("runtime.wiring")


def build_deps(*, breaker: Breaker | None = None) -> Deps:
    settings = get_settings()
    configure_logging(settings.log_level)
    matrix = load_yaml("compat", CompatMatrix)
    policy = load_threshold_policy()
    llm_policy = load_llm_policy()
    sources = load_sources_config()

    return Deps(
        collectors=build_collectors(sources, settings),
        matrix=matrix,
        policy=policy,
        spam=load_spam_policy(),
        notifier=NtfyNotifier(settings),
        breaker=breaker or Breaker(),
        conn_factory=connection,
        llm_enabled=llm_policy.enabled,
        mute_endpoint=_mute_endpoint(),
        parser_version=PARSER_VERSION,
        server_busy=_server_busy_probe(settings.llm_base_url),
        verify_multi_quantity=policy.guards.verify_multi_quantity,
    )


def build_scheduler() -> Scheduler:
    sources = load_sources_config()
    intervals = {name: sources.interval_for(name) for name in ("ebay", "reddit", "leboncoin")}
    return Scheduler(intervals)


def _mute_endpoint() -> str | None:
    """L'endpoint des boutons d'action n'existe qu'une fois WP09 en écoute."""
    return None


def _server_busy_probe(base_url: str) -> Callable[[], bool]:
    """Sonde d'occupation du serveur LLM local. `[À CONFIRMER]` selon le serveur."""
    health_url = base_url.rstrip("/").removesuffix("/v1") + "/health"

    def probe() -> bool:
        try:
            resp = httpx.get(health_url, timeout=3.0)
        except httpx.HTTPError:
            return True  # injoignable ⇒ traité comme occupé (prudence)
        # llama.cpp : 503 quand tous les slots sont pris.
        return resp.status_code == 503

    return probe
