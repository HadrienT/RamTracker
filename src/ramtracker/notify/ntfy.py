"""Implémentation ntfy — deux priorités, boutons d'action (WP05).

`[À CONFIRMER]` : les noms exacts des en-têtes ntfy (`X-Title`, `X-Priority`,
`X-Tags`, `X-Click`, `X-Actions`) sont à vérifier dans la doc officielle.
L'URL du sujet (jeton compris) n'apparaît dans aucun log.
"""

from __future__ import annotations

import json

import httpx

from ramtracker.core.config import Settings, get_settings
from ramtracker.core.errors import NotifyError
from ramtracker.core.logging import get_logger
from ramtracker.notify.base import Notification

_log = get_logger("notify.ntfy")


class NtfyNotifier:
    """Implémente `Notifier`."""

    def __init__(
        self, settings: Settings | None = None, *, client: httpx.Client | None = None
    ) -> None:
        self._url = (settings or get_settings()).ntfy_url.get_secret_value()
        self._client = client or httpx.Client(timeout=15.0)

    def send(self, n: Notification) -> None:
        headers = {
            "X-Title": _ascii(n.title),
            "X-Priority": str(n.priority),
        }
        if n.tags:
            headers["X-Tags"] = ",".join(n.tags)
        if n.click:
            headers["X-Click"] = n.click
        if n.actions:
            headers["X-Actions"] = json.dumps(
                [_action_header(a) for a in n.actions], ensure_ascii=True
            )
        try:
            resp = self._client.post(self._url, content=n.body.encode("utf-8"), headers=headers)
        except httpx.HTTPError as exc:
            raise NotifyError("ntfy injoignable") from exc
        if resp.status_code >= 300:
            raise NotifyError("ntfy a rejeté la notification", status=resp.status_code)
        _log.info("notify.sent", priority=n.priority, tags=n.tags)


def _action_header(action: object) -> dict[str, str]:
    from ramtracker.notify.base import Action

    assert isinstance(action, Action)
    payload = {"action": action.action, "label": action.label, "url": action.url}
    if action.method:
        payload["method"] = action.method
    return payload


def _ascii(text: str) -> str:
    """ntfy n'accepte que de l'ASCII dans les en-têtes."""
    return text.encode("ascii", "replace").decode("ascii")
