"""Rendu achat immédiat / enchère (WP05 §3.2).

Le titre doit se lire sans ouvrir la notification. Ordre d'importance :
€/Go, décote, capacité totale, source.
"""

from __future__ import annotations

from ramtracker.core.models import Deal, Urgency
from ramtracker.notify.base import Action, Notification

_PRIORITY = {Urgency.IMMEDIATE: 5, Urgency.QUIET: 2}


def render(deal: Deal, *, mute_endpoint: str | None = None) -> Notification:
    """Transforme un `Deal` en `Notification`. `mute_endpoint` vient de WP09."""
    spec = deal.spec
    listing = deal.listing
    total_gb = spec.total_gb or 0
    kind = spec.kind.value.upper()
    speed = f"{spec.speed_mts}" if spec.speed_mts else "?"
    discount_pct = round(deal.discount * 100)

    if deal.urgency is Urgency.QUIET:
        title = f"Enchère {deal.eur_per_gb} €/Go — {total_gb} Go, plafond {deal.max_bid} €"
    elif deal.market_ref is not None:
        title = f"{deal.eur_per_gb} €/Go — {discount_pct} % sous le marché"
    else:
        title = f"{deal.eur_per_gb} €/Go — {total_gb} Go"

    lines = [
        f"{spec.module_count} × {spec.module_capacity_gb} Go {kind} {speed} · {total_gb} Go",
        f"{listing.price} {listing.currency}"
        + (
            f" + {listing.shipping} port"
            if listing.shipping is not None
            else " · port estimé"
            if deal.shipping_estimated
            else ""
        )
        + f" · {listing.source}"
        + (f" · {listing.country}" if listing.country else ""),
    ]
    if spec.part_number:
        lines.append(f"réf. {spec.part_number}")
    if deal.urgency is Urgency.QUIET:
        left = _time_left(deal)
        if left:
            lines.append(f"fin dans {left}")

    actions = [Action(action="view", label="Ouvrir l'annonce", url=listing.url)]
    if mute_endpoint:
        actions.append(
            Action(
                action="http",
                label="Ignorer 24 h",
                url=f"{mute_endpoint}/mute/{deal.fingerprint}",
                method="POST",
            )
        )

    tags = ["moneybag"] if deal.urgency is Urgency.IMMEDIATE else ["hourglass"]
    if spec.speed_mts in (2133, 2400):
        tags.append("dart")

    return Notification(
        title=title,
        body="\n".join(lines),
        priority=_PRIORITY.get(deal.urgency, 3),
        tags=tags,
        click=listing.url,
        actions=actions,
    )


def _time_left(deal: Deal) -> str | None:
    if deal.listing.ends_at is None:
        return None
    from ramtracker.core.clock import utc_now

    minutes = int((deal.listing.ends_at - utc_now()).total_seconds() / 60)
    if minutes <= 0:
        return None
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"
