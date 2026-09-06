FROM python:3.13-slim AS base

# curl_cffi a besoin de la lib système pour l'impersonation TLS.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcurl4 ca-certificates sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
COPY src ./src
COPY migrations ./migrations
COPY configs ./configs

RUN uv sync --no-dev --frozen || uv sync --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    RAMTRACKER_CONFIG_DIR=/app/configs \
    RAMTRACKER_MIGRATIONS_DIR=/app/migrations

ENTRYPOINT ["ramtracker"]
CMD ["loop"]
