# RamTracker — tâches de développement et d'exploitation
set shell := ["bash", "-uc"]

# liste les tâches
default:
    @just --list

# installe l'environnement
sync:
    uv sync --all-extras

# lint + format check
lint:
    uv run ruff check src tests
    uv run ruff format --check src tests
    uv run mypy

# formate le code
fmt:
    uv run ruff format src tests
    uv run ruff check --fix src tests

# contrats d'architecture D1→D8
arch:
    uv run lint-imports

# tous les tests sauf @live
test:
    uv run pytest

# corpus doré + tableau de résolution par étage
test-golden:
    uv run pytest -m golden -q -s

# tests de propriété (hypothesis, I1 + grammaire)
test-property:
    uv run pytest -m property -q

# applique les migrations
migrate:
    uv run ramtracker migrate

# un cycle unique sur une source
run-once source="ebay":
    uv run ramtracker run-once --source {{source}}

# récupère l'historique
backfill days="30":
    uv run ramtracker backfill --days {{days}}

# rejoue le parseur sur l'archive brute
replay since:
    uv run ramtracker replay --since {{since}}

# rapport hebdomadaire
report:
    uv run ramtracker report --weekly

# sauvegarde de la base
backup db="ramtracker.db":
    mkdir -p backups
    sqlite3 {{db}} ".backup backups/ramtracker-$(date +%Y%m%d).db"

# CI locale : reproduit .github/workflows/ci.yml
ci: lint arch test
