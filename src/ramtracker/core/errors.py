"""Taxonomie d'erreurs — blueprint/07-ERRORS-AND-LOGGING.md §1.

Toute erreur dérive de `AppError`, porte un `code` stable et un `context`
sérialisable. Aucune de ces classes ne porte de message métier.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Racine de la taxonomie. `code` est stable et comparable en test."""

    code: str = "app_error"

    def __init__(self, message: str, /, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context

    def __str__(self) -> str:  # pragma: no cover - trivial
        if not self.context:
            return self.message
        pairs = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
        return f"{self.message} ({pairs})"


class ConfigError(AppError):
    """Variable ou fichier de configuration manquant / invalide. Arrête le démarrage."""

    code = "config_error"


class SourceError(AppError):
    """Racine des erreurs de collecte."""

    code = "source_error"


class SourceUnavailable(SourceError):
    """Réseau, 5xx, timeout — transitoire. Run marqué en échec, autres sources OK."""

    code = "source_unavailable"


class SourceBlocked(SourceError):
    """403, défi anti-bot, 429 — déclenche le disjoncteur, repli exponentiel."""

    code = "source_blocked"


class SourceAuthError(SourceError):
    """401, jeton expiré ou révoqué. Une seule reprise après rafraîchissement."""

    code = "source_auth_error"


class SourceSchemaChanged(SourceError):
    """La réponse ne correspond plus au contrat. Alerte technique immédiate."""

    code = "source_schema_changed"


class ExtractError(AppError):
    """Racine des erreurs d'extraction."""

    code = "extract_error"


class LowConfidence(ExtractError):
    """La cascade n'a pas tranché — mise en quarantaine, aucune alerte."""

    code = "low_confidence"


class LLMUnavailable(ExtractError):
    """Serveur LLM local saturé ou injoignable."""

    code = "llm_unavailable"


class NotifyError(AppError):
    """Échec d'envoi de la notification. Reprise une fois puis ERROR."""

    code = "notify_error"


class StorageError(AppError):
    """Base verrouillée, migration en échec. Arrête le cycle."""

    code = "storage_error"
