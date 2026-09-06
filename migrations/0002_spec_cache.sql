-- 0002_spec_cache — l'extraction, indexée sur le TEXTE (spec_hash), pas l'annonce.
-- Un repost, un doublon inter-sources ou une republication ne coûtent alors
-- aucun retraitement ni appel LLM.

CREATE TABLE spec_cache (
  spec_hash          TEXT PRIMARY KEY,
  module_capacity_gb INTEGER,
  module_count       INTEGER NOT NULL DEFAULT 1,
  total_gb           INTEGER,
  kind               TEXT    NOT NULL,
  speed_mts          INTEGER,
  ranks              TEXT,
  part_number        TEXT,
  price_basis        TEXT    NOT NULL,
  confidence         REAL    NOT NULL,
  method             TEXT    NOT NULL,   -- part_number | rules | llm
  reject_reason      TEXT,               -- NULL si qualifiée  <- cache NÉGATIF
  parser_version     INTEGER NOT NULL,
  created_at         TEXT    NOT NULL
);

CREATE INDEX idx_spec_reject ON spec_cache(reject_reason) WHERE reject_reason IS NOT NULL;
CREATE INDEX idx_spec_method ON spec_cache(method);
