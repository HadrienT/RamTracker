"""Étage 5 — repli LLM local (WP07). SEULE I/O du package (exception au contrat D8).

Le serveur d'inférence est **partagé avec OpenHands** : concurrence 1, appels
différables, décodage contraint par schéma (jamais du JSON en espérant).
Le repli sur l'API distante ne sert QUE la voie urgente.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from typing import Any

import httpx

from ramtracker.core.config import Settings, get_settings
from ramtracker.core.errors import LLMUnavailable
from ramtracker.core.logging import get_logger
from ramtracker.core.models import Kind, MemorySpec, Method, PriceBasis
from ramtracker.core.payloads import unpack

_log = get_logger("extract.llm")

# concurrence 1 côté RamTracker, sans exception (PRIMER §5.9).
_GATE = threading.Semaphore(1)

_SYSTEM_PROMPT = """Tu extrais une spécification mémoire depuis une annonce de RAM serveur.
Réponds UNIQUEMENT via l'outil/le schéma fourni.
- Ne devine jamais. Un champ incertain vaut null.
- price_basis="unit" si le prix affiché est celui d'UN module ("pièce", "l'unité",
  "chacune", "per stick", "Stück"). "lot" si un multiplicateur explicite est présent
  sans marqueur unitaire. Sinon "unknown".
- module_count = nombre de modules VENDUS, pas le nombre disponible en stock.
- "REG"/"Registered"/"RDIMM" => rdimm. "LR"/"LRDIMM" => lrdimm. "UDIMM ECC" => udimm_ecc.
- PC4-17000=2133, PC4-19200=2400, PC4-21300=2666.
"""

_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "module_capacity_gb": {"type": ["integer", "null"]},
        "module_count": {"type": "integer", "minimum": 1},
        "total_gb": {"type": ["integer", "null"]},
        "kind": {"enum": ["rdimm", "lrdimm", "udimm_ecc", "unknown"]},
        "speed_mts": {"type": ["integer", "null"]},
        "ranks": {"type": ["string", "null"]},
        "part_number": {"type": ["string", "null"]},
        "price_basis": {"enum": ["lot", "unit", "unknown"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["module_count", "kind", "price_basis", "confidence"],
}


class LlmConfig:
    """Vue `llm:` de thresholds.yaml (chargée par le runtime, pas ici)."""

    __slots__ = ("batch_size", "enabled", "remote_fallback", "timeout_s")

    def __init__(
        self, enabled: bool, batch_size: int, timeout_s: int, remote_fallback: bool
    ) -> None:
        self.enabled = enabled
        self.batch_size = batch_size
        self.timeout_s = timeout_s
        self.remote_fallback = remote_fallback


def _listing_text(raw_payload: bytes, title: str, description: str | None) -> str:
    try:
        payload = json.loads(unpack(raw_payload))
        hint = json.dumps(payload, ensure_ascii=False)[:600]
    except Exception:
        hint = ""
    body = f"TITRE: {title}"
    if description:
        body += f"\nDESCRIPTION: {description[:800]}"
    if hint:
        body += f"\nBRUT: {hint}"
    return body


def extract_batch(
    listings: Sequence[Any],
    *,
    settings: Settings | None = None,
    timeout_s: int = 45,
    allow_remote_fallback: bool = False,
    server_busy: Any = None,
) -> list[MemorySpec]:
    """Extrait un lot de specs. Voie urgente : `allow_remote_fallback=True`."""
    if not listings:
        return []
    settings = settings or get_settings()

    if server_busy is not None and callable(server_busy) and server_busy():
        if allow_remote_fallback and settings.anthropic_api_key is not None:
            return _remote(listings, settings)
        raise LLMUnavailable(
            "serveur LLM local occupé", lane="urgent" if allow_remote_fallback else "deferred"
        )

    with _GATE:
        try:
            return _local(listings, settings, timeout_s)
        except (httpx.HTTPError, LLMUnavailable, json.JSONDecodeError) as exc:
            _log.warning("llm.local.failed", error=str(exc))
            if allow_remote_fallback and settings.anthropic_api_key is not None:
                return _remote(listings, settings)
            raise LLMUnavailable("serveur LLM local injoignable") from exc


def _local(listings: Sequence[Any], settings: Settings, timeout_s: int) -> list[MemorySpec]:
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    specs: list[MemorySpec] = []
    with httpx.Client(timeout=timeout_s) as client:
        for listing in listings:
            content = _listing_text(listing.raw_payload, listing.title, listing.description)
            resp = client.post(
                url,
                json={
                    "model": settings.llm_model or "local",
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": content},
                    ],
                    "temperature": 0,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "memory_spec", "schema": _JSON_SCHEMA},
                    },
                },
            )
            if resp.status_code >= 300:
                raise LLMUnavailable("réponse LLM locale en erreur", status=resp.status_code)
            body = resp.json()
            text = body["choices"][0]["message"]["content"]
            specs.append(_parse(text))
    _log.info("llm.call.done", lane="local", batch_size=len(listings), fallback_used=False)
    return specs


def _remote(listings: Sequence[Any], settings: Settings) -> list[MemorySpec]:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dépendance optionnelle
        raise LLMUnavailable("SDK anthropic absent pour le repli distant") from exc

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())  # type: ignore[union-attr]
    specs: list[MemorySpec] = []
    tool = {
        "name": "memory_spec",
        "description": "Spécification mémoire extraite",
        "input_schema": _JSON_SCHEMA,
    }
    for listing in listings:
        content = _listing_text(listing.raw_payload, listing.title, listing.description)
        msg = client.messages.create(  # type: ignore[call-overload]
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_SYSTEM_PROMPT,
            tools=[tool],
            tool_choice={"type": "tool", "name": "memory_spec"},
            messages=[{"role": "user", "content": content}],
        )
        block = next((b for b in msg.content if b.type == "tool_use"), None)
        specs.append(_from_dict(dict(block.input)) if block else _invalid())
    _log.info("llm.call.done", lane="remote", batch_size=len(listings), fallback_used=True)
    return specs


def _parse(text: str) -> MemorySpec:
    try:
        return _from_dict(json.loads(text))
    except (json.JSONDecodeError, ValueError, TypeError):
        return _invalid()


def _from_dict(data: dict[str, Any]) -> MemorySpec:
    try:
        return MemorySpec(
            module_capacity_gb=data.get("module_capacity_gb"),
            module_count=int(data.get("module_count", 1)),
            total_gb=data.get("total_gb"),
            kind=Kind(data.get("kind", "unknown")),
            speed_mts=data.get("speed_mts"),
            ranks=data.get("ranks"),
            part_number=data.get("part_number"),
            price_basis=PriceBasis(data.get("price_basis", "unknown")),
            confidence=float(data.get("confidence", 0.0)),
            method=Method.LLM,
        )
    except (ValueError, TypeError):
        return _invalid()


def _invalid() -> MemorySpec:
    return MemorySpec(method=Method.LLM, confidence=0.0, reject_reason="llm_schema_invalid")
