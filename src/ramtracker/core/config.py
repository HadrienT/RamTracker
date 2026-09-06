"""Configuration — blueprint/06-CONFIG.md.

Deux niveaux : secrets et chemins en `.env`, comportement en YAML versionné.
Priorité : variable d'environnement > YAML > défaut du modèle pydantic.
`core` ne connaît aucun schéma métier : `load_yaml` reçoit le type de l'appelant.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from ramtracker.core.errors import ConfigError

T = TypeVar("T", bound=BaseModel)


class Settings(BaseSettings):
    """Secrets et chemins. Les champs sans défaut sont requis au démarrage."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=True
    )

    db_path: Path = Field(default=Path("./ramtracker.db"), alias="RAMTRACKER_DB_PATH")
    log_level: str = Field(default="INFO", alias="RAMTRACKER_LOG_LEVEL")
    config_dir: Path = Field(default=Path("./configs"), alias="RAMTRACKER_CONFIG_DIR")
    migrations_dir: Path = Field(default=Path("./migrations"), alias="RAMTRACKER_MIGRATIONS_DIR")
    state_dir: Path = Field(default=Path("./.state"), alias="RAMTRACKER_STATE_DIR")
    busy_timeout_ms: int = Field(default=5000, alias="RAMTRACKER_BUSY_TIMEOUT_MS")

    ebay_client_id: str = Field(alias="EBAY_CLIENT_ID")
    ebay_client_secret: SecretStr = Field(alias="EBAY_CLIENT_SECRET")
    ebay_zip: str | None = Field(default=None, alias="EBAY_ZIP")

    reddit_client_id: str | None = Field(default=None, alias="REDDIT_CLIENT_ID")
    reddit_client_secret: SecretStr | None = Field(default=None, alias="REDDIT_CLIENT_SECRET")
    reddit_user_agent: str | None = Field(default=None, alias="REDDIT_USER_AGENT")

    ntfy_url: SecretStr = Field(alias="NTFY_URL")

    llm_base_url: str = Field(default="http://127.0.0.1:8080/v1", alias="LLM_BASE_URL")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")

    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")


_REQUIRED_HINT = {
    "ebay_client_id": "EBAY_CLIENT_ID",
    "ebay_client_secret": "EBAY_CLIENT_SECRET",
    "ntfy_url": "NTFY_URL",
}


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton. Lève `ConfigError` en nommant la variable manquante."""
    try:
        return Settings()
    except ValidationError as exc:
        missing = [
            _REQUIRED_HINT.get(str(err["loc"][0]), str(err["loc"][0]))
            for err in exc.errors()
            if err["type"] in {"missing", "value_error.missing"}
        ]
        if missing:
            raise ConfigError(
                "variable(s) de configuration requise(s) manquante(s)", missing=missing
            ) from exc
        raise ConfigError("configuration invalide", detail=exc.errors()) from exc


def reset_settings_cache() -> None:
    """Vide le singleton (usage test uniquement)."""
    get_settings.cache_clear()


def load_yaml(name: str, model: type[T]) -> T:
    """Charge `configs/<name>.yaml` et valide contre `model`."""
    path = get_settings().config_dir / f"{name}.yaml"
    if not path.is_file():
        raise ConfigError("fichier de configuration absent", path=str(path))
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError("YAML invalide", path=str(path)) from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            "configuration YAML non conforme au schéma", path=str(path), detail=exc.errors()
        ) from exc
