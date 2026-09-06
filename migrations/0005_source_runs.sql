-- 0005_source_runs — le socle du chien de garde inversé (WP06).
-- Sans cette table, une source qui tombe est indiscernable d'un marché calme.

CREATE TABLE source_runs (
  run_id       TEXT    PRIMARY KEY,
  source       TEXT    NOT NULL,
  started_at   TEXT    NOT NULL,
  duration_ms  INTEGER NOT NULL,
  raw_count    INTEGER NOT NULL,       -- annonces vues, avant dédoublonnage
  new_count    INTEGER NOT NULL,
  qualified    INTEGER NOT NULL,
  alerted      INTEGER NOT NULL,
  challenged   INTEGER NOT NULL DEFAULT 0,
  error        TEXT
);

CREATE INDEX idx_runs_source ON source_runs(source, started_at);
