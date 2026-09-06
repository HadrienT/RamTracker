"""Accès SQLite — blueprint/04-DATA-MODEL.md.

Mode WAL, un fichier, migrations SQL brut forward-only et idempotentes.
Aucune requête métier ici.
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel

from ramtracker.core.clock import utc_now
from ramtracker.core.config import get_settings
from ramtracker.core.errors import StorageError
from ramtracker.core.logging import get_logger

_log = get_logger("core.db")
_MIGRATION_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class HealthReport(BaseModel):
    ok: bool
    schema_version: int
    journal_mode: str
    integrity: str


def _connect(path: Path) -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(path, isolation_level=None, timeout=settings.busy_timeout_ms / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {settings.busy_timeout_ms}")
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """Ouvre une connexion configurée, fermeture garantie."""
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def session_scope() -> Iterator[sqlite3.Connection]:
    """Transaction : commit en sortie normale, rollback sur exception, close garanti."""
    with connection() as conn:
        conn.execute("BEGIN")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")


def _discover_migrations() -> list[tuple[int, str, Path]]:
    root = get_settings().migrations_dir
    if not root.is_dir():
        raise StorageError("répertoire de migrations absent", path=str(root))
    found: list[tuple[int, str, Path]] = []
    for entry in sorted(root.iterdir()):
        match = _MIGRATION_RE.match(entry.name)
        if match:
            found.append((int(match.group(1)), match.group(2), entry))
    return found


def apply_migrations() -> int:
    """Applique `migrations/` dans l'ordre. Forward-only, idempotent. Renvoie le nb appliqué."""
    migrations = _discover_migrations()
    applied = 0
    with connection() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
        for version, name, path in migrations:
            if version in done:
                continue
            sql = path.read_text(encoding="utf-8")
            # `executescript` ouvre et ferme sa propre transaction ; on l'enveloppe
            # avec l'insertion du marqueur dans un seul script pour l'atomicité.
            script = (
                "BEGIN;\n"
                f"{sql}\n"
                "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) "
                f"VALUES ({version}, '{name}', '{utc_now().isoformat()}');\n"
                "COMMIT;"
            )
            try:
                conn.executescript(script)
            except sqlite3.Error as exc:
                with contextlib.suppress(sqlite3.Error):
                    conn.executescript("ROLLBACK;")
                raise StorageError("échec de migration", version=version, name=name) from exc
            _log.info("db.migration.applied", version=version, name=name)
            applied += 1
    return applied


def current_version() -> int:
    with connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations"
        ).fetchone()
        return int(row["v"])


def check_health() -> HealthReport:
    """Diagnostic : version de schéma, mode journal, intégrité."""
    try:
        with connection() as conn:
            journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            version_row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations"
            ).fetchone()
            version = int(version_row["v"])
    except sqlite3.Error as exc:
        raise StorageError("base injoignable") from exc
    return HealthReport(
        ok=(integrity == "ok"),
        schema_version=version,
        journal_mode=str(journal),
        integrity=str(integrity),
    )
