"""Nom de source → instance de `Collector`, construit depuis `sources.yaml`."""

from __future__ import annotations

from ramtracker.collect.base import Collector, SourcesConfig
from ramtracker.core.config import Settings, get_settings, load_yaml


def load_sources_config() -> SourcesConfig:
    return load_yaml("sources", SourcesConfig)


def build_collectors(
    config: SourcesConfig | None = None, settings: Settings | None = None
) -> dict[str, Collector]:
    """Construit un collecteur par source *activée*."""
    config = config or load_sources_config()
    settings = settings or get_settings()
    collectors: dict[str, Collector] = {}

    if config.ebay.enabled:
        from ramtracker.collect.ebay import EbayCollector

        collectors["ebay"] = EbayCollector(config.ebay, settings)

    if config.reddit.enabled:
        from ramtracker.collect.reddit import RedditCollector

        collectors["reddit"] = RedditCollector(config.reddit, settings)

    if config.leboncoin.enabled:
        from ramtracker.collect.leboncoin import LeboncoinCollector

        collectors["leboncoin"] = LeboncoinCollector(config.leboncoin)

    return collectors
